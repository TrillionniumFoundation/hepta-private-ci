# Lane E learning implementation closure

This directory is the implementation index for `learning.ledger`,
`learning.operator`, `learning.eval` and `learning.artifacts`. It binds the
stable module guides and mathematical specifications to concrete Rust symbols,
focused tests, cross-crate composition and exact-head CI.

## Truth boundary

Lane E uses separate states for separate facts:

```text
documented_target
-> source_implemented
-> source_qualified_exact_head
-> product_wired
-> independently_accepted
-> runtime_activated
-> longitudinally_validated
```

A later state is never inferred from an earlier state. In particular:

- source compilation is not a production caller;
- an authenticated schema is not a provisioned credential or signature;
- a synthetic timestamp is not a future-calendar observation;
- evaluation eligibility is not selection, operator acceptance or release;
- an immutable candidate load is not runtime activation;
- repository CI cannot issue independent human review, external-owner consent,
  production canary, hardware or future-window evidence.

`LANE_E_IMPLEMENTATION_MATRIX.json` records repository-controlled implementation
status and the exact external gates that remain outside repository authority.
An external gate stays open until an immutable, independently issued receipt is
bound to the exact candidate; it is never marked complete to make the local gap
count green.

## Exact-head automation rule

A generated commit is a new candidate and cannot inherit a predecessor's green
checks. Commits pushed with the repository `GITHUB_TOKEN` do not recursively
start another workflow chain, so automation that materializes binding bytes must
verify the committed result before publication and the final non-generated head
must run the normal exact-head and synthetic-merge gates. A predecessor receipt
must never be relabelled as evidence for a later cleanup or generated commit.

## Read order

1. `LANE_E_IMPLEMENTATION_MATRIX.json` — operation-to-symbol, test and gate map.
2. `END_TO_END_LEARNING_SEQUENCE.md` — decision, learning, evaluation,
   artifact, revocation and rollback sagas.
3. `../../qualification/lane-e/TEST_TRACEABILITY.json` — dossier case to native
   test and CI mapping.
4. Each crate's `NATIVE_MAPPING.md` — exported Rust surface and host obligations.
5. `../../scripts/hepta-lane-e-closure.py` — read-only closed-world verifier.
6. Existing normative sources under `docs/modules`, `docs/learning`,
   `docs/readiness` and `qualification/module-execution-dossiers`.

## Repository-controlled closure criteria

The repository portion is closed only when all of the following hold at one
exact commit and tree:

- every mapped source and test path exists;
- every required native symbol is present in its owning crate;
- every dossier case in the Lane E traceability registry maps to an actual test;
- the four crates and cross-crate qualification suite compile and pass;
- strict Clippy and rustfmt pass without mutating the tested source;
- generated dependency metadata is committed;
- the closed-world Lane E verifier passes;
- final-holdout admission is bound to sealed immutable analysis semantics, with
  conflict-stable same-ID drift rejection and stable exact replay;
- all authority-bearing outputs in this slice remain `DENY_ALL` or explicitly
  delegated to an external owner.

External evidence remains a different closure domain. The repository verifier
reports those dispositions but cannot satisfy them.
