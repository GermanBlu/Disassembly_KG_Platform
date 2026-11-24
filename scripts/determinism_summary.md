# Repeated questions on the pump graph

Two questions were each asked 10 times against the pump graph of
`sample_data/Centrifugal Pump/centrifugal_pump_product.json` (102 assembly
states, 340 transitions), with a fresh chat per run, gpt-6-luna, on
2 November 2026. Records: `determinism_first_step.json` and
`determinism_sequence.json`, written by `scripts/run_determinism.py`. Each
record holds, per run, the transition identifiers named in the answer and the
first 600 characters of the answer. The counts below can be recounted from
these two files. The summary fields at the top of each record are derived
from the per-run data: `first_named_transition_distribution` counts the
identifier named first in each answer (which need not be a transition from
the complete product), `distinct_transition_sets` the different sets of named
identifiers, and `runs_without_transition_ids` the answers that name none.

## How a path is selected

- **First step.** The generated Cypher anchors on the root assembly
  (`isRoot`) and returns all first transitions in a fixed order. The query
  selects nothing; the answer reports what the query returned.
- **Complete sequence.** The generated Cypher picks one transition per
  reached assembly state with a seeded hash; the seed is a new random literal
  in each query. Applied to every branch, this gives one complete sequence
  down to single parts (13 transitions for the pump). The selection happens
  inside the query; the language model formats the returned rows.

## "What is the first step to disassemble this product?" (10 runs)

The complete pump has four first steps: T337 (Unscrew 4x M12 Flange Bolt),
T338 (Unscrew 6x M20x2.5 Hex Bolt), T339 (M20 Cap Nut) and T340 (Pull Off
Coupling).

| Observation | Runs |
|---|---|
| Answer names a single first step, in each case Unscrew 4x M12 Flange Bolt, the first entry of the listings | 6 of 10 |
| of these, with the transition identifier (T337) | 1 |
| Answer lists all first steps without preferring one | 4 of 10 |
| Answer starts at the complete pump | 10 of 10 |

## "Generate a complete disassembly sequence for this product." (10 runs)

| Observation | Runs |
|---|---|
| Answer names 13 transition identifiers | 9 of 10 |
| Answer names no transition identifier | 1 of 10 |
| Different sequences (sets of 13 transitions) among the nine answers | 7 |

Each of the nine identifier sets is a complete sequence of the pump graph:
exactly one transition for every reached assembly state, ending in the 25
single components (checked against the transitions in the product file). Two
pairs of answers contain the same 13 transitions in a different order of
presentation (runs 3 and 4, runs 8 and 10). The answer of run 10 states that
the data does not give a complete sequence, although the 13 transitions it
names form one.

## Reading

- For a complete sequence, the choice among the alternatives is made in the
  query by a seeded tie-break. For the first step, the query returns all
  alternatives, and the answer may name only the first of them. The answers
  differ in wording and in whether they name identifiers.
- Several valid paths exist because the AND/OR graph keeps the alternatives
  (83 of the 102 states have more than one transition, at most 9 from one
  state). Repeated queries therefore return different valid complete
  sequences.
- The recorded answer openings contain no claim that a sequence is optimal or
  unique. Selecting an optimal sequence is an optimisation task on top of the
  graph.
