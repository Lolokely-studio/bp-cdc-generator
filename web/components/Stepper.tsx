const STEPS = ["Documents", "Idée", "Rédaction"];

/** Trois étapes numérotées : c'en est une vraie suite, et le numéro dit
 * combien il en reste. L'étape franchie porte une coche, pas son chiffre. */
export function Stepper({ current }: { current: 1 | 2 | 3 }) {
  return (
    <ol className="steps">
      {STEPS.map((label, index) => {
        const step = index + 1;
        const state = step < current ? "done" : step === current ? "now" : null;
        return (
          <li key={label} className={state ? `steps__item steps__item--${state}` : "steps__item"}
            aria-current={step === current ? "step" : undefined}>
            <span className="steps__pip">
              {state === "done"
                ? <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                    strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="m5 13 4 4L19 7" />
                  </svg>
                : step}
            </span>
            {label}
          </li>
        );
      })}
    </ol>
  );
}
