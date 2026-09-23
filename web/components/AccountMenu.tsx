"use client";

import { useEffect, useRef, useState } from "react";
import { initials } from "@/lib/messages";

/** Une seule cible à droite de la barre haute, là où il y en avait trois
 * pour une seule destination. */
export function AccountMenu({ email, onLogout }: { email: string; onLogout: () => void }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const dehors = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const echap = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      // Sans cela, le focus retombe sur le corps du document et la
      // navigation au clavier repart du début de la page.
      button.current?.focus();
    };
    document.addEventListener("mousedown", dehors);
    document.addEventListener("keydown", echap);
    return () => {
      document.removeEventListener("mousedown", dehors);
      document.removeEventListener("keydown", echap);
    };
  }, [open]);

  return (
    <div className="account" ref={root}>
      <button className="account__btn" type="button" ref={button}
        aria-expanded={open} aria-haspopup="true" aria-label={`Compte de ${email}`}
        onClick={() => setOpen((etait) => !etait)}>
        <span className="avatar" title={email} aria-hidden="true">{initials(email)}</span>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="2" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
      </button>
      {open && (
        <div className="account__menu">
          <div className="account__who"><p className="account__mail">{email}</p></div>
          <button className="account__item" type="button" onClick={onLogout}>
            Se déconnecter
          </button>
        </div>
      )}
    </div>
  );
}
