# Product comparison

## Knowledge graphs of the three products

The numbers follow from the three product files in `sample_data/`
(`ballpoint_pen.json`, `hypothetical_product.json`,
`Centrifugal Pump/centrifugal_pump_product.json`) and the construction rules
of `models/kg_builder.py`. Nodes and relationships are counted per product,
without the shared library; relationships from a product node to a library
node (connection type, skill, agent, tool) are included.

| Product | Components (of which fasteners) | Connections | Assembly states | Transitions | Tasks | KG nodes | KG relationships |
|---|---|---|---|---|---|---|---|
| Ballpoint pen | 6 (0) | 5 | 9 | 13 | 5 | 39 | 120 |
| Hypothetical product | 8 (2) | 6 | 41 | 114 | 6 | 176 | 729 |
| Centrifugal pump | 25 (10) | 40 | 102 | 340 | 20 | 528 | 3,238 |

Node count = 1 product + assembly states + components + connections +
transitions + tasks. The pump has 20 tasks for 40 connections because one
task acts on all connections of a bundle (the six M20 bolts of the three-part
joint: one task, 18 connections). The pump uses two fastener groups (six M20
bolts, four M12 bolts) and one product-specific rule: shaft and impeller stay
together while the cap nut, modelled as a part, is in place.

Shared library (`models/library.py`), common to all products: 15 connection
types, 14 skills, 3 agents and 7 tools (39 nodes) with 15 `SUITABLE_FOR`
relationships.

Checked on the three product files: every task is linked from at least one
transition, and every connection is acted on by a task. The pump graph has
4.4 times the relationships of the hypothetical product (3,238 and 729).

## Effect of fastener grouping on the pump (Table 8 of the paper)

Exact count of the connected subsets of the pump's contact graph
(`python scripts/count_state_space.py`, result in
`scripts/state_space_counts.json`). The count needs the liaison matrix only;
the AND/OR graph is not generated for it.

| Configuration | Units | Connected subsets |
|---|---|---|
| No grouping (25 components) | 25 | 4,043,349 |
| Only the four M12 bolts grouped | 22 | 613,444 |
| Only the six M20 bolts grouped | 20 | 127,362 |
| Both groups | 17 | 20,161 |

Reduction from no grouping to both groups: factor 200.6.

The four counts follow from one decomposition of the contact graph. Take the
graph without the ten bolts (15 vertices: 14 structural components and the
cap nut) and classify its connected subsets by the bolt hosts they contain.
The M12 bolts touch the volute casing cover and the suction nozzle; the M20
bolts touch the volute casing cover, the volute casing and the gasket. With
a = subsets without any host (1,019), b = subsets with M12 hosts only (1),
c = subsets with M20 hosts only (1,913), d = subsets with hosts of both groups
(3,828), k1 = 4 (M12) and k2 = 6 (M20):

    N(no grouping)  = a + b*2^k1 + c*2^k2 + d*2^(k1+k2) + k1 + k2 = 4,043,349
    N(M12 grouped)  = a + 2b + c*2^k2 + 2d*2^k2 + 1 + k2          =   613,444
    N(M20 grouped)  = a + b*2^k1 + 2c + 2d*2^k1 + k1 + 1          =   127,362
    N(both groups)  = a + 2b + 2c + 4d + 2                        =    20,161

The trailing terms are the subsets that consist of a single bolt or a single
group. A set of k identical bolts with common hosts multiplies the subsets
that contain a host by 2^k; as one unit the factor is 2.

Terms: *connected subsets* are the candidates that follow from the contact
graph alone; *assembly states* are the subsets that the generated AND/OR
graph contains (102 for the pump). The ten bolts stay in the model as
fastener components; grouping treats identical bolts with the same hosts as
one unit during generation.
