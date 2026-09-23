/* ==========================================================================
   Esquisse — les gestes de la maquette
   Rien ici n'enregistre quoi que ce soit : ces quelques fonctions servent à
   montrer comment les pièces réagissent. Dans l'application, chacune
   devient un composant React ; ce fichier dit ce qu'il doit faire.
   ========================================================================== */

/* --- Le menu du compte ---------------------------------------------------
   Une seule cible dans la barre haute. Elle s'ouvre au clic, se ferme à
   Échap, au clic dehors, et rend le focus au bouton.
   ---------------------------------------------------------------------- */
function menuCompte(root) {
  const bouton = root.querySelector(".account__btn");
  const menu = root.querySelector(".account__menu");
  if (!bouton || !menu) return;

  const ouvrir = (ouvert) => {
    menu.hidden = !ouvert;
    bouton.setAttribute("aria-expanded", String(ouvert));
  };

  bouton.addEventListener("click", (e) => {
    e.stopPropagation();
    ouvrir(menu.hidden);
  });

  document.addEventListener("click", (e) => {
    if (!menu.hidden && !root.contains(e.target)) ouvrir(false);
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !menu.hidden) {
      ouvrir(false);
      bouton.focus();
    }
  });
}

/* --- Onglets connexion / création ---------------------------------------
   De vrais onglets : flèches gauche/droite, Début et Fin, un seul arrêt de
   tabulation dans la bande.
   ---------------------------------------------------------------------- */
function onglets(bande) {
  const tabs = [...bande.querySelectorAll('[role="tab"]')];

  const choisir = (tab, donnerLeFocus = true) => {
    tabs.forEach((t) => {
      const actif = t === tab;
      t.setAttribute("aria-selected", String(actif));
      t.tabIndex = actif ? 0 : -1;
      const panneau = document.getElementById(t.getAttribute("aria-controls"));
      if (panneau) panneau.hidden = !actif;
    });
    if (donnerLeFocus) tab.focus();
  };

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => choisir(tab, false));
    tab.addEventListener("keydown", (e) => {
      const i = tabs.indexOf(tab);
      if (e.key === "ArrowRight") choisir(tabs[(i + 1) % tabs.length]);
      else if (e.key === "ArrowLeft") choisir(tabs[(i - 1 + tabs.length) % tabs.length]);
      else if (e.key === "Home") choisir(tabs[0]);
      else if (e.key === "End") choisir(tabs[tabs.length - 1]);
      else return;
      e.preventDefault();
    });
  });
}

/* --- Groupes à choix unique ---------------------------------------------
   Sert aux trois tuiles de documents comme au contrôle segmenté des
   profils : même comportement, deux apparences.
   ---------------------------------------------------------------------- */
function choixUnique(groupe) {
  const options = [...groupe.querySelectorAll('[role="radio"]')];

  const choisir = (option, donnerLeFocus = true) => {
    options.forEach((o) => {
      const actif = o === option;
      o.setAttribute("aria-checked", String(actif));
      o.tabIndex = actif ? 0 : -1;
    });
    if (donnerLeFocus) option.focus();
    groupe.dispatchEvent(new CustomEvent("choix", { detail: option.dataset.valeur }));
  };

  options.forEach((option) => {
    option.addEventListener("click", () => choisir(option, false));
    option.addEventListener("keydown", (e) => {
      const i = options.indexOf(option);
      if (e.key === "ArrowRight" || e.key === "ArrowDown") choisir(options[(i + 1) % options.length]);
      else if (e.key === "ArrowLeft" || e.key === "ArrowUp") choisir(options[(i - 1 + options.length) % options.length]);
      else if (e.key === " ") choisir(option);
      else return;
      e.preventDefault();
    });
  });
}

/* --- Compteur de caractères ---------------------------------------------
   La borne est celle du schéma de l'API. On la montre pendant la frappe :
   avant, elle n'apparaissait qu'en échec, après l'envoi.
   ---------------------------------------------------------------------- */
function compteur(champ) {
  const sortie = document.getElementById(champ.dataset.compteur);
  const max = Number(champ.getAttribute("maxlength") || champ.dataset.max);
  if (!sortie || !max) return;

  const rendre = () => {
    const n = champ.value.length;
    sortie.textContent = `${n.toLocaleString("fr-FR")} / ${max.toLocaleString("fr-FR")}`;
    sortie.classList.toggle("field__count--near", n >= max * 0.9 && n <= max);
    sortie.classList.toggle("field__count--over", n > max);
  };

  champ.addEventListener("input", rendre);
  rendre();
}

/* --- Ce que la page demande ---------------------------------------------- */
document.querySelectorAll(".account").forEach(menuCompte);
document.querySelectorAll('[role="tablist"]').forEach(onglets);
document.querySelectorAll('[role="radiogroup"]').forEach(choixUnique);
document.querySelectorAll("[data-compteur]").forEach(compteur);

/* Le choix des documents commande l'affichage des deux questions de profil :
   on ne demande pas à quoi servira un cahier des charges qu'on ne rédige
   pas. */
const documents = document.getElementById("choix-documents");
if (documents) {
  documents.addEventListener("choix", (e) => {
    const quoi = e.detail;
    document.querySelectorAll("[data-visible-si]").forEach((bloc) => {
      bloc.hidden = !bloc.dataset.visibleSi.split(" ").includes(quoi);
    });
  });
}
