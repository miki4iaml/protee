# protee

[English](README.md) | **Français**

> Traduction de [README.md](README.md) ; en cas d'écart, la version
> anglaise fait foi.

[![CI](https://github.com/miki4iaml/protee/actions/workflows/ci.yml/badge.svg?branch=develop)](https://github.com/miki4iaml/protee/actions/workflows/ci.yml)
[![CodeQL](https://github.com/miki4iaml/protee/actions/workflows/github-code-scanning/codeql/badge.svg)](https://github.com/miki4iaml/protee/actions/workflows/github-code-scanning/codeql)
[![Python](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2Fmiki4iaml%2Fprotee%2Fdevelop%2Fpyproject.toml)](pyproject.toml)
[![Licence](https://img.shields.io/github/license/miki4iaml/protee)](LICENSE)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.24619907.svg)](https://doi.org/10.5281/zenodo.24619907)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/)
[![Conventional Commits](https://img.shields.io/badge/Conventional%20Commits-1.0.0-fe5196)](https://www.conventionalcommits.org/fr/v1.0.0/)

**Protée : algorithmes de graphes et de recherche opérationnelle, dont
les méthodes sont choisies explicitement, comparées, et appuyées par
des certificats et des diagnostics.**

Paquet en pur Python, qui ne dépend que de NumPy et de SciPy (roues
pour toutes les plates-formes prises en charge) ; il fonctionne sur un
poste hors ligne (aucun solveur, service ou moteur en ligne).

> Pré-alpha : un premier ensemble d'algorithmes de graphes et de flots
> est disponible (`protee.graph`, `protee.paths`, `protee.routes`,
> `protee.flow`, `protee.structure`, `protee.transforms`, `protee.io`),
> ainsi que la traduction d'exigences en contraintes traçables sur les
> graphes (`protee.constraints`) ; leur API reste provisoire jusqu'à la
> version 1.0, et le modèle des profils de cycle de vie est en cours de
> conception.

Toutes les méthodes rendent le même [modèle de résultat](docs/results.md)
(`protee.results`) : un statut, le certificat qu'il appelle (une coupe
violée, un cycle améliorant, les nœuds atteints par une recherche), la
garantie de la méthode, des compteurs de travail déterministes, la
version et une empreinte des entrées. Chaque module liste ses méthodes
par `methods()`.

La description d'un sujet donne des valeurs, jamais des contraintes :
une phase de [dérivation](docs/derivations.md) (*derive*, page en
anglais) tire des fiches techniques des membres, et des groupes de
membres avec leurs effectifs, les valeurs que les exigences comparent
aux arcs (une enveloppe, une classe par seuils, une valeur choisie selon
cette classe, la longueur d'une colonne), chacune avec sa règle, le
membre qui la fixe et la source de chaque entrée ; une valeur inconnue
est comptée, et reste inconnue sauf si l'appelant en suppose une,
déclarée.

Les graphes typés s'échangent avec d'autres projets au format node-link
[`protee-node-link/0`](docs/node-link-format.md) (`protee.io`, page en
anglais), et se dessinent par `protee.viz` : sélection, groupes,
boucles, contraction, couleur par vocabulaire et vue en matrice
(diagramme N²) sans dépendance ; figures SVG, claires ou sombres, avec
leur légende et un pied de figure, et page à explorer hors ligne
(infobulles, formules, matrice sous le graphe), avec l'extra
facultatif `viz` (voir la [galerie](docs/gallery/README.md)).

## Pourquoi protee

Bien des problèmes de graphes partent d'exigences écrites par des
personnes : la spécification d'un client, une réglementation, une
doctrine, une norme. « La masse du véhicule reste dans la limite de
charge de chaque pont », ou « cette situation survient au plus deux
fois dans la vie du matériel », devient une contrainte sur un graphe,
et une méthode rend un itinéraire ou un flot. Pour se fier à ce
résultat, il faut pouvoir suivre chaque exigence de sa source à sa
preuve.

protee implémente cette chaîne de six maillons :

1. **source** : le document, son édition et son paragraphe, ou
   l'énoncé du client ;
2. **exigence normalisée** : un énoncé identifié, en anglais et, au
   besoin, dans d'autres langues ;
3. **motif de contrainte** : une forme générique et nommée
   (admissibilité d'un arc, plafond de vitesse, bornes d'occurrence…),
   sans valeur ;
4. **valeurs** : tirées de jeux de valeurs, chacune avec sa source, son
   édition et sa préséance ; une donnée absente reste inconnue, jamais
   présumée compatible ;
5. **méthode nommée** : choisie explicitement par l'appelant ;
6. **preuve** : chaque exigence vérifiée sur le résultat,
   indépendamment de la méthode (`applied`, `partial`, `not_applied`,
   `no_data`, `not_applicable`), avec son impact (le résultat avec et
   sans elle) et la provenance du résultat.

Chaque maillon a des précédents ; nous n'avons pas trouvé la chaîne
complète dans les sources consultées. Deux applications de référence
la guident et la valident : les profils de cycle de vie (le graphe des
situations que traverse un matériel, de sa fabrication à son usage) et
le routage sur de grands réseaux routiers. protee propose un jeu de
valeurs tiré d'un texte public, à des fins de test et d'illustration.

## Installation

Depuis PyPI, avec Python 3.12 ou plus récent :

```
pip install protee
```

Le dessin en SVG et la page à explorer (`protee.viz.render_svg`,
`protee.viz.render_html`) demandent l'extra facultatif `viz` :

```
pip install "protee[viz]"
```

La conversion des entrées d'une dérivation dans l'unité de leur
paramètre, et l'affichage lisible des valeurs
(`protee.constraints.readable`), demandent l'extra facultatif `units` :

```
pip install "protee[units]"
```

Pour travailler sur protee lui-même, voir le
[guide de contribution](.github/CONTRIBUTING.fr.md).

## Contribuer

Les contributions sont bienvenues : voir le [guide de contribution](.github/CONTRIBUTING.fr.md)
et les règles communes aux contributeurs et aux agents de codage dans
[AGENTS.md](AGENTS.md) (en anglais).

## Licence

[BSD-3-Clause](LICENSE). La page écrite par `protee.viz.render_html`
embarque cytoscape.js et cytoscape-expand-collapse, sous licence MIT
([notice](src/protee/_assets/NOTICE.md)) ; le jeu de valeurs embarqué
réutilise un texte public sous [Licence Ouverte 2.0](https://spdx.org/licenses/etalab-2.0.html),
crédité dans sa notice.

Comment protee s'exécute, se développe et se publie, et ce qu'il
embarque : [sécurité, chaîne d'approvisionnement et conformité](docs/security-and-compliance.md)
(page en anglais).
