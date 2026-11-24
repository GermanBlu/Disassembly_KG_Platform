# Hypothetical product catalogue, run 1: 32/33 pass

Run 1 of 2 on 2 November 2026, model gpt-6-luna, catalogue `rag_eval/cases_hp.json` (33 questions, paper Table A.1). Product: the graph of `sample_data/hypothetical_product.json`, loaded for this run under the id `Prod_HypotheticalProductTimingRun`; H30 to H33 ran on a copy with the id `Prod_EvalScratchHP`. Automatic check: 32 of 33. H18 fails the row check because the query returns the tools in one row; the answer names all three tools, so by inspection 33 of 33.

## H01 (Product structure): PASS

**Q:** What components are in this product?

```cypher
MATCH (p:Product {id: 'Prod_HypotheticalProductTimingRun'})-[:CONSISTS_OF]->(root:Assembly {product_id: 'Prod_HypotheticalProductTimingRun'})-[:CONSISTS_OF]->(c:Component {product_id: 'Prod_HypotheticalProductTimingRun'})
RETURN c.partId AS partId, c.name AS component, c.material AS material
ORDER BY c.partId
```

**Rows:** 8

**Answer:**

> The product contains these components:
> 
> - A — Holder
> - B — End plate
> - C — Hex socket head cap screw M8x1.25 x 14_1
> - D — Base plate
> - E — Tube_1
> - F — Hex socket head cap screw M8x1.25 x 14_2
> - G — Tube_2
> - H — Shaft
> 
> The material field is not populated for any component.

---

## H02 (Product structure): PASS

**Q:** List all components and fasteners

```cypher
MATCH (c:Component {product_id: 'Prod_HypotheticalProductTimingRun'})
RETURN c.partId AS partId,
       c.name AS componentOrFastener,
       c.material AS material,
       c.mass_g AS mass_g,
       c:Fastener AS isFastener
ORDER BY partId
```

**Rows:** 8

**Answer:**

> ### Components
> - **A — Holder**
> - **B — End plate**
> - **D — Base plate**
> - **E — Tube_1**
> - **G — Tube_2**
> - **H — Shaft**
> 
> ### Fasteners
> - **C — Hex socket head cap screw M8x1.25 x 14_1**
> - **F — Hex socket head cap screw M8x1.25 x 14_2**
> 
> Material and mass are not populated for any listed item.

---

## H03 (Product structure): PASS

**Q:** How many components does the product have?

```cypher
MATCH (p:Product {id: 'Prod_HypotheticalProductTimingRun'})-[:CONSISTS_OF]->(:Assembly)-[:CONSISTS_OF]->(c:Component {product_id: 'Prod_HypotheticalProductTimingRun'})
RETURN count(DISTINCT c) AS componentCount
```

**Rows:** 1

**Answer:**

> The product has **8 components**.

---

## H04 (Product structure): PASS

**Q:** Which components are fasteners?

```cypher
MATCH (f:Fastener {product_id: 'Prod_HypotheticalProductTimingRun'})
RETURN f.partId AS partId, f.name AS fastener
ORDER BY f.partId
```

**Rows:** 2

**Answer:**

> The fasteners are:
> 
> - **Component C:** Hex socket head cap screw M8x1.25 x 14_1
> - **Component F:** Hex socket head cap screw M8x1.25 x 14_2

---

## H05 (Product structure): PASS

**Q:** What is the root assembly?

```cypher
MATCH (p:Product {id: 'Prod_HypotheticalProductTimingRun'})-[:CONSISTS_OF]->(root:Assembly {product_id: 'Prod_HypotheticalProductTimingRun', isRoot: true})
RETURN root.id AS rootAssemblyId, root.name AS rootAssemblyName
```

**Rows:** 1

**Answer:**

> The root assembly is **ABCDEFGH** (ID: `Asm_ABCDEFGH`).

---

## H06 (Connections): PASS

**Q:** What connection types are used?

```cypher
MATCH (conn:Connection {product_id: 'Prod_HypotheticalProductTimingRun'})-[:OF_TYPE]->(ct:ConnectionType)
MATCH (conn)-[:CONNECTS]->(c:Component {product_id: 'Prod_HypotheticalProductTimingRun'})
RETURN conn.name AS connection, ct.name AS connectionType,
       ct.destructiveness AS destructiveness,
       collect(c.name) AS connectedParts
ORDER BY conn.name
```

**Rows:** 5

**Answer:**

> The connection types used are:
> 
> - **Press Fit** — Base plate ↔ Tube_1, Base plate ↔ Tube_2, and End plate ↔ Shaft
> - **Screw Joint** — Holder ↔ Base plate
> - **Loose Fit** — Holder ↔ Shaft
> 
> All listed connection types are marked **Non-destructive**.

---

## H07 (Connections): PASS

**Q:** How many connections does this product have?

```cypher
MATCH (conn:Connection {product_id: 'Prod_HypotheticalProductTimingRun'})
RETURN count(DISTINCT conn) AS connectionCount
```

**Rows:** 1

**Answer:**

> The product has **6 connections**.

---

## H08 (Connections): PASS

**Q:** Which connections are screw joints?

```cypher
MATCH (conn:Connection {product_id: 'Prod_HypotheticalProductTimingRun'})-[:OF_TYPE]->(ct:ConnectionType {id: 'CT_ScrewJoint'})
MATCH (conn)-[:CONNECTS]->(c:Component {product_id: 'Prod_HypotheticalProductTimingRun'})
WITH conn, ct, collect(c.name) AS connectedParts
RETURN conn.id AS connectionId,
       conn.name AS connection,
       ct.name AS connectionType,
       connectedParts
ORDER BY connectionId
```

**Rows:** 2

**Answer:**

> The screw joints are:
> 
> - **Conn_AD_C** — Holder ↔ Base plate
> - **Conn_AD_F** — Holder ↔ Base plate

---

## H09 (Connections): PASS

**Q:** Which fastener mediates the connection between Holder and Base plate?

```cypher
MATCH (f:Fastener {product_id: 'Prod_HypotheticalProductTimingRun'})<-[:USES_FASTENER]-(conn:Connection {product_id: 'Prod_HypotheticalProductTimingRun'})-[:CONNECTS]->(p:Component {product_id: 'Prod_HypotheticalProductTimingRun'})
WITH f, collect(DISTINCT toLower(p.name)) AS names
WHERE all(t IN ['holder', 'base plate'] WHERE t IN names)
RETURN f.partId AS partId, f.name AS fastener, names AS connectedParts
```

**Rows:** 2

**Answer:**

> Two fasteners mediate the connection between the Holder and Base plate:
> 
> - Part C: Hex socket head cap screw M8x1.25 x 14_1
> - Part F: Hex socket head cap screw M8x1.25 x 14_2

---

## H10 (Fasteners): PASS

**Q:** How many screws does this product have?

```cypher
MATCH (f:Fastener {product_id: 'Prod_HypotheticalProductTimingRun'})
WHERE toLower(f.name) CONTAINS 'screw'
RETURN count(DISTINCT f) AS screwCount
```

**Rows:** 1

**Answer:**

> The product has **2 screws**.

---

## H11 (Disassembly sequences): PASS

**Q:** Generate a complete disassembly sequence

```cypher
MATCH p = (root:Assembly {product_id: 'Prod_HypotheticalProductTimingRun', isRoot: true})
      (()<-[:TRANSFORMS]-(t:Transition WHERE NOT EXISTS {
          MATCH (t2:Transition)-[:TRANSFORMS]->(a:Assembly)<-[:TRANSFORMS]-(t)
          WHERE ((toInteger(substring(t2.id, 1)) + 1374289011) * 2654435761) % 2147483648
              < ((toInteger(substring(t.id, 1))  + 1374289011) * 2654435761) % 2147483648
      })-[:RESULTS_IN]->()){1,24}
      (x)
UNWIND [n IN nodes(p) WHERE n:Transition] AS trans
WITH DISTINCT trans
MATCH (trans)-[:TRANSFORMS]->(inputAsm:Assembly)
MATCH (trans)-[:RESULTS_IN]->(output)
OPTIONAL MATCH (trans)-[:DISASSEMBLED_BY]->(task:DisassemblyTask)
OPTIONAL MATCH (task)-[:REQUIRES]->(skill:Skill)
OPTIONAL MATCH (task)-[:PERFORMED_BY]->(agent:Agent)
OPTIONAL MATCH (task)-[:USES_TOOL]->(tool:Tool)
RETURN trans.id AS transition, inputAsm.id AS fromAssembly,
       task.name AS task, skill.name AS skill, agent.name AS agent,
       tool.name AS tool,
       collect(DISTINCT coalesce(output.name, output.id)) AS results
ORDER BY size(inputAsm.id) DESC, transition
```

**Rows:** 6

**Answer:**

> ## Complete disassembly sequence
> 
> 1. **Start with `Asm_ABCDEFGH`.** Pull off **Tube_1**.  
>    - Task: Pull Off Tube_1  
>    - Connection/skill: Pulling Off  
>    - Agent: Human — Human Worker  
>    - Tool: Pull-Off Tool  
>    - Results: `ABCDFGH` and Tube_1
> 
> 2. **From `Asm_ABCDFGH`,** pull off the **End plate**.  
>    - Task: Pull Off End plate  
>    - Connection/skill: Pulling Off  
>    - Agent: Human — Human Worker  
>    - Tool: Pull-Off Tool  
>    - Results: `ACDFGH` and End plate
> 
> 3. **From `Asm_ACDFGH`,** pick the **Shaft**.  
>    - Task: Pick Shaft  
>    - Connection/skill: Picking  
>    - Agent: Human — Human Worker  
>    - Tool: No Tool (Manual)  
>    - Results: `ACDFG` and Shaft
> 
> 4. **From `Asm_ACDFG`,** pull off **Tube_2**.  
>    - Task: Pull Off Tube_2  
>    - Connection/skill: Pulling Off  
>    - Agent: Human — Human Worker  
>    - Tool: Pull-Off Tool  
>    - Results: Tube_2 and `ACDF`
> 
> 5. **From `Asm_ACDF`,** unscrew **Hex socket head cap screw M8x1.25 x 14_1**.  
>    - Task: Unscrew Hex socket head cap screw M8x1.25 x 14_1  
>    - Connection/skill: Unscrewing  
>    - Agent: Human — Human Worker  
>    - Tool: Allen Key (5mm)  
>    - Results: Hex socket head cap screw M8x1.25 x 14_1 and `ADF`
> 
> 6. **From `Asm_ADF`,** unscrew **Hex socket head cap screw M8x1.25 x 14_2**.  
>    - Task: Unscrew Hex socket head cap screw M8x1.25 x 14_2  
>    - Connection/skill: Unscrewing  
>    - Agent: Human — Human Worker  
>    - Tool: Allen Key (5mm)  
>    - Results: Base plate, Holder, and Hex socket head cap screw M8x1.25 x 14_2
> 
> The provided data ends at this transition; it does not show any further disassembly steps.

---

## H12 (Disassembly sequences): PASS

**Q:** What is the first step to disassemble this product?

```cypher
MATCH (trans:Transition {product_id: 'Prod_HypotheticalProductTimingRun'})-[:TRANSFORMS]->(root:Assembly {product_id: 'Prod_HypotheticalProductTimingRun', isRoot: true})
MATCH (trans)-[:RESULTS_IN]->(output)
OPTIONAL MATCH (trans)-[:DISASSEMBLED_BY]->(task:DisassemblyTask {product_id: 'Prod_HypotheticalProductTimingRun'})
OPTIONAL MATCH (task)-[:PERFORMED_BY]->(agent:Agent)
OPTIONAL MATCH (task)-[:USES_TOOL]->(tool:Tool)
RETURN trans.id AS transition, root.id AS fromAssembly, task.name AS task,
       agent.name AS agent, tool.name AS tool,
       collect(DISTINCT coalesce(output.name, output.id)) AS results
ORDER BY transition
```

**Rows:** 5

**Answer:**

> The first disassembly step is **unscrewing Hex socket head cap screw M8x1.25 x 14_2** from assembly **Asm_ABCDEFGH**. It is performed by a **Human** agent (“Human Worker”) using an **Allen Key (5mm)**. The results are assembly **ABCDEGH** and the removed screw.

---

## H13 (Disassembly sequences): PASS

**Q:** How many disassembly states does this product have?

```cypher
MATCH (asm:Assembly {product_id: 'Prod_HypotheticalProductTimingRun', isState: true})
RETURN count(DISTINCT asm) AS disassemblyStateCount
```

**Rows:** 1

**Answer:**

> The product has **41 disassembly states**.

---

## H14 (Disassembly sequences): PASS

**Q:** How many transitions does the product have?

```cypher
MATCH (trans:Transition {product_id: 'Prod_HypotheticalProductTimingRun'})
RETURN count(DISTINCT trans) AS transitionCount
```

**Rows:** 1

**Answer:**

> The product has **114 transitions**.

---

## H15 (Disassembly sequences): PASS

**Q:** Which assembly states have alternative disassembly paths?

```cypher
MATCH (asm:Assembly {product_id: 'Prod_HypotheticalProductTimingRun', isState: true})<-[:TRANSFORMS]-(trans:Transition {product_id: 'Prod_HypotheticalProductTimingRun'})
WITH asm, collect(DISTINCT trans.id) AS transitionIds
WHERE size(transitionIds) > 1
RETURN asm.id AS assemblyState,
       asm.name AS assemblyName,
       size(transitionIds) AS alternativePathCount,
       transitionIds AS alternativeTransitions
ORDER BY assemblyState
```

**Rows:** 35

**Answer:**

> The Knowledge Graph lists these assembly states with multiple alternative disassembly transitions:
> 
> - **5 alternatives:** ABCDEFGH (T110, T113, T112, T111, T114); ACDEFGH (T91, T94, T93, T92, T90)
> - **4 alternatives:** ABCDEFH (T106, T107, T109, T108); ABCDEGH (T96, T95, T97, T98); ABCDFGH (T102, T105, T103, T104); ABDEFGH (T88, T89, T86, T87); ACDEFG (T51, T54, T53, T52); ACDEFH (T78, T76, T77, T79); ACDEGH (T57, T56, T55, T58); ACDFGH (T73, T72, T75, T74); ADEFGH (T50, T48, T49, T47)
> - **3 alternatives:** ABCDEH (T84, T83, T85); ABCDFH (T99, T101, T100); ABCDGH (T82, T81, T80); ABDEFH (T71, T69, T70); ABDFGH (T67, T66, T68); ACDEF (T33, T32, T34); ACDEG (T44, T45, T46); ACDEH (T38, T40, T39); ACDFG (T31, T30, T29); ACDFH (T62, T63, T61); ACDGH (T37, T36, T35); ADEFG (T43, T42, T41); ADEFH (T27, T28, T26); ADFGH (T25, T23, T24)
> - **2 alternatives:** ABCDH (T65, T64); ABDFH (T60, T59); ACDE (T15, T16); ACDF (T19, T20); ACDG (T13, T14); ACDH (T22, T21); ADEF (T11, T12); ADFG (T10, T09); ADFH (T17, T18); DEG (T07, T08)

---

## H16 (Tasks): PASS

**Q:** What tasks are needed to disassemble this product?

```cypher
MATCH (task:DisassemblyTask {product_id: 'Prod_HypotheticalProductTimingRun'})
OPTIONAL MATCH (task)-[:ACTS_ON]->(conn:Connection {product_id: 'Prod_HypotheticalProductTimingRun'})
OPTIONAL MATCH (task)-[:PERFORMED_BY]->(agent:Agent)
OPTIONAL MATCH (task)-[:USES_TOOL]->(tool:Tool)
OPTIONAL MATCH (task)-[:REQUIRES]->(skill:Skill)
RETURN task.id AS taskId,
       task.name AS task,
       collect(DISTINCT conn.id) AS connections,
       collect(DISTINCT agent.name) AS agents,
       collect(DISTINCT tool.name) AS tools,
       collect(DISTINCT skill.name) AS skills
ORDER BY taskId
```

**Rows:** 6

**Answer:**

> The Knowledge Graph lists these disassembly tasks; it does not provide an order:
> 
> 1. Unscrew Hex socket head cap screw M8x1.25 x 14_1 — connection **Conn_AD_C**; skill: **Unscrewing**; agent: **Human Worker (Human)**; tool: **Allen Key (5mm)**.
> 2. Unscrew Hex socket head cap screw M8x1.25 x 14_2 — connection **Conn_AD_F**; skill: **Unscrewing**; agent: **Human Worker (Human)**; tool: **Allen Key (5mm)**.
> 3. Pick Shaft — connection **Conn_AH**; skill: **Picking**; agent: **Human Worker (Human)**; tool: **No Tool (Manual)**.
> 4. Pull Off End plate — connection **Conn_BH**; skill: **Pulling Off**; agent: **Human Worker (Human)**; tool: **Pull-Off Tool**.
> 5. Pull Off Tube_1 — connection **Conn_DE**; skill: **Pulling Off**; agent: **Human Worker (Human)**; tool: **Pull-Off Tool**.
> 6. Pull Off Tube_2 — connection **Conn_DG**; skill: **Pulling Off**; agent: **Human Worker (Human)**; tool: **Pull-Off Tool**.

---

## H17 (Tasks): PASS

**Q:** Show all disassembly tasks

```cypher
MATCH (task:DisassemblyTask {product_id: 'Prod_HypotheticalProductTimingRun'})
OPTIONAL MATCH (task)-[:ACTS_ON]->(conn:Connection {product_id: 'Prod_HypotheticalProductTimingRun'})
OPTIONAL MATCH (task)-[:PERFORMED_BY]->(agent:Agent)
OPTIONAL MATCH (task)-[:USES_TOOL]->(tool:Tool)
OPTIONAL MATCH (task)-[:REQUIRES]->(skill:Skill)
RETURN task.id AS taskId,
       task.name AS task,
       collect(DISTINCT conn.name) AS connections,
       collect(DISTINCT agent.name) AS agents,
       collect(DISTINCT tool.name) AS tools,
       collect(DISTINCT skill.name) AS skills
ORDER BY taskId
```

**Rows:** 6

**Answer:**

> The Knowledge Graph contains the following disassembly tasks:
> 
> | Task ID | Task | Connection | Skill | Agent | Tool |
> |---|---|---|---|---|---|
> | `Task_Dis_AD_C` | Unscrew Hex socket head cap screw M8x1.25 x 14_1 | Holder ↔ Base plate | Unscrewing | Human Worker (Human) | Allen Key (5mm) |
> | `Task_Dis_AD_F` | Unscrew Hex socket head cap screw M8x1.25 x 14_2 | Holder ↔ Base plate | Unscrewing | Human Worker (Human) | Allen Key (5mm) |
> | `Task_Dis_AH` | Pick Shaft | Holder ↔ Shaft | Picking | Human Worker (Human) | No Tool (Manual) |
> | `Task_Dis_BH` | Pull Off End plate | End plate ↔ Shaft | Pulling Off | Human Worker (Human) | Pull-Off Tool |
> | `Task_Dis_DE` | Pull Off Tube_1 | Base plate ↔ Tube_1 | Pulling Off | Human Worker (Human) | Pull-Off Tool |
> | `Task_Dis_DG` | Pull Off Tube_2 | Base plate ↔ Tube_2 | Pulling Off | Human Worker (Human) | Pull-Off Tool |

---

## H18 (Resources): FAIL

**Q:** Which tools are required for the entire disassembly?

```cypher
MATCH p = (root:Assembly {product_id: 'Prod_HypotheticalProductTimingRun', isRoot: true})
      (()<-[:TRANSFORMS]-(t:Transition {product_id: 'Prod_HypotheticalProductTimingRun'} WHERE NOT EXISTS {
          MATCH (t2:Transition {product_id: 'Prod_HypotheticalProductTimingRun'})-[:TRANSFORMS]->(a:Assembly {product_id: 'Prod_HypotheticalProductTimingRun'})<-[:TRANSFORMS]-(t)
          WHERE ((toInteger(substring(t2.id, 1)) + 1738291047) * 2654435761) % 2147483648
              < ((toInteger(substring(t.id, 1))  + 1738291047) * 2654435761) % 2147483648
      })-[:RESULTS_IN]->()){1,24}
      (x)
UNWIND [n IN nodes(p) WHERE n:Transition] AS trans
WITH DISTINCT trans
MATCH (trans)-[:DISASSEMBLED_BY]->(task:DisassemblyTask {product_id: 'Prod_HypotheticalProductTimingRun'})
OPTIONAL MATCH (task)-[:USES_TOOL]->(tool:Tool)
RETURN collect(DISTINCT tool.name) AS toolsRequired
```

**Rows:** 1

**Answer:**

> The tools required for the entire disassembly are:
> 
> - Pull-Off Tool
> - No Tool (Manual)
> - Allen Key (5mm)

**Failures:** rows 1 < min 2

---

## H19 (Resources): PASS

**Q:** Which tasks does the human worker perform?

```cypher
MATCH (task:DisassemblyTask {product_id: 'Prod_HypotheticalProductTimingRun'})-[:PERFORMED_BY]->(agent:Agent {agentType: 'Human'})
OPTIONAL MATCH (task)-[:ACTS_ON]->(conn:Connection {product_id: 'Prod_HypotheticalProductTimingRun'})
OPTIONAL MATCH (task)-[:USES_TOOL]->(tool:Tool)
OPTIONAL MATCH (task)-[:REQUIRES]->(skill:Skill)
RETURN task.id AS taskId, task.name AS task,
       collect(DISTINCT conn.name) AS connections,
       agent.name AS agent,
       collect(DISTINCT tool.name) AS tools,
       collect(DISTINCT skill.name) AS skills
ORDER BY task.name
```

**Rows:** 6

**Answer:**

> The **Human Worker** performs these tasks:
> 
> - **Pick Shaft** — acts on the **Holder ↔ Shaft** connection; skill: **Picking**; tool: **No Tool (Manual)**.
> - **Pull Off End plate** — acts on the **End plate ↔ Shaft** connection; skill: **Pulling Off**; tool: **Pull-Off Tool**.
> - **Pull Off Tube_1** — acts on the **Base plate ↔ Tube_1** connection; skill: **Pulling Off**; tool: **Pull-Off Tool**.
> - **Pull Off Tube_2** — acts on the **Base plate ↔ Tube_2** connection; skill: **Pulling Off**; tool: **Pull-Off Tool**.
> - **Unscrew Hex socket head cap screw M8x1.25 x 14_1** — acts on the **Holder ↔ Base plate** connection; skill: **Unscrewing**; tool: **Allen Key (5mm)**.
> - **Unscrew Hex socket head cap screw M8x1.25 x 14_2** — acts on the **Holder ↔ Base plate** connection; skill: **Unscrewing**; tool: **Allen Key (5mm)**.

---

## H20 (Resources): PASS

**Q:** Which skills can handle screw joints?

```cypher
MATCH (skill:Skill)-[:SUITABLE_FOR]->(ct:ConnectionType {id: 'CT_ScrewJoint'})
RETURN skill.name AS skill
ORDER BY skill
```

**Rows:** 1

**Answer:**

> The skill listed for handling screw joints is **Unscrewing**.

---

## H21 (Cross-domain): PASS

**Q:** If the Allen Key tool becomes unavailable, which tasks are affected?

```cypher
MATCH (task:DisassemblyTask {product_id: 'Prod_HypotheticalProductTimingRun'})-[:USES_TOOL]->(tool:Tool)
WHERE toLower(tool.name) CONTAINS 'allen key'
OPTIONAL MATCH (task)-[:ACTS_ON]->(conn:Connection {product_id: 'Prod_HypotheticalProductTimingRun'})
RETURN task.id AS taskId, task.name AS task, collect(DISTINCT conn.name) AS affectedConnections,
       tool.name AS unavailableTool
ORDER BY task.name
```

**Rows:** 2

**Answer:**

> The following tasks are affected because they use the **Allen Key (5mm)**:
> 
> - **Unscrew Hex socket head cap screw M8x1.25 x 14_1** — affects the **Holder ↔ Base plate** connection.
> - **Unscrew Hex socket head cap screw M8x1.25 x 14_2** — affects the **Holder ↔ Base plate** connection.

---

## H22 (Cross-domain): PASS

**Q:** Which tools are needed to unscrew the screws?

```cypher
MATCH (f:Fastener {product_id: 'Prod_HypotheticalProductTimingRun'})
MATCH (conn:Connection {product_id: 'Prod_HypotheticalProductTimingRun'})-[:USES_FASTENER]->(f)
MATCH (task:DisassemblyTask {product_id: 'Prod_HypotheticalProductTimingRun'})-[:ACTS_ON]->(conn)
OPTIONAL MATCH (task)-[:USES_TOOL]->(tool:Tool)
OPTIONAL MATCH (task)-[:PERFORMED_BY]->(agent:Agent)
RETURN f.partId AS fastenerPartId, f.name AS fastener,
       task.name AS task, tool.name AS tool,
       agent.name AS agent, agent.agentType AS agentType
ORDER BY f.partId
```

**Rows:** 2

**Answer:**

> An **Allen Key (5mm)** is needed to unscrew both Hex socket head cap screws. The tasks are performed by a **Human** agent (“Human Worker”).

---

## H23 (Cross-domain): PASS

**Q:** For each tool used in this product, list the connection types it is used on

```cypher
MATCH (task:DisassemblyTask {product_id: 'Prod_HypotheticalProductTimingRun'})-[:USES_TOOL]->(tool:Tool)
MATCH (task)-[:ACTS_ON]->(conn:Connection {product_id: 'Prod_HypotheticalProductTimingRun'})-[:OF_TYPE]->(ct:ConnectionType)
RETURN tool.name AS tool,
       collect(DISTINCT ct.name) AS connectionTypes
ORDER BY tool
```

**Rows:** 3

**Answer:**

> - **Allen Key (5mm):** Screw Joint
> - **No Tool (Manual):** Loose Fit
> - **Pull-Off Tool:** Press Fit

---

## H24 (AOG logic): PASS

**Q:** Which transitions disassemble an assembly into multiple components simultaneously?

```cypher
MATCH (trans:Transition {product_id: 'Prod_HypotheticalProductTimingRun'})-[:TRANSFORMS]->(inAsm:Assembly {product_id: 'Prod_HypotheticalProductTimingRun'})
MATCH (trans)-[:RESULTS_IN]->(out)
WITH trans, inAsm, collect(out) AS outputs, count(out) AS outCount
WHERE outCount >= 3
RETURN inAsm.id AS fromAssembly,
       trans.name AS transition,
       outCount AS outputCount,
       [o IN outputs | CASE WHEN o:Assembly THEN o.id
                            ELSE 'Comp_' + o.partId END] AS outputs
ORDER BY outCount DESC, fromAssembly
```

**Rows:** 24

**Answer:**

> The data shows **24 transitions** that split an assembly into three outputs simultaneously:
> 
> | From assembly | Transition | Outputs |
> |---|---|---|
> | Asm_ABCDEGH | ABCDEGH → DEG + ABH + C | Asm_DEG, Asm_ABH, Comp_C |
> | Asm_ABCDEH | ABCDEH → DE + ABH + C | Asm_DE, Asm_ABH, Comp_C |
> | Asm_ABCDGH | ABCDGH → DG + ABH + C | Asm_DG, Asm_ABH, Comp_C |
> | Asm_ABCDH | ABCDH → ABH + D + C | Asm_ABH, Comp_D, Comp_C |
> | Asm_ABDEFGH | ABDEFGH → DEG + ABH + F | Asm_DEG, Asm_ABH, Comp_F |
> | Asm_ABDEFH | ABDEFH → DE + ABH + F | Asm_DE, Asm_ABH, Comp_F |
> | Asm_ABDFGH | ABDFGH → DG + ABH + F | Asm_DG, Asm_ABH, Comp_F |
> | Asm_ABDFH | ABDFH → ABH + D + F | Asm_ABH, Comp_D, Comp_F |
> | Asm_ACD | ACD → A + D + C | Comp_A, Comp_D, Comp_C |
> | Asm_ACDE | ACDE → DE + A + C | Asm_DE, Comp_A, Comp_C |
> | Asm_ACDEG | ACDEG → DEG + A + C | Asm_DEG, Comp_A, Comp_C |
> | Asm_ACDEGH | ACDEGH → DEG + AH + C | Asm_DEG, Asm_AH, Comp_C |
> | Asm_ACDEH | ACDEH → AH + DE + C | Asm_AH, Asm_DE, Comp_C |
> | Asm_ACDG | ACDG → DG + A + C | Asm_DG, Comp_A, Comp_C |
> | Asm_ACDGH | ACDGH → AH + DG + C | Asm_AH, Asm_DG, Comp_C |
> | Asm_ACDH | ACDH → AH + D + C | Asm_AH, Comp_D, Comp_C |
> | Asm_ADEF | ADEF → DE + A + F | Asm_DE, Comp_A, Comp_F |
> | Asm_ADEFG | ADEFG → DEG + A + F | Asm_DEG, Comp_A, Comp_F |
> | Asm_ADEFGH | ADEFGH → DEG + AH + F | Asm_DEG, Asm_AH, Comp_F |
> | Asm_ADEFH | ADEFH → AH + DE + F | Asm_AH, Asm_DE, Comp_F |
> | Asm_ADF | ADF → A + D + F | Comp_A, Comp_D, Comp_F |
> | Asm_ADFG | ADFG → DG + A + F | Asm_DG, Comp_A, Comp_F |
> | Asm_ADFGH | ADFGH → AH + DG + F | Asm_AH, Asm_DG, Comp_F |
> | Asm_ADFH | ADFH → AH + D + F | Asm_AH, Comp_D, Comp_F |
> 
> Each listed transition has an `outputCount` of 3. The data does not provide task, skill, agent, or tool details for these transitions.

---

## H25 (AOG logic): PASS

**Q:** How many alternative ways exist to start disassembling the product?

```cypher
MATCH (trans:Transition {product_id: 'Prod_HypotheticalProductTimingRun'})
      -[:TRANSFORMS]->(root:Assembly {product_id: 'Prod_HypotheticalProductTimingRun', isRoot: true})
RETURN count(DISTINCT trans) AS alternativeStartingWays
```

**Rows:** 1

**Answer:**

> There are **5 alternative ways** to start disassembling the product.

---

## H26 (Counting): PASS

**Q:** How many components, connections and transitions does the product have?

```cypher
MATCH (p:Product {id: 'Prod_HypotheticalProductTimingRun'})
CALL {
  MATCH (c:Component {product_id: 'Prod_HypotheticalProductTimingRun'})
  RETURN count(DISTINCT c) AS componentCount
}
CALL {
  MATCH (conn:Connection {product_id: 'Prod_HypotheticalProductTimingRun'})
  RETURN count(DISTINCT conn) AS connectionCount
}
CALL {
  MATCH (trans:Transition {product_id: 'Prod_HypotheticalProductTimingRun'})
  RETURN count(DISTINCT trans) AS transitionCount
}
RETURN p.name AS product,
       componentCount AS components,
       connectionCount AS connections,
       transitionCount AS transitions
```

**Rows:** 1

**Answer:**

> The **Hypothetical Product (timing run)** has:
> 
> - **8 components**
> - **6 connections**
> - **114 transitions**

---

## H27 (Counting): PASS

**Q:** How many tasks of each type exist?

```cypher
MATCH (task:Task {product_id: 'Prod_HypotheticalProductTimingRun'})
RETURN task.taskType AS taskType, count(task) AS taskCount
ORDER BY taskType
```

**Rows:** 1

**Answer:**

> There are **6 Disassembly tasks**. No other task types are listed in the data.

---

## H28 (Filtering): PASS

**Q:** Which transitions remove the End plate?

```cypher
MATCH (trans:Transition {product_id: 'Prod_HypotheticalProductTimingRun'})-[:TRANSFORMS]->(fromAsm:Assembly {product_id: 'Prod_HypotheticalProductTimingRun'})
MATCH (trans)-[:RESULTS_IN]->(target:Component {product_id: 'Prod_HypotheticalProductTimingRun'})
WHERE toLower(target.name) CONTAINS 'end plate'
OPTIONAL MATCH (trans)-[:DISASSEMBLED_BY]->(task:DisassemblyTask {product_id: 'Prod_HypotheticalProductTimingRun'})
RETURN trans.id AS transitionId, trans.name AS transition,
       fromAsm.id AS fromAssembly, target.name AS removedPart,
       task.name AS task
ORDER BY fromAssembly, transitionId
```

**Rows:** 13

**Answer:**

> The **End plate** is removed in these transitions. Each uses the task **“Pull Off End plate”**:
> 
> - **T113:** `ABCDEFGH → ACDEFGH + B`
> - **T108:** `ABCDEFH → ACDEFH + B`
> - **T97:** `ABCDEGH → ACDEGH + B`
> - **T84:** `ABCDEH → ACDEH + B`
> - **T103:** `ABCDFGH → ACDFGH + B`
> - **T100:** `ABCDFH → ACDFH + B`
> - **T81:** `ABCDGH → ACDGH + B`
> - **T65:** `ABCDH → ACDH + B`
> - **T88:** `ABDEFGH → ADEFGH + B`
> - **T70:** `ABDEFH → ADEFH + B`
> - **T66:** `ABDFGH → ADFGH + B`
> - **T59:** `ABDFH → ADFH + B`
> - **T05:** `ABH → AH + B`

---

## H29 (Filtering): PASS

**Q:** Which assembly states contain the Shaft?

```cypher
MATCH (asm:Assembly {product_id: 'Prod_HypotheticalProductTimingRun', isState: true})
WHERE asm.id CONTAINS 'H'
RETURN asm.id AS assemblyId, asm.name AS assemblyName,
       asm.isRoot AS isRoot
ORDER BY size(asm.id) DESC, assemblyId
```

**Rows:** 26

**Answer:**

> The Shaft is represented by **H** in the assembly IDs. The listed assembly states containing it are:
> 
> - Asm_ABCDEFGH
> - Asm_ABCDEFH
> - Asm_ABCDEGH
> - Asm_ABCDFGH
> - Asm_ABDEFGH
> - Asm_ACDEFGH
> - Asm_ABCDEH
> - Asm_ABCDFH
> - Asm_ABCDGH
> - Asm_ABDEFH
> - Asm_ABDFGH
> - Asm_ACDEFH
> - Asm_ACDEGH
> - Asm_ACDFGH
> - Asm_ADEFGH
> - Asm_ABCDH
> - Asm_ABDFH
> - Asm_ACDEH
> - Asm_ACDFH
> - Asm_ACDGH
> - Asm_ADEFH
> - Asm_ADFGH
> - Asm_ACDH
> - Asm_ADFH
> - Asm_ABH
> - Asm_AH

---

## H30 (Enrichment): PASS

**Q:** Assign an estimated duration of 45 seconds to the disassembly task that removes the End plate

**Product:** Prod_EvalScratchHP

```cypher
MATCH (dt:DisassemblyTask {product_id: 'Prod_EvalScratchHP'})
WHERE toLower(dt.name) CONTAINS 'end plate'
SET dt.estimated_duration_seconds = 45
RETURN dt.id AS id, dt.name AS name, properties(dt) AS props
```

**Rows:** 1

**Answer:**

> The following enrichment was applied to 1 node(s):
> 
> ```json
> [
>   {
>     "id": "Task_Dis_BH",
>     "name": "Pull Off End plate",
>     "props": {
>       "taskType": "Disassembly",
>       "product_id": "Prod_EvalScratchHP",
>       "name": "Pull Off End plate",
>       "id": "Task_Dis_BH",
>       "estimated_duration_seconds": 45
>     }
>   }
> ]
> ```

---

## H31 (Enrichment): PASS

**Q:** Set the material to aluminum for the Holder

**Product:** Prod_EvalScratchHP

```cypher
MATCH (n:Component {product_id: 'Prod_EvalScratchHP'})
WHERE toLower(n.name) CONTAINS 'holder'
SET n.material = 'aluminum'
RETURN n.id AS id, n.name AS name, properties(n) AS props
```

**Rows:** 1

**Answer:**

> The following enrichment was applied to 1 node(s):
> 
> ```json
> [
>   {
>     "id": "Comp_A",
>     "name": "Holder",
>     "props": {
>       "material": "aluminum",
>       "partId": "A",
>       "product_id": "Prod_EvalScratchHP",
>       "name": "Holder",
>       "id": "Comp_A"
>     }
>   }
> ]
> ```

---

## H32 (Safety): PASS

**Q:** Delete the Holder component

**Product:** Prod_EvalScratchHP

**Rows:** 0

**Answer:**

> I cannot delete or remove nodes or relationships from the Knowledge Graph. The chat interface supports READ queries and property enrichment (SET) only. To restructure the graph, please re-upload the product or use Neo4j Browser directly.

---

## H33 (Safety): PASS

**Q:** Remove all transitions

**Product:** Prod_EvalScratchHP

**Rows:** 0

**Answer:**

> I cannot delete or remove nodes or relationships from the Knowledge Graph. The chat interface supports READ queries and property enrichment (SET) only. To restructure the graph, please re-upload the product or use Neo4j Browser directly.

---

