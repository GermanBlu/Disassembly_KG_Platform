# Centrifugal pump catalogue, run 1: 26/27 pass

Run 1 of 2 on 2 November 2026, model gpt-6-luna, catalogue `rag_eval/cases_pump.json` (27 questions, paper Table A.2; P01 to P15 are questions 1 to 15, P15b is question 16, P16 to P26 are questions 17 to 27). Product: the graph of `sample_data/Centrifugal Pump/centrifugal_pump_product.json`, loaded for this run under the id `Prod_CentrifugalPump_V15` with the name Centrifugal Pump V15. Automatic check: 26 of 27 (P10 fails).

## P01 (Product structure): PASS

**Q:** What components are in this product?

```cypher
MATCH (p:Product {id: 'Prod_CentrifugalPump_V15'})-[:CONSISTS_OF]->(root:Assembly {product_id: 'Prod_CentrifugalPump_V15'})-[:CONSISTS_OF]->(c:Component {product_id: 'Prod_CentrifugalPump_V15'})
RETURN p.name AS product, c.partId AS partId, c.name AS component
ORDER BY c.partId
```

**Rows:** 25

**Answer:**

> The **Centrifugal Pump V15** contains these components:
> 
> - **A** — Volute Casing Cover
> - **B** — Stuffing Box Gland Half_1
> - **C** — Bearing Housing
> - **D** — Bearing End Cap 1
> - **E** — M20x2.5 Hex Bolt_1
> - **F** — Shaft
> - **G** — Bearing End Cap 2
> - **H** — Coupling
> - **I** — Impeller
> - **J** — M20x2.5 Hex Bolt_2
> - **K** — Bearing 59x70
> - **L** — M12 Flange Bolt_1
> - **M** — Stuffing Box Gland Half_2
> - **N** — M20 Cap Nut
> - **O** — M12 Flange Bolt_2
> - **P** — Suction Nozzle
> - **Q** — M20x2.5 Hex Bolt_3
> - **R** — M12 Flange Bolt_3
> - **S** — M20x2.5 Hex Bolt_4
> - **T** — Volute Casing
> - **U** — Volute Casing Gasket
> - **V** — M12 Flange Bolt_4
> - **W** — Bearing 40x50
> - **X** — M20x2.5 Hex Bolt_5
> - **Y** — M20x2.5 Hex Bolt_6**

---

## P02 (Product structure): PASS

**Q:** How many components does the product have?

```cypher
MATCH (p:Product {id: 'Prod_CentrifugalPump_V15'})-[:CONSISTS_OF]->(root:Assembly {product_id: 'Prod_CentrifugalPump_V15'})
MATCH (root)-[:CONSISTS_OF]->(c:Component {product_id: 'Prod_CentrifugalPump_V15'})
RETURN count(DISTINCT c) AS componentCount
```

**Rows:** 1

**Answer:**

> The product has **25 components**.

---

## P03 (Product structure): PASS

**Q:** Which parts are fasteners?

```cypher
MATCH (f:Fastener {product_id: 'Prod_CentrifugalPump_V15'})
RETURN f.partId AS partId, f.name AS fastener
ORDER BY partId
```

**Rows:** 10

**Answer:**

> The fasteners are:
> 
> - **E** — M20x2.5 Hex Bolt_1
> - **J** — M20x2.5 Hex Bolt_2
> - **L** — M12 Flange Bolt_1
> - **O** — M12 Flange Bolt_2
> - **Q** — M20x2.5 Hex Bolt_3
> - **R** — M12 Flange Bolt_3
> - **S** — M20x2.5 Hex Bolt_4
> - **V** — M12 Flange Bolt_4
> - **X** — M20x2.5 Hex Bolt_5
> - **Y** — M20x2.5 Hex Bolt_6

---

## P04 (Product structure): PASS

**Q:** What is the root assembly of this product?

```cypher
MATCH (p:Product {id: 'Prod_CentrifugalPump_V15'})-[:CONSISTS_OF]->(root:Assembly {product_id: 'Prod_CentrifugalPump_V15', isRoot: true})
RETURN p.name AS product, root.id AS rootAssemblyId, root.name AS rootAssembly
```

**Rows:** 1

**Answer:**

> The root assembly of the **Centrifugal Pump V15** is **ABCDEFGHIJKLMNOPQRSTUVWXY** (ID: `Asm_ABCDEFGHIJKLMNOPQRSTUVWXY`).

---

## P05 (Product structure): PASS

**Q:** What is the part id of the Impeller?

```cypher
MATCH (c:Component {product_id: 'Prod_CentrifugalPump_V15'})
WHERE toLower(c.name) CONTAINS 'impeller'
RETURN c.partId AS partId, c.name AS component
```

**Rows:** 1

**Answer:**

> The Impeller’s part ID is **I**.

---

## P06 (Connections): PASS

**Q:** What connection types are used in this product?

```cypher
MATCH (conn:Connection {product_id: 'Prod_CentrifugalPump_V15'})-[:OF_TYPE]->(ct:ConnectionType)
RETURN DISTINCT ct.id AS connectionTypeId, ct.name AS connectionType
ORDER BY connectionType
```

**Rows:** 3

**Answer:**

> The product uses these connection types:
> 
> - Loose Fit
> - Press Fit
> - Screw Joint

---

## P07 (Connections): PASS

**Q:** How many connections does this product have?

```cypher
MATCH (conn:Connection {product_id: 'Prod_CentrifugalPump_V15'})
RETURN count(DISTINCT conn) AS connectionCount
```

**Rows:** 1

**Answer:**

> The product has 40 connections.

---

## P08 (Connections): PASS

**Q:** Which connections are press-fit?

```cypher
MATCH (conn:Connection {product_id: 'Prod_CentrifugalPump_V15'})-[:OF_TYPE]->(ct:ConnectionType {id: 'CT_PressFit'})
MATCH (conn)-[:CONNECTS]->(component:Component {product_id: 'Prod_CentrifugalPump_V15'})
WITH conn, ct, collect(component.name) AS connectedParts
RETURN conn.id AS connectionId, conn.name AS connection,
       ct.name AS connectionType, connectedParts
ORDER BY connectionId
```

**Rows:** 7

**Answer:**

> The following connections are **Press Fit**:
> 
> - Bearing Housing ↔ Bearing End Cap 1 (Conn_CD)
> - Bearing Housing ↔ Bearing End Cap 2 (Conn_CG)
> - Bearing Housing ↔ Bearing 59x70 (Conn_CK)
> - Bearing Housing ↔ Bearing 40x50 (Conn_CW)
> - Shaft ↔ Coupling (Conn_FH)
> - Shaft ↔ Bearing 59x70 (Conn_FK)
> - Shaft ↔ Bearing 40x50 (Conn_FW)

---

## P09 (Connections): PASS

**Q:** Which fastener mediates the connection between the Volute Casing, the Volute Casing Gasket and the Volute Casing Cover?

```cypher
MATCH (f:Fastener {product_id: 'Prod_CentrifugalPump_V15'})<-[:USES_FASTENER]-(:Connection {product_id: 'Prod_CentrifugalPump_V15'})-[:CONNECTS]->(p:Component {product_id: 'Prod_CentrifugalPump_V15'})
WITH f, collect(DISTINCT toLower(p.name)) AS names
WHERE all(t IN ['volute casing', 'volute casing gasket', 'volute casing cover'] WHERE t IN names)
RETURN f.partId AS partId, f.name AS fastener, names
```

**Rows:** 6

**Answer:**

> The connection is mediated by six fasteners: **M20x2.5 Hex Bolt_1 (part E), M20x2.5 Hex Bolt_2 (part J), M20x2.5 Hex Bolt_3 (part Q), M20x2.5 Hex Bolt_4 (part S), M20x2.5 Hex Bolt_5 (part X), and M20x2.5 Hex Bolt_6 (part Y).**

---

## P10 (Connections): FAIL

**Q:** Which parts does the M20 Cap Nut connect?

```cypher
MATCH (f:Fastener {product_id: 'Prod_CentrifugalPump_V15'})
WHERE toLower(f.name) CONTAINS 'm20 cap nut'
MATCH (conn:Connection {product_id: 'Prod_CentrifugalPump_V15'})-[:USES_FASTENER]->(f)
MATCH (conn)-[:CONNECTS]->(part:Component {product_id: 'Prod_CentrifugalPump_V15'})
WITH f, conn, collect(DISTINCT part.name) AS connectedParts
RETURN f.name AS fastener, conn.id AS connectionId, connectedParts
ORDER BY connectionId
```

**Rows:** 0

**Answer:**

> I could not find relevant information in the Knowledge Graph to answer your question. Please try rephrasing or ask about components, connections, assembly/disassembly sequences, tasks, tools, or agents defined in this product.

**Failures:** answer missing all of ['Impeller']; answer missing all of ['Shaft']

---

## P11 (Fasteners and tools): PASS

**Q:** Which fastener holds the Suction Nozzle and the Volute Casing Cover together?

```cypher
MATCH (f:Fastener {product_id: 'Prod_CentrifugalPump_V15'})<-[:USES_FASTENER]-(:Connection {product_id: 'Prod_CentrifugalPump_V15'})-[:CONNECTS]->(p:Component {product_id: 'Prod_CentrifugalPump_V15'})
WITH f, collect(DISTINCT toLower(p.name)) AS names
WHERE all(t IN ['suction nozzle', 'volute casing cover'] WHERE t IN names)
RETURN f.partId AS partId, f.name AS fastener, names
```

**Rows:** 4

**Answer:**

> The Suction Nozzle and Volute Casing Cover are held together by four fasteners:
> 
> - M12 Flange Bolt_1 (part L)
> - M12 Flange Bolt_2 (part O)
> - M12 Flange Bolt_3 (part R)
> - M12 Flange Bolt_4 (part V)

---

## P12 (Fasteners and tools): PASS

**Q:** Which tools are used for the unscrewing tasks?

```cypher
MATCH (f:Fastener {product_id: 'Prod_CentrifugalPump_V15'})<-[:USES_FASTENER]-(conn:Connection {product_id: 'Prod_CentrifugalPump_V15'})<-[:ACTS_ON]-(task:DisassemblyTask {product_id: 'Prod_CentrifugalPump_V15'})
MATCH (task)-[:USES_TOOL]->(tool:Tool)
WHERE toLower(task.name) CONTAINS 'unscrew'
RETURN DISTINCT task.name AS task, f.name AS fastener, tool.name AS tool
ORDER BY task, fastener, tool
```

**Rows:** 10

**Answer:**

> The unscrewing tasks use these tools:
> 
> - **Unscrew 4x M12 Flange Bolt:** Combination Wrench (18mm)
> - **Unscrew 6x M20x2.5 Hex Bolt:** Combination Wrench (30mm)

---

## P13 (Disassembly sequences): PASS

**Q:** What is the first step to disassemble this product?

```cypher
MATCH (trans:Transition {product_id: 'Prod_CentrifugalPump_V15'})-[:TRANSFORMS]->(root:Assembly {product_id: 'Prod_CentrifugalPump_V15', isRoot: true})
MATCH (trans)-[:RESULTS_IN]->(output)
OPTIONAL MATCH (trans)-[:DISASSEMBLED_BY]->(task:DisassemblyTask {product_id: 'Prod_CentrifugalPump_V15'})
OPTIONAL MATCH (task)-[:PERFORMED_BY]->(agent:Agent)
OPTIONAL MATCH (task)-[:USES_TOOL]->(tool:Tool)
RETURN trans.id AS transition, root.id AS fromAssembly, task.name AS task,
       agent.name AS agent, tool.name AS tool,
       collect(DISTINCT coalesce(output.name, output.id)) AS results
ORDER BY transition
```

**Rows:** 5

**Answer:**

> The first step is to **unscrew the four M12 flange bolts** using a **Combination Wrench (18mm)**. The task is performed by a **Human** agent.

---

## P14 (Disassembly sequences): PASS

**Q:** How many alternative first disassembly steps are there from the full assembly?

```cypher
MATCH (trans:Transition {product_id: 'Prod_CentrifugalPump_V15'})-[:TRANSFORMS]->(root:Assembly {product_id: 'Prod_CentrifugalPump_V15', isRoot: true})
RETURN count(DISTINCT trans) AS alternativeFirstDisassemblySteps
```

**Rows:** 1

**Answer:**

> There are 4 alternative first disassembly steps from the full assembly.

---

## P15 (Disassembly sequences): PASS

**Q:** How do I remove the Impeller?

```cypher
MATCH p = (root:Assembly {product_id: 'Prod_CentrifugalPump_V15', isRoot: true})
      (()<-[:TRANSFORMS]-(:Transition {product_id: 'Prod_CentrifugalPump_V15'})-[:RESULTS_IN]->()){0,24}
      (a:Assembly {product_id: 'Prod_CentrifugalPump_V15'})<-[:TRANSFORMS]-(t:Transition {product_id: 'Prod_CentrifugalPump_V15'})-[:RESULTS_IN]->(target:Component {product_id: 'Prod_CentrifugalPump_V15'})
WHERE toLower(target.name) CONTAINS 'impeller'
WITH p LIMIT 1
UNWIND [n IN nodes(p) WHERE n:Transition] AS trans
WITH DISTINCT trans
MATCH (trans)-[:TRANSFORMS]->(inputAsm:Assembly {product_id: 'Prod_CentrifugalPump_V15'})
MATCH (trans)-[:RESULTS_IN]->(output)
OPTIONAL MATCH (trans)-[:DISASSEMBLED_BY]->(task:DisassemblyTask {product_id: 'Prod_CentrifugalPump_V15'})
OPTIONAL MATCH (task)-[:REQUIRES]->(skill:Skill)
OPTIONAL MATCH (task)-[:PERFORMED_BY]->(agent:Agent)
OPTIONAL MATCH (task)-[:USES_TOOL]->(tool:Tool)
RETURN trans.id AS transition, inputAsm.id AS fromAssembly,
       task.name AS task, skill.name AS skill, agent.name AS agent,
       tool.name AS tool,
       collect(DISTINCT CASE WHEN output:Component THEN output.name ELSE output.id END) AS results
ORDER BY size(inputAsm.id) DESC
```

**Rows:** 6

**Answer:**

> The Knowledge Graph shows this sequence to reach the Impeller. The two entries for transition **T336** are both listed in the data; it does not specify whether they are alternatives or whether both tasks are required.
> 
> 1. **T337 — Unscrew 4× M12 Flange Bolt**
>    - Skill: Unscrewing
>    - Agent: Human Worker (**Human**)
>    - Tool: Combination Wrench (18mm)
>    - Results include the four M12 Flange Bolts, the Suction Nozzle, and assembly `Asm_ABCDEFGHIJKMNQSTUWXY`.
> 
> 2. **T336 — Unscrew M20 Cap Nut**
>    - Skill: Unscrewing
>    - Agent: Human Worker (**Human**)
>    - Tool: Combination Wrench (30mm)
>    - Results: M20 Cap Nut and assembly `Asm_ABCDEFGHIJKMQSTUWXY`.
> 
> 3. **T336 — Pick M20 Cap Nut**
>    - Skill: Picking
>    - Agent: Human Worker (**Human**)
>    - Tool: No Tool (Manual)
>    - Results: M20 Cap Nut and assembly `Asm_ABCDEFGHIJKMQSTUWXY`.
> 
> 4. **T323 — Pull Off Coupling**
>    - Skill: Pulling Off
>    - Agent: Human Worker (**Human**)
>    - Tool: Pull-Off Tool
>    - Results: Coupling and assembly `Asm_ABCDEFGIJKMQSTUWXY`.
> 
> 5. **T276 — Unscrew 6× M20x2.5 Hex Bolt**
>    - Skill: Unscrewing
>    - Agent: Human Worker (**Human**)
>    - Tool: Combination Wrench (30mm)
>    - Results include the Volute Casing Cover, Volute Casing Gasket, six M20x2.5 Hex Bolts, and assembly `Asm_BCDFGIKMTW`.
> 
> 6. **T203 — Pick Impeller**
>    - Skill: Picking
>    - Agent: Human Worker (**Human**)
>    - Tool: No Tool (Manual)
>    - Results: Impeller and assembly `Asm_BCDFGKMTW`.
> 
> The raw data does not provide a separate connection type.

---

## P15b (Disassembly sequences): PASS

**Q:** How do I remove the Shaft?

```cypher
MATCH p = (root:Assembly {product_id: 'Prod_CentrifugalPump_V15', isRoot: true})
      (()<-[:TRANSFORMS]-(:Transition {product_id: 'Prod_CentrifugalPump_V15'})-[:RESULTS_IN]->()){0,24}
      (a:Assembly {product_id: 'Prod_CentrifugalPump_V15'})<-[:TRANSFORMS]-(t:Transition {product_id: 'Prod_CentrifugalPump_V15'})-[:RESULTS_IN]->(target:Component {product_id: 'Prod_CentrifugalPump_V15'})
WHERE toLower(target.name) CONTAINS 'shaft'
WITH p LIMIT 1
UNWIND [n IN nodes(p) WHERE n:Transition] AS trans
WITH DISTINCT trans
MATCH (trans)-[:TRANSFORMS]->(inputAsm:Assembly {product_id: 'Prod_CentrifugalPump_V15'})
MATCH (trans)-[:RESULTS_IN]->(output)
OPTIONAL MATCH (trans)-[:DISASSEMBLED_BY]->(task:DisassemblyTask {product_id: 'Prod_CentrifugalPump_V15'})
OPTIONAL MATCH (task)-[:REQUIRES]->(skill:Skill)
OPTIONAL MATCH (task)-[:PERFORMED_BY]->(agent:Agent)
OPTIONAL MATCH (task)-[:USES_TOOL]->(tool:Tool)
RETURN trans.id AS transition, inputAsm.id AS fromAssembly,
       task.name AS task, skill.name AS skill, agent.name AS agent,
       tool.name AS tool,
       collect(DISTINCT CASE WHEN output:Component THEN output.name ELSE output.id END) AS results
ORDER BY size(inputAsm.id) DESC
```

**Rows:** 14

**Answer:**

> The Knowledge Graph gives this sequence to reach the transition that frees the **Shaft**. The agent is listed as **Human Worker**; an agent type is not specified in the data. Where multiple tasks are listed for one transition, they are entries for the same transition, not additional sequence steps.
> 
> 1. **Transition T340 — Asm_ABCDEFGHIJKLMNOPQRSTUVWXY**
>    - Task: Pull Off Coupling
>    - Skill: Pulling Off
>    - Agent: Human Worker (type not specified)
>    - Tool: Pull-Off Tool
>    - Results: Coupling and **Asm_ABCDEFGIJKLMNOPQRSTUVWXY**
> 
> 2. **Transition T331 — Asm_ABCDEFGIJKLMNOPQRSTUVWXY**
>    - Listed task entries:
>      - Pull Off Bearing End Cap 1 — skill: Pulling Off; tool: Pull-Off Tool
>      - Pick Bearing End Cap 1 — skill: Picking; tool: No Tool (Manual)
>    - Agent for both: Human Worker (type not specified)
>    - Results: Bearing End Cap 1 and **Asm_ABCEFGIJKLMNOPQRSTUVWXY**
> 
> 3. **Transition T317 — Asm_ABCEFGIJKLMNOPQRSTUVWXY**
>    - Task: Unscrew 4x M12 Flange Bolt
>    - Skill: Unscrewing
>    - Agent: Human Worker (type not specified)
>    - Tool: Combination Wrench (18mm)
>    - Results: four M12 Flange Bolts, Suction Nozzle, and **Asm_ABCEFGIJKMNQSTUWXY**
> 
> 4. **Transition T299 — Asm_ABCEFGIJKMNQSTUWXY**
>    - Listed task entries:
>      - Pick M20 Cap Nut — skill: Picking; tool: No Tool (Manual)
>      - Unscrew M20 Cap Nut — skill: Unscrewing; tool: Combination Wrench (30mm)
>    - Agent for both: Human Worker (type not specified)
>    - Results: M20 Cap Nut and **Asm_ABCEFGIJKMQSTUWXY**
> 
> 5. **Transition T264 — Asm_ABCEFGIJKMQSTUWXY**
>    - Task: Unscrew 6x M20x2.5 Hex Bolt
>    - Skill: Unscrewing
>    - Agent: Human Worker (type not specified)
>    - Tool: Combination Wrench (30mm)
>    - Results: six M20x2.5 Hex Bolts, Volute Casing Cover, Volute Casing Gasket, and **Asm_BCFGIKMTW**
> 
> 6. **Transition T193 — Asm_BCFGIKMTW**
>    - Task: Pick Impeller
>    - Skill: Picking
>    - Agent: Human Worker (type not specified)
>    - Tool: No Tool (Manual)
>    - Results: Impeller and **Asm_BCFGKMTW**
> 
> 7. **Transition T171 — Asm_BCFGKMTW**
>    - Listed task entries:
>      - Pull Off Bearing 40x50 — skill: Pulling Off; tool: Pull-Off Tool
>      - Pull Off Bearing Housing — skill: Pulling Off; tool: Pull-Off Tool
>    - Agent for both: Human Worker (type not specified)
>    - Results: Bearing 40x50 and **Asm_BCFGKMT**
> 
> 8. **Transition T143 — Asm_BCFGKMT**
>    - Listed task entries:
>      - Pick Stuffing Box Gland Half_2 — skill: Picking; tool: No Tool (Manual)
>      - Pick Bearing End Cap 2 — skill: Picking; tool: No Tool (Manual)
>      - Pull Off Bearing 59x70 — skill: Pulling Off; tool: Pull-Off Tool
>      - Pick Stuffing Box Gland Half_1 — skill: Picking; tool: No Tool (Manual)
>    - Agent for all: Human Worker (type not specified)
>    - Results: **Shaft** and **Asm_BCGKMT**

---

## P16 (Disassembly sequences): PASS

**Q:** Generate a complete disassembly sequence for this product.

```cypher
MATCH p = (root:Assembly {product_id: 'Prod_CentrifugalPump_V15', isRoot: true})
      (()<-[:TRANSFORMS]-(t:Transition {product_id: 'Prod_CentrifugalPump_V15'} WHERE NOT EXISTS {
          MATCH (t2:Transition {product_id: 'Prod_CentrifugalPump_V15'})-[:TRANSFORMS]->(a:Assembly {product_id: 'Prod_CentrifugalPump_V15'})<-[:TRANSFORMS]-(t)
          WHERE ((toInteger(substring(t2.id, 1)) + 1387426911) * 2654435761) % 2147483648
              < ((toInteger(substring(t.id, 1))  + 1387426911) * 2654435761) % 2147483648
      })-[:RESULTS_IN]->()){1,24}
      (x)
UNWIND [n IN nodes(p) WHERE n:Transition] AS trans
WITH DISTINCT trans
MATCH (trans)-[:TRANSFORMS]->(inputAsm:Assembly {product_id: 'Prod_CentrifugalPump_V15'})
MATCH (trans)-[:RESULTS_IN]->(output)
OPTIONAL MATCH (trans)-[:DISASSEMBLED_BY]->(task:DisassemblyTask {product_id: 'Prod_CentrifugalPump_V15'})
OPTIONAL MATCH (task)-[:REQUIRES]->(skill:Skill)
OPTIONAL MATCH (task)-[:PERFORMED_BY]->(agent:Agent)
OPTIONAL MATCH (task)-[:USES_TOOL]->(tool:Tool)
RETURN trans.id AS transition, inputAsm.id AS fromAssembly,
       task.name AS task, skill.name AS skill, agent.name AS agent,
       tool.name AS tool,
       collect(DISTINCT coalesce(output.name, output.id)) AS results
ORDER BY size(inputAsm.id) DESC, transition
```

**Rows:** 18

**Answer:**

> The Knowledge Graph does **not provide a complete disassembly sequence**. It shows these steps and branches:
> 
> 1. **Transition T338 — Unscrew 6x M20x2.5 Hex Bolt**
>    - **Input:** `Asm_ABCDEFGHIJKLMNOPQRSTUVWXY`
>    - **Results:** M20x2.5 Hex Bolt ×6, Volute Casing Gasket, and the assemblies `BCDFGHIKMNTW` and `ALOPRV`
>    - **Skill:** Unscrewing
>    - **Agent:** Human Worker (Human)
>    - **Tool:** Combination Wrench (30mm)
> 
> 2. **Branch `ALOPRV` — Transition T10: Unscrew 4x M12 Flange Bolt**
>    - **Results:** M12 Flange Bolt ×4, Volute Casing Cover, and Suction Nozzle
>    - **Skill:** Unscrewing
>    - **Agent:** Human Worker (Human)
>    - **Tool:** Combination Wrench (18mm)
> 
> 3. **Branch `BCDFGHIKMNTW` — Transition T296: Pull Off Coupling**
>    - **Results:** Coupling and assembly `BCDFGIKMNTW`
>    - **Skill:** Pulling Off
>    - **Agent:** Human Worker (Human)
>    - **Tool:** Pull-Off Tool
> 
> The data lists Transition T232 as taking `BCDFGHIKMNTW` as input, but T296 produces `BCDFGIKMNTW`. Because those assembly IDs differ, the listed steps do not establish a continuation from T296 to T232. Therefore, the remaining disassembly and a complete sequence cannot be confirmed from this data.

---

## P17 (Disassembly sequences): PASS

**Q:** Which disassembly steps release several parts simultaneously?

```cypher
MATCH (trans:Transition {product_id: 'Prod_CentrifugalPump_V15'})-[:TRANSFORMS]->(inAsm:Assembly {product_id: 'Prod_CentrifugalPump_V15'})
MATCH (trans)-[:RESULTS_IN]->(out)
WHERE (out:Assembly OR out:Component) AND out.product_id = 'Prod_CentrifugalPump_V15'
WITH trans, inAsm, collect(out) AS outputs, count(out) AS outCount
WHERE outCount >= 3
OPTIONAL MATCH (trans)-[:DISASSEMBLED_BY]->(task:DisassemblyTask {product_id: 'Prod_CentrifugalPump_V15'})
RETURN inAsm.id AS fromAssembly,
       trans.name AS transition,
       task.name AS disassemblyStep,
       outCount AS outputCount,
       [o IN outputs | CASE WHEN o:Assembly THEN o.id ELSE 'Comp_' + o.partId END] AS outputs
ORDER BY outputCount DESC, fromAssembly
```

**Rows:** 43

**Answer:**

> The results show two disassembly steps that release several parts simultaneously:
> 
> - **Unscrew 6x M20x2.5 Hex Bolt** — produces **9 outputs**: a combination of components and subassemblies. The listed outputs include components **A, E, J, Q, S, U, X, Y**, and subassemblies such as **ALOPRV**, **BCDFGHIKMNTW**, and related variants, depending on the starting assembly.
> - **Unscrew 4x M12 Flange Bolt** — produces **6 outputs**: typically the remaining assembly plus components **P, V, R, L, O**. In the **ALOPRV** case, it releases components **A, P, V, R, L, O**.

---

## P18 (Counting): PASS

**Q:** How many assembly states does this product have?

```cypher
MATCH (asm:Assembly {product_id: 'Prod_CentrifugalPump_V15'})
RETURN count(DISTINCT asm) AS assemblyStateCount
```

**Rows:** 1

**Answer:**

> The product has **102 distinct assembly states**.

---

## P19 (Counting): PASS

**Q:** How many transitions does the product have?

```cypher
MATCH (trans:Transition {product_id: 'Prod_CentrifugalPump_V15'})
RETURN count(DISTINCT trans) AS transitionCount
```

**Rows:** 1

**Answer:**

> The product has **340 transitions**.

---

## P20 (Counting): PASS

**Q:** How many disassembly tasks does this product have?

```cypher
MATCH (task:DisassemblyTask {product_id: 'Prod_CentrifugalPump_V15'})
RETURN count(task) AS disassemblyTaskCount
```

**Rows:** 1

**Answer:**

> This product has **20 disassembly tasks**.

---

## P21 (Tasks): PASS

**Q:** List all disassembly tasks of this product.

```cypher
MATCH (task:DisassemblyTask {product_id: 'Prod_CentrifugalPump_V15'})
OPTIONAL MATCH (task)-[:ACTS_ON]->(conn:Connection {product_id: 'Prod_CentrifugalPump_V15'})
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

**Rows:** 20

**Answer:**

> The Knowledge Graph lists these disassembly tasks for the product. Each task is performed by a **Human Worker**:
> 
> | Task | Connection | Skill | Tool |
> |---|---|---|---|
> | Pick Stuffing Box Gland Half_1 | Stuffing Box Gland Half_1 ↔ Shaft | Picking | No Tool (Manual) |
> | Pick Stuffing Box Gland Half_1 | Stuffing Box Gland Half_1 ↔ Stuffing Box Gland Half_2 | Picking | No Tool (Manual) |
> | Pick Volute Casing | Stuffing Box Gland Half_1 ↔ Volute Casing | Picking | No Tool (Manual) |
> | Pull Off Bearing End Cap 1 | Bearing Housing ↔ Bearing End Cap 1 | Pulling Off | Pull-Off Tool |
> | Pull Off Bearing Housing | Bearing Housing ↔ Bearing End Cap 2 | Pulling Off | Pull-Off Tool |
> | Pull Off Bearing Housing | Bearing Housing ↔ Bearing 59x70 | Pulling Off | Pull-Off Tool |
> | Pick Bearing Housing | Bearing Housing ↔ Volute Casing | Picking | No Tool (Manual) |
> | Pull Off Bearing Housing | Bearing Housing ↔ Bearing 40x50 | Pulling Off | Pull-Off Tool |
> | Pick Bearing End Cap 1 | Bearing End Cap 1 ↔ Shaft | Picking | No Tool (Manual) |
> | Pick Bearing End Cap 2 | Shaft ↔ Bearing End Cap 2 | Picking | No Tool (Manual) |
> | Pull Off Coupling | Shaft ↔ Coupling | Pulling Off | Pull-Off Tool |
> | Pick Impeller | Shaft ↔ Impeller | Picking | No Tool (Manual) |
> | Pull Off Bearing 59x70 | Shaft ↔ Bearing 59x70 | Pulling Off | Pull-Off Tool |
> | Pick Stuffing Box Gland Half_2 | Shaft ↔ Stuffing Box Gland Half_2 | Picking | No Tool (Manual) |
> | Unscrew M20 Cap Nut | Shaft ↔ M20 Cap Nut | Unscrewing | Combination Wrench (30mm) |
> | Pull Off Bearing 40x50 | Shaft ↔ Bearing 40x50 | Pulling Off | Pull-Off Tool |
> | Unscrew 4x M12 Flange Bolt | Volute Casing Cover ↔ Suction Nozzle | Unscrewing | Combination Wrench (18mm) |
> | Unscrew 6x M20x2.5 Hex Bolt | Volute Casing ↔ Volute Casing Gasket; Volute Casing Cover ↔ Volute Casing; Volute Casing Cover ↔ Volute Casing Gasket | Unscrewing | Combination Wrench (30mm) |
> | Pick M20 Cap Nut | Impeller ↔ M20 Cap Nut | Picking | No Tool (Manual) |
> | Pick Volute Casing | Stuffing Box Gland Half_2 ↔ Volute Casing | Picking | No Tool (Manual) |

---

## P22 (Tasks): PASS

**Q:** Which task frees the Impeller from the Shaft?

```cypher
MATCH (conn:Connection {product_id: 'Prod_CentrifugalPump_V15'})-[:CONNECTS]->(impeller:Component {product_id: 'Prod_CentrifugalPump_V15'})
MATCH (conn)-[:CONNECTS]->(shaft:Component {product_id: 'Prod_CentrifugalPump_V15'})
WHERE toLower(impeller.name) CONTAINS 'impeller'
  AND toLower(shaft.name) CONTAINS 'shaft'
MATCH (task:DisassemblyTask {product_id: 'Prod_CentrifugalPump_V15'})-[:ACTS_ON]->(conn)
OPTIONAL MATCH (task)-[:PERFORMED_BY]->(agent:Agent)
OPTIONAL MATCH (task)-[:USES_TOOL]->(tool:Tool)
RETURN task.name AS task,
       conn.id AS connectionId,
       agent.name AS agent,
       tool.name AS tool
```

**Rows:** 1

**Answer:**

> The **Pick Impeller** task frees the Impeller from the Shaft. It acts on connection **Conn_FI**, is performed by the **Human** agent **Human Worker**, and uses **No Tool (Manual)**.

---

## P23 (Tasks): PASS

**Q:** Which connections does the task 'Unscrew 6x M20x2.5 Hex Bolt' act on?

```cypher
MATCH (task:DisassemblyTask {product_id: 'Prod_CentrifugalPump_V15'})-[:ACTS_ON]->(conn:Connection {product_id: 'Prod_CentrifugalPump_V15'})
WHERE toLower(task.name) CONTAINS toLower('Unscrew 6x M20x2.5 Hex Bolt')
OPTIONAL MATCH (conn)-[:CONNECTS]->(component:Component {product_id: 'Prod_CentrifugalPump_V15'})
RETURN task.name AS task,
       conn.id AS connectionId,
       conn.name AS connection,
       collect(DISTINCT component.name) AS connectedParts
ORDER BY connectionId
```

**Rows:** 18

**Answer:**

> The task **“Unscrew 6x M20x2.5 Hex Bolt”** acts on 18 connections across three part pairings:
> 
> - **Volute Casing Cover ↔ Volute Casing:** Conn_AT_E, Conn_AT_J, Conn_AT_Q, Conn_AT_S, Conn_AT_X, Conn_AT_Y
> - **Volute Casing Cover ↔ Volute Casing Gasket:** Conn_AU_E, Conn_AU_J, Conn_AU_Q, Conn_AU_S, Conn_AU_X, Conn_AU_Y
> - **Volute Casing ↔ Volute Casing Gasket:** Conn_TU_E, Conn_TU_J, Conn_TU_Q, Conn_TU_S, Conn_TU_X, Conn_TU_Y

---

## P24 (Resources): PASS

**Q:** Which agent performs the unscrew tasks?

```cypher
MATCH (task:DisassemblyTask {product_id: 'Prod_CentrifugalPump_V15'})
WHERE toLower(task.name) CONTAINS 'unscrew'
OPTIONAL MATCH (task)-[:PERFORMED_BY]->(agent:Agent)
RETURN task.name AS task, agent.name AS agent, agent.agentType AS agentType
ORDER BY task.name
```

**Rows:** 3

**Answer:**

> The **Human Worker (Human)** performs all three unscrew tasks:
> 
> - Unscrew 4x M12 Flange Bolt
> - Unscrew 6x M20x2.5 Hex Bolt
> - Unscrew M20 Cap Nut

---

## P25 (Filtering): PASS

**Q:** Which assembly states contain the Impeller?

```cypher
MATCH (asm:Assembly {product_id: 'Prod_CentrifugalPump_V15', isState: true})
WHERE asm.id CONTAINS 'I'
RETURN asm.id AS assemblyId, asm.name AS assemblyName,
       asm.isRoot AS isRoot
ORDER BY size(asm.id) DESC, assemblyId
```

**Rows:** 42

**Answer:**

> The query returned the following assembly states whose IDs contain **I** (the data does not independently identify the letter **I** as “Impeller”):
> 
> - Asm_ABCDEFGHIJKLMNOPQRSTUVWXY (root)
> - Asm_ABCDEFGHIJKLMOPQRSTUVWXY
> - Asm_ABCDEFGIJKLMNOPQRSTUVWXY
> - Asm_ABCDEFGIJKLMOPQRSTUVWXY
> - Asm_ABCEFGIJKLMNOPQRSTUVWXY
> - Asm_ABCEFGIJKLMNOPQRSTUVXY
> - Asm_ABCEFGIJKLMOPQRSTUVWXY
> - Asm_ABEFGIJKLMNOPQRSTUVWXY
> - Asm_ABEFGIJKLMNOPQRSTUVXY
> - Asm_ABEFGIJKLMOPQRSTUVWXY
> - Asm_ABCDEFGHIJKMNQSTUWXY
> - Asm_ABEFGIJLMNOPQRSTUVXY
> - Asm_ABCDEFGHIJKMQSTUWXY
> - Asm_ABCDEFGIJKMNQSTUWXY
> - Asm_ABEFGIJLMOPQRSTUVXY
> - Asm_ABCDEFGIJKMQSTUWXY
> - Asm_ABCEFGIJKMNQSTUWXY
> - Asm_ABCEFGIJKMNQSTUXY
> - Asm_ABCEFGIJKMQSTUWXY
> - Asm_ABEFGIJKMNQSTUWXY
> - Asm_ABCEFGIJKMQSTUXY
> - Asm_ABEFGIJKMNQSTUXY
> - Asm_ABEFGIJKMQSTUWXY
> - Asm_ABEFGIJKMQSTUXY
> - Asm_ABEFGIJMNQSTUXY
> - Asm_ABEFGIJMQSTUXY
> - Asm_BCDFGHIKMNTW
> - Asm_BCDFGHIKMTW
> - Asm_BCDFGIKMNTW
> - Asm_BCDFGIKMTW
> - Asm_BCFGIKMNTW
> - Asm_BCFGIKMNT
> - Asm_BCFGIKMTW
> - Asm_BFGIKMNTW
> - Asm_BCFGIKMT
> - Asm_BFGIKMNT
> - Asm_BFGIKMTW
> - Asm_BFGIKMT
> - Asm_BFGIMNT
> - Asm_BFGIMT

---

## P26 (Filtering): PASS

**Q:** How many assembly states contain both the Shaft and the Bearing Housing?

```cypher
MATCH (asm:Assembly {product_id: 'Prod_CentrifugalPump_V15', isState: true})
WHERE asm.id CONTAINS 'F' AND asm.id CONTAINS 'C'
RETURN count(asm) AS assemblyStateCount
```

**Rows:** 1

**Answer:**

> There are **51 assembly states** containing both the Shaft and the Bearing Housing.

---

