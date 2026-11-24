# Centrifugal pump catalogue, run 2: 25/27 pass

Run 2 of 2 on 2 November 2026, model gpt-6-luna, catalogue `rag_eval/cases_pump.json` (27 questions, paper Table A.2; P01 to P15 are questions 1 to 15, P15b is question 16, P16 to P26 are questions 17 to 27). Product: the graph of `sample_data/Centrifugal Pump/centrifugal_pump_product.json`, loaded for this run under the id `Prod_CentrifugalPump_V15` with the name Centrifugal Pump V15. Automatic check: 25 of 27 (P10 and P15b fail).

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
> - **A:** Volute Casing Cover
> - **B:** Stuffing Box Gland Half_1
> - **C:** Bearing Housing
> - **D:** Bearing End Cap 1
> - **E:** M20x2.5 Hex Bolt_1
> - **F:** Shaft
> - **G:** Bearing End Cap 2
> - **H:** Coupling
> - **I:** Impeller
> - **J:** M20x2.5 Hex Bolt_2
> - **K:** Bearing 59x70
> - **L:** M12 Flange Bolt_1
> - **M:** Stuffing Box Gland Half_2
> - **N:** M20 Cap Nut
> - **O:** M12 Flange Bolt_2
> - **P:** Suction Nozzle
> - **Q:** M20x2.5 Hex Bolt_3
> - **R:** M12 Flange Bolt_3
> - **S:** M20x2.5 Hex Bolt_4
> - **T:** Volute Casing
> - **U:** Volute Casing Gasket
> - **V:** M12 Flange Bolt_4
> - **W:** Bearing 40x50
> - **X:** M20x2.5 Hex Bolt_5
> - **Y:** M20x2.5 Hex Bolt_6**

---

## P02 (Product structure): PASS

**Q:** How many components does the product have?

```cypher
MATCH (p:Product {id: 'Prod_CentrifugalPump_V15'})-[:CONSISTS_OF]->(root:Assembly {product_id: 'Prod_CentrifugalPump_V15'})-[:CONSISTS_OF]->(c:Component {product_id: 'Prod_CentrifugalPump_V15'})
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
ORDER BY f.partId
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
RETURN p.name AS product, root.id AS rootAssemblyId, root.name AS rootAssemblyName
```

**Rows:** 1

**Answer:**

> The root assembly of the **Centrifugal Pump V15** is **Asm_ABCDEFGHIJKLMNOPQRSTUVWXY**, named **ABCDEFGHIJKLMNOPQRSTUVWXY**.

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

> The part ID of the Impeller is **I**.

---

## P06 (Connections): PASS

**Q:** What connection types are used in this product?

```cypher
MATCH (conn:Connection {product_id: 'Prod_CentrifugalPump_V15'})-[:OF_TYPE]->(ct:ConnectionType)
RETURN DISTINCT ct.id AS connectionTypeId,
       ct.name AS connectionType
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

> The product has **40 connections**.

---

## P08 (Connections): PASS

**Q:** Which connections are press-fit?

```cypher
MATCH (conn:Connection {product_id: 'Prod_CentrifugalPump_V15'})-[:OF_TYPE]->(ct:ConnectionType {id: 'CT_PressFit'})
MATCH (conn)-[:CONNECTS]->(c:Component {product_id: 'Prod_CentrifugalPump_V15'})
WITH conn, ct, collect(c.name) AS connectedParts
RETURN conn.id AS connectionId, conn.name AS connection,
       ct.name AS connectionType, connectedParts
ORDER BY connectionId
```

**Rows:** 7

**Answer:**

> The following connections are **Press Fit**:
> 
> - Bearing Housing ↔ Bearing End Cap 1
> - Bearing Housing ↔ Bearing End Cap 2
> - Bearing Housing ↔ Bearing 59x70
> - Bearing Housing ↔ Bearing 40x50
> - Shaft ↔ Coupling
> - Shaft ↔ Bearing 59x70
> - Shaft ↔ Bearing 40x50

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

> The connection between the Volute Casing, Volute Casing Gasket, and Volute Casing Cover is mediated by six fasteners:
> 
> - Part E — M20x2.5 Hex Bolt_1
> - Part J — M20x2.5 Hex Bolt_2
> - Part Q — M20x2.5 Hex Bolt_3
> - Part S — M20x2.5 Hex Bolt_4
> - Part X — M20x2.5 Hex Bolt_5
> - Part Y — M20x2.5 Hex Bolt_6

---

## P10 (Connections): FAIL

**Q:** Which parts does the M20 Cap Nut connect?

```cypher
MATCH (f:Fastener {product_id: 'Prod_CentrifugalPump_V15'})
WHERE toLower(f.name) CONTAINS 'm20 cap nut'
MATCH (conn:Connection {product_id: 'Prod_CentrifugalPump_V15'})-[:USES_FASTENER]->(f)
MATCH (conn)-[:CONNECTS]->(c:Component {product_id: 'Prod_CentrifugalPump_V15'})
RETURN f.name AS fastener,
       collect(DISTINCT c.name) AS connectedParts
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
RETURN DISTINCT task.name AS task, tool.name AS tool
ORDER BY task
```

**Rows:** 2

**Answer:**

> The unscrewing tasks use:
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

> The raw data lists multiple possible first disassembly steps from the complete assembly; it does not identify a single one. They are:
> 
> - **Unscrew 4× M12 Flange Bolt** — Human Worker, using a **Combination Wrench (18mm)**.
> - **Unscrew 6× M20x2.5 Hex Bolt** — Human Worker, using a **Combination Wrench (30mm)**.
> - **Pick M20 Cap Nut** — Human Worker, using **No Tool (Manual)**.
> - **Unscrew M20 Cap Nut** — Human Worker, using a **Combination Wrench (30mm)**.
> - **Pull Off Coupling** — Human Worker, using a **Pull-Off Tool**.

---

## P14 (Disassembly sequences): PASS

**Q:** How many alternative first disassembly steps are there from the full assembly?

```cypher
MATCH (trans:Transition {product_id: 'Prod_CentrifugalPump_V15'})-[:TRANSFORMS]->(root:Assembly {product_id: 'Prod_CentrifugalPump_V15', isRoot: true})
RETURN count(DISTINCT trans) AS alternativeFirstDisassemblySteps
```

**Rows:** 1

**Answer:**

> There are **4 alternative first disassembly steps** from the full assembly.

---

## P15 (Disassembly sequences): PASS

**Q:** How do I remove the Impeller?

```cypher
MATCH p = (root:Assembly {product_id: 'Prod_CentrifugalPump_V15', isRoot: true})
      (()<-[:TRANSFORMS]-(t:Transition {product_id: 'Prod_CentrifugalPump_V15'})-[:RESULTS_IN]->()){0,24}
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

```cypher
MATCH p = (root:Assembly {product_id: 'Prod_CentrifugalPump_V15', isRoot: true})
      (()<-[:TRANSFORMS]-(pathTrans:Transition {product_id: 'Prod_CentrifugalPump_V15'})-[:RESULTS_IN]->()){0,24}
      (a:Assembly {product_id: 'Prod_CentrifugalPump_V15'})<-[:TRANSFORMS]-(targetTrans:Transition {product_id: 'Prod_CentrifugalPump_V15'})-[:RESULTS_IN]->(target:Component {product_id: 'Prod_CentrifugalPump_V15'})
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

> To remove the **Impeller**, follow the recorded sequence:
> 
> 1. **Unscrew 4× M12 Flange Bolt** from `Asm_ABCDEFGHIJKLMNOPQRSTUVWXY`.  
>    - Connection released: **Suction Nozzle** and four M12 Flange Bolts  
>    - Skill: Unscrewing  
>    - Agent: **Human** — Human Worker  
>    - Tool: Combination Wrench (18mm)
> 
> 2. **Unscrew the M20 Cap Nut** from `Asm_ABCDEFGHIJKMNQSTUWXY`.  
>    - Skill: Unscrewing  
>    - Agent: **Human** — Human Worker  
>    - Tool: Combination Wrench (30mm)
> 
> 3. **Pick the M20 Cap Nut** from `Asm_ABCDEFGHIJKMNQSTUWXY`.  
>    - Skill: Picking  
>    - Agent: **Human** — Human Worker  
>    - Tool: No Tool (Manual)
> 
> 4. **Pull off the Coupling** from `Asm_ABCDEFGHIJKMQSTUWXY`.  
>    - Skill: Pulling Off  
>    - Agent: **Human** — Human Worker  
>    - Tool: Pull-Off Tool
> 
> 5. **Unscrew 6× M20×2.5 Hex Bolt** from `Asm_ABCDEFGIJKMQSTUWXY`.  
>    - Connection released: **Volute Casing Cover** and **Volute Casing Gasket**, along with six M20×2.5 Hex Bolts  
>    - Skill: Unscrewing  
>    - Agent: **Human** — Human Worker  
>    - Tool: Combination Wrench (30mm)
> 
> 6. **Pick the Impeller** from `Asm_BCDFGIKMTW`.  
>    - Result: **Impeller** and `Asm_BCDFGKMTW`  
>    - Skill: Picking  
>    - Agent: **Human** — Human Worker  
>    - Tool: No Tool (Manual)

---

## P15b (Disassembly sequences): FAIL

**Q:** How do I remove the Shaft?

```cypher
MATCH p = (root:Assembly {product_id: 'Prod_CentrifugalPump_V15', isRoot: true})
      (()<-[:TRANSFORMS]-(t:Transition)-[:RESULTS_IN]->()){0,24}
      (a:Assembly)<-[:TRANSFORMS]-(t:Transition)-[:RESULTS_IN]->(target:Component)
WHERE toLower(target.name) CONTAINS 'shaft'
  AND target.product_id = 'Prod_CentrifugalPump_V15'
  AND all(n IN nodes(p) WHERE
      (n:Assembly OR n:Transition) AND n.product_id = 'Prod_CentrifugalPump_V15')
WITH p LIMIT 1
UNWIND [n IN nodes(p) WHERE n:Transition] AS trans
WITH DISTINCT trans
MATCH (trans)-[:TRANSFORMS]->(inputAsm:Assembly {product_id: 'Prod_CentrifugalPump_V15'})
MATCH (trans)-[:RESULTS_IN]->(output)
WHERE output.product_id = 'Prod_CentrifugalPump_V15'
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

```cypher
MATCH p = (root:Assembly {product_id: 'Prod_CentrifugalPump_V15', isRoot: true})
      (()<-[:TRANSFORMS]-(:Transition)-[:RESULTS_IN]->()){0,24}
      (a:Assembly)<-[:TRANSFORMS]-(lastTrans:Transition)-[:RESULTS_IN]->(target:Component)
WHERE toLower(target.name) CONTAINS 'shaft'
  AND target.product_id = 'Prod_CentrifugalPump_V15'
  AND all(n IN nodes(p) WHERE
      (n:Assembly OR n:Transition) AND n.product_id = 'Prod_CentrifugalPump_V15')
WITH p LIMIT 1
UNWIND [n IN nodes(p) WHERE n:Transition] AS trans
WITH DISTINCT trans
MATCH (trans)-[:TRANSFORMS]->(inputAsm:Assembly {product_id: 'Prod_CentrifugalPump_V15'})
MATCH (trans)-[:RESULTS_IN]->(output)
WHERE output.product_id = 'Prod_CentrifugalPump_V15'
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

**Rows:** 0

**Answer:**

> I could not find relevant information in the Knowledge Graph to answer your question. Please try rephrasing or ask about components, connections, assembly/disassembly sequences, tasks, tools, or agents defined in this product.

**Failures:** answer missing all of ['Shaft']; answer missing all of ['Step', 'step']; rows 0 < min 1

---

## P16 (Disassembly sequences): PASS

**Q:** Generate a complete disassembly sequence for this product.

```cypher
MATCH p = (root:Assembly {product_id: 'Prod_CentrifugalPump_V15', isRoot: true})
      (()<-[:TRANSFORMS]-(t:Transition {product_id: 'Prod_CentrifugalPump_V15'} WHERE NOT EXISTS {
          MATCH (t2:Transition {product_id: 'Prod_CentrifugalPump_V15'})-[:TRANSFORMS]->(a:Assembly {product_id: 'Prod_CentrifugalPump_V15'})<-[:TRANSFORMS]-(t)
          WHERE ((toInteger(substring(t2.id, 1)) + 73190417) * 2654435761) % 2147483648
              < ((toInteger(substring(t.id, 1))  + 73190417) * 2654435761) % 2147483648
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

**Rows:** 20

**Answer:**

> ## Disassembly sequence
> 
> The data shows the initial disassembly splitting into two assembly branches, **Asm_BCDFGHIKMNTW** and **Asm_ALOPRV**. The branches are handled independently.
> 
> 1. **Asm_ABCDEFGHIJKLMNOPQRSTUVWXY — T338**
>    - **Task:** Unscrew 6× M20x2.5 Hex Bolt
>    - **Skill:** Unscrewing
>    - **Agent:** Human Worker (**Human**)
>    - **Tool:** Combination Wrench (30mm)
>    - **Results:** Six M20x2.5 Hex Bolts, Volute Casing Gasket, and assembly branches **Asm_BCDFGHIKMNTW** and **Asm_ALOPRV**.
> 
> ### Branch: Asm_BCDFGHIKMNTW
> 
> 2. **Asm_BCDFGHIKMNTW — T295**
>    - **Tasks:** Pick M20 Cap Nut; Unscrew M20 Cap Nut
>    - **Skill:** Picking; Unscrewing
>    - **Agent:** Human Worker (**Human**)
>    - **Tools:** No Tool (Manual); Combination Wrench (30mm)
>    - **Results:** M20 Cap Nut and **Asm_BCDFGHIKMTW**.
> 
> 3. **Asm_BCDFGHIKMTW — T293**
>    - **Task:** Pick Impeller
>    - **Skill:** Picking
>    - **Agent:** Human Worker (**Human**)
>    - **Tool:** No Tool (Manual)
>    - **Results:** Impeller and **Asm_BCDFGHKMTW**.
> 
> 4. **Asm_BCDFGHKMTW — T198**
>    - **Task:** Pull Off Coupling
>    - **Skill:** Pulling Off
>    - **Agent:** Human Worker (**Human**)
>    - **Tool:** Pull-Off Tool
>    - **Results:** Coupling and **Asm_BCDFGKMTW**.
> 
> 5. **Asm_BCDFGKMTW — T172**
>    - **Tasks:** Pull Off Bearing Housing; Pick Bearing End Cap 1; Pull Off Bearing 40x50; Pick Bearing Housing; Pull Off Bearing 59x70
>    - **Skills:** Pulling Off; Picking
>    - **Agent:** Human Worker (**Human**)
>    - **Tools:** Pull-Off Tool; No Tool (Manual)
>    - **Results:** **Asm_BFGMT** and **Asm_CDKW**. Continue both resulting assembly branches independently.
> 
> #### Branch: Asm_BFGMT
> 
> 6. **Asm_BFGMT — T58**
>    - **Tasks:** Pick Stuffing Box Gland Half_2; Pick Volute Casing; Pick Stuffing Box Gland Half_1
>    - **Skill:** Picking
>    - **Agent:** Human Worker (**Human**)
>    - **Tool:** No Tool (Manual)
>    - **Results:** **Asm_MT** and **Asm_BFG**.
> 
> 7. **Asm_BFG — T28**
>    - **Task:** Pick Stuffing Box Gland Half_1
>    - **Skill:** Picking
>    - **Agent:** Human Worker (**Human**)
>    - **Tool:** No Tool (Manual)
>    - **Results:** Stuffing Box Gland Half_1 and **Asm_FG**.
> 
> 8. **Asm_FG — T01**
>    - **Task:** Pick Bearing End Cap 2
>    - **Skill:** Picking
>    - **Agent:** Human Worker (**Human**)
>    - **Tool:** No Tool (Manual)
>    - **Results:** Bearing End Cap 2 and Shaft.
> 
> 9. **Asm_MT — T09**
>    - **Task:** Pick Volute Casing
>    - **Skill:** Picking
>    - **Agent:** Human Worker (**Human**)
>    - **Tool:** No Tool (Manual)
>    - **Results:** Volute Casing and Stuffing Box Gland Half_2.
> 
> #### Branch: Asm_CDKW
> 
> 10. **Asm_CDKW — T47**
>     - **Task:** Pull Off Bearing Housing
>     - **Skill:** Pulling Off
>     - **Agent:** Human Worker (**Human**)
>     - **Tool:** Pull-Off Tool
>     - **Results:** Bearing 59x70 and **Asm_CDW**.
> 
> 11. **Asm_CDW — T21**
>     - **Task:** Pull Off Bearing End Cap 1
>     - **Skill:** Pulling Off
>     - **Agent:** Human Worker (**Human**)
>     - **Tool:** Pull-Off Tool
>     - **Results:** Bearing End Cap 1 and **Asm_CW**.
> 
> 12. **Asm_CW — T08**
>     - **Task:** Pull Off Bearing Housing
>     - **Skill:** Pulling Off
>     - **Agent:** Human Worker (**Human**)
>     - **Tool:** Pull-Off Tool
>     - **Results:** Bearing 40x50 and Bearing Housing.
> 
> ### Branch: Asm_ALOPRV
> 
> 13. **Asm_ALOPRV — T10**
>     - **Task:** Unscrew 4× M12 Flange Bolt
>     - **Skill:** Unscrewing
>     - **Agent:** Human Worker (**Human**)
>     - **Tool:** Combination Wrench (18mm)
>     - **Results:** Four M12 Flange Bolts, Volute Casing Cover, and Suction Nozzle.
> 
> The data provides no further transitions for the final results listed above.

---

## P17 (Disassembly sequences): PASS

**Q:** Which disassembly steps release several parts simultaneously?

```cypher
MATCH (trans:Transition {product_id: 'Prod_CentrifugalPump_V15'})-[:TRANSFORMS]->(inAsm:Assembly {product_id: 'Prod_CentrifugalPump_V15'})
MATCH (trans)-[:RESULTS_IN]->(out)
WITH trans, inAsm, collect(DISTINCT out) AS outputs
WHERE size(outputs) >= 3
OPTIONAL MATCH (trans)-[:DISASSEMBLED_BY]->(task:DisassemblyTask {product_id: 'Prod_CentrifugalPump_V15'})
RETURN inAsm.id AS fromAssembly,
       trans.name AS transition,
       task.name AS disassemblyStep,
       size(outputs) AS outputCount,
       [o IN outputs | CASE WHEN o:Assembly THEN o.id
                            ELSE 'Comp_' + o.partId END] AS outputs
ORDER BY outputCount DESC, fromAssembly
```

**Rows:** 43

**Answer:**

> The graph shows two disassembly steps that release several outputs simultaneously:
> 
> - **Unscrew 6x M20x2.5 Hex Bolt** — produces **9 outputs**: either two assemblies plus seven individual components, or one assembly plus eight individual components, depending on the input assembly.
> - **Unscrew 4x M12 Flange Bolt** — produces **6 outputs**: one assembly plus five individual components, or six individual components when disassembling **Asm_ALOPRV**.
> 
> The graph provides multiple input-assembly variants for these steps. It does not provide human-readable names for the individual components; they are identified by IDs such as **Comp_A**, **Comp_P**, and **Comp_V**.

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
RETURN count(trans) AS transitionCount
```

**Rows:** 1

**Answer:**

> The product has **340 transitions**.

---

## P20 (Counting): PASS

**Q:** How many disassembly tasks does this product have?

```cypher
MATCH (task:DisassemblyTask {product_id: 'Prod_CentrifugalPump_V15'})
RETURN count(DISTINCT task) AS disassemblyTaskCount
```

**Rows:** 1

**Answer:**

> The product has **20 disassembly tasks**.

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

> The Knowledge Graph lists these disassembly tasks for the product. Each is performed by a **Human Worker**:
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
MATCH (conn:Connection {product_id: 'Prod_CentrifugalPump_V15'})-[:CONNECTS]->(c1:Component {product_id: 'Prod_CentrifugalPump_V15'})
MATCH (conn)-[:CONNECTS]->(c2:Component {product_id: 'Prod_CentrifugalPump_V15'})
MATCH (task:DisassemblyTask {product_id: 'Prod_CentrifugalPump_V15'})-[:ACTS_ON]->(conn)
WHERE toLower(c1.name) CONTAINS 'impeller'
  AND toLower(c2.name) CONTAINS 'shaft'
RETURN task.name AS task, conn.name AS connection,
       c1.name AS firstPart, c2.name AS secondPart
```

**Rows:** 1

**Answer:**

> The **Pick Impeller** task frees the **Impeller** from the **Shaft** at the **Shaft ↔ Impeller** connection.

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

> The task **“Unscrew 6x M20x2.5 Hex Bolt”** acts on 18 connections:
> 
> - **Volute Casing Cover ↔ Volute Casing:** `Conn_AT_E`, `Conn_AT_J`, `Conn_AT_Q`, `Conn_AT_S`, `Conn_AT_X`, `Conn_AT_Y`
> - **Volute Casing Cover ↔ Volute Casing Gasket:** `Conn_AU_E`, `Conn_AU_J`, `Conn_AU_Q`, `Conn_AU_S`, `Conn_AU_X`, `Conn_AU_Y`
> - **Volute Casing ↔ Volute Casing Gasket:** `Conn_TU_E`, `Conn_TU_J`, `Conn_TU_Q`, `Conn_TU_S`, `Conn_TU_X`, `Conn_TU_Y`

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

> The returned assembly states all contain the letter **I**. The raw data does not explicitly identify the letter **I** as the Impeller, so that part-name mapping cannot be confirmed from these results alone.
> 
> Assembly states returned (duplicates removed):
> 
> - `ABCDEFGHIJKLMNOPQRSTUVWXY`
> - `ABCDEFGHIJKLMOPQRSTUVWXY`
> - `ABCDEFGIJKLMNOPQRSTUVWXY`
> - `ABCDEFGIJKLMOPQRSTUVWXY`
> - `ABCEFGIJKLMNOPQRSTUVWXY`
> - `ABCEFGIJKLMNOPQRSTUVXY`
> - `ABCEFGIJKLMOPQRSTUVWXY`
> - `ABEFGIJKLMNOPQRSTUVWXY`
> - `ABCEFGIJKLMOPQRSTUVXY`
> - `ABEFGIJKLMNOPQRSTUVXY`
> - `ABEFGIJKLMOPQRSTUVWXY`
> - `ABCDEFGHIJKMNQSTUWXY`
> - `ABEFGIJLMNOPQRSTUVXY`
> - `ABCDEFGHIJKMQSTUWXY`
> - `ABCDEFGIJKMNQSTUWXY`
> - `ABEFGIJLMOPQRSTUVXY`
> - `ABCDEFGIJKMQSTUWXY`
> - `ABCEFGIJKMNQSTUWXY`
> - `ABCEFGIJKMNQSTUXY`
> - `ABCEFGIJKMQSTUWXY`
> - `ABEFGIJKMNQSTUWXY`
> - `ABCEFGIJKMQSTUXY`
> - `ABEFGIJKMNQSTUXY`
> - `ABEFGIJKMQSTUWXY`
> - `ABEFGIJKMQSTUXY`
> - `ABEFGIJMNQSTUXY`
> - `ABEFGIJMQSTUXY`
> - `BCDFGHIKMNTW`
> - `BCDFGHIKMTW`
> - `BCDFGIKMNTW`
> - `BCDFGIKMTW`
> - `BCFGIKMNTW`
> - `BCFGIKMNT`
> - `BCFGIKMTW`
> - `BFGIKMNTW`
> - `BCFGIKMT`
> - `BFGIKMNT`
> - `BFGIKMTW`
> - `BFGIKMT`
> - `BFGIMNT`
> - `BFGIMT`

---

## P26 (Filtering): PASS

**Q:** How many assembly states contain both the Shaft and the Bearing Housing?

```cypher
MATCH (asm:Assembly {product_id: 'Prod_CentrifugalPump_V15', isState: true})
WHERE asm.id CONTAINS 'F' AND asm.id CONTAINS 'C'
RETURN count(DISTINCT asm) AS assemblyStateCount
```

**Rows:** 1

**Answer:**

> There are **51 assembly states** containing both the Shaft and the Bearing Housing.

---

