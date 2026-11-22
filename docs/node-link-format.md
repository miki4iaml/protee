# Node-link format `protee-node-link/0`

A JSON file, in UTF-8, that describes a typed directed graph, to exchange
it between projects and to draw it. It follows the node-link layout of
NetworkX, so that `networkx.node_link_graph(data, edges="edges")` reads
it, and it imposes no dependency on its producer: a project writes it
without protee.

- **Producer**: the program that writes a file. **Consumer**: the program
  that reads it (protee to draw it, NetworkX…).
- **Type**: the nature of a node or of an edge, named by a vocabulary
  prefix and a name, for instance `skos:exactMatch`.

## Example

```json
{
  "directed": true,
  "multigraph": true,
  "graph": {
    "format": "protee-node-link/0",
    "producer": {"name": "example", "version": "1.0"},
    "language": "en",
    "prefixes": {
      "skos": "http://www.w3.org/2004/02/skos/core#",
      "qudt": "http://qudt.org/schema/qudt/",
      "example": null
    },
    "vocabulary": {
      "type": [
        {"id": "example:kind", "on": "node", "label": "quantity kind"},
        {"id": "qudt:specializationOf", "on": "edge", "label": "specializes"},
        {"id": "skos:exactMatch", "on": "edge", "label": "exact match", "symmetric": true}
      ],
      "status": [
        {"id": "verified", "on": "node", "label": "verified"},
        {"id": "to-confirm", "on": "node", "label": "to confirm"}
      ]
    }
  },
  "nodes": [
    {"id": "kinds.RelativeHumidity", "label": "Relative humidity",
     "type": "example:kind", "family": "humidity", "status": "verified",
     "iri": "http://qudt.org/vocab/quantitykind/RelativeHumidity"},
    {"id": "kinds.Humidity", "label": "Humidity", "type": "example:kind",
     "status": "to-confirm"}
  ],
  "edges": [
    {"source": "kinds.RelativeHumidity", "target": "kinds.Humidity", "key": 0,
     "type": "qudt:specializationOf"}
  ]
}
```

## Rules

| Where | Key | Required | Rule |
|---|---|---|---|
| root | `directed` | yes | always `true` |
| root | `multigraph` | yes | a boolean; when `false`, at most one edge per (source, target) pair |
| root | `graph`, `nodes`, `edges` | yes | an object, an array, an array; `links` is read in place of `edges` |
| `graph` | `format` | yes | `"protee-node-link/0"` |
| `graph` | `producer` | no | `{"name", "version"?}`: who wrote the file, for traceability |
| `graph` | `language` | no | a BCP 47 language tag (`"en"`, `"fr-FR"`): the language of the labels |
| `graph` | `label`, `description` | no | texts: the name and description of the whole graph (the title or caption of a figure) |
| `graph` | `prefixes` | no | prefix → IRI, or `null` for a producer without a published namespace (its identifiers then do not export to RDF); every prefix used is declared here |
| `graph` | `vocabulary` | no | attribute → list of declared values `{"id", "on": "node" or "edge", "label", "description"?, "symmetric"?}`. Examples of attributes: `type`, `status`, `role`. **For every attribute declared here, each value used by a node or an edge is declared, with the right `on`.** An identifier is either `prefix:name` (a declared prefix) or a plain name, local to the file. `symmetric` applies to an edge only. A value used on nodes and on edges is declared twice, one entry for each `on`, each with its label. |
| node | `id` | yes | an **opaque** string, or an integer for a graph without labels; **unique, and stable** from one version of the producer to the next. An IRI is allowed (for an external entity, for instance); an `id` is never expanded, even if it contains `:`. Only the identifiers declared in `graph.vocabulary` take the form `prefix:name` |
| node | `label` | no | the text shown, the `id` otherwise |
| node | `type`, `status`, `role`… | no | attributes declared in `graph.vocabulary` (see above); `role` serves, for instance, the role of a variable in a system of equations (input, unknown, intermediate) |
| node | `iri` | no | the absolute IRI of the entity of an external vocabulary that the node stands for (a QUDT quantity kind, a CF standard name, a Wikidata item); the `id` stays the producer's |
| node | `family` | no | a group, which a consumer may fold or draw as one (`protee.viz.collapse`, the page of `protee.viz.render_html`) |
| node, edge | `metrics` | no | an object, name → number, `"inf"`, `"-inf"` or `null` |
| node | `url`, `description` | no | a link to the documentation, the text of a tooltip |
| edge | `source`, `target` | yes | identifiers of existing nodes |
| edge | `key` | no | an integer, unique among the edges with the same source and target |
| edge | `type`, `label`, `metrics` | no | as for nodes |
| anywhere | other keys | allowed | a consumer keeps them and may ignore them (protee writes its attribute columns there) |

**Order.** The order of the nodes and of the edges is significant. A
producer keeps it stable, for reproducible figures.

**Absent or `null`.** An optional key that is absent and one that is
`null` mean the same. This rule does not apply to the entries of
`graph.prefixes` and of `metrics`, where `null` is a value, kept when
written. protee writes no other `null`.

**Versions.** An optional addition stays in `/0`, since unknown keys are
allowed. A removal, a renaming or a change of meaning goes to `/1`.

**Out of the format.** The layout, the visual styles, the drawing API,
computations, and other formats (GraphML…).

## JSON Schema

[`protee-node-link-0.schema.json`](../src/protee/schemas/protee-node-link-0.schema.json)
(JSON Schema 2020-12), shipped in the package and returned by
`protee.io.node_link_schema()`, checks the structure of a document: the
required keys, the types and the allowed values. It does not check the
rules that cross parts of a document: every value used declared in
`graph.vocabulary`, every prefix used declared, unique node identifiers,
edges between existing nodes, unique keys, one edge per pair when
`multigraph` is `false`. A document that `check_node_link` accepts
passes the schema.

## In protee

- `protee.io.check_node_link(data)` returns the departures of a decoded
  document from these rules, an empty tuple when there is none.
- `protee.io.to_node_link` and `protee.io.write_node_link` write a graph
  of protee with its attribute columns; `protee.io.from_node_link` and
  `protee.io.read_node_link` read a document without loss: the `graph`
  block, the `multigraph` flag, the edge keys and the node identifiers,
  texts or integers, are kept.
- `protee.viz` draws a document (selection, groups, loops, SVG, a page to
  explore it offline): see the [gallery](gallery/README.md).
