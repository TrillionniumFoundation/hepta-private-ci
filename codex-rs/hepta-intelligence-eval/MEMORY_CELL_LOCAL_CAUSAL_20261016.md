# MemoryCell source-local controlled causal read — 2026-10-16

Source of actual local execution: `a53e84a84f63c90df4d8f59855b7d1f7f2b3c482` on PR #1452. 
Frozen input GitHub artifact: `11827287296`; archive SHA-256:
`31c6f191ecf62095779f7c9a5dd6c5b2f89c6ae408fe9c26f74e017a2d62c47a`.

## Scope and answer-producing rules

This run **does not use an answer-space oracle**. The bounded deterministic parser sees
only the published question text, actually delivered document IDs and their
original event bytes. It does not read hidden corpus documents, pre-answer
target labels or the previous Oracle-assisted ranking pool. Each inferred
value must follow a complete entity/attribute chain at the requested logical
revision. Every hop yields a citation to its original delivered label.
Missing premises, conflicting heads, unknown grammar, invalid source identity,
future calendar observations, cross-scope data or revoked roots fail closed.
This is **not a language model** or independent human semantic oracle.

The six arms and eight questions are the **previously exposed, authored
development cohort**. `program_support` is explicitly an authored Oracle
control; `hybrid` and `entity_time` use the previously frozen original
retrieval/selection. Comparing the symbolic parser against the SmolLM2
free-generation arm is an architectural comparison, not a same-reader or
equal-token-budget memory gain.

## Source-bound observed outcome

48/48 model-free controlled answer executions were durably journaled before
opening original answer annotations. Twelve constrained original worker
executions were observed for the two procedure cases under all six arms.

| Arm | Correct task | Complete program-declared support cited | Abstained |
| --- | ---: | ---: | ---: |
| empty | 0/8 | 0/8 | 8/8 |
| hybrid | 8/8 | 8/8 | 0/8 |
| entity_time | 8/8 | 8/8 | 0/8 |
| organized | 8/8 | 8/8 | 0/8 |
| program_support (authored Oracle) | 8/8 | 8/8 | 0/8 |
| without_prerequisite | 0/8 | 0/8 | 8/8 |

Original raw-answer JSONL SHA-256:
`48057b6d3449aa5c8eaa094985351f42b67834327db9a1bb41cbfa4d2608513e` (43,407 bytes).
Original scored-answer JSON SHA-256:
`26f074f97a6c84793b79136088e4d7ff7bea325a023e14220a0f61f718ab8745` (61,448 bytes).
A separate replay process recomputed all 48 source/request/citation/answer bindings and reran
12 original program checks, **zero new model calls**. Eight focused adversarial
tests passed locally, including negative revocation, missing-hop, conflict,
future timestamp, and forged event JSON controls. Local isolated host is
not the user dot host.

**No independent source families, three future windows, real project
program-debugging tasks, qualified human citation reviews, model adaptation,
or production acceptance** were generated. Maintenance, revocation and
cross-host recovery costs are unknown, not zero. `blocking-ci` remains
mandatory and is not bypassed. The new exact-head workflow independently
reconstructs the same source-only experiment and must be checked at its
terminal result; a queued job is not a completed certification.

This evidence can serve as an improved **structured nonparametric RAG
control**, equally available to all future learning candidates. Its success
must not be attributed to a learned MemoryCell or a stronger Reader.
