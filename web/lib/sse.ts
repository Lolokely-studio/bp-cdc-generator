import { API_URL, ApiError, errorCode, getToken } from "@/lib/api";

export type SseFrame = { event: string; data: string };
export type StreamEvent = { name: string; data: Record<string, unknown> };

/** Découpe un flux SSE en événements.
 *
 * Tenu à part du réseau pour être testé sur des morceaux arbitraires : un
 * paquet coupe où il veut, au milieu d'une ligne comme au milieu d'un
 * caractère accentué — d'où le décodage en flux dans `readStream`. */
export class SseParser {
  private buffer = "";

  push(chunk: string): SseFrame[] {
    this.buffer += chunk;
    this.buffer = this.buffer.replace(/\r\n/g, "\n");
    const frames: SseFrame[] = [];
    let end = this.buffer.indexOf("\n\n");
    while (end !== -1) {
      const block = this.buffer.slice(0, end);
      this.buffer = this.buffer.slice(end + 2);
      let event = "message";
      const data: string[] = [];
      for (const line of block.split("\n")) {
        // Une ligne qui commence par « : » est un commentaire : le battement
        // du serveur, qui tient la connexion ouverte et ne dit rien.
        if (line === "" || line.startsWith(":")) continue;
        const colon = line.indexOf(":");
        const field = colon === -1 ? line : line.slice(0, colon);
        let value = colon === -1 ? "" : line.slice(colon + 1);
        if (value.startsWith(" ")) value = value.slice(1);
        if (field === "event") event = value;
        else if (field === "data") data.push(value);
      }
      if (data.length > 0) frames.push({ event, data: data.join("\n") });
      end = this.buffer.indexOf("\n\n");
    }
    return frames;
  }
}

/** Lit le flux d'un projet jusqu'à sa fin ou jusqu'à l'abandon du signal.
 *
 * `fetch` et non `EventSource` : ce dernier ne sait pas envoyer d'en-tête
 * `Authorization`, et la route exige le jeton. */
export async function readStream(
  projectId: string,
  onEvent: (event: StreamEvent) => void,
  onOpen: () => void,
  signal: AbortSignal,
): Promise<void> {
  const token = getToken();
  const response = await fetch(`${API_URL}/projects/${projectId}/stream`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    signal,
    cache: "no-store",
  });
  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => undefined);
    const detail = payload && typeof payload === "object" ? (payload as { detail?: unknown }).detail : undefined;
    throw new ApiError(response.status, errorCode(detail), detail);
  }
  onOpen();

  const reader = response.body.getReader();
  signal.addEventListener("abort", () => { reader.cancel().catch(() => {}); }, { once: true });
  const decoder = new TextDecoder();
  const parser = new SseParser();
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    for (const frame of parser.push(decoder.decode(value, { stream: true }))) {
      let data: unknown;
      try {
        data = JSON.parse(frame.data);
      } catch {
        continue;
      }
      if (data && typeof data === "object") onEvent({ name: frame.event, data: data as Record<string, unknown> });
    }
  }
}
