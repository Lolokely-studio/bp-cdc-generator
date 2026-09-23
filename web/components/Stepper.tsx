const STEPS = ["Documents", "Idée", "Rédaction"];

export function Stepper({ current }: { current: 1 | 2 | 3 }) {
  return (
    <div className="m-stepper">
      {STEPS.map((label, index) => {
        const step = index + 1;
        return (
          <span key={label} className={step === current ? "on" : step < current ? "past" : ""}
            aria-current={step === current ? "step" : undefined}>
            <em>{step}</em>{label}
          </span>
        );
      })}
    </div>
  );
}
