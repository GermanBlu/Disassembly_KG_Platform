# `docs/`: Detailed Documentation

The top-level [`README.md`](../README.md) is the front door. This folder holds the deeper references.

| File | Read when you need to … |
|---|---|
| [`schema.md`](schema.md) | … understand or change the Neo4j schema: labels, relationships, properties, the shared library. The distinguishing feature is that the AND/OR-graph formalism (Homem de Mello & Sanderson, 1990) is encoded in the graph topology itself (AND via multiple `RESULTS_IN` edges from one `Transition`, OR via multiple `Transition` nodes on one `Assembly`) rather than via explicit AND/OR labels; the full rationale and prior-work contrast live in `schema.md` and `../ARCHITECTURE.md`. **Canonical reference.** |
| [`pipeline.md`](pipeline.md) | … understand the STEP → KG pipeline end-to-end, including the four semantic checks and the optional precedence rules of transition extraction. They add a semantic-validation layer on top of CAD-driven AND/OR-graph generation (Münker & Schmitt, 2022; Prasad et al., 2022): standard CAD-AOG generation emits every *geometrically* feasible transition, whereas these checks discard transitions that are geometrically possible but semantically meaningless (e.g. a screw-removed state where the clamped parts remain joined). See `pipeline.md` for the full prior-work contrast. |
| [`input-format.md`](input-format.md) | … author a JSON product file by hand or integrate another upstream producer. |
| [`rag.md`](rag.md) | … understand or extend the GraphRAG engine's three pipelines (read, enrichment, reassignment) and safety gates. |
| [`reproduce.md`](reproduce.md) | … replicate the reference use cases query-by-query. |
| [`documentation-rules.md`](documentation-rules.md) | … contribute a change and want to know which docs to touch in the same PR. |
| [`demo-deployment.md`](demo-deployment.md), [`server-deployment.md`](server-deployment.md) | … run the read-only demo or deploy it on a server. |

The system overview, the technical implementation and the operating details are in [`../ARCHITECTURE.md`](../ARCHITECTURE.md).

## References

The prior methods these documents build on are cited inline above. The bracketed reference numbers are the numbering of this documentation; they differ from the reference numbers of the paper. The works referenced on this page:

- **[11]** L. S. Homem de Mello, A. C. Sanderson, *And/or graph representation of assembly plans*, IEEE Transactions on Robotics and Automation 6 (2) (1990) 188–199. doi:10.1109/70.54734
- **[14]** S. Münker, R. H. Schmitt, *CAD-based AND/OR graph generation algorithms in (dis)assembly sequence planning of complex products*, Procedia CIRP 106 (2022) 144–149. doi:10.1016/j.procir.2022.02.169
- **[31]** V. S. S. Vara Prasad, M. Hymavathi, C. S. P. Rao, M. V. A. Raju Bahubalendruni, *A novel computative strategic planning projections algorithm (CSPPA) to generate oblique directional interference matrix for different applications in computer-aided design*, Computers in Industry 141 (2022) 103703. doi:10.1016/j.compind.2022.103703
