# Review order and dependency boundaries

All pull requests are research drafts against a pinned R19 base or an explicitly declared component dependency. No production merge or activation is requested.

| Order | Draft | Dependency | Review focus |
| --- | --- | --- | --- |
| 1 | #4605 native financial | pinned R19 | Bounded three-parameter constructor; independent high-precision references; rejection scope |
| 2 | #4606 live runtime | #4605 | Live numerical state from paid receipts; exact ELF identity; cold pending-action recovery |
| 3 | #4607 directional | pinned R19 | Tie-aware directional algebra; V1 cycling correction; generic gradient failures |
| 4 | #4608 planner | pinned R19 | Uniform durable-query charges; independent resource audit; failed CPU/investment gates |
| 5 | #4610 content | pinned R19 | Fixed samples; conservative fallback controls; label/coverage/Brier failures; late auditor dependency disclosure |
| 6 | #4611 checkpoint | #4608 | Strict typed restore admission; unchanged old modules; 117-process cold correctness; no performance qualification |

COMPOSITION.json binds exact component heads and source publication chronology. The integrated convergence commit preserves the final delivery tree and records all six component heads as additional parents; it does not transform failed research gates into passes.

Before replay, run each component's restore_evidence.py as described in TRANSPORT.md. The live runtime additionally needs its exact formal executable restored via BINARY_RESUME.md. Read STATUS.json and the independent scope review before interpreting numerical passes as broader qualifications.
