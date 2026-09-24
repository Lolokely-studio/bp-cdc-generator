# Plan 8 — les décisions prises pendant l'exécution

Le plan 8 a été exécuté par sous-agents, tâche par tâche, avec une revue
après chacune et une revue finale de toute la branche. Trente-huit
décisions ont été prises en cours de route sans que le propriétaire soit
consulté : conflits entre le plan et la réalité, défauts du plan lui-même,
constats de revue à arbitrer.

Elles sont ici pour qu'aucune ne soit prise en secret. Chacune dit ce qui a
été décidé, pourquoi, et **ce que ça coûte si la décision était mauvaise** —
c'est cette dernière ligne qui permet de défaire ce qui mérite de l'être.

Le registre d'exécution complet vivait dans `.superpowers/sdd/`, un
répertoire de travail ignoré par git, supprimé à la fin du chantier. Ce
fichier en est l'extrait durable.

**Ce qui revient le plus souvent :** le plan avait tort. Sept de ses défauts
n'ont été vus qu'à l'exécution — une liste de classes incomplète, un test
qui passait pour une mauvaise raison, une structure de DOM qui cassait son
propre sélecteur, une note d'aide qui polluait le nom accessible d'un champ
(trois fois), une assertion intenable, une énumération de fichiers fausse,
un filtre qui ne trouvait pas ce qu'il annonçait.

---

### 1

P1 — `.m-tag` reste dans l'échafaudage jusqu'à T6, qui le retire en
même temps qu'il convertit `ExportFiles`. Le plan le faisait disparaître en
T4 alors que `ExportFiles` s'en sert encore : la pastille « Brouillon »
serait restée nue pendant deux tâches. — Coût si faux : nul, c'est une règle
morte de plus pendant deux commits.

### 2

P2 — même chose pour `.m-head`, retiré en T6. — Coût si faux : nul.

### 3

P3 — `useSetCrumbs` d'`ExportsView` appartient à T6, qui réécrit le
composant. T2 étape 7 ne le pose plus : elle n'en donne que la forme, pour
que T6 sache quoi écrire. Sans cela, deux tâches insèrent le même appel. —
Coût si faux : le fil d'ariane manque sur l'écran des documents entre T2 et
T6, ce qui se voit tout de suite.

### 4

P4 — T5 n'ajoute pas un second bloc identique : elle élargit le
sélecteur existant en liste. Un bloc dupliqué mot pour mot est exactement ce
qu'une revue signale. — Coût si faux : nul.

### 5

P5 — `.m-note` porte deux sens et ne peut pas tomber sur un seul
ton. Le bandeau passager de la page de projet devient `callout--live` ; le
relevé d'auto-critique de `ReviewPanel`, qui demande qu'on regarde quelque
chose, devient `callout--wait`. — Coût si faux : un encart du mauvais ton,
rattrapable en une ligne.

### 6

P6 — les chemins du test des jetons partent de `import.meta.url` et
non de `process.cwd()`. Le répertoire courant de Vitest dépend d'où la
commande est lancée ; l'URL du module, non. — Coût si faux : nul.

### 7

P7 — la barre haute écrivait `rgba(248, 250, 252, 0.88)`, c'est-à-dire
`--ground` recopié à la main. Elle passe à
`color-mix(in srgb, var(--ground) 88%, transparent)`, et le test des jetons
interdit désormais `rgba(` et `rgb(` hors de `tokens.css`. La maquette est
corrigée en même temps. — Coût si faux : `color-mix` demande Safari 16.2,
Chrome 111, Firefox 113 ; sur un navigateur plus ancien la barre haute perd
sa transparence et reste lisible, puisque `background` retombe sur la
déclaration précédente. Aucun écran ne devient illisible.

### 8

P6 bis — la forme que j'avais mise dans le plan,
``new URL(`../${chemin}`, import.meta.url)``, est cassée sous Vitest avec
l'environnement jsdom : Vite transforme ce motif pour son résolveur
d'assets et perd la partie dynamique. **Vérifié moi-même** par une sonde
jetable : le chemin résout vers `web/tests/undefined`. L'implémenteur a
gardé l'intention (relatif au module, pas au répertoire courant) et changé
la plomberie pour `dirname(fileURLToPath(import.meta.url))` + `join`. La
déviation est acceptée, et le texte du plan est corrigé pour que la tâche 7,
qui amende ce même fichier, ne réintroduise pas la forme cassée. — Coût si
faux : nul, le test lit les mêmes fichiers et porte les mêmes assertions.

### 9

les deux fichiers non suivis `web/AGENTS.md` et `web/CLAUDE.md`
sont générés par `next dev` / `next build` (règles Next pour les agents).
Ils sont ajoutés à `web/.gitignore` plutôt que commités : ils ne sont pas
notre travail, et ils réapparaîtront à chaque construction. — Coût si faux :
si Brice veut les versionner, c'est un `git add -f` et une ligne retirée.

### 10

la liste de classes de la tâche 1 était incomplète — mon erreur
d'écriture du plan. `.m-src` et ses trois modificateurs viennent de
l'ancien `globals.css` et sont posés par `FactsColumn`, `WorkspaceCenter`
et `ReviewPanel` jusqu'à la tâche 7 ; `workspace.css` ne les redéfinit pas,
la nouvelle `.src` du socle porte un autre nom. Les ajouter à
`legacy.css` n'enfreint pas la décision 4 (« aucune règle nouvelle après la
tâche 1 ») : on achève la liste de la tâche 1, on ne l'étend pas. — Coût si
faux : une règle morte de plus, supprimée avec le fichier en tâche 7.

### 11

réserve 1 — le cas « ferme à Échap et rend le focus au bouton »,
que mon plan donnait au caractère près, **passe pour une mauvaise raison**.
Le clic d'ouverture laisse déjà le focus sur le bouton, donc l'assertion
finale est vraie que le code rende le focus ou non. **Vérifié moi-même** :
`button.current?.focus()` retiré, 6/6 passent quand même. Le test est
renforcé — le focus part d'abord sur « Se déconnecter », ce qui est aussi
le vrai parcours au clavier — et l'implémenteur doit prouver la mutation
dans les deux sens. Le plan est corrigé dans le même commit. — Coût si
faux : nul ; un test plus exigeant ne peut pas rendre le code plus faux.

### 12

réserve 2 — `title={email}` ajouté sur l'avatar, absent de mon
brief. `tests/AuthGate.test.tsx` le vérifiait déjà sur l'ancienne barre
haute, et c'est une affordance réelle au survol. Accepté tel quel. — Coût
si faux : nul.

### 13

réserve 3 — le test du `removeEventListener` espionne
`document.removeEventListener` au lieu de vérifier « ne lève rien ». En
React 19 une mise à jour d'état sur un composant démonté est ignorée en
silence : « ne lève rien » ne distinguerait pas le bug du correctif.
Accepté. — Coût si faux : nul, le test devient seulement plus précis.

### 14

ce contrôle devient un test, posé en tâche 3 dans
`tests/tokens.test.ts`. Le plan retire une quarantaine de classes de
l'échafaudage sur six tâches ; une classe retirée mais encore posée ne
casse aucun test — jsdom n'applique pas le CSS — et l'écran s'affiche nu.
C'est arrivé une fois (`.m-src`) et seule une relecture l'a vu. Un test le
verra pour les tâches 4 à 7. C'est une étape de plus que le plan d'origine
ne prévoyait, assumée. — Coût si faux : un test de plus à maintenir, et un
faux positif possible si un composant compose un nom de classe d'une façon
que l'expression régulière ne reconnaît pas — auquel cas il se voit tout de
suite et se corrige en une ligne.

### 15

les comptes de tests attendus du plan étaient faux à partir de la
tâche 2 — la tâche 2 a livré un cas de plus que prévu (le trou du
`removeEventListener`), et mes substitutions en chaîne s'étaient
télescopées sur deux valeurs identiques. Recalés sur le réel :
136 / 144 / 149 / 154 / 161 / 162 / 163. — Coût si faux : un implémenteur
qui doute de son propre compte ; rattrapable en le mesurant.

### 16

la mise en garde du plan sur `next/link` hors routeur (tâche 3,
étape 5) était spéculative. **Vérifié par sonde jetable** : un `next/link`
monté seul sous Vitest et jsdom, sans routeur, se rend et porte son `href`.
`WakeGate.test.tsx` n'a rien à changer. Le plan porte maintenant le fait au
lieu de la supposition, et interdit le contournement par `vi.mock` — si ça
échoue, c'est que le montage a bougé et il faut le dire. — Coût si faux :
nul ; si le montage bouge, l'implémenteur remonte au lieu de masquer.

### 17

Critique — le fil d'ariane disparaît **entièrement** sous 48 rem.
`app.css` porte `.crumbs > :not(.crumbs__here) { display: none }`, mais mon
`Crumbs.tsx` enveloppait chaque maillon dans un `<span>` sans classe : c'est
lui l'enfant direct, et le sélecteur le masque avec les autres. **Vérifié
moi-même** sur la structure rendue : aucun enfant direct ne porte
`crumbs__here`. Ma note du plan affirmait même que l'enveloppe était
« nécessaire » — c'est l'inverse. Corrigé en `Fragment`, comme la maquette
qui est plate, et verrouillé par un test sur la forme du DOM (jsdom
n'applique pas le CSS, on ne peut pas tester le masquage lui-même). — Coût
si faux : nul ; la maquette prouve que la forme plate fonctionne, l'audit
de responsivité y était passé.

### 18

le Mineur « identifiants en français » est requalifié en Important.
**Vérifié** : tout le code existant de `web/` nomme ses identifiants en
anglais, sans exception — la contrainte n'est pas décorative. Mon plan s'en
écartait dans tous ses blocs de code, et cinq tâches allaient recopier le
style. Corrigé dans le plan pour les tâches 3 à 7 et dans la tâche 2 par la
ronde de correction. **Borné** : on ne rouvre pas rétroactivement les
fichiers déjà livrés, sauf `tokens.test.ts` que la tâche 3 modifie déjà.
— Coût si faux : un mélange de conventions dans un seul fichier de test si
je me suis trompé sur la convention ; le reste du dépôt tranche.

### 19

réserve 2 — l'écran de connexion n'a aucun titre. Le relecteur le
juge fidèle à la maquette, et il a raison : `connexion.html` n'en pose pas
non plus. Je le traite quand même comme un défaut réel, pour deux raisons —
une page sans titre ne donne aucun repère à qui navigue de titre en titre,
et `npm run e2e` cassera à la tâche 7, qui le lance
(`e2e/documents.spec.ts:67`, seul endroit cassé ; la ligne 66 reste bonne).

### 20

le Mineur — « Entrez les identifiants d'un compte activé. » a
disparu dans la fusion des deux notes de pied. Ma table des libellés ne
l'avait pas listée ; l'implémenteur a suivi mon snippet fidèlement. **Je
garde la disparition** : la note commune dit déjà qu'un compte doit être
activé, et elle le dit dans les deux modes plutôt qu'un seul. La table du
plan reçoit la ligne manquante, pour qu'elle cesse de mentir. — Coût si
faux : une phrase à remettre, une ligne.

### 21

réserve 1 — `expect(queryByRole("link")).toBeNull()` dans le test
du chargement était intenable : « Nouveau projet » est un lien rendu sans
condition, y compris dans la maquette. Remplacé par un comptage des vraies
fiches. Accepté. — Coût si faux : nul, l'intention du cas est la même.

### 22

réserve 2 — mon plan disait que le remplacement mécanique des cinq
classes touchait trois fichiers. Il en touchait **dix**. L'implémenteur les
a tous traités, sans quoi le garde-fou tombait. Ce n'était pas une
énumération assumée mais une erreur ; le plan porte désormais la liste
réelle. — Coût si faux : nul.

### 23

le troisième point est le plus important, et c'est **le garde-fou
qui est en faute, pas le code**. Son découpeur coupait sur `[\s${}]+`, donc
`` `tag tag--${tone}` `` lui donnait `tag`, `tag--` et `tone` — un préfixe
incomplet et un nom de variable pris pour des classes. L'implémenteur a
hissé l'expression dans une variable pour le faire taire : le code pliait
devant le test, et le garde-fou devenait aveugle à cet attribut. Corrigé à
la source : on découpe d'abord sur les interpolations, puis on jette tout
jeton collé à l'une d'elles. **Prototypé et vérifié sur neuf cas avant
envoi**, dont ceux qui arriveront aux tâches 5 à 7
(`steps__item--${state}`, `src src--${badge.className}`,
`field__count${tone}`). `ProjectCard` revient à l'écriture naturelle. —
Coût si faux : le garde-fou ne vérifie pas les classes composées à
l'exécution, limite désormais écrite dans son commentaire ; il garde sa
vraie fonction, attraper une classe littérale devenue orpheline.

### 24

Important — le filtre d'état ne trouve pas tout ce qu'il annonce.
`idle` et `running` portent le même libellé « En cours » sur la fiche, mais
`filterProjects` comparait les valeurs brutes : un projet `idle` affichait
« En cours » et disparaissait quand on filtrait dessus. **Vérifié
moi-même** dans `lib/labels.ts` : les deux rendent bien
`{ label: "En cours" }`. Le code venait de mon plan au caractère près.
Corrigé en comparant le libellé plutôt que la valeur, ce qui garde le type
`Filters` et la liste `STATUSES` inchangés. — Coût si faux : si un jour
deux états devaient être filtrables séparément malgré un libellé commun,
il faudrait filtrer sur la valeur et donner deux libellés distincts ; ce
serait de toute façon le vrai correctif.

### 25

le second défaut est **le même piège qu'à la tâche 3** — mon plan
niche une note ou un compteur dans le `<label>`, ce qui les fait entrer
dans le nom accessible du champ et casse `getByLabelText`. Deux fois, c'est
un motif, pas un accident. **Vérifié** : les tâches 6 et 7 le décrivent
encore en toutes lettres — « `ReopenForm` … avec `<label className="field">`
… `.field__hint` », et la table de correspondance qui mappe `.m-label` vers
« dans un `<label className="field">` » et `.m-q` vers `.field` alors qu'une
question porte une note d'aide et une case à cocher. Plutôt que de le
corriger une troisième fois après coup, la règle entre dans les
**contraintes globales**, qui voyagent avec chaque brief, et les textes des
tâches 6 et 7 sont repris. — Coût si faux : une contrainte de plus à lire ;
elle ne contraint rien qui ne soit déjà vrai du code existant.

### 26

le premier défaut — mon étape 8 listait `.m-chips`, `.m-chip`,
`.m-cap` et `.m-actions` parmi les classes à retirer de l'échafaudage alors
qu'elles servent encore à neuf composants jusqu'aux tâches 6 et 7.
L'implémenteur n'a retiré que les quatre réellement orphelines. C'est le
même genre d'erreur que `.m-tag`/`.m-head` à la tâche 4, que j'avais
attrapée au pré-vol ; celle-ci m'avait échappé. Accepté tel quel. — Coût si
faux : nul, le garde-fou aurait de toute façon refusé le retrait.

### 27

l'Important est la **troisième** occurrence du piège du `<label>`,
et cette fois c'est une **régression** : le champ « Nom du projet » était
correct avant la tâche (`git show c3746c7` : `<label htmlFor="nom">` non
enveloppant, erreur en frère), et la recomposition l'a enveloppé avec son
message d'erreur dedans. **Prouvé moi-même par sonde jetable** : une fois
l'erreur affichée, `getByLabelText("Nom du projet")` échoue sur *Unable to
find a label with the text of: Nom du projet*. Aucun test de la suite ne le
voyait — le cas qui déclenche cette erreur la cherche par `getByText`.
Corrigé sur le modèle du champ « Votre idée », plus un test de
non-régression qui couvre les deux champs. — Coût si faux : nul, la forme
corrigée est celle d'avant la tâche.

### 28

la re-revue a relevé que la maquette devenait incohérente — un
fichier à la forme corrigée, les autres à l'ancienne. J'ai balayé les
treize maquettes : **cinq étiquettes polluées subsistaient**, et ce sont
exactement celles que les tâches 6 et 7 vont porter — la consigne de
réouverture dans `documents.html` et `documents-rendu.html`, et les trois
questions d'`atelier-questions.html`. Le piège était donc dans la référence
elle-même, prêt à se refermer deux fois de plus. Corrigées toutes les cinq
avant de lancer la tâche 6, note ajoutée au README de la maquette.
Trouvé au passage un défaut que je ne cherchais pas : la case « je ne sais
pas » était un `<span>` niché dans l'étiquette du champ, donc son clic
rivalisait avec celui du champ. Elle est maintenant son propre
`<label class="check">`. **Audit de responsivité des maquettes repassé
après ces changements de balisage : 52 combinaisons, rien à signaler.**
— Coût si faux : la maquette s'écarte de ce que le code fera ; mais c'est
le code qui suit la règle, et les tâches 6 et 7 la portent dans leur brief.

### 29

mon étape 5 demandait de retirer `.m-note` de l'échafaudage, alors
que `ReviewPanel` et `projets/[id]/page.tsx` s'en servent jusqu'à la
tâche 7. C'est la **troisième** fois que ma liste de retraits emporte une
classe encore vivante (après `.m-tag`/`.m-head` au pré-vol et les quatre de
la tâche 5). Le garde-fou aurait attrapé celle-ci — il fait son travail.
Accepté tel quel, plan corrigé. — Coût si faux : nul.

### 30

réserve orthographique de l'implémenteur — ma maquette et mon plan
écrivaient « Regénérer », sans accent. « Régénérer » est la bonne
orthographe, et c'est celle que le code a gardée. **Vérifié** : la faute
n'était que dans mes deux fichiers de référence, jamais dans le code.
Corrigée dans les deux ; partira avec le commit de la tâche 7. — Coût si
faux : aucun, c'est de l'orthographe.

### 31

réserve 3 de l'implémenteur — il n'a pas fait la revue visuelle de
l'étape 8, par prudence envers un serveur de développement branché sur la
vraie configuration du poste. La prudence est justifiée, mais l'étape ne
l'est pas moins : **personne n'avait encore regardé l'application portée**,
tout ayant été vérifié par lecture et par tests. Je l'ai faite moi-même
avec le harnais de bout en bout, qui tourne sur la base jetable et le
modèle simulé — aucun risque pour la configuration du poste. Spec jetable,
supprimée après lecture.

### 32

le relecteur signale que `responsive.spec.ts` ne couvre que les
quatre routes de mon brief — l'atelier et les documents en sont absents.
C'est une lacune de mon plan, et elle porte à conséquence : **l'atelier est
le seul écran à trois colonnes du produit**, avec deux replis successifs
(la mémoire passe dessous à 1100 px, tout s'empile à 760 px). Les quatre
routes couvertes sont des colonnes simples. Un garde-fou qui protège le
facile et laisse le difficile à nu ne protège pas grand-chose. Je fais
étendre le contrôle aux deux écrans manquants. — Coût si faux : un cas de
bout en bout de plus à maintenir, et quelques secondes de suite.

### 33

mais en lisant ce nouveau cas, j'ai trouvé un défaut dans ce que
**j'avais spécifié**. Il clique la première fiche de projet, dont la
destination dépend de l'état : un projet terminé mène aux documents, les
autres à l'atelier. Lors de mon exécution la première fiche était
« Terminé » — donc le cas n'a testé que les documents, et **l'atelier n'a
jamais été visité**. Exactement l'écran pour lequel j'avais demandé ce cas.
Un test dont le nom promet plus qu'il ne vérifie rassure à tort. Second
défaut de ma spécification : le `test.skip` conditionnel, qui laisserait
passer un montage cassé en silence. Corrigé — on prend l'identifiant du
projet et on visite les deux routes, et l'absence de projet devient une
assertion dure. — Coût si faux : le cas devient plus lent de quelques
secondes.

### 34

la re-revue ciblée du dernier correctif affirme qu'il reste un faux
vert — « si le projet est terminé, `/projets/{id}` redirige vers
`/projets/{id}/exports` ». **C'est faux, et je l'ai vérifié** : il n'existe
aucun `middleware.ts` dans `web/`, aucun `redirect`, `router.push` ni
`router.replace` dans `app/(app)/projets/[id]/page.tsx`, et cette page rend
toujours `<div className="m-ws">` — la coquille à trois colonnes — quel que
soit le statut. Seul le contenu de la colonne centrale change : `DonePanel`
pour un projet terminé, la prose ou un formulaire sinon. La mise en page à
trois colonnes, avec ses deux replis, est donc bien exercée aux quatre
largeurs dans les deux cas. Le constat est écarté. — Coût si faux : si une
redirection était ajoutée un jour, le cas testerait deux fois le même
écran ; le nom du cas et son commentaire disent ce qu'il vise, un futur
lecteur le verrait.

### 35

constat 3, la couleur en dur du `data:` URI du `.select`. Un URI de
données ne peut pas lire une variable CSS : c'est une limite du procédé,
pas un oubli. On ajoute un commentaire disant que la valeur duplique
`--ink-soft` et doit suivre si le jeton change, on ne feint pas de la
corriger. — Coût si faux : si `--ink-soft` change, la flèche du menu
déroulant ne suit pas ; le commentaire est là pour ça.

### 36

constat 4, les angles morts du garde-fou des classes orphelines.
C'est un garde-fou, pas une preuve. Sa limite est écrite dans son
commentaire, et il a attrapé deux vrais défauts pendant le chantier. On ne
le rend pas plus malin aujourd'hui. — Coût si faux : une classe composée à
l'exécution pourrait devenir orpheline sans qu'il le dise.

### 37

constat 10, les deux lignes de `web/.gitignore`. Elles ignorent
`AGENTS.md` et `CLAUDE.md`, régénérés par `next dev` et `next build`. C'est
moi qui les ai ajoutées, c'est voulu. — Coût si faux : un `git add -f` si
Brice veut les versionner.

### 38

les deux mineurs que la revue plaçait après la fusion —
`STATUS_TAG[…].done` mort et l'`aria-valuetext` des encoches — sont pris
maintenant. Il y a un commit de correction de toute façon, et la revue elle
même notait que le premier devait l'accompagner s'il existait. — Coût si
faux : un commit un peu plus large.

