# Native 1631: three actual failures

Execution is the original source 1631e01fd086f79bef8bf19bd6fe5859565b7976, run 43243479903, job 131269839345. The original full suite ran 1733 methods: 1697 passed, 36 failed, no retries. This candidate has not been formatted, compiled or executed. The existing failure evidence remains unchanged.

## Evaluation receipt failures

Both old success loops include InsufficientEvidence. The production prepare_cell_learning_evaluation_v1 explicitly returns CellLearningEvaluationErrorV1::InsufficientEvidence instead of creating an Evaluation receipt; it maps only a complete Ineligible result to NoUpdate. Its existing native regression insufficient_evidence_keeps_the_original_training_cut already checks that exact refusal at clocks 50, 60 and 351, unchanged Training cut, and continued authentication of the original signature.

The real fixture is not repaired or weakened. It constructs a signed original execution and obtains an actual insufficient product qualification by removing future windows. The two peripheral success loops were stale. They retain all original assertions for Qualified and complete Ineligible, including original signatures, recovery bytes and witness rollback rejection.

Two separate native regressions cover the omitted case through the actual readback adapter and receipt owner. They require exact InsufficientEvidence errors; no request may reach either dormant evidence channel. A corrupted original product signature must still fail authentication. The original owner journal and independent witness bytes must stay identical through a fresh attestation attempt, fresh readback and original cold recovery; the snapshot remains at the Training cut. No Evaluation receipt or synthetic NoUpdate is constructed.

## Unsorted policy fixture failure

The original fixture permutes definition.candidates into the original input order but leaves bindings[0].routes in configuration order. For descending IDs the first candidate is b while the first route is a. The original CircuitCellRegistryV1::new performs an exact positional route/candidate check, so the fixture fails with InvalidBinding before any B Source publication exists.

The fix permutes the complete existing route objects by the same candidate ID and then executes the existing route digest pin and registry constructor. Duplicate, missing and leftover routes fail. Outcomes and selected edge lists are moved unchanged; no route, candidate, permission or production check is added or removed. Existing production drift rejection remains unchanged.

The original failing end-to-end method remains intact: real original Source/Cell/ledger owners execute, policy bytes remain in their original noncanonical order, and physical source/witness/ledger bytes must not change during cohort readback. This existing regression is the behavioral acceptance test; a second toy sorting test is unnecessary.

## Integration and validation boundary

Only the three test files listed in MANIFEST.json are postimages. No production source, expectation for complete Ineligible, caller inventory, allowlist, grant or threshold changes. The original three failing method names and full 1733 denominator are retained; two refusal methods are added. Root's separate model-proposal correction should preserve exact NoUpdate refusal for complete Ineligible and assert the existing Evaluation(InsufficientEvidence) error for incomplete input, not broaden NoUpdate.

Run the unchanged project format/source gates and native suite on the actual integrated source. This bare immutable tree is review material and carries no runtime success claim.
