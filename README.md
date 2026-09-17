# Suivi du prix des carburants

Une petite application web, à héberger chez soi, qui répond à une question
précise : **faut-il faire le plein maintenant, ou attendre ?**

Elle fait cinq choses :

- **comparer** les stations autour d'une commune, sur une carte ou en liste,
  triées par prix ou par distance, avec leur enseigne ;
- **montrer ce qui vient de bouger** — baril, moyenne nationale et stations
  voisines, sur 24 heures et sur 7 jours, côte à côte ;
- **suivre** l'évolution du prix et la comparer au cours du pétrole brut ;
- **prévoir** le sens de la prochaine variation, et prévenir par courriel quand il change ;
- **comparer des stations précises** en cochant leur courbe dans la liste.

---

## Ce que vaut la prévision, sans enjoliver

Ce point mérite d'être lu avant tout le reste, car il détermine la confiance à
accorder à l'outil.

**Le prix exact est imprévisible.** La première version de ce projet cherchait à
répondre à « combien vaudra le gazole dans quinze jours ». Elle y répondait
moins bien que la phrase « la même chose qu'aujourd'hui » — de 12 à 44 % moins
bien selon les cas. Ce n'est pas un défaut de réglage : le niveau futur d'un
prix de carburant est une marche aléatoire, et aucun algorithme n'y peut rien.

**Le sens de la variation, lui, se devine en partie.** Les stations répercutent
leurs hausses par paliers sur plusieurs jours, si bien qu'une tendance entamée a
de bonnes chances de se poursuivre. C'est ce que l'outil exploite, et c'est
aussi tout ce dont on a besoin pour décider de faire le plein ou non.

**Ce n'est pas l'algorithme le plus savant qui gagne.** Trois familles ont
concouru, et le classement est instructif. Les *arbres de gradient*, les plus
sophistiqués, arrivent derniers : chaque arbre corrigeant les erreurs du
précédent, ils finissent par apprendre le bruit par cœur. La *régression
logistique* fait honorablement, sa simplicité même l'empêchant de s'égarer. Et
c'est la *forêt aléatoire* qui l'emporte de trois à cinq points — cinq cents
arbres indépendants dont on moyenne les avis, si bien que leurs erreurs se
compensent au lieu de s'accumuler.

Une version antérieure de ce projet concluait que « les arbres sont mauvais
ici ». C'était faux, et l'erreur vaut d'être signalée : un seul essai avait été
fait, avec le gradient. La manière dont les arbres sont assemblés compte
davantage que le fait d'en employer.

Justesse mesurée sur des périodes que le modèle n'avait jamais vues
(2019-2026, validation glissante) :

Justesse **réellement constatée**, sur les prévisions déjà arrivées à échéance
(février 2025 → aujourd'hui, plus de 6 500 prévisions jugées) :

| Carburant | à 7 jours | à 14 jours | à 30 jours |
|-----------|-----------|------------|------------|
| Gazole    | 76 %      | 62 %       | 57 % ✗ |
| SP95      | **84 %**  | 67 %       | 57 % ✗ |
| SP98      | 81 %      | 65 %       | 55 % ✗ |
| E10       | 77 %      | 63 %       | 49 % ✗ |
| E85       | 88 %      | 83 %       | 65 % |
| GPLc      | —         | 85 %       | 81 % |

Les cases marquées ✗ tombent sous les 60 % : **l'application refuse d'y donner
un avis** et l'affiche comme « non communiqué ». Annoncer une tendance qu'on
sait fausse une fois sur deux rendrait un service douteux.

**Ces chiffres sont plus bas que ceux de la validation**, et l'écart mérite
d'être expliqué. La validation découpe l'historique en six périodes successives
et moyenne les résultats — mais certaines périodes anciennes, comme la flambée
de 2022, étaient bien plus faciles à prévoir que le marché actuel. Sur le gazole
à trente jours, la moyenne des six annonce 66 % là où la dernière période seule
en donne 58. Ce qui intéresse celui qui consulte la page n'est pas la moyenne
des six dernières années, mais si l'outil voit juste **en ce moment**. C'est
donc le palmarès réel qui s'affiche dès qu'il compte plus de cent prévisions
jugées.

Autrement dit : **à sept jours, l'outil se trompe environ une fois sur cinq.**
À quatorze, une fois sur trois. À trente, il se tait.

Encore ces erreurs ne se répartissent-elles pas régulièrement : elles arrivent
par séries de plusieurs jours. Un second modèle apprend à reconnaître ces
périodes et l'application y relève son exigence avant de se prononcer, en
l'affichant (« ⚠ Période instable »). Le détail est plus bas, mais le principe
tient en une phrase : **l'outil sait à peu près quand il ne sait pas.**

### Ce n'est pas le baril qu'il faut regarder

Une station n'achète pas de pétrole brut : elle achète du gazole ou de
l'essence **déjà raffinés**, dont le prix de gros a sa propre dynamique —
capacités de raffinage, saisonnalité, arbitrages entre continents. Le baril
n'en est qu'une composante.

Substituer ces cotations de gros au seul cours du brut fait gagner deux à
quatre points de justesse sur les essences : le SP95 à sept jours passe de
78 à 82 %. C'est le gain le plus net obtenu sur ce projet, et il ne vient pas
d'un algorithme plus savant mais d'une donnée mieux choisie.

Un indice de peur des marchés (l'OVX, volatilité du pétrole) a été testé dans
la foulée : il n'apporte rien du tout — corrélation de 0,03 avec les
variations à venir — et dégrade même légèrement les résultats. Il a donc été
écarté.

### Pourquoi deux méthodes selon les carburants

Le modèle statistique n'est pas retenu partout. Sur l'E85 et le GPLc, il se fait
battre de dix à vingt-cinq points par une simple règle de tendance. La raison
est limpide : ces carburants ne suivent pas le pétrole. L'E85 est de l'éthanol,
dont le prix dépend de la betterave et de la canne à sucre ; le GPLc est du
propane, négocié sur un autre marché. Les variables construites autour du baril
de Brent n'y apportent rien et égarent le modèle.

Le programme mesure les deux méthodes à chaque entraînement et conserve celle
qui a réellement gagné, carburant par carburant et horizon par horizon. La page
d'accueil indique toujours laquelle a été employée.

### Ce que dit la recherche, et ce qu'elle a donné ici

La littérature sur la prévision du pétrole converge sur un point décourageant :
**la marche aléatoire est très difficile à battre** à court horizon. Alquist,
Kilian et Vigfusson montrent qu'un modèle nourri des stocks mondiaux et de
l'activité économique y parvient, mais à l'échelle mensuelle et sur des
horizons allant jusqu'à neuf mois ; les travaux récents d'Ellwanger et Snudden
vont plus loin et doutent qu'un modèle quelconque batte durablement le prix de
fin de mois. Les contrats à terme n'aident qu'au-delà d'un an.

Cela oriente la recherche ailleurs : non pas prévoir le baril, mais **mieux
modéliser sa répercussion à la pompe**. C'est le domaine des modèles à
correction d'erreur asymétrique issus de Borenstein, Cameron et Gilbert, avec
leur raffinement le plus intéressant — une *bande d'inaction*, en deçà de
laquelle les stations ne changent pas leurs étiquettes, et dont le seuil
diffère selon le sens du mouvement.

Trois familles de variables ont été construites et mesurées sur cette base :
correction d'erreur asymétrique avec bande d'inaction, indicateurs d'analyse
technique (force relative, MACD, bandes de Bollinger, croisements de moyennes),
et effets de calendrier.

**Aucune n'apporte de gain durable.** Une première mesure sur six périodes
annonçait +1,25 point ; reprise sur vingt-cinq fenêtres glissantes, elle tombe
à +0,2 point, et la part des fenêtres où le jeu enrichi l'emporte oscille
autour de cinquante pour cent — un tirage à pile ou face. L'explication est
probablement que la forêt aléatoire voyait déjà cette information : la
correction d'erreur et la force relative ne sont que des transformations non
linéaires du même historique de prix, qu'un ensemble d'arbres approche seul.

### En revanche, les pourcentages affichés mentaient

Cette recherche a révélé un défaut plus grave que l'absence de gain, et qui
n'avait jamais été vérifié : **la confiance annoncée ne correspondait pas à la
réussite constatée.**

Mesuré sur les prévisions déjà jugées, à trente jours :

| Confiance annoncée | Réussite réelle | Écart |
|--------------------|-----------------|-------|
| 90-100 %           | 60,0 %          | −34,2 |
| 80-89 %            | 63,3 %          | −20,8 |
| 70-79 %            | 56,0 %          | −18,3 |

Annoncer « 90 % de probabilité » pour réussir six fois sur dix n'est pas une
imprécision, c'est une promesse non tenue. La décomposition par méthode
désignait le coupable principal : la régression logistique sur l'E10 à trente
jours, qui annonçait 75,5 % pour 48,8 % de réussite.

Un correcteur de confiance est désormais ajusté pour chaque carburant et chaque
horizon, sur les probabilités rendues pendant la validation — donc sur des
jours jamais appris. Trois candidats concourent, dont l'absence de correction,
et le meilleur est retenu sur une moitié d'observations que l'ajustement n'a
pas vue.

| Horizon | Écart avant | Écart après |
|---------|-------------|-------------|
| 7 jours | 6,8 points  | **3,6** |
| 14 jours| 4,6 points  | 4,5 |
| 30 jours| 16,8 points | **4,1** |

La justesse y gagne accessoirement deux points — le correcteur fait basculer du
bon côté des prévisions qui hésitaient. Le palmarès affiche désormais la
confiance annoncée en regard de la réussite constatée : les deux colonnes
doivent rester proches, et c'est vérifiable d'un coup d'œil.

### Un modèle plus puissant ferait-il mieux ?

La question mérite d'être posée franchement, et elle a été traitée comme les
autres : en mesurant. Deux familles bien plus lourdes que la forêt aléatoire
ont concouru sur les mêmes données, avec la même validation.

**Réseaux de neurones.** Un réseau dense et un réseau récurrent (LSTM), les
deux architectures que la littérature applique aux séries de prix.

| Cas | Forêt | Dense | LSTM |
|-----|-------|-------|------|
| Gazole 7 j | **77,2 %** | 74,3 % | 70,8 % |
| Gazole 30 j | **63,9 %** | 54,4 % | 60,6 % |
| SP95 7 j | **84,3 %** | 83,1 % | 78,7 % |
| SP95 30 j | **63,8 %** | 56,5 % | 56,4 % |
| E10 7 j | **78,9 %** | 75,9 % | 72,1 % |
| E10 30 j | **61,0 %** | 55,7 % | 54,3 % |

La forêt gagne les six cas, souvent largement. Ce n'est pas une surprise : un
réseau de neurones réclame des dizaines de milliers d'exemples pour donner sa
mesure. Il y en a ici deux mille cinq cents, et vingt variables.

**Modèle de fondation.** Chronos-Bolt, pré-entraîné par Amazon sur des
milliards de points de séries temporelles, appliqué tel quel — sans le moindre
apprentissage sur les données de ce projet.

| Cas | Chronos | « rien ne change » | Forêt |
|-----|---------|--------------------|-------|
| Gazole 7 j | 73,5 % | 73,5 % | **79,4 %** |
| Gazole 30 j | 59,5 % | 51,4 % | **62,2 %** |
| SP95 7 j | 64,5 % | 67,7 % | **71,0 %** |
| SP95 30 j | 54,5 % | **57,6 %** | 51,5 % |

Il ne bat la forêt nulle part, et ne bat le naïf qu'une fois sur deux. La
raison est structurelle plutôt que technique : Chronos ne voit que la série des
prix à la pompe. Il ignore la cotation de gros — c'est-à-dire précisément
l'information qui a apporté le gain le plus net de ce projet.

Autrement dit, **la taille du modèle n'est pas ce qui limite.** Ce qui limite,
c'est la quantité d'information disponible, et elle est modeste : sept ans de
prix quotidiens et une poignée de cotations. Aucune architecture n'invente une
information absente des données.

### Les erreurs n'arrivent pas au hasard, et cela se voit venir

Une observation a ouvert la seule piste qui ait abouti. En comptant les erreurs
du modèle jour après jour, on trouve des **séries de quinze jours consécutifs
faux**, là où l'indépendance en prédirait quatre. Cinq épisodes de ce genre
concentrent 36 % de toutes les erreurs.

L'hypothèse d'une cause fiscale — les hausses de taxes de janvier — a été
testée puis rejetée : janvier est au contraire le mois le plus facile (13,7 %
d'erreurs), le pire étant mai (35,4 %).

Il existe donc des périodes où le modèle est durablement à côté. Reste à les
reconnaître à l'avance, et c'est le rôle d'un **second modèle entraîné non pas
sur les prix, mais sur les erreurs du premier** — à partir des mêmes variables,
toutes connues au moment de prévoir.

Contrôlé comme le reste, en le réajustant à chaque fenêtre et en le jugeant sur
la suivante, comme il le serait en service. Voici ce que le programme lui-même
a mesuré et décidé au dernier entraînement :

| Cas | Écart médian | Fenêtres réussies | Verdict |
|-----|--------------|-------------------|---------|
| Gazole 7 j | **+22,8 pt** | 75 % | **retenu** |
| E10 7 j | **+20,0 pt** | 82 % | **retenu** |
| SP98 7 j | **+16,5 pt** | 70 % | **retenu** |
| E10 14 j | **+13,3 pt** | 69 % | **retenu** |
| Gazole 30 j | +16,7 pt | 57 % | écarté — irrégulier |
| SP98 14 j | +16,0 pt | 54 % | écarté — irrégulier |
| SP98 30 j | +13,3 pt | 57 % | écarté — irrégulier |
| Gazole 14 j | +11,7 pt | 57 % | écarté — irrégulier |
| SP95 7 j | +6,7 pt | 67 % | écarté — écart trop faible |
| SP95 30 j | +6,7 pt | 62 % | écarté |
| SP95 14 j | +0,0 pt | 33 % | écarté |
| E10 30 j | −5,0 pt | 43 % | écarté |

*L'écart est le taux d'erreur des jours signalés risqués moins celui des jours
jugés sûrs. Un signal utilisable demande un écart franc **et** régulier : au
moins 8 points, et deux fenêtres sur trois réussies. Les deux conditions
comptent — le gazole à trente jours affiche un écart de 17 points, mais une
fenêtre sur deux seulement, ce qui ne vaut guère mieux qu'un tirage au sort.*

Sur le gazole à sept jours, les jours signalés se trompent vingt-trois points
plus souvent que les autres, et le signal tient sur trois fenêtres sur quatre.
Quatre cas sur douze franchissent la barre ; les huit autres sont écartés,
exactement comme une méthode battue en validation. L'E85 et le GPLc n'y
figurent pas : ils tournent à la règle de tendance, qui n'a pas d'erreurs
à donner à apprendre.

Ce veilleur ne rend pas la prévision meilleure. Il la rend plus prudente quand
il le faut : les jours signalés, l'outil n'ose une recommandation qu'au-delà de
72 % de probabilité au lieu de 62 %, et la page l'annonce en clair
(« ⚠ Période instable »). **Savoir quand se taire** est le seul progrès que
cette campagne de mesures ait produit — et il ne doit rien à un modèle plus
gros.

### Pistes explorées et écartées

Consignées ici pour éviter de refaire le trajet. Toutes ont été mesurées, pas
supposées.

| Piste | Résultat |
|-------|----------|
| Prévoir le prix exact | 12 à 44 % **moins bien** que « le même prix qu'aujourd'hui » |
| Arbres de gradient | derniers des trois familles testées |
| Indice de peur du pétrole (OVX) | corrélation 0,03 avec l'avenir ; dégrade le modèle |
| Marge de raffinage | n'ajoute rien aux cotations de gros dont elle dérive |
| Indice base 100 pour le graphique | amplitudes trop inégales, les courbes ne se superposent pas |
| **Entraîner sur les 13 régions** | **neutre à 7 jours, −7 points à 14 jours** |
| Dispersion entre régions comme signal | neutre (±0,3 point) |
| Correction d'erreur asymétrique, bande d'inaction | +0,2 point sur 25 fenêtres |
| Analyse technique (RSI, MACD, Bollinger) | +0,2 point, gagne une fenêtre sur deux |
| **Réseaux de neurones (dense, LSTM)** | **perd les 6 cas face à la forêt** |
| **Modèle de fondation Chronos-Bolt** | **ne bat ni la forêt, ni « rien ne change »** |
| Cause fiscale des erreurs groupées | janvier est le mois le plus **facile** |
| Effets de calendrier | −0,1 point |
| Tensions de raffinage | −1,1 point |
| **Une enseigne qui baisse en premier** | **artefact : avance réelle de 0 jour** |

La piste régionale méritait d'être tentée : treize séries de 2 800 jours, c'est
soixante-treize fois plus de lignes d'entraînement. Elle échoue pour une raison
qui saute aux yeux une fois mesurée — les régions corrèlent à **0,99** avec la
moyenne nationale et bougent le **même jour** qu'elle. Ce ne sont pas treize
informations, mais treize copies. Le modèle s'y dilue en apprenant une « région
moyenne » qui ne correspond à aucune.

Quant aux niveaux de prix, ils diffèrent bien d'une région à l'autre, mais de
5 centimes entre les extrêmes — là où les stations d'un même bassin de vie
s'étalent couramment sur 25 centimes. Le comparateur de stations répond déjà à
cette question, et bien mieux.

---

## Les enseignes : ce qu'on en a appris, et pourquoi le tableau a disparu

Le fichier officiel des prix ne publie pas l'enseigne : quarante-sept champs,
aucun ne la porte. Elle est reconstituée à partir d'un référentiel
communautaire publié sur data.gouv.fr, enrichi par OpenStreetMap, qui couvre
98 % des stations en service. **Cette reconstitution reste en place** : c'est
elle qui met « Carrefour » ou « E.Leclerc » en face de chaque ligne de la liste
des stations.

Ce qui a disparu, c'est le **classement national des enseignes** qui occupait
une section entière de la page. Il répondait à une question mal posée. Savoir
qu'un réseau est en moyenne le moins cher de France ne sert à rien si l'on n'en
a aucun exemplaire à vingt kilomètres — et si l'on en a un, la liste des
stations voisines le dit déjà, avec son prix réel plutôt qu'une médiane
nationale. Les mesures ci-dessous, elles, gardent leur intérêt : elles
expliquent ce qu'on observe dans cette liste.

Les stations d'autoroute étaient systématiquement écartées de ces comparaisons.
Elles se vendent nettement plus cher, et les réseaux n'en comportent pas la
même proportion : Shell en compte sept sur dix, les supermarchés aucune. Les
inclure imputerait à la politique commerciale d'une enseigne ce qui ne tient
qu'à l'emplacement de ses stations — l'écart apparent entre la moins chère et
la plus chère tombe de 41 à 30 centimes une fois l'autoroute retirée.

### Des marges très inégales

Trente centimes par litre séparent le réseau le moins cher du plus cher, soit
quinze euros sur un plein de cinquante litres.

Cet écart se lit directement comme un écart de marge, et c'est ce qui rend la
comparaison solide : les taxes sont identiques pour toutes les enseignes sur un
même carburant, et le carburant de gros s'achète à peu près au même prix. Tout
ce qui diffère est donc la marge — sans qu'il soit besoin de connaître le
montant des taxes, qui s'annule dans la soustraction. Sur trente centimes
d'écart à la pompe, vingt-cinq reviennent au distributeur ; le reste part en
TVA, qui frappe aussi la marge.

### Aucune enseigne ne baisse en premier

Question naturelle : un réseau annonce-t-il les baisses avant les autres ? Une
première mesure semblait le confirmer — E.Leclerc paraissait devancer le marché
de onze jours sur trente épisodes de baisse depuis 2019.

**C'était un artefact.** La méthode cherchait le premier jour où une enseigne
fléchissait de plus d'un centime : une enseigne qui ajuste souvent franchit
naturellement ce seuil avant une enseigne inerte, sans rien anticiper du tout.
Or E.Leclerc est justement la plus réactive du panel — 0,61 centime de
variation quotidienne contre 0,30 pour la plus lente, et 22 % de jours en
baisse contre 10 %.

Reprise avec une mesure insensible au bruit — la date du point bas de chaque
épisode, qui ne dépend d'aucun seuil — l'avance médiane de **toutes** les
enseignes tombe à zéro jour. Elles bougent ensemble.

C'est la conclusion pratique à retenir : **il n'y a pas d'enseigne à guetter**.
Il y a des stations plus ou moins chères, et la liste les donne. La réactivité
d'un réseau ne mesure que la fréquence de ses ajustements, à la hausse comme à
la baisse, et non une capacité d'anticipation.

---

## Lire la page

### « Ce qui a bougé récemment »

Trois tuiles côte à côte, et c'est leur juxtaposition qui compte : le **baril**,
la **moyenne française à la pompe**, et les **stations autour de chez soi**,
chacune sur deux échéances.

| | Ce qu'on y lit |
|---|---|
| Pétrole brut | dernière séance et 7 jours, en pourcentage |
| Le carburant choisi à la pompe | 24 heures et 7 jours, en centimes par litre |
| Les stations du voisinage | médiane des variations de ces stations |

L'écart entre la première tuile et les deux autres est l'information utile :
quand le baril prend 12 % en une semaine et la pompe 1,7 %, la hausse n'est pas
finie. Une phrase sous les tuiles énonce cette lecture, avec les deux nombres
qui la fondent.

Deux honnêtetés de vocabulaire. Pour le baril on écrit « dernière séance » et
non « 24 heures » : les marchés ne cotent ni le week-end ni les jours fériés,
et la donnée publique accuse quelques jours de retard — affichés sous la tuile.
Pour une station dont l'historique ne remonte pas assez loin, on écrit « — »
plutôt que zéro : un prix inconnu n'est pas un prix stable.

### La liste des stations

Elle se trie **par prix** ou **par distance**, et le tri intervient avant la
troncature de la liste : trier par distance ne montre pas les plus proches
parmi les moins chères, mais bien les plus proches. Trois centimes ne valent
pas vingt kilomètres de détour, et l'outil n'a pas à trancher à la place de
celui qui conduit.

La station la moins chère reste en gras où qu'elle se trouve dans la liste.

L'adresse ne figure plus dans le tableau — enseigne et commune suffisent à
reconnaître une station — mais elle reste dans l'infobulle de la carte, qui est
la vue de détail qu'on ouvre exprès, et c'est bien là qu'on a besoin de savoir
où aller.

---

## Installation sur un NAS Synology

L'image est compilée automatiquement par GitHub à chaque modification du code,
puis publiée sur `ghcr.io`. Le NAS se contente de la récupérer : il ne compile
rien, ce qui lui épargne un travail dont il est bien incapable.

### 1. Créer le projet dans Container Manager

**Container Manager** → **Projet** → **Créer** → *Créer un fichier
docker-compose.yml*, puis coller le contenu de
[`docker-compose.synology.yml`](docker-compose.synology.yml).

L'application est ensuite accessible sur `http://adresse-du-nas:8100`.

> Le port 8100 est celui du NAS ; le conteneur, lui, écoute toujours en 8000.
> En cas de conflit, seul le nombre de **gauche** est à changer dans la ligne
> `- "8100:8000"`.

Au premier démarrage, l'application constitue seule son historique : environ
210 Mo d'archives à télécharger et à analyser, soit **cinq à dix minutes**. La
page reste accessible pendant ce temps, simplement dépeuplée. Ensuite, elle se
met à jour toute seule chaque jour à 11 h.

### 2. Rafraîchir à la demande

L'en-tête indique en permanence de quand datent les prix affichés et à quelle
heure aura lieu la prochaine collecte. Le bouton **Mettre à jour** la déclenche
sans attendre — utile avant de prendre la route, ou après une mise à jour de
l'image.

Le démarrage vérifie par ailleurs que rien ne manque en base : référentiel des
stations, enseignes, moyennes nationales, cotations de marché, modèles de
prévision, fraîcheur des relevés. Tout manque déclenche une reconstruction
immédiate, sans attendre le lendemain.

Ce contrôle a été écrit après deux occurrences du même défaut. À chaque mise à
jour apportant un nouveau besoin de données — les modèles d'abord, les
enseignes ensuite — l'application démarrait sans rien reconstruire et affichait
des colonnes vides pendant vingt-quatre heures. Les vérifications sont
désormais réunies dans `carburants/diagnostic.py`, où toute nouveauté ajoute la
sienne.

### 3. Mises à jour automatiques

Le conteneur porte l'étiquette
`com.centurylinklabs.watchtower.scope=gestion-locative`, qui le place sous la
surveillance du Watchtower déjà en service sur le NAS. Aucun second Watchtower
n'est à lancer — et il ne le faudrait pas, le nom de conteneur entrerait en
conflit.

Le cycle complet, sans intervention : modification du code → push sur `main` →
GitHub compile et publie → Watchtower le remarque dans les cinq minutes →
le conteneur redémarre sur la nouvelle version. Les données, logées dans un
volume nommé, traversent l'opération intactes.

Une modification portant uniquement sur la documentation ne déclenche aucune
compilation : recompiler et redéployer une application dont le code n'a pas
bougé ne ferait que la redémarrer pour rien.

### Comparer des stations précises

Une case à cocher **en tête de chaque ligne** de la liste affiche la courbe de
la station sur le graphique, jusqu'à six à la fois — au-delà, les couleurs ne
se distinguent plus. C'est la colonne qu'on parcourt du doigt pour cocher :
elle n'a rien à faire au bout d'un tableau qui défile.

L'historique complet n'est conservé que pour le voisinage de la commune
configurée (soixante kilomètres par défaut) et pour les stations suivies. Tout
garder représenterait onze millions de lignes et quatre cents mégaoctets par
an, au bénéfice d'un usage qui n'existe pas : personne ne consulte la courbe
d'une station qu'il ne fréquentera jamais.

Les autres stations gardent **quatre-vingt-dix jours**, de quoi afficher leurs
variations récentes. Au-delà, la tâche quotidienne élague. Rien n'est perdu
pour autant : le jour où l'on déménage ou l'on suit une nouvelle station, le
programme repère qu'elle est dépourvue d'historique et va le rechercher dans
les archives annuelles. L'élagage est suspendu tant que la commune de référence
reste introuvable, faute de quoi il effacerait précisément ce qu'il doit
protéger.

### En cas d'erreur « unauthorized » au téléchargement

L'image est publiée publiquement et se télécharge sans identification. Si le
NAS venait malgré tout à se plaindre, c'est que la visibilité du paquet a été
modifiée : `github.com/Mathiaspayet?tab=packages` → **suivi-prix-essence** →
*Package settings* → *Change visibility* → **Public**.

### Alertes par courriel (facultatif)

Tout se règle depuis le bouton **Réglages** de la page : serveur de messagerie,
destinataire, choix des alertes actives et de leur sensibilité. Un bouton
*Envoyer un message d'essai* vérifie la configuration et rapporte l'erreur en
clair — une messagerie mal réglée échoue presque toujours en silence.

Avec Gmail, il faut créer un **mot de passe d'application** dans les réglages
de sécurité du compte Google : le mot de passe habituel est systématiquement
refusé par les programmes.

Les lignes `SMTP_*` du fichier compose restent acceptées comme configuration
initiale. Ce qui est saisi dans la page l'emporte sur elles, et effacer un
champ dans la page rend la main au fichier.

> **Cette page règle des identifiants de messagerie et n'est protégée par
> aucun mot de passe par défaut.** C'est acceptable sur un réseau domestique
> fermé. Dès que l'application est publiée au-delà — reverse proxy,
> QuickConnect, ouverture de port — définissez `MOT_DE_PASSE_ADMIN` dans le
> fichier compose. Seule la configuration est alors verrouillée ; la
> consultation reste libre.
>
> Le mot de passe de messagerie est conservé en clair dans la base SQLite, sur
> votre NAS. C'est inévitable : s'authentifier auprès d'un serveur SMTP exige
> de le détenir en clair au moment de l'envoi. Il n'est en revanche jamais
> renvoyé par l'interface, qui peut l'écrire sans jamais le relire.

Cinq événements déclenchent un message, et uniquement au moment où la situation
bascule — jamais tant qu'elle se maintient :

1. la prévision passe à la baisse (inutile de faire le plein tout de suite) ;
2. la prévision passe à la hausse (mieux vaut ne pas attendre) ;
3. le prix chute brutalement — plus de quatre fois le mouvement habituel sur
   trois jours, une occasion qui se referme souvent vite ;
4. une prévision est démentie par les faits, d'au moins trois centimes ;
5. une station suivie descend sous le seuil qu'on lui a fixé.

Les seuils sont calibrés sur l'historique pour produire **une trentaine de
courriels par an**, soit un tous les douze jours. Tout ce qui se déclenche le
même jour part dans un seul message à plusieurs rubriques : trois courriels
d'affilée, ce sont trois courriels ignorés.

---

## Installation sans Docker

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python scripts/initialiser.py      # une seule fois : constitue l'historique
python scripts/entrainer.py        # entraîne les modèles

# Par la suite :
python scripts/entrainer.py --reajuster   # rapide, quotidien
python scripts/entrainer.py --valider     # complet, une fois par mois
uvicorn carburants.web.app:application --host 0.0.0.0 --port 8100
```

---

## D'où viennent les données

| Donnée | Source | Fréquence |
|--------|--------|-----------|
| Prix de ~9 800 stations | [data.economie.gouv.fr](https://data.economie.gouv.fr/explore/dataset/prix-des-carburants-en-france-flux-instantane-v2/) | continue |
| Historique depuis 2019 | [donnees.roulez-eco.fr](https://donnees.roulez-eco.fr/) | quotidienne |
| Enseignes des stations | [Référentiel enrichi par OpenStreetMap](https://www.data.gouv.fr/datasets/referentiel-des-noms-et-enseignes-de-stations-service-enrichi-par-openstreetmap) (ODbL) | quotidienne |
| Baril de Brent | [FRED](https://fred.stlouisfed.org/series/DCOILBRENTEU) (Réserve fédérale de Saint-Louis) | jours ouvrés |
| Taux euro/dollar | [FRED](https://fred.stlouisfed.org/series/DEXUSEU) | jours ouvrés |

Toutes sont gratuites et ne demandent aucune inscription.

> **Outre-mer :** les départements 971, 972, 973, 974 et 976 ne figurent pas
> dans ces données. Le prix y est fixé chaque mois par arrêté préfectoral et
> s'impose à toutes les stations, qui n'ont donc aucun prix à déclarer. La
> comparaison entre stations n'y aurait de toute façon pas d'objet.

---

## Comment le projet est organisé

```
carburants/
├── config.py              tous les réglages, regroupés ici
├── base.py                schéma de la base SQLite
├── variations.py          ce que le baril et la pompe viennent de faire
├── diagnostic.py          ce qui manque dans la base, et comment le dire
├── reglages.py            réglages modifiables depuis la page
├── alertes.py             courriels
├── sources/
│   ├── stations.py        prix station par station (flux instantané)
│   ├── historique.py      reconstitution de l'historique depuis les archives
│   └── marche.py          Brent et taux de change
├── modele/
│   ├── caracteristiques.py   ce qu'on donne à voir au modèle
│   └── entrainement.py       entraînement, évaluation, prévision
└── web/
    ├── app.py             l'application web (FastAPI)
    └── templates/         la page
scripts/
├── initialiser.py         constitution de l'historique, à lancer une fois
├── mettre_a_jour.py       tâche quotidienne
└── entrainer.py           réentraînement à la demande
```

Pour comprendre le projet, deux fichiers suffisent : `config.py` pour les
réglages, et `modele/caracteristiques.py` pour la manière dont la prévision
est construite. Chacun est abondamment commenté.

---

## Une subtilité qui compte

Le fichier officiel ne contient pas un relevé quotidien par station : une
station n'y publie une ligne que lorsqu'elle **change** son prix. Calculer
naïvement la moyenne des lignes d'un jour donné reviendrait à ne moyenner que
les stations ayant bougé ce jour-là — un échantillon tout sauf représentatif.

`sources/historique.py` reconstitue donc, pour chaque station, le prix en
vigueur chaque jour en propageant le dernier changement connu. C'est ce qui rend
les moyennes comparables d'un jour à l'autre.

---

## Licence

MIT.
