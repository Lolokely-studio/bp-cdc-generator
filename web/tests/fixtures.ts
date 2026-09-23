import type { Catalogue, ProjectState, ProjectSummary } from "@/lib/contracts";

// Un catalogue réduit, mais qui porte chaque cas qu'un écran distingue :
// une section propre à un profil, chaque type de fait.
export const catalogue: Catalogue = {
  documents: {
    cdc: {
      profils: { consultation: "Envoyé à des prestataires.", cadrage: "Document interne." },
      sections: [
        { id: "contexte_objectifs", titre: "Contexte et objectifs", ordre_lecture: 1,
          profils: ["consultation", "cadrage"], validation: "toujours" },
        { id: "perimetre", titre: "Périmètre", ordre_lecture: 2,
          profils: ["consultation", "cadrage"], validation: "si_note_basse" },
        { id: "cadre_reponse", titre: "Cadre de réponse", ordre_lecture: 3,
          profils: ["consultation"], validation: "si_note_basse" },
      ],
    },
    bp: {
      profils: { banque: "Banque.", investisseur: "Investisseur." },
      sections: [
        { id: "etude_marche", titre: "Étude de marché", ordre_lecture: 1,
          profils: ["banque", "investisseur"], validation: "si_note_basse" },
        { id: "compte_resultat", titre: "Compte de résultat", ordre_lecture: 2,
          profils: ["banque"], validation: "toujours" },
      ],
    },
  },
  faits: {
    budget_projet: { libelle: "Budget projet", type: "montant", unite: null, options: [], exemple: 60000 },
    concurrents: { libelle: "Concurrents directs", type: "liste", unite: null, options: [], exemple: null },
    positionnement_prix: { libelle: "Positionnement tarifaire", type: "choix", unite: null,
      options: ["entree_de_gamme", "milieu_de_gamme", "premium"], exemple: null },
    hypothese_croissance: { libelle: "Croissance", type: "pourcentage", unite: null, options: [], exemple: null },
    delai_paiement_clients: { libelle: "Délai de paiement client", type: "duree", unite: "jours",
      options: [], exemple: null },
    nom_projet: { libelle: "Nom du projet", type: "texte_court", unite: null, options: [], exemple: "CoachDom." },
    deja_lance: { libelle: "Déjà lancé", type: "booleen", unite: null, options: [], exemple: null },
    date_lancement_visee: { libelle: "Date de lancement visée", type: "date", unite: null, options: [], exemple: null },
  },
};

export function summary(overrides: Partial<ProjectSummary> = {}): ProjectSummary {
  return {
    id: "p-1", nom: "CoachDom", documents: "cdc", profil_cdc: "cadrage", profil_bp: null,
    run_status: "running", created_at: "2026-09-22T08:00:00Z", updated_at: "2026-09-22T08:00:00Z",
    sections_faites: 0, sections_total: 2, ...overrides,
  };
}

export function projectState(overrides: Partial<ProjectState> = {}): ProjectState {
  return {
    projet: summary(),
    plan: [
      { document: "cdc", section_id: "contexte_objectifs", order: 0 },
      { document: "cdc", section_id: "perimetre", order: 1 },
    ],
    curseur: 0,
    faits: {},
    sections: [],
    interaction: null,
    ...overrides,
  };
}
