# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Write the gallery of ``protee.viz``: SVG drawings and the page that shows them.

The documents are those written by the graph export of nomogram (producer
version 0.8.0) and kept in the tests of protee. Each drawing is written by
the call shown under it on the page.
From the root of the repository, with the optional extra ``viz``::

    uv run python docs/gallery/make_gallery.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, NamedTuple

from protee import viz

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "tests" / "data" / "node_link"
GALLERY = Path(__file__).resolve().parent


class Case(NamedTuple):
    """A drawing: its file, its title, what it shows, and the call that
    writes it (evaluated with ``viz``, ``coare``, ``kinds``, ``CLOSING`` and
    ``MARK``).
    """

    stem: str
    title: str
    text: str
    call: str


CASES = (
    Case(
        stem="coare-loop",
        title="A system of equations, in the order of its source",
        text=(
            "The surface layer of COARE 3.6: equations (ellipses) give or read "
            "variables (rectangles); inputs, unknowns and intermediates are told "
            "apart by their fill and border. The reads that close the loop are "
            "dashed and do not constrain the layout."
        ),
        call='viz.render_svg(coare, styles=CLOSING, order_by="rank", legend="below")',
    ),
    Case(
        stem="coare-condensed",
        title="The same system, its loop condensed",
        text=(
            "The 26 equations and variables solved together become one node, "
            "with a triple border; the inputs stay outside. In the legend, the "
            "unknowns and intermediates, which no node shown carries, take a "
            "rounded box."
        ),
        call='viz.render_svg(viz.condense(coare), styles=CLOSING, legend="below")',
    ),
    Case(
        stem="coare-friction-velocity",
        title="The neighbourhood of one variable",
        text=(
            "The friction velocity and the nodes one link away; the neighbours "
            "of the selection are dashed and grey, with the number of their "
            "neighbours not shown."
        ),
        call=(
            "viz.render_svg(\n"
            '    viz.select(coare, ["variables.u_s"], depth=1),\n'
            "    styles=CLOSING,\n"
            '    legend="below",\n'
            ")"
        ),
    ),
    Case(
        stem="coare-contracted",
        title="The same system, each equation joined with what it gives",
        text=(
            "Each equation and the variable it gives become one node, which "
            "keeps the variable and the rank of its equation: the loop reads "
            "from variable to variable. The legend, at the left, shows only the "
            "values that the drawing carries."
        ),
        call=(
            "viz.render_svg(\n"
            '    viz.contract(coare, edge_type="nomogram:gives"),\n'
            "    styles=CLOSING,\n"
            '    order_by="rank",\n'
            '    legend="below-left",\n'
            '    legend_values="present",\n'
            ")"
        ),
    ),
    Case(
        stem="coare-contracted-dark",
        title="The same drawing, dark, with a footer",
        text=(
            "The dark theme, smaller texts for all nodes and edges, and an image "
            "under the drawing at the right of the legend (here a mark made by "
            "the script; a logo, or the attribution that a licence of open data "
            "asks for). The image is embedded in the drawing."
        ),
        call=(
            "viz.render_svg(\n"
            '    viz.contract(coare, edge_type="nomogram:gives"),\n'
            "    styles=CLOSING,\n"
            '    attributes={"node": {"fontsize": "11"}, "edge": {"fontsize": "11"}},\n'
            "    theme=viz.DARK,\n"
            '    order_by="rank",\n'
            '    legend="below-left",\n'
            '    legend_values="present",\n'
            "    footer=MARK,\n"
            ")"
        ),
    ),
    Case(
        stem="coare-matrix",
        title="The same system as a matrix",
        text=(
            "The N² chart of the contracted system: the nodes on the diagonal in "
            "the order of their rank; a row gives, a column reads. The discs above "
            "the diagonal follow the order, the squares below are feedbacks: "
            "exactly the reads that close the loop, framed with the nodes they "
            "join. The top row counts the inputs of each column."
        ),
        call=(
            "viz.render_matrix_svg(\n"
            '    viz.contract(coare, edge_type="nomogram:gives"),\n'
            '    order_by="rank",\n'
            "    loops=True,\n"
            ")"
        ),
    ),
    Case(
        stem="humidity-kinds",
        title="A forest of quantity kinds, from right to left",
        text=(
            "Kinds of humidity, in several trees, and their counterparts in "
            "QUDT, the CF standard names and Wikidata; the relations of SKOS "
            "are told apart by their heads, a symmetric one drawn at both ends."
        ),
        call='viz.render_svg(kinds, direction="RL", legend="below")',
    ),
    Case(
        stem="humidity-families",
        title="The same forest, one node per family",
        text=(
            "Each family (moist air, water vapour, sea water, boundary layer) is "
            "collapsed into one node with a double border."
        ),
        call='viz.render_svg(viz.collapse(kinds), direction="RL", legend="below")',
    ),
    Case(
        stem="humidity-kinds-legend",
        title="A legend alone",
        text=(
            "One column per declared attribute and per kind of element (nodes, "
            "edges), in the order of declaration, to set beside a figure."
        ),
        call="viz.render_legend_svg(kinds)",
    ),
)

#: The reads that close a loop: dashed, and free of the layout.
CLOSING: viz.Styles = {
    "edge": {("role", "nomogram:closing"): {"style": "dashed", "constraint": "false"}}
}

#: The image of a footer: a mark made here, in the colours of the dark theme.
MARK = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 48">'
    b'<rect x="1" y="1" width="158" height="46" rx="6" fill="none"'
    b' stroke="#8B949E" stroke-width="2"/>'
    b'<text x="80" y="30" font-family="Helvetica,Arial,sans-serif"'
    b' font-size="16" text-anchor="middle" fill="#E6EDF3">protee gallery</text>'
    b"</svg>"
)

HEADER = """\
# Gallery of `protee.viz`

Drawings of node-link documents (format
[`protee-node-link/0`](../node-link-format.md)) by `protee.viz`, with the
optional extra `viz`. The documents are written by the graph export of
[nomogram](https://github.com/miki4iaml/nomogram) (producer version 0.8.0)
and kept in the tests of protee (`tests/data/node_link/`); `coare` and
`kinds` are those documents, decoded from JSON. The styles come from the
vocabulary each document declares; the only style given here is
`CLOSING`, and `MARK` is the bytes of a small SVG image made by the
script, drawn as a footer:

```python
CLOSING = {
    "edge": {("role", "nomogram:closing"): {"style": "dashed", "constraint": "false"}}
}
```

`viz.render_html` writes a page to explore the same documents offline
(groups folded and unfolded, filters by declared value and by family, a
search in the labels, tooltips, and links for the nodes that have a
`url`); it is not shown here, as it embeds the JavaScript of
cytoscape.js.

This page and its drawings are written by
[`make_gallery.py`](make_gallery.py):
`uv run python docs/gallery/make_gallery.py`.
"""


def _load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((DATA / name).read_text(encoding="utf-8"))
    return data


def write(folder: Path) -> None:
    """Write the drawings and the page of the gallery into ``folder``."""
    namespace = {
        "viz": viz,
        "CLOSING": CLOSING,
        "MARK": MARK,
        "coare": _load("nomogram-0.8.0-coare36-surface-layer.json"),
        "kinds": _load("nomogram-0.8.0-humidity-kinds.json"),
    }
    sections = [HEADER]
    for stem, title, text, call in CASES:
        svg = eval(call, namespace)  # the literal calls above, shown on the page
        (folder / f"{stem}.svg").write_text(svg, encoding="utf-8", newline="\n")
        sections.append(
            f"## {title}\n\n{text}\n\n```python\n{call}\n```\n\n"
            f"![{title}]({stem}.svg)\n"
        )
    (folder / "README.md").write_text(
        "\n".join(sections), encoding="utf-8", newline="\n"
    )


if __name__ == "__main__":
    write(Path(sys.argv[1]) if len(sys.argv) > 1 else GALLERY)
