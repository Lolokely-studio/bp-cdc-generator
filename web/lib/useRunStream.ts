"use client";

import { useEffect, useRef } from "react";
import { ApiError } from "@/lib/api";
import { readStream, type StreamEvent } from "@/lib/sse";

export const RETRY_DELAYS_MS = [1000, 2000, 5000];

function pause(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => { clearTimeout(timer); resolve(); }, { once: true });
  });
}

/** Reste abonné au flux du projet tant que `active` est vrai.
 *
 * Une coupure — hébergeur qui redémarre, intermédiaire qui ferme, abonné en
 * retard que le serveur congédie — se rattrape par une reconnexion, et
 * chaque ouverture appelle `onSync` pour relire `/state` : aucun état ne vit
 * dans la connexion (§8).
 *
 * `active` n'est vrai que pendant que le run avance. En attente d'une
 * réponse, terminé ou en échec, rien ne peut arriver par le flux avant un
 * geste de l'utilisateur, et un flux ouvert enverrait un battement toutes
 * les quinze secondes : un onglet oublié une nuit tiendrait le service
 * éveillé jusqu'au matin et brûlerait le quota mensuel (§9.4). */
export function useRunStream(
  projectId: string,
  active: boolean,
  onEvent: (event: StreamEvent) => void,
  onSync: () => void,
  delays: number[] = RETRY_DELAYS_MS,
): void {
  const handlers = useRef({ onEvent, onSync });
  useEffect(() => {
    handlers.current = { onEvent, onSync };
  });

  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    let failures = 0;

    (async () => {
      while (!controller.signal.aborted) {
        try {
          await readStream(
            projectId,
            (event) => handlers.current.onEvent(event),
            () => {
              failures = 0;
              handlers.current.onSync();
            },
            controller.signal,
          );
        } catch (error) {
          if (controller.signal.aborted) return;
          // Sans session, sans droit ou sans projet, se reconnecter ne
          // changera rien : on s'arrête là.
          if (error instanceof ApiError && [401, 403, 404].includes(error.status)) return;
        }
        if (controller.signal.aborted) return;
        await pause(delays[Math.min(failures, delays.length - 1)], controller.signal);
        failures += 1;
      }
    })();

    return () => controller.abort();
  }, [projectId, active, delays]);
}
