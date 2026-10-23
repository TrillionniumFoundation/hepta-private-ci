# Independent memory structural refactor review

Conclusion: no blocking finding. Reviewed actual `git diff HEAD`: five files, 109 insertions / 24 deletions, comprising three production files and two extensions to existing test cases. No public API, SQL, schema, transaction boundary, authorization check, or error mapping changed; no lint suppression added.

Base `b6cae33e26f09474f96df5598edb59d3d74ddd69`. Donor `6e4da822b02c8ed116c38146e18ef3d5e3bb314a`. All three production preimages independently verified byte-identical to donor parent; postimages byte-identical to donor. Full actual diff SHA256 `5208c0fcc980ea34d2957c4efe6f9f97958c65d78f6514bcb0c4e0340234ffea`; combined tree `99d59da60e1b778e91473136afc84fd58b1860f2` (temporary review index, actual index untouched). Per-file hashes in independent-review-manifest.json.

## Source review

- cognitive_intelligence_writer.rs:39–44 introduces crate-private ExpectedMemoryRevision, grouping the same borrowed StableMemoryId and u64 CAS revision. Public correct_with_kg signature remains intact; the internal tx function unpacks exactly those fields at the previous revise_memory_revision_tx call. Both internal callers were located and updated. No ownership/clone or lifetime extension changes.
- production_writer.rs:1612 groups those same parameters. The production path still verifies authority, prepares semantic mutation, begins BEGIN IMMEDIATE, admits the prepared mutation, performs correction in that same transaction, finishes the mutation, commits, and validates the receipt in the original order. No extra commit or pool operation introduced.
- local_lease_outbox.rs:54–59 introduces private OutcomeTransitionPolicy grouping allowed states, resulting state and exact replay flag. Both append_outcome_in_transaction callers preserve all prior values: forwarding wrapper passes its existing parameters; apply_in_transaction retains Queued/Indeterminate -> Committed and allow_exact_replay=true. All references were changed mechanically to policy.field. Validation, lease/fence checks, current-state check, existing transition digest comparison, event append and transaction commit order are unchanged. Existing external_effect=false values and single-consumption errors remain unchanged.

## Regression additions

- cognitive_intelligence_writer_tests.rs:144–184 strengthens the existing product-writer test: stale revision preserves the complete current memory; a never-created stable target with otherwise-current revision fails specifically with Invalid("memory does not exist"); its preceding source append rolls back; existing memory remains equal to the corrected revision. This covers the identity and revision fields separately without changing successful correction/forget behavior. It is a real SQLite transaction assertion, not a synthetic receipt validator.
- local_lease_outbox_tests.rs:1084–1110 strengthens the existing reopen/reconcile case: exact indeterminate replay returns the complete same receipt, different payload returns the existing precise CasConflict, journal counts stay unchanged, state remains Indeterminate. The existing subsequent close/reopen and committed reconciliation remain. This tests local persistence and replay; it does not claim process-kill, power-loss, downstream external-effect exactly-once, or new recovery guarantees.

## Validation evidence and limits

Independently read baseline-lib-clippy.log/exit: exactly two too_many_arguments errors in the two refactored internal functions, exit101. fixed-lib-clippy.log reports successful dev completion, exit0. These are parent-executed logs, not reviewer-executed Cargo.

memory-clippy.log still reports 17 all-targets errors: an unchanged cognitive_schema_tests direct SQLite connect plus expect_used calls in existing production_writer test helpers. None is a changed line of this patch. app-server-clippy.log reports two dead-code errors in hepta-memory-extension and map_response_events too_many_arguments in core, all outside this diff. This review does not characterize strict all-targets or app-server Clippy as passed. No unrelated repair or suppression is requested.

At review time tests.log was still compiling the parent's selected three-module test run. No test success is asserted yet. Reviewer did not run parallel Cargo, generate credentials, call a vendor, or modify repository sources. Source review is complete; parent must retain final test outcomes bound to this tree before reporting validation complete. Wider workspace behavior, external-effect execution and production crash durability were not exercised here.
