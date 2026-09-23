import { describe, expect, it, vi } from "vitest";
import { SseParser, readStream } from "@/lib/sse";

const FRAMES =
  'event: token\ndata: {"text": "Bon"}\n\n' +
  ": battement\n\n" +
  'event: section_saved\ndata: {"document": "cdc", "section_id": "perimetre", "score": 8}\n\n';

describe("SseParser", () => {
  it("recompose les trames quel que soit le découpage", () => {
    for (let cut = 0; cut <= FRAMES.length; cut++) {
      const parser = new SseParser();
      const events = [...parser.push(FRAMES.slice(0, cut)), ...parser.push(FRAMES.slice(cut))];
      expect(events.map((e) => e.event)).toEqual(["token", "section_saved"]);
      expect(JSON.parse(events[0].data)).toEqual({ text: "Bon" });
    }
  });

  it("ignore un battement et joint les lignes de données", () => {
    const parser = new SseParser();
    expect(parser.push(": battement\n\n")).toEqual([]);
    expect(parser.push("data: a\ndata: b\n\n")).toEqual([{ event: "message", data: "a\nb" }]);
  });

  it("accepte des fins de ligne CRLF", () => {
    const parser = new SseParser();
    expect(parser.push('event: done\r\ndata: {}\r\n\r\n')).toEqual([{ event: "done", data: "{}" }]);
  });
});

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

describe("readStream", () => {
  it("rend les événements décodés et signale l'ouverture", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(streamOf([FRAMES.slice(0, 20), FRAMES.slice(20)]))));
    const events: unknown[] = [];
    const onOpen = vi.fn();
    await readStream("p-1", (e) => events.push(e), onOpen, new AbortController().signal);
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(events).toEqual([
      { name: "token", data: { text: "Bon" } },
      { name: "section_saved", data: { document: "cdc", section_id: "perimetre", score: 8 } },
    ]);
  });

  it("lève une ApiError sur un refus, sans signaler d'ouverture", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: { code: "projet_introuvable" } }), { status: 404 })));
    const onOpen = vi.fn();
    await expect(readStream("p-1", () => {}, onOpen, new AbortController().signal))
      .rejects.toMatchObject({ status: 404, code: "projet_introuvable" });
    expect(onOpen).not.toHaveBeenCalled();
  });
});
