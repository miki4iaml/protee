# Contribuer à protee

[English](CONTRIBUTING.md) | **Français**

> Traduction de [CONTRIBUTING.md](CONTRIBUTING.md) ; en cas d'écart,
> la version anglaise fait foi.

Merci de votre intérêt. Ce guide décrit l'installation, les contrôles
et le circuit d'une contribution. Les règles de code et d'architecture
sont dans [AGENTS.md](../AGENTS.md), qui s'applique aux humains comme
aux agents de codage.

## Comment contribuer

Toutes les contributions sont bienvenues : signaler un problème,
proposer une amélioration dans une issue, ou contribuer au code
(installation, contrôles et parcours ci-dessous). Le paquet n'en est
qu'à ses débuts : son modèle et ses solveurs sont en cours de
conception.

## Prérequis

- Python 3.14 ou plus récent.
- [uv](https://docs.astral.sh/uv/). Il est indispensable : les hooks
  ruff, mypy et pytest passent par `uv run --frozen`, pour utiliser
  exactement les versions figées dans `uv.lock` (une seule source de
  version, en local comme en CI). Sans uv, ces hooks échouent.
- Une clé de signature des commits (voir plus bas).

## Installation

```
uv sync --all-extras
uv run pre-commit install
```

La première commande installe aussi les extras optionnels, s'il y en
a, couverts par les tests. La seconde commande installe les hooks aux
trois stades (pre-commit, commit-msg, pre-push).

## Contrôles locaux

| Stade | Contrôles |
|---|---|
| pre-commit | hygiène des fichiers (espaces, fin de fichier, fins de ligne LF, BOM, YAML, TOML, conflits, gros fichiers), clé privée, refus de commit direct sur `main` et `develop`, `ruff check --fix` et `ruff format`, codespell (orthographe), zizmor (audit de sécurité des workflows), gitleaks, nbstripout, anonymisation, métadonnées des images, caractères cachés et fichiers locaux |
| commit-msg | anonymisation du message, Conventional Commits, sujet sans accent |
| pre-push | mypy strict, pytest |

Dans VS Code, la tâche « Quality gates » enchaîne ruff check,
ruff format --check, mypy et pytest.

### Anonymisation

Inutile d'être expert pour rester anonyme ici : une commande suffit à
la mise en place, et le hook vérifie ensuite chaque commit pour vous.

**Pourquoi.** Des informations personnelles fuient plus facilement
qu'on ne le croit dans un dépôt public : votre répertoire personnel
dans un chemin copié d'un terminal ou d'une sortie de notebook, le
domaine de messagerie de votre employeur, le nom de code d'un projet,
votre nom civil dans un commentaire ou dans les métadonnées d'un
fichier. Une fois poussées, elles restent dans l'historique.

**Fonctionnement.** Le hook `scripts/check_anonymity.py` refuse un
commit quand le contenu d'un fichier, son chemin ou le message de
commit correspond à un *motif interdit*. Il applique :

- des motifs génériques, versionnés ici (chemins de répertoires
  personnels) ;
- vos motifs personnels, lus dans un fichier situé **hors** du dépôt,
  pour que la liste elle-même ne soit jamais publiée.

Le hook signale seulement `fichier:ligne` et n'affiche jamais un motif.

**Mise en place en une commande** (depuis la racine du dépôt) :

```
uv run python scripts/check_anonymity.py --init
```

Elle crée `~/.config/anonymity/deny-patterns.txt` (sous
`$XDG_CONFIG_HOME` s'il est défini), avec un mode d'emploi et des
exemples commentés. Complétez-le avec ce que vous voulez garder privé.
Sans ce fichier, le hook avertit et n'applique que les motifs
génériques.

**Une seule liste pour tous vos dépôts.** Les noms appartiennent à
l'outil, pas à ce projet : tout dépôt qui utilise ce hook lit le même
fichier, et vous ne tenez votre liste qu'une fois. Pour ajouter des
motifs propres à un projet (noms de code d'un client, nom d'un autre
compte que vous gardez séparé), donnez à la variable d'environnement
`ANONYMITY_DENY_PATTERNS` plusieurs fichiers, séparés comme dans `PATH`
(`;` sous Windows, `:` ailleurs), par exemple
`~/.config/anonymity/deny-patterns.txt;~/.config/anonymity/client.txt`.
Chaque fichier listé doit exister : une faute de frappe fait échouer le
hook au lieu d'être ignorée en silence.

**Des motifs pour ce seul dépôt.** La variable d'environnement vaut pour
tous les dépôts. Pour ajouter une liste à ce dépôt seulement, écrivez
son chemin dans `.git/anonymity-deny-patterns` (dans le dossier git,
donc jamais commité) : un chemin par ligne, absolu ou relatif à la
racine du dépôt, par exemple `../mes-notes-privees/motifs-protee.txt`.
Les mêmes règles s'appliquent : le fichier doit exister et rester hors
du dépôt.

**Votre dossier personnel.** Un dossier `_priv/` à la racine du dépôt
est ignoré par git : rangez-y vos notes, analyses ou fichiers
d'assistant, et sauvegardez-les comme vous l'entendez. N'y mettez jamais
de fichier de motifs : un fichier de motifs doit rester hors du dépôt.

**Bien écrire ses motifs.** Une expression régulière par ligne,
insensible à la casse ; lignes vides et commentaires `#` ignorés.

- `\b` marque une frontière de mot : `\bdoe\b` trouve « Doe » mais pas
  « Doerr ».
- Échappez les points : `exemple\.fr` (un point seul vaut n'importe
  quel caractère).
- Pas de normalisation Unicode : prévoyez les variantes avec et sans
  accent, par exemple `h[eé]l[eè]ne`.
- N'y mettez pas votre pseudonyme public s'il figure volontairement
  dans le dépôt (auteur, adresses) : tous les commits seraient refusés.
- Évitez les quantificateurs imbriqués comme `(a+)+` : ils peuvent
  bloquer le hook.

**La liste se protège elle-même.** Un fichier de motifs situé dans le
dépôt est refusé. Le fichier créé par `--init` commence par une ligne
repère, et tout fichier qui la contient est refusé, même en CI : une
copie de votre liste ne peut pas être commitée par erreur. Gardez cette
ligne : une copie partielle qui ne la contient pas n'est pas détectée.

**Images et PDF.** Une image ne porte aucune métadonnée : le hook
`scripts/check_image_metadata.py` refuse texte, EXIF (avec le lieu de
prise d'une photographie), XMP, IPTC, commentaires, horodatages et
profils de couleur, et tout bloc qu'il ne connaît pas, en PNG, JPEG,
GIF, WebP et SVG ; les autres formats sont refusés comme non vérifiés.
Le message nomme le bloc, jamais son contenu. Un PDF garde ses
métadonnées (les auteurs officiels d'une référence) : le hook
d'anonymisation les fouille, décompressées quand elles sont dans un
flux compressé.

**Ce que le hook ne couvre pas.** Les contenus compressés (docx, pages
d'un PDF), l'historique déjà poussé, les noms de branches et
d'étiquettes, et tout ce qui se saisit directement sur GitHub : titres
et descriptions de PR, issues, commentaires. Relisez-les avant de
publier. Le hook peut aussi être sauté en local
(`git commit --no-verify`) : la CI applique alors toujours les motifs
génériques et le contrôle de la ligne repère, mais jamais vos motifs
personnels, qui restent sur votre poste par conception.

## Circuit d'une contribution

1. Créer une branche depuis `develop` (branche par défaut), par
   exemple `feature/graphe-de-profil`.
2. Commits signés, au format Conventional Commits, sujet sans accent :
   `feat: ajout du graphe de profil`.
3. PR vers `develop`. Le titre de la PR suit le même format : il
   devient le message du commit à la fusion par squash.
4. La CI doit être verte. Contrôles exigés :
   - `quality` : les hooks ci-dessus, sur tout le dépôt ;
   - `tests` : Ubuntu et Windows × Python 3.14 et 3.15, avec un plancher
     de couverture des branches à 80 % ;
   - `signatures` : chaque commit de la PR est signé et vérifié.
5. La branche doit être à jour avec `develop` avant fusion.

### Signer ses commits

Avec une clé SSH (la plus simple) :

```
git config gpg.format ssh
git config user.signingkey ~/.ssh/ma_cle.pub
git config commit.gpgsign true
```

Puis enregistrer la clé publique sur GitHub comme *Signing key*
(Settings → SSH and GPG keys). Le badge « Verified » doit apparaître
sur vos commits. Une clé GPG convient aussi.

## Sécurité

Ne signalez jamais une vulnérabilité dans une issue publique : suivez
la [politique de sécurité](SECURITY.md), qui passe par le signalement
privé de vulnérabilités de GitHub.

## Code de conduite

Ce projet applique le [Contributor Covenant](CODE_OF_CONDUCT.md). En
participant, vous vous engagez à le respecter.

## Agents de codage

Ce projet utilise des agents de codage ; toute contribution est relue
et signée par un contributeur humain. Aucune mention d'outil n'est
ajoutée aux commits ni aux PR : la signature humaine engage le
contributeur, quel que soit l'outil employé.

Les fichiers d'instructions des agents de codage se relisent comme du
code. AGENTS.md est le seul suivi, à la racine : le hook
`check-integrity` refuse un AGENTS.md dans un sous-dossier, les fichiers
d'instructions des autres outils (`GEMINI.md`, `.cursorrules`,
`.github/copilot-instructions.md`…), les fichiers qui restent locaux
(`CLAUDE.md`, `.claude/`, `.mcp.json`) et les caractères cachés (largeur
nulle, bidirectionnels, étiquettes, sélecteurs de variante, caractères de
contrôle). Un mainteneur lit une PR d'un tiers comme un diff, sur GitHub
ou avec `gh pr diff`, et ne l'extrait jamais dans un arbre de travail où
tourne un agent de codage : l'agent chargerait les instructions qu'elle
apporte. `.github/CODEOWNERS` liste les chemins dont les modifications
demandent la relecture du mainteneur.

## Licence

En contribuant, vous acceptez que votre contribution soit publiée sous
la licence [BSD-3-Clause](../LICENSE) du projet.
