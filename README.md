# protee

**English** | [Français](README.fr.md)

[![CI](https://github.com/miki4iaml/protee/actions/workflows/ci.yml/badge.svg?branch=develop)](https://github.com/miki4iaml/protee/actions/workflows/ci.yml)
[![CodeQL](https://github.com/miki4iaml/protee/actions/workflows/github-code-scanning/codeql/badge.svg)](https://github.com/miki4iaml/protee/actions/workflows/github-code-scanning/codeql)
[![Python](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2Fmiki4iaml%2Fprotee%2Fdevelop%2Fpyproject.toml)](pyproject.toml)
[![License](https://img.shields.io/github/license/miki4iaml/protee)](LICENSE)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.24619907.svg)](https://doi.org/10.5281/zenodo.24619907)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/)
[![Conventional Commits](https://img.shields.io/badge/Conventional%20Commits-1.0.0-fe5196)](https://www.conventionalcommits.org/en/v1.0.0/)

**Proteus: graph and operations research algorithms whose methods are
chosen explicitly, compared, and backed by certificates and
diagnostics.**

Pure Python package, depending only on NumPy and SciPy (wheels for
every supported platform); it works on an offline workstation (no
online solver, service or engine).

> Pre-alpha: a first set of graph and flow algorithms is available
> (`protee.graph`, `protee.paths`, `protee.routes`, `protee.flow`,
> `protee.structure`, `protee.transforms`, `protee.io`), with
> requirements turned into traceable constraints on graphs
> (`protee.constraints`); their API is provisional until version 1.0,
> and the model of life-cycle profiles is being designed.

Every method returns the same [result model](docs/results.md)
(`protee.results`): a status, the certificate it calls for (a violated
cut, an improving cycle, the nodes a search reached), the guarantee of
the method, deterministic work counters, the version and a fingerprint
of the inputs. Each module lists its methods with `methods()`.

Typed graphs are exchanged with other projects in the node-link format
[`protee-node-link/0`](docs/node-link-format.md) (`protee.io`), and
drawn by `protee.viz`: selection, groups, loops, contraction, colour by
vocabulary and a matrix view (N² chart) without dependency; SVG figures,
light or dark, with their legend and a footer, and a page to explore
offline (tooltips, formulas, the matrix under the graph), with the
optional extra `viz` (see the [gallery](docs/gallery/README.md)).

## Why protee

Many graph problems start from requirements written by people: a
client's specification, a regulation, a doctrine, a standard. "The
mass of the vehicle stays within the load limit of each bridge", or
"this situation occurs at most twice in the life of the equipment",
becomes a constraint on a graph, and a method returns a route or a
flow. To trust that result, each requirement must be traceable from its
source to its proof.

protee implements this chain of six links:

1. **source**: the document, its edition and paragraph, or the
   client's statement;
2. **normalized requirement**: an identified statement, in English and
   in other languages if needed;
3. **constraint pattern**: a generic, named form (arc admissibility,
   speed cap, occurrence bounds…), without values;
4. **values**: from value sets, each value with its source, edition and
   precedence; missing data stay unknown, never presumed compatible;
5. **named method**: chosen explicitly by the caller;
6. **proof**: each requirement verified on the result, independently of
   the method (`applied`, `partial`, `not_applied`, `no_data`,
   `not_applicable`), with its impact (the result with and without it)
   and the provenance of the result.

Each link has precedents; we did not find the complete chain in the
sources we reviewed. Two reference applications guide and validate it:
life-cycle profiles (the graph of the situations an equipment goes
through, from manufacture to use) and route planning on large road
networks. protee provides a value set taken from a public text, for
testing and illustration.

## Installation

From PyPI, with Python 3.12 or later:

```
pip install protee
```

The drawing in SVG and in a page to explore (`protee.viz.render_svg`,
`protee.viz.render_html`) needs the optional extra `viz`:

```
pip install "protee[viz]"
```

Converting the inputs of a derivation into the unit of their parameter,
and showing values readably (`protee.constraints.readable`), need the
optional extra `units`:

```
pip install "protee[units]"
```

To work on protee itself, see the
[contributing guide](.github/CONTRIBUTING.md).

## Contributing

Contributions are welcome: see the [contributing guide](.github/CONTRIBUTING.md)
and the rules shared by contributors and coding agents in
[AGENTS.md](AGENTS.md).

## License

[BSD-3-Clause](LICENSE). The page written by `protee.viz.render_html`
embeds cytoscape.js and cytoscape-expand-collapse, under the MIT licence
([notice](src/protee/_assets/NOTICE.md)); the embedded value set reuses a
public text under the [Licence Ouverte 2.0](https://spdx.org/licenses/etalab-2.0.html),
credited in its notice.

How protee runs, is developed and published, and what it ships:
[security, supply chain and compliance](docs/security-and-compliance.md).
