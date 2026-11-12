# Provider fixture and signature-expiry repair

## Exact failures

The focused native run tested `cc22a69972d029d3ef28d49096f396eb5214c616`. Its original stderr reports:

- `original_evaluation_accepts_unsorted_source_policy_without_reordering_its_bytes`: `Circuit task Cell: Cell(IncompleteCandidates)`, before an original B publication could be consumed.
- `original_evaluation_provider_refuses_missing_outcomes_renewal_and_zero_support`: the `expired-window` branch failed its `Evidence(_)` assertion at `circuit_original_evaluation_provider_tests.rs:311`, after 57.206 seconds. The assertion did not print the returned value.

The raw failure excerpts remain in `native-cc22-focused-review/failure-provider-timeout.h-view.txt`. This draft is based on `521283379701cca53987cf5c3fe85b85fdda04e6`, tree `778a2c1c1f77fd1ea3d3cd0c203cef6c38db2ec0`; the two changed Rust baselines have exactly the same blobs as cc22.

## Unsorted source fixture

`hepta-neuron/src/cell.rs` (blob `7f99ec906d3102582e4a9ba4ea6353b56a69d82b`) requires each input mask to match its frozen definition candidate at the same position. The test reversed the input masks while leaving the fixture definition in its original order. The real Cell correctly rejected that mismatch.

`CellDefinitionV1::semantic_digest` in `cell_binding.rs` (blob `669e52b01affd89b954d8ed099f8b097cf8ea488`) allows a complete, unique candidate sequence in a caller-declared order. The fixture now establishes that same order before creating the registry, Cell journal or Source. It preserves the original candidate-to-activation mapping and selected ID. Consuming a map by ID rejects duplicate or unknown masks, and an empty-remainder check rejects omissions. No existing journal, publication, signature or output bytes are rewritten.

The real published policy must retain the input's original candidate order. The existing unsorted test continues to compare all Source and Cell journal/witness bytes before and after provider reads. Production Cell and provider rules are unchanged.

## Signature expiry

The original verifier in `hepta-learning-ledger/src/signed_evidence.rs` (blob `214cae5c9fc4e60598a572faeca5d92c87b0be7f`) rejects `now > evidence.expires_at`; the expiry second itself is valid. The old test set the clock to `expires_at`, which does not establish signature expiry.

Version 1 of this draft prematurely attributed the failure to the work-envelope check. That diagnosis and hunk were withdrawn before integration. Reading the actual fixture showed a 900-second work envelope and a 600-second Training-signature bound. Version 2 keeps the original signature-expiry scenario: it verifies the unchanged signature at its last valid second, advances exactly one second, asserts that the original work envelope is still live, and requires `Evidence(SignedEvidenceError::ValidityWindow)`. A second read must remain `Indeterminate`; the original signature and ledger/witness bytes must stay unchanged.

## Scenario mapping and timing

The previous combined test attempted six real cohorts in one 60-second test. It had already spent 57.206 seconds before the sixth, zero-support cohort. The same scenarios now have separate fixtures and retain the original 60-second limit.

| Original scenario | New test |
| --- | --- |
| Missing last Outcome; wrong terminal Outcome unit | `original_evaluation_provider_refuses_missing_and_wrong_unit_outcomes` |
| Valid freeze-signature renewal; valid Training-signature renewal | `original_evaluation_provider_refuses_renewed_original_signatures` |
| Original Training-signature expiry | `original_evaluation_provider_expired_training_signature_permanently_fences_readback` |
| Unsupported candidate action / zero support; holdout consumed once | `original_evaluation_provider_zero_support_consumes_holdout_once` |
| Complete unsorted original Source policy; original bytes preserved | Existing unsorted-source test name is unchanged |

Every prior source-byte, ledger-byte, exact signature-pin, permanent-fence, release-count and holdout-consumption assertion remains in the corresponding scenario. The zero-support case still requires the exact `OpeError::UnsupportedAction` path and prevents another release.

The preceding withdrawal/corruption test function is untouched here; the recovery agent owns its separate timeout split. Root will merge the two function-local changes against the same original file.

## Validation boundary

This is a two-file test-fixture patch. It changes no product code, caller scanner, authorization, source profile, runtime timeout or qualification count. Formatting and native execution of these postimages are **UNRUN** and are assigned to the shared integration pipeline. The original cc22 failures remain recorded as failures. These mechanism fixtures do not qualify ordinary NoUpdate, ordinary Adopt or complete daemon-plus-Root cold recovery.
