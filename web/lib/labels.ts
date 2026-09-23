import type { ProjectCreation } from "@/lib/api";
import type { Catalogue, DocumentKind, Documents, ProjectSummary, RunStatus } from "@/lib/contracts";

export const DOCUMENT_LABEL: Record<DocumentKind, string> = {
  cdc: "Cahier des charges",
  bp: "Business plan",
};

export const DOCUMENT_SHORT: Record<DocumentKind, string> = { cdc: "CDC", bp: "BP" };

export const DOCUMENTS_LABEL: Record<Documents, string> = {
  cdc: "Cahier des charges",
  bp: "Business plan",
  both: "Cahier des charges et business plan",
};

// Les profils, dans les mots de la maquette : on demande à quoi servira le
// document, pas quel « profil » choisir.
export const CDC_PROFILES = [
  { value: "consultation", label: "Consulter des prestataires" },
  { value: "cadrage", label: "Cadrer mon projet" },
] as const;

export const BP_PROFILES = [
  { value: "banque", label: "Une banque ou un financeur public" },
  { value: "investisseur", label: "Un investisseur privé" },
] as const;

export const STATUS_TAG: Record<RunStatus, { label: string; done: boolean }> = {
  idle: { label: "En cours", done: false },
  running: { label: "En cours", done: false },
  waiting: { label: "À vous de répondre", done: false },
  failed: { label: "Interrompu", done: false },
  done: { label: "Terminé", done: true },
};

export function sectionTitle(catalogue: Catalogue, document: DocumentKind, sectionId: string): string {
  return catalogue.documents[document].sections.find((s) => s.id === sectionId)?.titre ?? sectionId;
}

/** `bp.etude_marche` devient « BP · Étude de marché ». */
export function qualifiedTitle(catalogue: Catalogue, qualified: string): string {
  const [document, sectionId] = qualified.split(".", 2);
  if (document !== "cdc" && document !== "bp") return qualified;
  return `${DOCUMENT_SHORT[document]} · ${sectionTitle(catalogue, document, sectionId)}`;
}

export function sectionCount(catalogue: Catalogue, documents: Documents, profilCdc: string, profilBp: string): number {
  const count = (document: DocumentKind, profil: string) =>
    catalogue.documents[document].sections.filter((s) => s.profils.includes(profil)).length;
  return (documents !== "bp" ? count("cdc", profilCdc) : 0) + (documents !== "cdc" ? count("bp", profilBp) : 0);
}

export function projectsHeadline(projects: ProjectSummary[]): string {
  if (projects.length === 0) return "Aucun projet pour l'instant.";
  const ongoing = projects.filter((p) => p.run_status !== "done").length;
  const total = `${projects.length} projet${projects.length > 1 ? "s" : ""}`;
  return ongoing ? `${total}, dont ${ongoing} en cours de rédaction` : total;
}

const relative = new Intl.RelativeTimeFormat("fr", { numeric: "auto" });

export function relativeDate(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "";
  const seconds = Math.round((new Date(iso).getTime() - now.getTime()) / 1000);
  if (Math.abs(seconds) < 60) return "à l'instant";
  const minutes = Math.round(seconds / 60);
  if (Math.abs(minutes) < 60) return relative.format(minutes, "minute");
  const hours = Math.round(seconds / 3600);
  if (Math.abs(hours) < 24) return relative.format(hours, "hour");
  return relative.format(Math.round(seconds / 86_400), "day");
}

export function creationPayload(input: {
  nom: string; documents: Documents; profilCdc: string; profilBp: string; idee: string;
}): ProjectCreation {
  return {
    nom: input.nom.trim(),
    documents: input.documents,
    // Le backend refuse un profil manquant pour un document choisi ; il
    // ignore celui d'un document absent, mais l'envoyer serait mentir sur
    // ce que l'utilisateur a demandé.
    profil_cdc: input.documents !== "bp" ? input.profilCdc : null,
    profil_bp: input.documents !== "cdc" ? input.profilBp : null,
    idee: input.idee.trim(),
  };
}
