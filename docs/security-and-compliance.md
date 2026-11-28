# protee — security, supply chain and compliance

*A file to help assess protee, dated 22 November 2026.*

| Item | Value |
|---|---|
| Component | protee, a Python package of graph and operations research algorithms |
| Published version assessed | 0.1.0 (22 November 2026), on PyPI |
| State of development | branch `develop` on 22 November 2026 |
| Repository | <https://github.com/miki4iaml/protee> |
| Licence | BSD-3-Clause (code); MIT (embedded JavaScript); Licence Ouverte 2.0 (embedded value set) |
| Persistent identifier | none yet for 0.1.0; the next versions are to be archived on Zenodo |
| Vulnerability reporting | GitHub private reporting, see [`.github/SECURITY.md`](../.github/SECURITY.md) |

## 1. Purpose and method

This file is for those who must authorize the use of protee on a
laboratory network, in particular one without direct Internet access, and
for the users who prepare that request. It describes:
- how the component behaves when it runs;
- how it is developed, checked and published;
- how licences and the rights of sources are respected;
- the regulatory landmarks that apply;
- the known limits, and what remains for the user to do;
- the outlook, tied to the DevSecOps cycle.

Each statement points to something that can be checked. Four levels of
evidence are told apart:
- **[public]**: anyone can check it, in the repository, on PyPI or in the
  logs of continuous integration;
- **[administrator]**: a setting of the GitHub repository, visible to its
  administrator only, declared here by the maintainer;
- **[maintainer]**: a practice declared by the maintainer, with no public
  trace to check today;
- **[user]**: a check the user makes.

The file describes a dated state. It is neither a certification, nor an
independent audit, nor legal advice.

**Citing this file**: by its path in the repository at a given version
(file `docs/security-and-compliance.md` of the tag `vX.Y.Z`). A citation
then names a fixed text that can be checked.

## 2. Summary

| Area | Finding |
|---|---|
| Running | No network access, no telemetry, no file written unless the caller asks. Works entirely offline. One subprocess only: orthogonal edges are laid out by a child process of the same Python, without a shell. |
| Input data | Graphs and node-link documents are data: checked against the format, never executed; the package uses neither `eval` nor `exec`. Texts drawn in SVG or HTML are escaped, and links that would open a script are dropped. An image given for the footer of a figure is embedded as an image, never linked. |
| Dependencies | Two runtime dependencies (NumPy, SciPy), under permissive licences; pygraphviz with its bundled Graphviz (EPL-2.0) in the optional extra `viz`. |
| Approach | DevSecOps principles applied from planning to publication on PyPI, with the security means GitHub offers to public repositories (section 12). |
| Development | Protected branches, owner review, signed and verified commits, blocking automatic checks, code scanning (CodeQL), secret detection. |
| Publication | Built once, provenance (SLSA Build Level 2) and software bill of materials (SBOM) attested, published without a stored token after human approval, rehearsal on TestPyPI. |
| Licences and sources | Code BSD-3-Clause; embedded third-party files declared with their licences; embedded values taken from a public text, with its notice. |
| Regulation | No personal data processed; free software, not monetized; the right of rights holders to object is respected. |
| Main limits | One maintainer; version 0.x; no external audit; no DOI for 0.1.0. |

## 3. Description of the component

protee is a Python package (version 3.12 or later) of graph and operations
research algorithms whose methods are chosen explicitly, compared, and
backed by certificates and diagnostics. It also turns requirements taken
from a source into traceable constraints on graphs.

**Runtime dependencies** (package installed without an extra) [public]:

| Dependency | Version on 22 November 2026 | Lower bound | Licence |
|---|---|---|---|
| numpy | 2.5.4 | 2.3.2 (2.5.2 on Python 3.15) | BSD-3-Clause (and components 0BSD, MIT, Zlib, CC0-1.0) |
| scipy | 1.18.1 | 1.16.1 (1.18.1 on Python 3.15) | BSD-3-Clause |

`import protee` imports neither of them: the subpackages that use them
import them when they are first used.

**Optional extra `viz`** [public]: pygraphviz 2.0.4 (BSD-3-Clause), for the
SVG drawing and the exploration page. Its wheels for Windows, Linux
(manylinux, x86-64 and ARM 64) and macOS bundle the Graphviz library and
programs, under the Eclipse Public License 2.0 (text in the wheel,
`LICENSE.graphviz`). On another platform, pygraphviz builds from its
source archive against a Graphviz installed on the workstation.

`pyproject.toml` declares lower bounds, not pinned versions: see
section 7 for an installation at locked versions.

**Embedded data** [public]:
- the JavaScript of the exploration page, cytoscape.js 3.35.0 and
  cytoscape-expand-collapse 4.1.1 (MIT), in `src/protee/_assets/`, whose
  `NOTICE.md` gives their origin and the SHA-256 digests of the files as
  published and as shipped;
- the JSON Schema of the exchange format `protee-node-link/0`
  (`src/protee/schemas/`), written by protee;
- a value set taken from a public text, the French order of 4 May 2006 on
  exceptional transport (`src/protee/constraints/data/`), reused under the
  Licence Ouverte 2.0, credited in the notice of the file.

## 4. Behaviour when running

**Network, processes, files** [public, checkable by reading the code in
`src/protee/`]:
- no network access: the package imports no network module; the rule
  "works on an offline workstation" is part of the project's rules
  (`AGENTS.md`);
- one subprocess, and no other system call: the drawing calls the
  Graphviz library that pygraphviz loads into the same process, and never
  the Graphviz programs its wheels also contain, except for orthogonal
  edges (`splines="ortho"`). Their routing in Graphviz can stop the
  process that runs it, so `protee.viz.render_svg` lays them out in a
  child process of the same Python (`sys.executable -I`, its arguments as
  a list, no shell, the import path and the DOT text on its input), which
  writes the SVG; it raises an error if that child stops or cannot start,
  whatever the spelling of `ortho`;
- an image given as the footer of a figure (`render_svg(footer=...)`, or
  of the page, `render_html(footer=...)`) is bytes, never a file name or a
  URL: only a PNG or an SVG with a `viewBox` is read (an SVG with a
  DOCTYPE is refused), and it is embedded whole as an image (an `image`
  element in the SVG, an `img` element in the page, with a `data:` URI),
  which browsers draw without running its scripts or fetching anything;
- a formula shown in the exploration page (`render_html(math=...)`) is
  data, never markup: a tree checked in Python (eleven MathML elements of
  a closed list, no attribute; at most 4000 elements and texts, 20,000
  characters of text, 32 levels), then built by the page element by
  element (`createElementNS`), its texts as text nodes; the page script
  uses neither `innerHTML` nor `setAttribute`;
- no telemetry and no data collection;
- no file written unless the caller asks: `protee.io.write_node_link`,
  `write_arcs_csv` and `write_dimacs_min` write the file they are given;
  the drawing functions return text;
- embedded data is read only, through `importlib.resources`.

**Input data** [public: `src/protee/io.py`, `src/protee/viz.py`]:
- a node-link document is plain JSON data; `protee.io.check_node_link`
  lists its departures from the format, and the drawing refuses a document
  that does not follow it; the JSON Schema of the format allows a consumer
  to check a document without protee;
- `read_node_link` refuses the non-JSON tokens `NaN` and `Infinity`;
  `write_node_link` writes strict JSON;
- the package contains no `eval` and no `exec`; no text of a document is
  executed;
- the texts of a document are escaped where they are drawn: quoted in the
  Graphviz DOT language, every `&` written `&amp;` so that a character
  reference is drawn as written and never decoded by the reader of the
  SVG (a character that XML cannot carry is refused), escaped in HTML, and
  every `<` escaped in the data of the exploration page, so that no text
  can close or comment out an element;
- a node's link is kept only for an `http`, `https` or `mailto` address
  or a link relative to the page, read as a browser reads it (character
  references decoded): a `javascript:` or `data:` address, or a link to
  another host without a scheme (`//host`, which a page opened from a
  file reads as `file://host`), is dropped from the SVG and from the
  page;
- the exploration page fetches nothing: it embeds its scripts and opens
  offline.

**Concurrency** [public]: no mutable global state; reference data is
immutable (frozen structures, read-only arrays).

## 5. Secure development: practices and checks (DevSecOps approach)

### 5.1 Change management

- **Protected branches** [administrator]: on `develop` and `main`,
  deletion and history rewriting are forbidden; every change goes through
  a pull request, up to date with its target branch; merged as one commit
  (squash) on `develop`, by a merge commit on `main`.
- **Checks required before merging** [administrator, public results]:
  quality (all the automatic checks of section 5.2, strict typing
  included), signatures, and tests on six configurations (Ubuntu and
  Windows, Python 3.12, 3.13 and 3.14).
- **Owner review** [public: `.github/CODEOWNERS`]: changes to the
  workflows, the scripts, the configuration of the checks and the
  instruction files of coding agents need the maintainer's review.
- **Signed and verified commits** [administrator, checkable on each
  commit]: required on the protected branches; a check of continuous
  integration (`signatures`) also verifies each commit of a pull request,
  which the squash merge would hide.

### 5.2 Automatic checks

Run on each contributor's workstation before each commit, then replayed
identically in continuous integration [public:
`.pre-commit-config.yaml`, `.github/workflows/ci.yml`]:
- formatting, static analysis (ruff), strict typing (mypy), spelling
  (codespell);
- **secret detection** (gitleaks, private key detection);
- **security analysis of the GitHub Actions workflows** (zizmor);
- **integrity**: refusal of invisible or control characters, of
  unauthorized instruction files of coding agents and of files that must
  stay local (`scripts/check_integrity.py`);
- **confidentiality**: refusal of personal or internal data in files and
  commit messages (`scripts/check_anonymity.py`), and of metadata in
  images (`scripts/check_image_metadata.py`);
- format of commit messages (Conventional Commits, ASCII-only subject).

Continuous integration also checks that the lock file `uv.lock` matches
`pyproject.toml` [public: `.github/workflows/ci.yml`].

**Tests** [public]: 618 tests on 22 November 2026, run on the complete and
blocking matrix, including property-based tests (Hypothesis) and tests
against independent oracles (NetworkX, HiGHS, jsonschema, enumeration);
branch coverage measured (99 % on 22 November 2026), with a floor of 80 %
required in each configuration.

### 5.3 Platform security

- **GitHub Actions pinned by digest** (commit SHA), not by a moving tag
  [public: workflows; administrator: pinning enforced by the repository];
  only actions from GitHub and verified creators are allowed
  [administrator].
- **Least privilege** [public: workflows; administrator]: read-only
  permissions by default, raised only in the job that needs them;
  workflows cannot approve a pull request.
- **No stored secret**: publication on PyPI authenticates with short-lived
  OIDC tokens [public: workflows].
- **Code scanning**: CodeQL (Python and GitHub Actions) [administrator,
  results in the Security tab].
- **Dependencies**: Dependabot alerts and security updates; version
  updates grouped and proposed seven days at the earliest after their
  release, so that a compromised version has more chances of being
  detected before it is adopted [public: `.github/dependabot.yml`].
  Dependabot does not watch the embedded JavaScript: the GitHub Advisory
  Database is checked for it before each release [public: release
  procedure in `.github/CONTRIBUTING.md`].
- **Secrets**: detection and push protection [administrator].
- **Vulnerabilities**: private reporting enabled, policy published
  [public: `.github/SECURITY.md`].

### 5.4 Coding agents

The project uses coding agents (artificial intelligence assistants). Every
contribution is reviewed and signed by a human, who answers for it. The
instruction files of these agents are treated as code: owner review,
integrity check, and contributions from others read as differences,
without running them in an environment where an agent works [public:
`.github/CONTRIBUTING.md`, section "Coding agents"].

## 6. Publication and provenance

[public: `.github/workflows/release.yml`, `.github/CONTRIBUTING.md`
(section "Releasing"), PyPI, GitHub]
- Version tags (`v*`) are protected against deletion and modification;
  GitHub releases are immutable [administrator].
- Publication is triggered by a GitHub release, made from a version tag
  signed by the maintainer. The workflow checks that the tag matches the
  declared version, builds the package **once**, checks it
  (`twine check --strict`, no relative link left in its description) and
  publishes exactly the files it built.
- It produces two **signed attestations** (Sigstore): the provenance of
  the build and a software bill of materials (SBOM) in the CycloneDX
  format. According to GitHub's documentation, a provenance attestation
  of this kind meets Build Level 2 of SLSA v1.0.
- Publication on PyPI goes through **Trusted Publishing** (OIDC, no stored
  token), after **human approval** of the protected environment `pypi`,
  reserved to the tags `v*`.
- A release can first be **rehearsed** on TestPyPI, with a unique
  development version and without creating a release; version 0.1.0 was.
- PyPI shows the provenance attestation (PEP 740) of each published file;
  for the wheel and the source archive of version 0.1.0, it names the
  repository `miki4iaml/protee`, the workflow `release.yml` and the
  environment `pypi`.
- Version 0.1.0 has no DOI; the next versions are to be archived on
  Zenodo, each with its own DOI.

**Verification** [user, on a connected workstation]:

```
gh attestation verify protee-0.1.0-py3-none-any.whl --repo miki4iaml/protee
gh attestation verify protee-0.1.0-py3-none-any.whl --repo miki4iaml/protee --predicate-type https://cyclonedx.org/bom
```

The first command checks the provenance, the second the SBOM.

## 7. Installation on a network without Internet access

A suggested procedure, to adapt to local rules [user]:
1. On a connected workstation, download protee and its dependencies for
   the target platform (with the extra `viz` if the drawing is needed):

   ```
   python -m pip download "protee[viz]==0.1.0" --dest packages --only-binary=:all:
   ```

   For another platform or Python version than the workstation's, give
   `--platform` and `--python-version`. pygraphviz publishes wheels for
   Windows, Linux (manylinux, x86-64 and ARM 64) and macOS only.
2. Verify the attestations of protee (section 6) and record the SHA-256
   digests of the downloaded files.
3. Transfer the files following the local procedure, after the required
   antivirus check.
4. On the target workstation, install without network access:

   ```
   python -m pip install --no-index --find-links packages "protee[viz]==0.1.0"
   ```

   To lock versions and digests, use a requirements file with digests
   (`--require-hashes`).
5. protee then works entirely offline, its exploration page included.

## 8. Licences, citations and rights of sources

- **Code**: BSD-3-Clause. Every source file carries its SPDX licence
  identifier [public].
- **Embedded third-party files** [public: `pyproject.toml`,
  `src/protee/_assets/NOTICE.md`, `src/protee/constraints/data/`]: the
  JavaScript of the exploration page (MIT) and the value set reused under
  the Licence Ouverte 2.0. The licence expression of the package declares
  them all (`BSD-3-Clause AND MIT AND etalab-2.0`). The texts of the MIT
  licences ship in the package; the Licence Ouverte 2.0 asks for the
  source to be acknowledged, which the notice of the value set does.
- **Optional extra `viz`**: pygraphviz (BSD-3-Clause) and the Graphviz it
  bundles (Eclipse Public License 2.0). protee does not redistribute
  Graphviz: the user installs it with pygraphviz.
- **Traceability of requirements** [public: `protee.constraints`]: each
  requirement keeps its source (document, edition, paragraph); each value
  keeps its origin, its rulebook, its edition and its precedence; each
  result records its provenance (method, parameters, version, digests of
  its inputs).
- **Citing protee**: `CITATION.cff` [public]; a DOI from the next version
  on.
- **Rights of source documents** [maintainer]:
  - standards under licence (ISO, AFNOR) are for internal use only: never
    reproduced, never published;
  - the package ships only value sets taken from public texts, each with
    its notice; no source document is redistributed, neither in the
    repository nor in the package [public, checkable by the content of
    the repository and of the package];
  - before a document is analysed, a clause forbidding its processing by
    artificial intelligence is looked for; a document that carries one is
    not analysed;
  - protections against robots and paid access are never bypassed.
- **Personal data**: none collected; automatic checks keep personal or
  internal data out of the repository (section 5.2).

## 9. Regulatory landmarks

These landmarks inform the assessment of an organization; they are not
legal advice.

- **Data protection (GDPR)**: protee collects, transmits and keeps no
  personal data. It therefore performs no processing within the meaning of
  Regulation (EU) 2016/679; the data a user gives it stay under that
  user's responsibility.
- **Cyber Resilience Act** (Regulation (EU) 2024/2847): it targets products
  made available on the market, that is supplied in the course of a
  commercial activity (recital 18). Its article 14 (reporting obligations)
  applies since 11 September 2026, its other provisions from 11 December
  2027 (article 71, paragraph 2). According to the text:
  - supplying free software that its manufacturer does not monetize is not
    a commercial activity (recital 18);
  - hosting it in an open repository or a package manager is not, in
    itself, making it available on the market (recital 20);
  - the status of open-source software steward is reserved to legal
    persons (article 3, point 14).

  protee, supplied free of charge by a natural person, is therefore, on
  this reading, outside the scope of these obligations. A manufacturer who
  integrates protee into a product placed on the market exercises due
  diligence on this component (article 13, paragraph 5) and reports its
  vulnerabilities to its maintainer (article 13, paragraph 6). The SBOM,
  the attestations and the reporting policy (`.github/SECURITY.md`) make
  this diligence easier. protee also applies several practices the
  regulation expects from manufacturers: a vulnerability handling policy,
  an SBOM, security updates.
- **Text and data mining**: Directive (EU) 2019/790 (article 4),
  transposed in article L. 122-5-3 of the French intellectual property
  code, lets rights holders object to the mining of their works; under
  article R. 122-28 of the same code, the objection need not be reasoned
  and may be expressed by any means. Checking for prohibition clauses
  before an analysis (section 8) respects this right to object.
- **Licences**: the BSD-3-Clause and MIT licences allow use, modification
  and redistribution, including internally, provided the copyright notice
  and the licence are kept; the Licence Ouverte 2.0 allows reuse provided
  the source is acknowledged. The Eclipse Public License 2.0 of Graphviz,
  in the optional extra, is a weak copyleft licence: it constrains whoever
  redistributes Graphviz, not its use.

## 10. Known limits and open points

- **One maintainer.** The continuity of the project and the time to fix
  rest on one person; acknowledging a report within seven days is a
  target, not a contractual commitment (`.github/SECURITY.md`).
- **Version 0.x.** The public interface is not yet stable; only the latest
  published version receives security fixes.
- **No independent audit** of security or code has been carried out.
- **No standardized assessment published** (OpenSSF Scorecard, OpenSSF
  Best Practices badge).
- **SLSA**: Build Level 3 would need an isolated build in a reusable
  workflow; it is not targeted today.
- **Binary reproducibility** of the build is not checked. The SVG drawings
  are identical for the same document, the same versions and the same
  fonts: Graphviz measures text with the fonts of the workstation.
- **SBOM**: attested on GitHub, it is not published on PyPI.
- **Versions of dependencies**: the package declares lower bounds; locking
  versions and digests is up to the user (section 7).
- **Verifying attestations** needs network access; it is done on a
  connected workstation, before the transfer.
- **No lint rule forbids `eval` or `exec`** in the package: their absence
  is checked by reading the code, not enforced by a blocking rule.
- **Embedded JavaScript**: Dependabot does not watch it; the advisories are
  checked by hand before each release.
- **No fuzzing** of the readers of the formats; property-based tests cover
  the writing and reading of node-link documents, not arbitrary input.
- **No DOI for version 0.1.0**: its persistent archiving starts with the
  next version.
- **Rights of sources**: the practices of section 8 marked [maintainer]
  are not yet written in the public rules of the project
  (`.github/CONTRIBUTING.md`), where they would become checkable and
  binding on contributors.

## 11. Checklist

| # | Checkpoint | State | Where to check |
|---|---|---|---|
| 1 | Code licence compatible with the intended use | Done (BSD-3-Clause) | `LICENSE` |
| 2 | Licences of embedded data and dependencies identified | Done | `pyproject.toml`, `NOTICE.md`, section 3 |
| 3 | No network access or telemetry when running | Done | Source code, section 4 |
| 4 | No execution of supplied text (`eval`, `exec`) | Done, by code reading | Source code, section 4 |
| 5 | No personal data processed | Done | Sections 4 and 9 |
| 6 | Protected branches, review and signed commits | Done | Commit history, section 5.1 |
| 7 | Blocking automatic checks and tests | Done | Logs of continuous integration |
| 8 | Secret detection, code scanning | Done | `.pre-commit-config.yaml`, Security tab |
| 9 | Pinned actions, least privilege | Done | `.github/workflows/` |
| 10 | Attested publication (SLSA Build Level 2), without a stored token | Done | `release.yml`, PyPI, `gh attestation verify` |
| 11 | Vulnerability reporting policy | Done | `.github/SECURITY.md` |
| 12 | Sources of requirements and values traced | Done | `protee.constraints`, embedded value set |
| 13 | Texts drawn in SVG or HTML escaped, script links dropped | Done | `src/protee/viz.py`, tests |
| 14 | Rules on the rights of sources written and public | To do | Section 10 |
| 15 | Blocking rule against `eval` and `exec` | To do | Section 10 |
| 16 | Attestation checked before transfer | Up to the user | Section 6 |
| 17 | Versions and digests locked at installation | Up to the user | Section 7 |
| 18 | Independent audit | To do | — |
| 19 | OpenSSF assessment published | To do | — |
| 20 | Binary reproducibility checked, SLSA Build Level 3 | To do | — |
| 21 | Continuity beyond one maintainer | To do | — |
| 22 | Fuzzing of the format readers | To do | Section 10 |
| 23 | SBOM published on PyPI | To do | Section 10 |
| 24 | Persistent identifier (DOI) for each version | To do from the next version | Section 6 |

## 12. Outlook and DevSecOps principles

The DevSecOps approach builds security into each stage of the software
life cycle, automates it, and shares its responsibility between those who
develop the software and those who operate it. protee applies it to the
stages it controls, from planning to publication on PyPI, its only channel
of distribution today. Deployment and operation take place in the user's
information system: the project contributes what it supplies (offline
operation, attestations, SBOM, installation procedure), without
controlling them.

The project uses for this the security means GitHub offers free of charge
to public repositories: protection rules for branches and tags, CodeQL
code scanning, secret detection and push protection, Dependabot alerts
and updates, private vulnerability reporting, protected environments, OIDC
tokens, artifact attestations and immutable releases.

The project will keep following DevSecOps principles and good practices.
Any change to its chain will be described in this file, dated and
versioned with the code. This is an intention of the maintainer, not a
contractual commitment.

The table below ties each checkpoint of section 11 to a stage of the
DevOps cycle, and to the corresponding practices of the NIST SSDF
(SP 800-218, version 1.1). A checkpoint may belong to several stages.

| Stage | Contribution of protee | Done | To do | Up to the user | SSDF practices |
|---|---|---|---|---|---|
| Plan | Project rules, offline operation required, dependencies under permissive licences | 1, 2, 12 | 14, 21 | — | PO.1, PO.2, PW.4 |
| Code | No execution of supplied text, escaping of drawn texts, owner review, signed commits, checks before commit | 3, 4, 5, 6, 8, 13 | 15 | — | PS.1, PW.1, PW.5, PW.7 |
| Build | Pinned actions, least privilege, built once | 9 | 20 | — | PO.3, PO.5, PW.6 |
| Test | Blocking checks and tests on six configurations, oracles, CodeQL | 7, 8 | 18, 22 | — | PO.4, PW.7, PW.8 |
| Release | Attestations, Trusted Publishing, human approval, rehearsal, immutable releases | 10 | 23, 24 | — | PS.2, PS.3 |
| Deploy | Offline installation procedure (section 7) | — | — | 16, 17 | PS.2, PW.4 (user side) |
| Operate | Offline operation, without network, telemetry or personal data | 3, 5 | — | — | PW.9 |
| Monitor | Dependabot, CodeQL, private vulnerability reporting, advisories of embedded JavaScript checked | 11 | 19 | — | RV.1, RV.2 |

Checkpoints 1, 12 and 14 (licences, traceability of requirements, rights
of sources) belong to legal compliance and scientific integrity; the SSDF
does not cover them.

**Outlook.** Integrating protee into an information system run with
DevOps (containers, orchestration, continuous deployment, central
management of secrets) is the organization's business. The published
attestations and SBOM can feed the verification of components when
images are built. The project publishes no container image today.

## References

- Scientific Python, SPEC 8, *Securing the Release Process*:
  <https://scientific-python.org/specs/spec-0008/>.
- GitHub, *Using artifact attestations to establish provenance for
  builds* (SLSA v1.0 Build Level 2):
  <https://docs.github.com/en/actions/security-guides/using-artifact-attestations-to-establish-provenance-for-builds>.
- PEP 740, *Index support for digital attestations*.
- NIST SP 800-218, *Secure Software Development Framework (SSDF)
  Version 1.1*, February 2022: <https://csrc.nist.gov/pubs/sp/800/218/final>.
- Regulation (EU) 2024/2847 (Cyber Resilience Act), OJ L of 20 November
  2024: <http://data.europa.eu/eli/reg/2024/2847/oj>; recitals 18 to 20,
  articles 3, 13, 14, 24 and 71.
- European Commission, *Cyber Resilience Act — open source*:
  <https://digital-strategy.ec.europa.eu/en/policies/cra-open-source>.
- Regulation (EU) 2016/679 (GDPR); Directive (EU) 2019/790, article 4;
  French intellectual property code, articles L. 122-5-3 and R. 122-28.
- Etalab, Licence Ouverte 2.0 (SPDX `etalab-2.0`):
  <https://spdx.org/licenses/etalab-2.0.html>.
- Security policy of the project: `.github/SECURITY.md`.
- Rules of the project: `AGENTS.md`, `.github/CONTRIBUTING.md`.
