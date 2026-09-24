"use client";

import { useEffect, useState, type ReactNode } from "react";
import { AuthCard } from "@/components/AuthCard";
import { API_URL } from "@/lib/api";

type Phase = "checking" | "waking" | "ready" | "down";
type Timings = { quietMs: number; retryMs: number; giveUpMs: number };

// Silence d'une seconde et demie avant d'afficher quoi que ce soit : un
// serveur éveillé répond bien avant, et l'écran ne clignote pas.
const DEFAULT_TIMINGS: Timings = { quietMs: 1500, retryMs: 3000, giveUpMs: 180_000 };

async function probeHealth(): Promise<boolean> {
  try {
    const response = await fetch(`${API_URL}/health`, {
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    return response.ok;
  } catch {
    return false;
  }
}

/** L'écran d'attente du §8 : l'hébergement gratuit s'endort après quinze
 * minutes et met environ une minute à se réveiller.
 *
 * La sonde ne tourne qu'ici, au chargement, et s'arrête dès que le serveur
 * répond. Jamais de sonde périodique pour le tenir éveillé : deux services
 * allumés en permanence épuisent le quota mensuel de Render (§9.4). */
export function WakeGate({
  children,
  probe = probeHealth,
  timings = DEFAULT_TIMINGS,
}: {
  children: ReactNode;
  probe?: () => Promise<boolean>;
  timings?: Timings;
}) {
  const [phase, setPhase] = useState<Phase>("checking");
  const [attempt, setAttempt] = useState(0);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    let alive = true;
    const started = Date.now();
    const quiet = setTimeout(() => {
      if (alive) setPhase((current) => (current === "checking" ? "waking" : current));
    }, timings.quietMs);
    const clock = setInterval(() => {
      if (alive) setElapsed(Math.round((Date.now() - started) / 1000));
    }, 1000);

    (async () => {
      while (alive) {
        if (await probe()) {
          if (alive) setPhase("ready");
          return;
        }
        if (Date.now() - started >= timings.giveUpMs) {
          if (alive) setPhase("down");
          return;
        }
        await new Promise((resolve) => setTimeout(resolve, timings.retryMs));
      }
    })().finally(() => {
      clearTimeout(quiet);
      clearInterval(clock);
    });

    return () => {
      alive = false;
      clearTimeout(quiet);
      clearInterval(clock);
    };
  }, [attempt, probe, timings]);

  if (phase === "ready") return <>{children}</>;
  if (phase === "checking") return null;
  if (phase === "down") {
    return (
      <AuthCard footer="Rien n'est perdu : vos projets reprendront là où ils se sont arrêtés.">
        <h1 className="t-section">Le serveur ne répond pas</h1>
        <p className="t-note" style={{ marginTop: ".375rem" }}>
          Il ne s'est pas réveillé au bout de trois minutes.
        </p>
        <div style={{ marginTop: "1.125rem" }}>
          <button className="btn btn--primary btn--block" type="button"
            onClick={() => { setElapsed(0); setPhase("checking"); setAttempt((n) => n + 1); }}>
            Réessayer
          </button>
        </div>
      </AuthCard>
    );
  }
  return (
    <AuthCard footer="Rien n'est perdu : vos projets reprendront là où ils se sont arrêtés.">
      <h1 className="t-section">Le serveur se réveille</h1>
      <p className="t-note" style={{ marginTop: ".375rem" }}>
        L'hébergement s'endort après quinze minutes sans visite. Il redémarre : comptez
        environ une minute.
      </p>
      <div className="callout callout--live" role="status" style={{ marginTop: "1.125rem" }}>
        <span className="spinner" aria-hidden="true" />
        <span className="callout__body">Réveil en cours, <span className="t-num">{elapsed}</span> s</span>
      </div>
    </AuthCard>
  );
}
