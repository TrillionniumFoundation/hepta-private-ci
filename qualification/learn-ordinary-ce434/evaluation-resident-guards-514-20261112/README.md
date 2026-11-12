# Resident and Evaluator format-guard qualification

Source: `cd4b4327b35ae142578fb7a42574964d0ed029ae`.
Tree: `7ebeb491f0533815941461740e38e48b518fa585`.
Only parent: `514fe5f53cfdc254477667f8862d652ea756c807`.

The source changes only CALLERS and five existing source-closure test modules.
It preserves 480 boundaries, 368 protected rows (including duplicate-path rows),
all original callers, authority metadata, ignore rules, inventory, function-order
constraints, and test method names. The complete 31-row before/after delta is
retained. Three match arms follow rustfmt's inserted braces. The shared
completed-source caller marker uses the common method spelling; each original
caller still has an exact full receiver-call guard, covered by receiver
substitution and separated-call mutations and typed unexpected-caller rejection.

## Actual local observations

- All 53 owned protected rows passed the unchanged repository verifier.
- The 12 original Root bootstrap regression methods passed.
- On the independent source change alone, the nine-module suite executed 66
  methods: 64 passed, two errored because the independently owned Candidate
  Evaluation/readback protected rows were still their 514 text.
- A separate read-only validation overlay used exactly those two rows from
  `4ae6c73ea7731e69c6819c1d188f8ff26ba1fbb7` (CALLERS blob
  `47323db6a89601a6da059b71a01a8cb874a0a05e`). All 66 methods passed on that
  explicitly combined manifest. Both original row files and their hashes are
  retained. The overlay is not claimed as a standalone committed source.
- Earlier failed local passes and original raw logs are retained without
  reclassification. The first and second passes preceded the final duplicate
  marker relocation and exact quoted-literal preservation.
- Final diff whitespace check passed. The six source postimages were read back
  from GitHub at the fixed commit and were byte-for-byte equal to the tested
  postimages. A local commit attempt hit an unrelated missing object in the
  inherited sparse clone, so the fixed source was published through Git objects.

No Rust, Cargo, daemon, cross-UID deployment, full caller proof, or ordinary
learning acceptance result is asserted by this evidence. EvalMaterial 4fbb and
Model 9ea remain separate unqualified work; their scope-authentication issue is
not covered here.

## Match-arm representation changes

The three exact original and formatted spans are retained in
`gate-match-arm-format-delta.json`. They map `Current` to `RequireDispatch`,
`Begin(stage)` to `Begin`, and `Checkpoint(next)` to `Checkpoint` in
`authority_host_learning_resident_gate.rs::local_inner`. The formatted span adds
`{` and the actual line break/indentation immediately after `=>`; no variant,
argument, effect, sequence item, or top-level constraint is removed.
