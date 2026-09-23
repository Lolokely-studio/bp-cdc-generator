import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useRunStream } from "@/lib/useRunStream";

const DELAYS = [10];
const encoder = new TextEncoder();

function closingStream(frame: string) {
  return new ReadableStream<Uint8Array>({
    start(controller) { controller.enqueue(encoder.encode(frame)); controller.close(); },
  });
}

function openStream() {
  return new ReadableStream<Uint8Array>({ start() {} });
}

describe("useRunStream", () => {
  it("se reconnecte après une coupure et relit l'état à chaque ouverture", async () => {
    const bodies = [closingStream('event: token\ndata: {"text": "a"}\n\n'), openStream()];
    const fetchMock = vi.fn(async () => new Response(bodies.shift() ?? openStream()));
    vi.stubGlobal("fetch", fetchMock);
    const onEvent = vi.fn();
    const onSync = vi.fn();

    const { unmount } = renderHook(() => useRunStream("p-1", true, onEvent, onSync, DELAYS));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(onEvent).toHaveBeenCalledWith({ name: "token", data: { text: "a" } });
    await waitFor(() => expect(onSync).toHaveBeenCalledTimes(2));
    unmount();
  });

  it("ne s'ouvre pas inactif, et se coupe quand il le devient", async () => {
    const signals: AbortSignal[] = [];
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      signals.push(init.signal as AbortSignal);
      return new Response(openStream());
    });
    vi.stubGlobal("fetch", fetchMock);

    const { rerender } = renderHook(
      ({ active }) => useRunStream("p-1", active, () => {}, () => {}, DELAYS),
      { initialProps: { active: false } },
    );
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(fetchMock).not.toHaveBeenCalled();

    rerender({ active: true });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    rerender({ active: false });
    expect(signals[0].aborted).toBe(true);
  });

  it("abandonne sur un projet introuvable", async () => {
    const fetchMock = vi.fn(async () => new Response("{}", { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);
    renderHook(() => useRunStream("p-1", true, () => {}, () => {}, DELAYS));
    await new Promise((resolve) => setTimeout(resolve, 60));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
