# Third-party files

Embedded in the pages written by `protee.viz.render_html`, which open
offline. Each file comes from its npm package, checked against the
integrity published by the npm registry. Two changes only, which keep
the meaning of the code: a final newline where it lacks, and, in
`cytoscape.min.js`, the one zero-width space of a string literal
written as its escape `\u200B` (the same JavaScript value), so that
the repository's check for hidden characters passes.

| File | Package | Version | Path in the package | SHA-256 upstream | SHA-256 here |
|---|---|---|---|---|---|
| `cytoscape.min.js` | cytoscape | 3.35.0 | `package/dist/cytoscape.min.js` | `71fa9ebec21a7ca2c40cff6aacc30d1f6464e363662ad4b2c197e1adc770cd94` | `48de7dc1403b3455cf8ee85c440637f1525ca5c0f518d62daadefe4b3efef853` |
| `cytoscape.LICENSE.txt` | cytoscape | 3.35.0 | `package/LICENSE` | `eb319c6e6f233607f71e8e2f450391751883cfc0eeb3ca7ef574c13d1d9c2203` | `f7ebdc2a36c48b5413fe0b60f7a16b6163ff171d5bb35f27dfda432962dd4f49` |
| `cytoscape-expand-collapse.js` | cytoscape-expand-collapse | 4.1.1 | `package/cytoscape-expand-collapse.js` | `0f2ad3c36a62c61071076044f70f7db844a816d199de3619373efd9d1ab864e6` | `75182544e61fd5317a60e2840db31bcf3d1426a3326a9563c6d007aed043fbe8` |
| `cytoscape-expand-collapse.LICENSE.md` | cytoscape-expand-collapse | 4.1.1 | `package/LICENSE.md` | `7653ed3cdf53bc1b49f15666b964de4b24eae3bbffcb1fba6fe4817bc9be9926` | `7653ed3cdf53bc1b49f15666b964de4b24eae3bbffcb1fba6fe4817bc9be9926` |

Licences: both packages are under the MIT licence; their texts are
`cytoscape.LICENSE.txt` (The Cytoscape Consortium) and
`cytoscape-expand-collapse.LICENSE.md` (iVis@Bilkent).
