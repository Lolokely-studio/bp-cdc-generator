import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WakeGate } from "@/components/WakeGate";

const timings = { quietMs: 1000, retryMs: 2000, giveUpMs: 10_000 };

beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
afterEach(() => vi.useRealTimers());

describe("WakeGate", () => {
  it("rend l'application tout de suite quand le serveur répond", async () => {
    const probe = vi.fn(async () => true);
    render(<WakeGate probe={probe} timings={timings}><p>appli</p></WakeGate>);
    expect(screen.queryByText("Le serveur se réveille")).toBeNull();
    expect(await screen.findByText("appli")).toBeInTheDocument();
    expect(screen.queryByText("Le serveur se réveille")).toBeNull();
    expect(probe).toHaveBeenCalledTimes(1);
  });

  it("montre l'écran de réveil quand le serveur tarde, puis l'application", async () => {
    const answers = [false, false, true];
    const probe = vi.fn(async () => answers.shift() ?? true);
    render(<WakeGate probe={probe} timings={timings}><p>appli</p></WakeGate>);
    await act(() => vi.advanceTimersByTimeAsync(1100));
    expect(screen.getByText("Le serveur se réveille")).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(4100));
    expect(screen.getByText("appli")).toBeInTheDocument();
    expect(probe).toHaveBeenCalledTimes(3);
    // Plus aucun appel une fois le serveur joint : pas de ping (§9.4).
    await act(() => vi.advanceTimersByTimeAsync(20_000));
    expect(probe).toHaveBeenCalledTimes(3);
  });

  it("abandonne après le délai et laisse réessayer", async () => {
    let up = false;
    const probe = vi.fn(async () => up);
    render(<WakeGate probe={probe} timings={timings}><p>appli</p></WakeGate>);
    await act(() => vi.advanceTimersByTimeAsync(12_500));
    expect(screen.getByText("Le serveur ne répond pas")).toBeInTheDocument();
    const calls = probe.mock.calls.length;
    await act(() => vi.advanceTimersByTimeAsync(10_000));
    expect(probe).toHaveBeenCalledTimes(calls);
    up = true;
    await userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
      .click(screen.getByRole("button", { name: "Réessayer" }));
    expect(await screen.findByText("appli")).toBeInTheDocument();
  });
});
