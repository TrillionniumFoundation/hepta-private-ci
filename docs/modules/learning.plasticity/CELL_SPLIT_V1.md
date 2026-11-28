# CellSplitV1 governed planner

`codex-rs/hepta-plasticity/src/cell_split.rs` turns one
`CellSplitProposalSignalV1` into a complete, deterministic `CellSplitV1`
proposal. The signal is an observation, not an instruction to mutate the
running topology. The planner emits exactly two candidates: the content-bound
change and a no-change competitor. Candidate order and all digests are
deterministic.

The planner requires four distinct role identities: generator, independent
evaluator, independent reviewer, and operator. Distinct strings are an
identity binding only; authentication and semantic evidence are supplied by
the respective owner boundaries. A generator cannot submit a selected
candidate. The generated status is always `RequiresIndependentReview`, and
the authority posture is `DENY_ALL`; acceptance, selection, promotion,
release, activation and rollback are outside this crate.

Admission fails closed for a missing signal or evidence, a stale baseline or
non-successor generation, a malformed operation lineage, zero budgets, an
exceeded risk ceiling, absent rollback procedure, absent canary/quarantine or
absent independent holdout. The five structural operations are `add`, `split`,
`merge`, `rewire` and `retire`. `add` and `retire` use one-sided lineage;
the other operations require distinct predecessor and candidate digests.

`CELL_SPLIT_V1_SCHEMA.json` is the protocol projection. It requires both
candidates, all safety bindings and the non-authorizing status. JSON schema
validation does not authenticate the role identities or prove the evidence;
those checks remain owner-specific admission work.
