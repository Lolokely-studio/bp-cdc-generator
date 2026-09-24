"use client";

import { useRef, type KeyboardEvent, type ReactNode } from "react";

export type RadioOption<T extends string> = { value: T; render: ReactNode };

/** Un choix exclusif se navigue aux flèches et n'occupe qu'un arrêt de
 * tabulation : c'est ce qu'attend un lecteur d'écran, et ce que trois
 * boutons `aria-pressed` ne disaient pas. */
export function RadioGroup<T extends string>({
  label, value, onChange, options, className = "", optionClassName = "",
}: {
  label: string;
  value: T;
  onChange: (value: T) => void;
  options: RadioOption<T>[];
  className?: string;
  optionClassName?: string;
}) {
  // Une référence par option, indexée par sa valeur : on donne le focus à
  // l'élément lui-même, sans attendre un rendu. Interroger le DOM après
  // `onChange` retomberait sur l'option qu'on vient de quitter, puisque le
  // parent n'a pas encore rendu la nouvelle.
  const optionRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
    if (step === undefined) return;
    event.preventDefault();
    const index = options.findIndex((option) => option.value === value);
    const next = options[(index + step + options.length) % options.length];
    onChange(next.value);
    // Le focus suit la sélection : sans cela, les flèches suivantes
    // repartiraient de l'option qu'on vient de quitter.
    optionRefs.current[next.value]?.focus();
  }

  return (
    <div className={className} role="radiogroup" aria-label={label} onKeyDown={onKeyDown}>
      {options.map((option) => (
        <button key={option.value} className={optionClassName} type="button" role="radio"
          ref={(el) => { optionRefs.current[option.value] = el; }}
          aria-checked={option.value === value} tabIndex={option.value === value ? 0 : -1}
          onClick={() => onChange(option.value)}>
          {option.render}
        </button>
      ))}
    </div>
  );
}
