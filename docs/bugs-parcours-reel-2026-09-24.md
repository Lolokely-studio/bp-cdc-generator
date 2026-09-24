# Quatre bugs trouvés en pilotant l'application réelle

Le 2026-09-24, après la fusion du redesign, l'application a été pilotée de
bout en bout sur la **vraie base Supabase** et les **vrais fournisseurs de
modèles** : création du projet « Sillage », les deux documents, réponses
substantielles aux questionnaires.

Le parcours s'est arrêté **à la section 14 sur 30**, sur
`CDC · risques_cdc`. Treize sections étaient rédigées et approuvées,
41 faits en mémoire.

Aucun de ces quatre défauts ne vient du redesign. Aucun n'est visible par
la suite de tests. Trois d'entre eux ont la même cause profonde : **les
tests ne parlent qu'au Postgres local et au modèle simulé**, jamais au
pooler Supabase ni à un vrai modèle.

---

## 1. Les requêtes préparées tuent l'application derrière le pooler

**Gravité : bloquant en production.** *Corrigé, non commité au moment de
l'écriture.*

`app/core/db.py` ouvrait le pool avec `kwargs={"autocommit": True}`, sans
désactiver les requêtes préparées. psycopg3 en prépare une après sa
**cinquième** exécution. Derrière le pooler de transactions de Supabase
(port 6543), chaque transaction peut atterrir sur une connexion serveur
différente, où l'instruction préparée n'existe pas.

```
psycopg.errors.InvalidSqlStatementName: prepared statement "_pg3_0" does not exist
```

Observé exactement à la sixième requête authentifiée : connexion, liste des
projets et création passaient, puis `/state` échouait. **Le navigateur
affichait une erreur CORS**, parce que FastAPI n'ajoute pas ses en-têtes sur
une exception non gérée — le symptôme désigne le mauvais coupable.

**Correctif appliqué :** `kwargs={"autocommit": True, "prepare_threshold": None}`.

**Pourquoi aucun test ne le voit :** `tests/conftest.py:15` force
`SUPABASE_DB_PORT=5433`, le Postgres local en direct. Sans pooler, les
requêtes préparées fonctionnent.

---

## 2. La prompt annonce un tableau fantôme nommé « aucun »

**Gravité : bloquant.** *Non corrigé.*

`app/agent/prompts.py:212-213` rend :

```
Tableaux disponibles, à placer par leur repère :
{markers or "- aucun"}
```

Quand la section ne déclare aucun calcul, le repli `"- aucun"` est formaté
**exactement comme une entrée de liste**. Le modèle lit « un tableau
disponible, nommé *aucun* » et écrit `[Tableau : aucun]`. L'analyseur
échoue, la rédaction meurt.

**Étendue : 23 des 30 sections** d'un projet « les deux documents ».
Les 15 sections du cahier des charges ne déclarent **aucun** calcul ; 8 des
15 du business plan non plus. Seules 7 sections du BP en ont.

**Correctif proposé :**

```python
tableaux = (f"Tableaux disponibles, à placer par leur repère :\n{markers}"
            if markers else
            "Aucun tableau n'est disponible pour cette section : "
            "n'écris aucun repère [Tableau: …].")
```

---

## 3. Un repère de tableau inconnu tue la rédaction, sans issue

**Gravité : bloquant.** *Non corrigé.* Aggrave le nº 2.

`app/agent/prompts.py:117` lève `ValueError` dès qu'un repère ne
correspond à aucun calcul. Le commentaire l'assume : « Échouer ici fait
repartir la section, ce qui est réparable. Laisser passer produirait un
document avec un trou silencieux. » Le raisonnement est bon, mais la
réparation n'en est pas une quand le modèle **refait le même geste**.

Sur `CDC · risques_cdc` — une section qui appelle naturellement un tableau
de risques — huit reprises consécutives ont échoué, avec un nom inventé
différent à chaque fois :

```
risques_et_points_attention   ×3
risques_et_parades            ×2
risques_points_attention      ×1
gravites_incidents            ×1
controle_qualite_projet       ×1
controle_qualite_par_phase    ×1
```

L'écran dit « La rédaction s'est interrompue » et propose « Reprendre ».
Un utilisateur cliquera en boucle sans jamais passer.

**Correctif proposé :** ignorer un repère inconnu plutôt que de tuer le
run, et enregistrer l'incident. Un trou silencieux dans un document est
moins grave qu'un projet définitivement bloqué — et le correctif nº 2
devrait de toute façon tarir la source.

---

## 4. Le nom du projet n'arrive jamais jusqu'à l'agent

**Gravité : gênant, visible dans le document livré.** *Non corrigé.*

Le nom saisi à la création est écrit sur la ligne du projet, mais **jamais
posé comme fait `nom_projet`**. L'agent le cherche, ne le trouve pas, et le
déduit manquant :

```
nom_projet   valeur='donnée à compléter'   source=deduced
```

La prose porte alors `[nom_projet]` en toutes lettres — et l'auto-critique
le relève elle-même : « Le nom du projet est indiqué comme [nom_projet]
sans valeur ».

**Correctif proposé :** semer `nom_projet` comme fait de source `user` à la
création du projet, à partir de `projet.nom`.

---

## Ce que le redesign, lui, a prouvé

Tous les écrans tiennent en conditions réelles : connexion et son titre
masqué, état vide, groupes radio, contrôle segmenté, compteur de
caractères à l'espace fine française, fil d'ariane à trois niveaux, atelier
à trois colonnes, mémoire avec ses badges de provenance, prose en Source
Serif, mentions « à compléter » surlignées, et le relevé d'auto-critique
avec ses puces — le défaut trouvé par la revue finale de branche est bien
corrigé, vérifié sur une section fraîchement générée. L'écran de panne
aussi, qu'on n'espérait pas voir.

---

## Suite : les correctifs, et le parcours mené à son terme

Les bugs 1 à 4 ont été corrigés le même jour. **576 tests backend passent**,
dont cinq nouveaux et un réécrit.

Le test réécrit est `test_a_table_marker_without_its_computation_is_refused`,
devenu `…_is_dropped`. Il affirmait le comportement qui bloquait les
projets, avec un argument qui se tenait : « Mieux vaut échouer ici — la
section repart, le modèle recommence — que produire un document avec un
trou silencieux ». Le terrain l'a démenti : le modèle ne recommence pas
autrement, il réinvente un nom. L'argument est conservé dans le commentaire
du nouveau test, pour qu'on sache pourquoi il a été retourné.

**Après correctif, le parcours est allé jusqu'au bout :**

- la section qui avait échoué huit fois d'affilée est passée du premier coup ;
- **30 sections sur 30**, 73 faits, aucune section passée sans validation ;
- contrôle de cohérence croisé : 3 incohérences relevées entre les deux
  documents, ignorées par le pilote ;
- export : **4 fichiers** — Word et PDF pour chaque document, tous
  téléchargés et vérifiés (50 à 162 ko, types MIME corrects) ;
- `fidele=True` sur les deux PDF : ils viennent du **vrai Gotenberg**, pas
  du convertisseur de secours.

### Deux observations de plus, non corrigées

**Le premier export a échoué sur un délai réseau**, en lisant le point de
reprise du graphe :

```
psycopg.OperationalError: consuming input failed: could not receive data from server
SSL SYSCALL error: Operation timed out
```

La relance a réussi sans rien changer. Le point de reprise d'un projet de
trente sections est volumineux, et il transite par le pooler en SSL. Le
produit traite le cas — l'écran annonce l'échec et invite à relancer — mais
un `statement_timeout` plus généreux, ou une lecture du point de reprise
hors pooler, épargnerait à l'utilisateur un aller-retour inexpliqué.

**La liste « à compléter » compte plus de cent trente entrées**, dont des
faits déjà connus. L'analyse est nuancée :

- `perimetre_exclu`, `evolutions_prevues`, `equipe_projet_client` valent
  `None` de source `user`, c'est-à-dire « je ne sais pas » — **à cause d'un
  défaut du pilote de test**, pas du produit : son sélecteur ramassait les
  paragraphes d'aide, dont l'`id` dérive de celui du champ, et cochait « je
  ne sais pas » sur la question qu'il venait de remplir ;
- `taux_commission` n'est réclamé par aucune section de ce profil, donc
  jamais demandé — mais le modèle l'évoque dans une douzaine de sections et
  le marque à compléter ;
- `nom_projet` est le bug nº 4.

Reste que l'écran affiche cent trente entrées sans regroupement ni compte :
utilisable, mais rude à lire.
