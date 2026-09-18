# Que doit contenir un cahier des charges et un business plan

> Document de travail pour Esquisse — 17 septembre 2026.
> Il sert de source aux templates `cdc.yaml`, `bp.yaml`, `catalogue-faits.yaml` et aux grilles de relecture.
> Il n'est pas figé : chaque section traitée en atelier vient l'enrichir.

---

## 1. Cahier des charges : deux traditions, pas une

Il n'existe pas un plan unique du cahier des charges. Deux familles cohabitent, et elles ne répondent pas à la même question.

### 1.1 La tradition normative (AFNOR)

La norme **NF X50-151**, *Expression fonctionnelle du besoin et cahier des charges fonctionnel*, a longtemps servi de référence pour les projets industriels comme informatiques. Elle a été **remplacée en février 2013 par la NF EN 16271**. Sa logique : décrire le besoin en termes de **fonctions** et de **niveaux à atteindre**, jamais en termes de solution, pour laisser au fournisseur la liberté de proposer.

**1) Présentation générale du problème**

| Sous-partie | Information attendue |
|---|---|
| Projet | Présentation, finalités, retour sur investissement envisagé |
| Contexte | Situation générale de l'organisation, autres projets en cours, études déjà menées sur le sujet ou des sujets similaires, parties concernées, confidentialité |
| Énoncé du besoin | Services rendus par le produit à l'utilisateur final |
| Environnement du produit | Personnes, équipements et matériaux impliqués, contraintes environnementales, caractéristiques de chaque élément |

**2) Expression fonctionnelle du besoin**

| Sous-partie | Information attendue |
|---|---|
| Fonctions de service et de contrainte | Fonctions principales, fonctions complémentaires, contraintes limitant la liberté du réalisateur |
| Critères d'appréciation | Ce qui permettra de juger qu'une fonction est remplie |
| Niveaux des critères | Niveau **indispensable** et niveau **souhaité, révisable**, avec la flexibilité admise |

**3) Cadre de réponse**

| Sous-partie | Information attendue |
|---|---|
| Par fonction | Solution proposée, niveau atteint, modalités de contrôle, décomposition des coûts |
| Pour l'ensemble | Prix global, options et variantes, mesures d'adaptation aux contraintes, outils de mise en place et de maintenance, prévisions de fiabilité |

Le couple **critère + niveau** est l'apport le plus réutilisable de cette norme : il transforme une exigence molle en exigence vérifiable, et il alimente directement la recette.

### 1.2 La tradition praticienne (projets web et logiciels)

Plan plus opérationnel, orienté consultation d'un prestataire :

- **Contexte et objectifs** — problème résolu, profils d'utilisateurs, objectifs **mesurables** (gain de temps, chiffre d'affaires, réduction d'erreurs), description de l'existant et de ses limites, données à migrer.
- **Fonctionnalités** — listées par ordre de priorité, sous forme de *user stories* groupées par module. Règle constante : décrire le besoin utilisateur, pas la solution technique ni le choix d'interface.
- **Contraintes techniques** — hébergement (cloud, on-premise, infogéré), performance (utilisateurs simultanés, temps de réponse), sécurité et RGPD, intégrations externes (ERP, CRM, API), accessibilité (RGAA).
- **Planning et budget** — enveloppe budgétaire, jalons critiques, approche MVP pour maîtriser les coûts.
- **Maintenance et vie après la mise en production** — qui maintient, comment les évolutions sont traitées, calendrier des mises à jour.

Volume conseillé : 15 à 25 pages pour la plupart des projets.

### 1.3 La règle de rédaction à retenir

> Chaque exigence doit être assez précise pour vérifier objectivement si elle est remplie.

« Interface moderne » est proscrit. « Temps de chargement sous 2 secondes », « conformité à la charte graphique fournie », « score d'accessibilité minimal » sont des exigences. Cette règle devient un critère de grille dans nos templates.

---

## 2. Business plan : la trame Bpifrance

Bpifrance Création décrit un business plan en huit blocs. Le document formalise le projet dans toutes ses dimensions : économique, marketing, commerciale, juridique, organisationnelle et financière.

| # | Bloc | Information attendue |
|---|---|---|
| 1 | Sommaire | Placé avant l'executive summary |
| 2 | Executive summary | Synthèse « vendeuse », une à deux pages. **À rédiger en dernier** |
| 3 | Porteur de projet et équipe | Expérience pertinente, motivations et objectifs personnels, complémentarité de l'équipe |
| 4 | Présentation générale du projet | Genèse de l'idée, motivations, objectifs poursuivis, atouts pour réussir |
| 5 | Partie économique | Produits et services, résultats de l'étude de marché, caractéristiques des clients potentiels, analyse concurrentielle, stratégie commerciale et positionnement, chiffre d'affaires prévisionnel, moyens opérationnels, modèle économique |
| 6 | Partie financière | Voir §2.1 |
| 7 | Partie juridique | Justification du régime juridique choisi, répartition du capital et des pouvoirs |
| 8 | Partie documentaire | Pièces justificatives et annexes, en dossier séparé |

**Qualités attendues du document** : soigné, concis (10 à 30 pages hors annexes), complet, clairement rédigé, logiquement structuré, précis avec ses sources citées, d'une tonalité « vendeuse mais crédible ».

### 2.1 La partie financière n'est pas un tableau, elle en compte sept

| Tableau | Horizon | Ce qu'il montre |
|---|---|---|
| Tableau des investissements | 3 ans | Matériel et immatériel à acquérir |
| Plan de financement initial | Au démarrage | Compare les besoins (investissements, stock initial, besoin en fonds de roulement, trésorerie de sécurité) aux ressources (apports, emprunts, aides) |
| Compte de résultat prévisionnel | 3 ans | Résultat net, marge, revenus, charges d'exploitation ; permet de simuler plusieurs hypothèses de ventes |
| Plan de trésorerie | 12 mois, mensuel | Vérifie que l'entreprise pourra faire face à ses engagements mois après mois |
| Seuil de rentabilité et point mort | — | Chiffre d'affaires minimal pour couvrir toutes les charges, et le moment où il est atteint |
| Plan de financement à 3 ans | 3 ans | Équilibre durable des ressources et des besoins |
| Tableau d'annuités de crédit | Durée du prêt | Seulement s'il y a emprunt |

Conséquence pour nos templates : **une seule section « Prévisionnel financier » ne suffit pas.** Le compte de résultat, la trésorerie mensuelle et le seuil de rentabilité n'ont ni les mêmes hypothèses d'entrée, ni la même grille de relecture.

---

## 3. Confrontation avec les 21 sections du mockup

Les sections listées dans `mockup.html` (tableau `PLAN`) couvrent l'essentiel, avec cinq manques réels.

| Manque | Document | Pourquoi il compte |
|---|---|---|
| **Partie juridique** | BP | Bpifrance la liste explicitement : forme juridique et sa justification, répartition du capital et des pouvoirs. Aucune section ne la porte aujourd'hui. |
| **Maintenance et vie du produit** | CDC | Toutes les trames praticiennes y insistent. « Livrables, planning et jalons » ne couvre ni la maintenance, ni le traitement des évolutions, ni les engagements de service. |
| **Existant et reprise de données** | CDC | Absent. C'est pourtant l'un des postes qui font le plus dériver un budget. |
| **Charte graphique et identité** | CDC | Présent dans les deux traditions, absent chez nous. |
| **Prévisionnel éclaté** | BP | Une seule section pour sept tableaux. À découper en au moins trois. |

**Ajout recommandé, emprunté à la norme** : des **critères d'appréciation et leurs niveaux** (indispensable / souhaité) sur chaque exigence fonctionnelle. C'est ce qu'un modèle de langage bâcle s'il n'y est pas contraint, et c'est ce qui donne sa matière à la section « Recette et critères d'acceptation » — qui, sans cela, ne sera que du remplissage.

**Ordre de grandeur après correction** : environ 14 sections pour le CDC, environ 15 pour le BP, soit une trentaine au lieu de vingt-et-une. Le tableau `PLAN` du mockup devra être mis à jour une fois le périmètre arrêté.

---

## 4. Décisions prises

Prises le 17 septembre 2026 avec Brice.

**Le CDC sert aux deux usages, selon le projet.** Une question au début du parcours fait basculer entre deux variantes :

- *Consulter des prestataires* — le document doit être opposable. On active le cadre de réponse de la norme : décomposition des coûts demandée, niveaux indispensables et souhaités sur chaque exigence, modalités de contrôle.
- *Cadrer son propre projet* — document interne. Le cadre de réponse et les modalités de consultation disparaissent ; l'accent va sur le périmètre, les priorités et les critères d'acceptation.

**Le BP vise la banque ou l'investisseur privé.** Trame commune, avec des sections dont le ton et le contenu s'adaptent au lecteur choisi au départ :

- *Banque ou financeur public* — la trame Bpifrance s'applique telle quelle, la partie financière est le cœur du document, la prudence des hypothèses prime sur l'ambition.
- *Investisseur privé* — l'accent se déplace vers la taille de marché, la traction, la scalabilité et l'équipe ; le prévisionnel sert à montrer une trajectoire, pas à rassurer sur un remboursement.

**Conséquence sur le graphe** : l'étape 2 du workflow ne pose plus une question mais trois — quels documents, à quoi servira le CDC, qui lira le BP. Les templates portent des sections et des faits **conditionnés par un profil**.

### 4.1 Accès : inscription ouverte, activation manuelle

Décidé le 17 septembre 2026, après avoir constaté que la maquette affichait un tableau de bord « Mes projets » alors que l'authentification avait été retirée du périmètre. Sans compte, l'identifiant du projet serait devenu le mot de passe : qui détient l'URL détient l'idée d'entreprise, le prévisionnel et le budget.

Le choix retenu rétablit l'authentification, mais sous condition :

- Inscription et connexion **gérées par l'API elle-même**, avec pages dédiées. Le service d'authentification de Supabase n'est pas utilisé : seule sa base l'est.
- Une table de comptes porte l'adresse, l'empreinte du mot de passe, et un drapeau `is_active` à faux par défaut, **passé à vrai à la main dans la base**. Un compte créé n'est pas un compte utilisable.
- Chaque projet et chaque document sont rattachés à leur propriétaire. Le cloisonnement est appliqué par l'API, qui filtre toujours sur le propriétaire.
- Un écran « votre compte attend son activation » ferme la création de projet tant que le drapeau est faux.

**Ce que l'authentification maison ajoute au chantier** : empreinte de mot de passe, émission et vérification des jetons de session, expiration et renouvellement, réinitialisation de mot de passe. Ces quatre morceaux étaient fournis par Supabase Auth ; ils sont désormais à écrire et à tenir. C'est un choix assumé, il faut juste le compter dans le plan.

### 4.2 Connexion à la base : pooler en mode transaction

La base est jointe par le pooler Supabase en **mode transaction**, port 6543. La connexion a été testée le 17 septembre 2026 : PostgreSQL 17.6, région `eu-central-1`, schéma `public` encore vide, droits de création et de suppression de table confirmés.

Trois vérifications valent d'être notées, parce qu'elles décident de la façon d'écrire le code.

| Vérification | Résultat | Ce qu'on en fait |
|---|---|---|
| Requêtes préparées | Elles passent. Le pooler de Supabase les gère, contrairement à un pgbouncer classique en mode transaction. | Aucune précaution particulière côté client ; inutile de désactiver la préparation. |
| État de session entre deux transactions | Il a survécu **pendant le test**. | À ne surtout pas en conclure qu'il est fiable : le test était seul sur le pool. En charge, la connexion est réattribuée et l'état disparaît. **Rien ne doit reposer sur une variable de session.** |
| `SET LOCAL` dans une transaction | Fonctionne. | C'est le seul mécanisme sûr pour porter une valeur le temps d'une requête. |

Conséquence directe : puisque l'authentification n'est pas celle de Supabase, `auth.uid()` n'existe pas, et un cloisonnement par politiques de sécurité au niveau des lignes devrait s'appuyer sur une variable posée en `SET LOCAL` à chaque transaction. Le cloisonnement est donc porté par l'API, qui filtre systématiquement sur le propriétaire. Les politiques de ligne peuvent venir plus tard, en seconde barrière.

**Pourquoi ce détour plutôt qu'une inscription libre.** Toute la génération repose sur des paliers gratuits dont les quotas sont journaliers et partagés entre tous les utilisateurs. Une inscription libre exposerait le service à épuiser ses quotas en une matinée. L'activation manuelle est le robinet, et elle ne coûte rien à construire.

---

## 5. Le retournement : des plans aux faits

Tout ce qui précède décrit des **plans**. Esquisse en a déjà un. Ce dont l'agent a besoin, c'est du **catalogue de faits** : l'information atomique qu'il faut avoir collectée pour qu'une section devienne rédigeable.

C'est là que le couple CDC + BP prend son sens, parce qu'un même fait sert des deux côtés.

| Fait | Alimente, côté BP | Alimente, côté CDC |
|---|---|---|
| Prix moyen par unité vendue | Modèle économique, compte de résultat, seuil de rentabilité | — |
| Budget de développement | Investissements, plan de financement initial | Budget et modalités |
| Date de lancement visée | Plan opérationnel, mois de démarrage du chiffre d'affaires en trésorerie | Livrables, planning et jalons |
| Périmètre fonctionnel | Coût de développement, plan opérationnel | Exigences fonctionnelles |
| Cible principale | Étude de marché, stratégie commerciale | Parties prenantes et utilisateurs |

Les lignes « budget de développement » et « date de lancement » sont exactement les incohérences mises en scène à l'étape 15 du mockup (4 mois contre 6 mois, 80 000 € contre 60 000 €). Ce ne sont pas des cas inventés pour la démonstration : ce sont les points de friction structurels entre les deux documents.

---

## 6. Format des templates

Arrêté sur un exemple avant d'en produire une trentaine.

Les trois fichiers vivent dans `backend/app/templates/` : `cdc.yaml`, `bp.yaml` et `catalogue-faits.yaml`.

> `utilise_par` est **dérivé**, pas écrit à la main : il est l'inverse exact de ce que les sections déclarent. Il doit être régénéré à chaque fois qu'une section change de faits.

### 6.1 Une section, dans `bp.yaml`

```yaml
- id: probleme_solution
  document: bp
  titre: "Problème, solution et proposition de valeur"
  ordre: 1
  profils: [banque, investisseur]        # active pour les deux lecteurs
  objectif: >
    Poser en une page ce que le projet change pour quelqu'un de précis,
    et pourquoi cette solution-là plutôt qu'une autre.
  depend_de: []                          # section racine
  longueur_cible: 400-600 mots

  faits_requis: [nom_projet, probleme_resolu, cible_principale, solution_proposee, benefice_mesurable]
  faits_utiles:  [origine_idee, alternatives_actuelles, avantage_differenciant, type_projet]

  consignes: |
    Ouvrir sur le problème vécu, jamais sur la solution.
    Nommer la cible par ce qu'elle fait, pas par une tranche d'âge.
    Décrire ce que la personne fait aujourd'hui faute de mieux : c'est la vraie concurrence.
    Chiffrer le bénéfice si le fait est disponible, sinon écrire le marqueur
    [Donnée à compléter] — ne jamais inventer un chiffre.
    Pour un lecteur « banque » : rester factuel, pas de superlatif.
    Pour un lecteur « investisseur » : montrer en quoi le problème est répandu.

  grille:
    - "Le problème est décrit du point de vue de celui qui le vit, pas du porteur"
    - "La cible est identifiable : on saurait à qui envoyer un message demain"
    - "Ce que la cible fait aujourd'hui faute de mieux est explicite"
    - "Aucun chiffre qui ne vienne d'un fait fourni"
    - "Aucun superlatif invérifiable (révolutionnaire, unique, leader)"
```

### 6.2 Les faits, dans `catalogue-faits.yaml`

```yaml
- id: probleme_resolu
  libelle: "Le problème résolu"
  type: texte_long
  question: "Quel problème concret rencontrent les personnes à qui vous vous adressez ?"
  exemple: "Trouver un coach sportif à domicile se fait au bouche-à-oreille, sans garantie sur son niveau."
  deductible: true                       # extractible de l'idée saisie, à confirmer
  utilise_par: [bp.probleme_solution, bp.resume_executif, cdc.contexte_objectifs]

- id: benefice_mesurable
  libelle: "Le bénéfice, chiffré"
  type: texte_court
  question: "Qu'est-ce que votre solution fait gagner, concrètement ? Un temps, un coût, un risque évité."
  exemple: "Un coach vérifié réservé en moins de 5 minutes, contre plusieurs jours de recherche."
  deductible: false
  utilise_par: [bp.probleme_solution, bp.resume_executif, cdc.contexte_objectifs]
```

### 6.3 Trois principes qui se répètent trente fois

**`utilise_par` fait tout le travail.** C'est lui qui garantit qu'un fait n'est demandé qu'une seule fois, lui qui alimente l'analyse des manques de l'étape 6, et lui qui permettra de savoir quelles sections rouvrir quand un fait change.

**`deductible` sépare deux régimes.** Ce que le modèle peut tirer de l'idée saisie — à confirmer par une question fermée — et ce qu'il ne peut qu'ignorer, donc demander.

**`faits_requis` et `faits_utiles` sont deux niveaux, pas une liste et son reliquat.** Un fait requis rend la section inécrivable tant qu'il manque : il est toujours demandé. Un fait utile n'est ajouté au lot de questions que s'il reste de la place. Dans les deux cas, « Je ne sais pas » reste une réponse valable, et le fait devient une hypothèse déclarée dans le texte. La première version des templates appelait la seconde liste `faits_optionnels`, ce qui encodait une erreur : l'étape 6 ne pose de questions que sur les faits requis, donc 42 faits sur 70 n'auraient jamais été demandés — y compris la masse salariale, que la démonstration du mockup pose pourtant à l'écran.

**La grille est faite de phrases vérifiables.** « Aucun superlatif invérifiable » se vérifie. « Le texte est convaincant » ne se vérifie pas et produira une note aléatoire, donc une boucle de révision aléatoire.

### 6.4 Types de faits

`texte_court` · `texte_long` · `nombre` · `montant` · `pourcentage` · `date` · `duree` · `liste` · `choix` · `booleen`

Les faits de type `montant`, `nombre` et `pourcentage` sont ceux que le vérificateur de chiffres (étape 11) utilise comme référence : tout nombre présent dans un brouillon doit venir d'un de ces faits ou d'un calcul outillé.

---

## 7. Ce que la mise en templates a révélé

Les trois fichiers de `backend/app/templates/` matérialisent tout ce qui précède : **30 sections** (15 pour le BP, 15 pour le CDC) et **74 faits**, dont 12 seulement sont déductibles de l'idée saisie. Tous les renvois croisés sont vérifiés dans les deux sens : aucun fait orphelin, aucune dépendance vers une section générée plus tard.

**Charge de questions.** Sur les 74 faits, **42 sont requis** par au moins une section et 32 ne sont demandés que si le budget de questions de la section le permet. Parmi les 42 requis, 7 sont déductibles de l'idée saisie et ne demandent qu'une confirmation : il reste donc **35 questions réellement ouvertes** pour produire les deux documents complets.

Quatre sections n'ont aucun fait requis, et c'est voulu : les deux sections de risques, le résumé exécutif et le cadre de réponse se déduisent entièrement des sections déjà validées.

**Douze faits sont partagés entre les deux documents** : `type_projet`, `probleme_resolu`, `cible_principale`, `solution_proposee`, `benefice_mesurable`, `porteurs`, `competences_manquantes`, `date_lancement_visee`, `jalons_operationnels`, `budget_developpement`, `perimetre_inclus`, `contraintes_calendaires`. C'est la mesure exacte du gain : douze questions qu'un porteur qui remplirait les deux documents séparément aurait dû traiter deux fois.

### 7.1 Le contrôle de cohérence ne peut pas faire ce que le mockup montre

Et c'est là qu'une contradiction apparaît. Si `budget_developpement` est **un seul fait**, partagé par `cdc.budget_modalites` et `bp.moyens_investissements`, alors les deux documents ne peuvent plus annoncer deux montants différents. L'incohérence mise en scène à l'étape 15 du mockup — *« Budget de développement : 80 000 € dans le CDC, 60 000 € dans le BP »* — devient **impossible par construction**.

Ce n'est pas un défaut, c'est un progrès : prévenir vaut mieux que détecter. Mais cela oblige à redéfinir ce que le contrôle de cohérence vérifie réellement. Il lui reste trois objets, tous légitimes :

1. **Les relations entre faits distincts.** `date_livraison_souhaitee` (quand le produit est livré) et `date_lancement_visee` (quand on commence à vendre) sont deux faits différents, et ils doivent rester ordonnés. Un lancement annoncé avant la livraison est une vraie incohérence, détectable et fréquente. De même, le besoin de financement doit couvrir `investissements_initiaux` **plus** `budget_developpement`.
2. **La dérive du texte par rapport aux faits.** Un nombre apparu dans une section rédigée sans venir d'aucun fait ni d'aucun calcul. C'est déjà le rôle du vérificateur de chiffres à l'étape 11, mais il travaille section par section ; le contrôle final le refait à l'échelle des deux documents.
3. **Les faits révisés après coup.** Une section validée tôt qui cite une valeur modifiée depuis. C'est `utilise_par` qui dit quelles sections rouvrir.

**Conséquence pour le mockup, appliquée le 17 septembre 2026.** Les deux incohérences de l'étape 15 ont été réécrites pour n'opposer que des faits distincts :

| Avant | Après | Ce qui est vérifié |
|---|---|---|
| « Lancement : 4 mois dans le CDC, 6 mois dans le BP » | « Les ventes démarrent à 4 mois dans le BP, la livraison est fixée à 6 mois dans le CDC » | Ordre entre `date_livraison_souhaitee` et `date_lancement_visee` |
| « Budget : 80 000 € dans le CDC, 60 000 € dans le BP » | « Le financement réunit 75 000 €, le besoin total en atteint 90 000 € » | Couverture : ressources ≥ `budget_developpement` + `investissements_initiaux` |

L'ancienne formulation du planning laissait croire que la même date était saisie deux fois. La nouvelle oppose bien deux faits différents, dont l'un doit précéder l'autre.

---

## 8. Ancrage sur des documents réels

Les sections 1 et 2 s'appuient sur des **trames** : des listes de ce qu'un document devrait contenir. Le 17 septembre 2026, les consignes ont été confrontées à des **documents réellement écrits**, ce qui est différent et plus instructif.

### 8.1 Une asymétrie de disponibilité

Côté cahier des charges, la matière est abondante : la commande publique publie ses documents. Le CCTP retenu — refonte du site de Sia Habitat, bailleur social, juin 2022 — fait 47 pages, comprend l'hébergement, la maintenance et le webmastering, et a servi à une vraie consultation.

Côté business plan, l'inverse : un plan d'affaires est confidentiel par nature. Ce qui se publie est soit une trame vide, soit un document d'un autre genre. Le seul document réel et complet trouvé est le plan d'affaires 2007-2010 de la Coopérative des exploitants motorisés de Koutiala (Mali), 66 pages, rédigé avec le CIRAD. Le genre est éloigné — coopérative agricole existante, pas création d'entreprise française — mais sa manière de traiter les hypothèses chiffrées se transpose sans peine.

**Conséquence à assumer :** les consignes du cahier des charges sont désormais adossées à un document réel, celles du business plan restent adossées à la trame Bpifrance plus un seul document d'un autre genre. C'est l'évaluation sur de vrais projets qui devra combler l'écart.

### 8.2 Ce que le CCTP réel a corrigé

| Ce que j'avais écrit | Ce que fait le document réel | Correction |
|---|---|---|
| Exigences numérotées EF-01, en « besoin utilisateur » | Pas de numérotation ; **futur simple d'obligation** — « le CMS prendra en charge », « un bouton proposera » — et description de **situations** : « dès lors qu'une recherche n'aboutira à aucun résultat, un module proposera… » | Numérotation conservée pour que la recette y renvoie, mais le futur simple et la forme scénario deviennent des règles, avec deux critères de grille |
| Recette : qui teste, où, combien de temps | Un **tableau de contrôles croisant audits et phases** — maquettes, charte, développement, pré-production, production — réalisés par le prestataire, qui en produit les rapports | La recette commence par ce tableau ; la recette finale vient après |
| Maintenance : « marquer les délais à compléter » | Un **tableau de gravités** : bloquant / majeur / mineur, chacun avec délai de prise en compte, de contournement et de correction, en heures et jours ouvrés | Le tableau devient obligatoire ; TMA et évolutions sont deux rubriques distinctes ; le produit doit être à jour avant que la garantie ne coure |
| Rien sur l'organisation du projet | Une partie « **Moyens humains & organisation** » : qui de chaque côté, rythme des réunions, espace de travail collaboratif | **Nouvelle section** `gouvernance_projet`, le CDC passe à 15 sections |
| Contexte : présenter l'organisation | Le document s'ouvre sur la **désignation des parties** et un **objet découpé en missions**, chacune avec sa durée | Ajouté aux consignes et à la grille du contexte |
| Formation mentionnée en passant | Une **partie entière**, plus un **récapitulatif final des livrables** en tableau | Ajouté aux consignes des livrables |

### 8.3 Ce que le plan d'affaires réel a corrigé

**Sourcer ne suffit pas, il faut se situer.** Après chaque tableau d'hypothèses, le document écrit d'où viennent ses coefficients *et* où il se place par rapport à eux : « les doses utilisées sont les doses moyennes des résultats du Service Suivi Évaluation… ces doses sont inférieures aux recommandations ». Le lecteur sait immédiatement si l'hypothèse est prudente ou optimiste, sans refaire le calcul. C'est devenu un critère de grille.

**Deux scénarios nommés, pas un abattement.** Le document produit ses comptes prévisionnels « avec des conditions ordinaires » puis « avec des conditions favorables ». C'est meilleur que la variante à −30 % que j'avais inventée : chaque scénario dit ce qui change et pourquoi, au lieu d'appliquer un pourcentage arbitraire. La règle des −30 % est supprimée.

**Les tableaux sont numérotés et titrés.** « Tableau 6 : Besoins en intrants de la coopérative ». Évident, absent de mes consignes.

**Le risque s'écrit où il se joue.** Chaque option du plan porte sa propre rubrique « Les risques et les modes de financement ». La section finale consolide, elle ne découvre pas. Les sections opérationnelles se terminent désormais par le risque qui leur est propre.

---

## 9. La relecture est sélective

Trente sections, c'est trente arrêts « lisez, approuvez ou demandez une révision » dans la conception d'origine. Les questions, elles, ne suivent pas le nombre de sections — elles suivent le catalogue de faits, qui est partagé, et restent à 35. Le point de fatigue n'est donc pas le questionnaire, c'est la relecture.

Décidé le 17 septembre 2026 : **le graphe ne s'arrête que lorsque la relecture sert à quelque chose.**

Chaque section porte un champ `validation` :

- **`toujours`** — sept sections s'arrêtent quoi qu'il arrive. `bp.probleme_solution` et `cdc.contexte_objectifs`, parce qu'elles ouvrent chaque document et donnent le ton : mieux vaut le corriger à la première section qu'à la trentième. `cdc.perimetre`, `cdc.exigences_fonctionnelles`, `cdc.budget_modalites`, `bp.compte_resultat` et `bp.besoin_financement`, parce qu'elles engagent — un périmètre, un budget, un prévisionnel se relisent.
- **`si_note_basse`** — les vingt-trois autres ne s'arrêtent que si l'auto-critique reste sous `seuil_relecture`, fixé à 8, après ses révisions automatiques.

Les deux seuils ne servent pas la même chose et ne doivent pas être confondus : **sous 7, le graphe fait réécrire la section** (deux fois au maximum) ; **sous 8 après cela, il réveille l'utilisateur**. Entre les deux, la section est jugée acceptable mais imparfaite et repasse à la machine avant de déranger qui que ce soit.

Une section passée sans arrêt n'est pas une section soustraite : elle est marquée comme telle dans le plan et reste ouvrable à tout moment. L'utilisateur relit ce qu'il veut, quand il veut, au lieu de le subir trente fois.

**Ce qu'il faudra surveiller.** Une section validée sans arrêt puis rouverte par l'utilisateur est le signal le plus précieux du dispositif : il dit que le seuil est trop bas. C'est la métrique à suivre dans LangSmith, avec la proportion de sections passées sans relecture.

**Une réserve, puisque la note vient du modèle.** Le seuil de 8 s'applique à une note produite par le modèle lui-même, donc variable d'un appel à l'autre. Concrètement, une même section peut s'arrêter ou passer selon l'exécution. C'est acceptable tant que les sept sections qui engagent s'arrêtent de toute façon — c'est précisément pour cela qu'elles sont marquées `toujours`.

---

## 10. Reste à faire

- **Relire les 30 sections une à une.** Une première relecture a eu lieu le 17 septembre : elle a corrigé la confusion requis / optionnels, promu douze faits au rang de requis, ajouté le fait `nom_projet` qu'aucune section ne portait, et vérifié que le budget de longueur (~15 pages par document) tient dans les fourchettes des sources. Restent les consignes et les grilles : elles sont un premier jet écrit d'après les sources, et c'est la manière dont l'agence rédige réellement qui doit les remplacer. C'est le seul endroit du projet où aucun modèle ne peut décider à la place de Brice.
- **Écrire les calculs outillés** référencés par les templates : `tam_sam_som`, `marge_unitaire`, `tableau_investissements`, `compte_resultat_3ans`, `plan_tresorerie_12mois`, `seuil_rentabilite`, `point_mort`, `plan_financement_initial`, `plan_financement_3ans`, `annuites_credit`.
- **Décider du sort du « cadre de réponse »** : section à part entière comme aujourd'hui, ou colonnes ajoutées au tableau des exigences.

---

## Sources

**Documents réels analysés**
- Sia Habitat, [*Cahier des Clauses Techniques Particulières — refonte graphique, ergonomique et technique du site web, hébergement, TMA et webmastering*](https://www.natural-net.fr/media/21872/Cahier-des-Clauses-Techniques-Particulieres--CCTP----refonte-du-site-https__.pdf), 16 juin 2022, 47 pages.
- Coopérative des exploitants motorisés de Koutiala (Mali), avec l'AFDI Aveyron et le CIRAD, [*Plan d'affaire — période 2007-2010*](https://agritrop.cirad.fr/543454/1/document_543454.pdf), mars 2007, 66 pages.

**Corpus repéré, pas encore dépouillé**

Autres cahiers des charges réels, librement accessibles, disponibles pour une prochaine passe d'ancrage. Ils permettront de vérifier si les règles tirées du CCTP de Sia Habitat se retrouvent ailleurs ou lui sont propres.

- Centre des monuments nationaux, [*CCTP — refonte du portail internet et de l'intranet (usine à sites)*](https://www.club-innovation-culture.fr/wp-content/uploads/CCTP.pdf) — établissement public, périmètre multi-sites.
- Communauté de communes de Falaise, [*CCTP lot 2 — site internet*](http://www.falaise.fr/wp-content/uploads/2010/09/Cahier-des-Clauses-Techniques-Particuli%C3%A8res-Lot-2-Site-internet-CDC.pdf) — collectivité, avec migration de messagerie.
- Ville de Mios, [*CCTP*](https://www.villemios.fr/wp-content/uploads/2011/02/CCTP.pdf) — petite collectivité, document plus court.
- PNUD, [*Cahier des clauses techniques particulières*](https://procurement-notices.undp.org/view_file.cfm?doc_id=148229) — commande internationale, utile pour voir ce qui change hors du droit français.

Côté business plan, aucun corpus équivalent n'a été trouvé : le document est confidentiel par nature. Voir §8.1.

**Trames et normes**

- AFNOR — [NF X50-151, *Expression fonctionnelle du besoin et cahier des charges fonctionnel*](https://www.boutique.afnor.org/en-gb/standard/nf-x50151/value-management-functional-expression-of-the-need-and-functional-performan/fa122246/29935), remplacée en février 2013 par la [NF EN 16271](https://www.boutique.afnor.org/en-gb/standard/nf-x50151/value-analysis-functional-analysis-functional-expression-of-need-and-tender/fa023106/55933), *Management par la valeur — expression fonctionnelle du besoin et cahier des charges fonctionnel*.
- [Cahier des charges fonctionnel : méthodologie et plan détaillé](https://cahiersdescharges.com/cahier-des-charges-fonctionnel/) — plan complet dérivé de la NF X50-151.
- [Cahier des charges pour une application web : le guide complet](https://www.itefficience.com/article/cahier-des-charges-application-web-guide-complet) — trame praticienne, règle de vérifiabilité des exigences, maintenance post-production.
- [Code de la commande publique — le cahier des clauses techniques particulières](https://www.code-commande-publique.com/cahier-des-clauses-techniques-particulieres-cctp/) — statut et fonction du CCTP dans un marché public, ce qui explique la forme des documents dépouillés en §8.
- Bpifrance Création — [Faire son business plan](https://bpifrance-creation.fr/encyclopedie/previsions-financieres-business-plan/business-plan/faire-son-business-plan) — les huit blocs, les tableaux financiers, les qualités attendues.
- Bpifrance Création — [Prévisions financières et business plan](https://bpifrance-creation.fr/encyclopedie/previsions-financieres-business-plan) et [Le plan de financement initial](https://bpifrance-creation.fr/encyclopedie/previsions-financieres-business-plan/previsions-financieres/plan-financement-initial) — détail et horizon de chaque tableau.

*Sources consultées en septembre 2026. Les trames institutionnelles évoluent : vérifier avant toute mise en service. Les deux documents réels du premier bloc sont des documents publics, cités à titre de références méthodologiques ; aucun de leur contenu n'est repris dans les templates, seules leurs manières de faire le sont.*
