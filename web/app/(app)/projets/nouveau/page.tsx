"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { useSetCrumbs } from "@/components/Crumbs";
import { Stepper } from "@/components/Stepper";
import { api } from "@/lib/api";
import { useCatalogue } from "@/lib/catalogue";
import type { Documents } from "@/lib/contracts";
import { BP_PROFILES, CDC_PROFILES, creationPayload, sectionCount } from "@/lib/labels";

const TILES: { value: Documents; title: string; text: string }[] = [
  { value: "cdc", title: "Cahier des charges",
    text: "Besoins, exigences, contraintes, planning et budget pour cadrer la réalisation." },
  { value: "bp", title: "Business plan",
    text: "Marché, modèle économique, stratégie et prévisionnel financier sur trois ans." },
  { value: "both", title: "Les deux",
    text: "Les deux documents rédigés en cohérence, avec un contrôle croisé à la fin." },
];

// La borne du schéma `ProjectCreate` côté API.
const MAX_IDEA = 5000;

type Errors = { nom?: string; idee?: string; form?: string };

export default function NewProjectPage() {
  useSetCrumbs([{ label: "Mes projets", href: "/projets" }, { label: "Nouveau projet" }]);
  const catalogue = useCatalogue();
  const router = useRouter();
  const [step, setStep] = useState<1 | 2>(1);
  const [documents, setDocuments] = useState<Documents>("both");
  const [profilCdc, setProfilCdc] = useState<string>("consultation");
  const [profilBp, setProfilBp] = useState<string>("banque");
  const [nom, setNom] = useState("");
  const [idee, setIdee] = useState("");
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);

  async function create(event: FormEvent) {
    event.preventDefault();
    const next: Errors = {};
    if (!nom.trim()) next.nom = "Donnez un nom au projet.";
    if (!idee.trim()) next.idee = "Décrivez votre idée en quelques phrases.";
    else if (idee.trim().length > MAX_IDEA) next.idee = `L'idée tient en ${MAX_IDEA} caractères au plus.`;
    setErrors(next);
    if (Object.keys(next).length > 0) return;

    setBusy(true);
    try {
      const project = await api.createProject(creationPayload({ nom, documents, profilCdc, profilBp, idee }));
      router.push(`/projets/${project.id}`);
    } catch {
      setErrors({ form: "Le projet n'a pas pu être créé. Réessayez dans un instant." });
      setBusy(false);
    }
  }

  if (step === 1) {
    return (
      <main className="page page--narrow">
        <Stepper current={1} />
        <h1 className="t-page">Quel(s) document(s) voulez-vous générer ?</h1>
        <p className="t-note">Les informations communes aux deux documents ne vous seront demandées qu'une seule fois.</p>
        <div className="m-tiles">
          {TILES.map((tile) => (
            <button key={tile.value} className="m-tile" type="button"
              aria-pressed={documents === tile.value} onClick={() => setDocuments(tile.value)}>
              <b>{tile.title}</b>
              <span className="t-note t-fine">{sectionCount(catalogue, tile.value, profilCdc, profilBp)} sections</span>
              <span className="t-fine">{tile.text}</span>
            </button>
          ))}
        </div>
        {documents !== "bp" && (
          <div className="m-profile">
            <p className="m-cap">À quoi servira le cahier des charges ?</p>
            <p className="t-note t-fine">
              Pour consulter des prestataires, le document doit être opposable : il gagne une section
              « cadre de réponse » et un niveau d'exigence sur chaque besoin.
            </p>
            <div className="m-chips">
              {CDC_PROFILES.map((profile) => (
                <button key={profile.value} className="m-chip" type="button"
                  aria-pressed={profilCdc === profile.value} onClick={() => setProfilCdc(profile.value)}>
                  {profile.label}
                </button>
              ))}
            </div>
          </div>
        )}
        {documents !== "cdc" && (
          <div className="m-profile">
            <p className="m-cap">Qui lira le business plan ?</p>
            <p className="t-note t-fine">Le lecteur change le ton et l'ordre des arguments. Les chiffres, eux, ne bougent pas.</p>
            <div className="m-chips">
              {BP_PROFILES.map((profile) => (
                <button key={profile.value} className="m-chip" type="button"
                  aria-pressed={profilBp === profile.value} onClick={() => setProfilBp(profile.value)}>
                  {profile.label}
                </button>
              ))}
            </div>
          </div>
        )}
        <div className="m-actions">
          <Link className="m-btn sec" href="/projets">Annuler</Link>
          <button className="m-btn" type="button" onClick={() => setStep(2)}>Continuer</button>
        </div>
      </main>
    );
  }

  return (
    <main className="page page--narrow">
      <Stepper current={2} />
      <h1 className="t-page">Décrivez votre projet</h1>
      <p className="t-note">Quelques phrases suffisent : le problème, pour qui, et comment vous le résolvez.</p>
      <form onSubmit={create} noValidate>
        <div style={{ marginTop: 18 }}>
          <label className="m-label" htmlFor="nom">Nom du projet</label>
          <input id="nom" className="m-input" maxLength={200} value={nom}
            aria-invalid={errors.nom ? true : undefined} onChange={(e) => setNom(e.target.value)} />
          {errors.nom && <p className="m-err">{errors.nom}</p>}
        </div>
        <div style={{ marginTop: 14 }}>
          <label className="m-label" htmlFor="idee">Votre idée</label>
          <textarea id="idee" className="m-input" rows={5} value={idee}
            aria-invalid={errors.idee ? true : undefined} onChange={(e) => setIdee(e.target.value)} />
          {errors.idee && <p className="m-err">{errors.idee}</p>}
        </div>
        {errors.form && <p className="m-err" role="alert">{errors.form}</p>}
        <div className="m-actions">
          <button className="m-btn sec" type="button" onClick={() => setStep(1)}>Retour</button>
          <button className="m-btn" type="submit" disabled={busy}>Analyser mon idée</button>
        </div>
      </form>
    </main>
  );
}
