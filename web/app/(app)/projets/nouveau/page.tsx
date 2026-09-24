"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { CharCount } from "@/components/CharCount";
import { useSetCrumbs } from "@/components/Crumbs";
import { RadioGroup } from "@/components/RadioGroup";
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
        <div>
          <h1 className="t-page">Quels documents voulez-vous générer ?</h1>
          <p className="page__sub">Ce qui est commun aux deux ne vous sera demandé qu'une fois.</p>
        </div>

        <RadioGroup label="Documents à générer" className="choices" optionClassName="choice"
          value={documents} onChange={setDocuments}
          options={TILES.map((tile) => ({
            value: tile.value,
            render: (
              <>
                <span className="choice__top">
                  <span className="choice__name">{tile.title}</span>
                  <span className="choice__pip" aria-hidden="true" />
                </span>
                <span className="tag tag--idle tag--flat">
                  {sectionCount(catalogue, tile.value, profilCdc, profilBp)} sections
                </span>
                <span className="choice__text">{tile.text}</span>
              </>
            ),
          }))} />

        {documents !== "bp" && (
          <div className="ask">
            <p className="ask__q">À quoi servira le cahier des charges ?</p>
            <p className="ask__why">
              Pour consulter des prestataires, le document doit être opposable : il gagne une
              section « cadre de réponse » et un niveau d'exigence sur chaque besoin.
            </p>
            <RadioGroup label="Usage du cahier des charges" className="segment"
              optionClassName="segment__opt" value={profilCdc} onChange={setProfilCdc}
              options={CDC_PROFILES.map((p) => ({ value: p.value, render: p.label }))} />
          </div>
        )}

        {documents !== "cdc" && (
          <div className="ask">
            <p className="ask__q">Qui lira le business plan ?</p>
            <p className="ask__why">
              Le lecteur change le ton et l'ordre des arguments. Les chiffres, eux, ne bougent pas.
            </p>
            <RadioGroup label="Lecteur du business plan" className="segment"
              optionClassName="segment__opt" value={profilBp} onChange={setProfilBp}
              options={BP_PROFILES.map((p) => ({ value: p.value, render: p.label }))} />
          </div>
        )}

        <div className="actions">
          <Link className="btn btn--ghost" href="/projets">Annuler</Link>
          <button className="btn btn--primary" type="button" onClick={() => setStep(2)}>Continuer</button>
        </div>
      </main>
    );
  }

  return (
    <main className="page page--narrow">
      <Stepper current={2} />
      <div>
        <h1 className="t-page">Décrivez votre projet</h1>
        <p className="page__sub">
          Quelques phrases suffisent : le problème, pour qui, et comment vous le résolvez.
        </p>
      </div>
      <form onSubmit={create} noValidate>
        <label className="field">
          <span className="field__label">Nom du projet</span>
          <input className="input" maxLength={200} value={nom}
            aria-invalid={errors.nom ? true : undefined}
            onChange={(e) => setNom(e.target.value)} />
          {errors.nom && <span className="field__error">{errors.nom}</span>}
        </label>
        <div className="field">
          <span className="field__head">
            {/* Un `<span>`, pas un `<label>` autour du compteur : sinon « 0 / 5 000 »
                rejoint « Votre idée » dans le nom accessible du champ, et
                `getByLabelText("Votre idée")` cesse de le reconnaître. Le lien se
                fait par `htmlFor`/`id`, comme pour la note du mot de passe. */}
            <label className="field__label" htmlFor="idee">Votre idée</label>
            <CharCount value={idee} max={MAX_IDEA} id="compte-idee" />
          </span>
          <textarea id="idee" className="textarea" rows={7} value={idee}
            aria-invalid={errors.idee ? true : undefined} aria-describedby="compte-idee"
            onChange={(e) => setIdee(e.target.value)} />
          {errors.idee && <span className="field__error">{errors.idee}</span>}
        </div>
        {errors.form && (
          <div className="callout callout--stop" role="alert" style={{ marginTop: "1rem" }}>
            <span className="callout__body">{errors.form}</span>
          </div>
        )}
        <div className="actions">
          <button className="btn btn--ghost" type="button" onClick={() => setStep(1)}>Retour</button>
          <button className="btn btn--primary" type="submit" disabled={busy}>
            {busy ? "Analyse…" : "Analyser mon idée"}
          </button>
        </div>
      </form>
    </main>
  );
}
