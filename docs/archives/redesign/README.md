# Redesign d'Esquisse — maquettes

Maquettes statiques des écrans redessinés. Ouvrez `index.html` : il les liste toutes.

La couleur vient de la refonte Pont (`~/Desktop/PONT/docs/design/redesign`) : encre slate 900
sur blanc cassé. Aucune donnée réelle, aucun appel réseau.

## Ce qui change, et ce qui ne change pas

**L'atelier de rédaction garde sa structure** : plan à gauche, ce qu'on écrit au centre,
mémoire du projet à droite. Il figure ici uniquement pour vérifier que les nouveaux jetons y
tiennent. Tout le reste est redessiné.

| Avant | Maintenant |
|---|---|
| Un seul `globals.css` de 189 lignes, jetons et classes mêlés | Quatre feuilles : jetons, socle, coquille, atelier |
| Mode sombre complet, jamais demandé | Clair uniquement — trois blocs de jetons en moins |
| Trois polices : Bricolage Grotesque, Hanken Grotesk, Source Serif | Deux : Inter pour l'interface, Source Serif pour la prose |
| `--l0` à `--l5` : six couleurs déclarées, deux utilisées | Cinq tons d'état, chacun avec un sens fixe |
| Barre haute : trois éléments à plat pour une seule destination | Marque, fil d'ariane, un menu de compte |
| Connexion : un formulaire nu, la bascule en bouton secondaire | Une carte centrée, deux onglets au clavier |
| Liste de projets : `Chargement…`, puis les fiches d'un coup | Fiches fantômes, puis les vraies — la page ne saute pas |
| Aucun projet : rien du tout | Un vide qui dit quoi faire |
| Barre de progression en pourcentage | Une encoche par section : on lit l'avancement et la taille |
| Trois boutons `aria-pressed` pour choisir les documents | Un groupe radio, navigable aux flèches |
| Puces de profil, qui ne disent pas qu'un seul choix est possible | Un contrôle segmenté |
| Limite des 5 000 caractères visible après l'échec | Un compteur qui se lit pendant la frappe |
| Erreurs en ligne rouge nue | Encarts, du ton de ce qui arrive |

## Les fichiers

```
index.html            sommaire des écrans
css/tokens.css        couleur, mesure, police — la seule source
css/base.css          typographie, boutons, champs, pastilles
css/app.css           barre haute, page, panneaux, fiches, encarts
css/workspace.css     l'atelier : les classes `.m-*`, sur les nouveaux jetons
js/mock.js            menu, onglets, groupes radio, compteur
audit.mjs             le contrôle de responsivité (voir plus bas)
```

## Responsivité

Trois paliers, calés sur ce qu'on fait à l'écran et non sur des appareils.

**Sous 768 px** — tout passe sur une colonne. Les boutons d'une barre d'action prennent la
largeur, et l'action principale remonte au-dessus, là où le pouce arrive. Un contrôle
segmenté cesse d'être une piste et devient une liste d'options empilées. Le fil d'ariane ne
garde que la position courante. L'atelier empile ses trois colonnes, le plan devenant une
bande déroulante de 15 rem de haut.

**De 768 à 1100 px** — les grilles se dédoublent, le fil d'ariane se déplie en entier. Dans
l'atelier, la mémoire du projet passe sous les deux autres colonnes plutôt que de les serrer.

**Au-delà de 1100 px** — l'atelier tient ses trois colonnes. Les grilles de fiches se
remplissent librement, à partir de 17 rem par fiche.

### Le contrôle

`audit.mjs` ouvre les treize pages à 390, 768, 1024 et 1440 px — cinquante-deux combinaisons —
et cherche trois choses : un débordement horizontal, une cible tactile sous 32 px, un lien
interne cassé. Il nomme l'élément fautif quand il en trouve un.

```sh
cd docs/archives/redesign
python3 -m http.server 8731 &
node audit.mjs
```

Il emprunte Playwright à `web/node_modules` : c'est la seule copie du dépôt.

## Notes de reprise

- `js/mock.js` ne fait que du rendu. Chaque fonction dit ce que son composant React devra
  faire : le menu se ferme à Échap et rend le focus, les onglets et les groupes radio
  répondent aux flèches, le compteur change de ton à 90 % de la borne.
- L'atelier emprunte au socle ses boutons, ses champs et ses titres. `workspace.css` ne garde
  que ce qui lui est propre — au port, `.m-btn`, `.m-input`, `.m-label`, `.m-h` et `.m-err`
  deviennent `.btn`, `.input`, `.field__label`, `.t-page` et `.field__error`.
- Deux emplacements des tests de `web/` regardent des classes qui disparaissent :
  `ProjectCard.test.tsx` attend `m-tag done`, `projets.test.tsx` cherche `.m-projects`. Les
  quatre autres (`.m-q`, `.m-planlist`) visent l'atelier et ne bougent pas.
- Les avertissements de l'export — filigrane du brouillon, PDF du convertisseur de secours —
  sont repris mot pour mot. Ils disent une vraie limite, pas une décoration.
- L'écran de génération ne montre pas d'étapes : l'API ne rapporte pas d'avancement, et en
  inventer un serait mentir. Un indicateur, et la raison des deux minutes.
- Inter et Source Serif viennent de Google Fonts. Dans l'application, `next/font` les sert
  depuis le domaine du site.
- `.topbar` recopiait `--ground` à la main dans un `rgba()` : la barre haute ne suivait plus
  le fond si le jeton bougeait. Elle le dérive maintenant avec `color-mix(in srgb, var(--ground)
  88%, transparent)`. `color-mix()` demande Safari 16.2, Chrome 111 ou Firefox 113 ; en deçà,
  la barre perd sa transparence, sans devenir illisible.
- `connexion.html` nichait la note d'aide du mot de passe (`.field__hint`) à l'intérieur du
  `<label>` du champ. Un lecteur d'écran annonce alors le nom du champ suivi de la note
  entière, et c'est aussi ce que `getByLabelText("Mot de passe")` lit : il cesse de
  reconnaître « Mot de passe » tout court. Le champ « Mot de passe » à l'inscription pose
  maintenant la note comme sœur du `<label>`, reliée par `aria-describedby`.
- `connexion.html` ne posait aucun titre : les deux autres écrans d'entrée (compte en
  attente, réveil du serveur) ont chacun un `<h1>`, celui-ci n'en avait pas — rien ne dit à
  qui navigue de titre en titre que la page a changé. Chaque volet (`#volet-connexion`,
  `#volet-creation`) porte maintenant son propre `<h1 class="sr">`, masqué à l'œil parce que
  l'onglet actif dit déjà le même texte visuellement ; un titre visible en plus aurait fait
  doublon avec lui.
- `nouveau-idee.html` avait le même défaut que `connexion.html` : le `<label class="field">`
  du champ « Votre idée » enveloppait à la fois `.field__label` et `.field__count`, si bien
  que `getByLabelText("Votre idée")` lisait « Votre idée 0 / 5 000 » et cessait de reconnaître
  « Votre idée » seul. Le champ pose maintenant un `<div class="field">`, un
  `<label class="field__label" for="idee">` qui ne contient que le texte du champ, et relie
  le compteur et l'indice au `<textarea>` par `aria-describedby`.
- `nouveau-idee.html` posait aussi le champ « Nom du projet » dans un `<label class="field">`
  enveloppant. Il ne portait pas encore d'erreur visible dans la maquette statique, mais la
  même forme dans l'application s'est révélée sujette au même défaut dès qu'un message
  d'erreur s'affiche à l'intérieur. Le champ pose maintenant, comme celui de « Votre idée »,
  un `<div class="field">` et un `<label class="field__label" for="nom">` qui ne contient
  que le texte.
