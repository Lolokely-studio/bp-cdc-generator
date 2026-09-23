import { z } from "zod";

// Les contrats de l'API, tels que le backend les rend. Chaque réponse passe
// par l'un d'eux : un champ renommé côté serveur échoue ici, bruyamment, au
// lieu de s'afficher `undefined` trois écrans plus loin. Les noms de champs
// restent ceux du contrat, en français.

export const RunStatus = z.enum(["idle", "running", "waiting", "failed", "done"]);
export type RunStatus = z.infer<typeof RunStatus>;

export const Documents = z.enum(["cdc", "bp", "both"]);
export type Documents = z.infer<typeof Documents>;

export const DocumentKind = z.enum(["cdc", "bp"]);
export type DocumentKind = z.infer<typeof DocumentKind>;

export const ProjectSummary = z.object({
  id: z.string(),
  nom: z.string(),
  documents: Documents,
  profil_cdc: z.string().nullable(),
  profil_bp: z.string().nullable(),
  run_status: RunStatus,
  created_at: z.string().nullable().optional(),
  updated_at: z.string().nullable().optional(),
  sections_faites: z.number().int(),
  sections_total: z.number().int(),
});
export type ProjectSummary = z.infer<typeof ProjectSummary>;

export const Block = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("paragraph"), text: z.string() }),
  z.object({
    kind: z.literal("table"),
    number: z.number(),
    title: z.string(),
    columns: z.array(z.string()),
    rows: z.array(z.array(z.string())),
  }),
  z.object({ kind: z.literal("list"), items: z.array(z.string()) }),
  z.object({ kind: z.literal("placeholder"), label: z.string() }),
]);
export type Block = z.infer<typeof Block>;

export const PlanRef = z.object({ document: DocumentKind, section_id: z.string(), order: z.number() });
export type PlanRef = z.infer<typeof PlanRef>;

// `value` à `null` avec `source: "user"`, c'est « je ne sais pas » : une
// réponse, pas une absence.
export const Fact = z.object({
  fact_id: z.string(),
  value: z.unknown(),
  source: z.enum(["user", "deduced"]),
  confidence: z.number().nullable().optional(),
});
export type Fact = z.infer<typeof Fact>;

export const Section = z.object({
  section_id: z.string(),
  document: DocumentKind,
  ordre: z.number(),
  statut: z.string(),
  blocks: z.array(Block),
  note: z.number().nullable(),
  revisions: z.number(),
});
export type Section = z.infer<typeof Section>;

export const QuestionsInteraction = z.object({
  id: z.string(),
  kind: z.literal("questions"),
  questions: z.array(z.object({ fact_id: z.string(), question: z.string() })),
});
export type QuestionsInteraction = z.infer<typeof QuestionsInteraction>;

export const ReviewInteraction = z.object({
  id: z.string(),
  kind: z.literal("review"),
  section: z.string(),
  score: z.number().nullable(),
  problems: z.array(z.string()),
  blocks: z.array(Block).default([]),
});
export type ReviewInteraction = z.infer<typeof ReviewInteraction>;

export const Inconsistency = z.object({
  kind: z.string(),
  description: z.string(),
  sections: z.array(z.string()),
  proposal: z.string().nullable().optional(),
});
export type Inconsistency = z.infer<typeof Inconsistency>;

export const InconsistenciesInteraction = z.object({
  id: z.string(),
  kind: z.literal("inconsistencies"),
  inconsistencies: z.array(Inconsistency),
});
export type InconsistenciesInteraction = z.infer<typeof InconsistenciesInteraction>;

export const Interaction = z.discriminatedUnion("kind", [
  QuestionsInteraction, ReviewInteraction, InconsistenciesInteraction,
]);
export type Interaction = z.infer<typeof Interaction>;

export const ProjectState = z.object({
  projet: ProjectSummary,
  plan: z.array(PlanRef),
  curseur: z.number(),
  faits: z.record(z.string(), Fact),
  sections: z.array(Section),
  interaction: Interaction.nullable(),
});
export type ProjectState = z.infer<typeof ProjectState>;

export const FactDefinition = z.object({
  libelle: z.string(),
  type: z.string(),
  unite: z.string().nullable(),
  options: z.array(z.string()),
  exemple: z.unknown().optional(),
});
export type FactDefinition = z.infer<typeof FactDefinition>;

export const SectionTemplate = z.object({
  id: z.string(),
  titre: z.string(),
  ordre_lecture: z.number(),
  profils: z.array(z.string()),
  validation: z.string(),
});
export type SectionTemplate = z.infer<typeof SectionTemplate>;

const DocumentTemplate = z.object({
  profils: z.record(z.string(), z.string()),
  sections: z.array(SectionTemplate),
});

export const Catalogue = z.object({
  documents: z.object({ cdc: DocumentTemplate, bp: DocumentTemplate }),
  faits: z.record(z.string(), FactDefinition),
});
export type Catalogue = z.infer<typeof Catalogue>;

export const ExportFile = z.object({
  document: DocumentKind,
  format: z.enum(["docx", "pdf"]),
  brouillon: z.boolean(),
  fidele: z.boolean(),
  lien: z.string(),
  cree_le: z.string(),
});
export type ExportFile = z.infer<typeof ExportFile>;

export const Exports = z.object({
  en_cours: z.boolean(),
  dernier_export: z.enum(["ok", "echec"]).nullable(),
  fichiers: z.array(ExportFile),
});
export type Exports = z.infer<typeof Exports>;

export const Me = z.object({ email: z.string(), compte_actif: z.boolean() });
export const LoginResult = z.object({ jeton: z.string() });
export const RegisterResult = z.object({ compte_actif: z.boolean(), message: z.string() });
export const AnswerResult = z.object({ rejoue: z.boolean(), run_status: z.string() });
export const ResumeResult = z.object({ reprise: z.boolean(), run_status: z.string() });
export const ReopenResult = z.object({
  sections: z.array(z.string()),
  touchees: z.number(),
  run_status: z.string(),
});
export const LaunchResult = z.object({ export: z.string() });
export const Health = z.object({ statut: z.string() });
