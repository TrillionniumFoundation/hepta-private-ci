{
  "format": "hepta-trusted-material-codec-source-review-v1",
  "reviewed_at_utc": "2026-11-13T04:02:30.073073+00:00",
  "source_commit": "cc57c7198db6293ccca562253c42fffbe2a04633",
  "status": "STATIC_ORIGINAL_SOURCE_REVIEW_ONLY",
  "inputs": [
    {
      "file": "scope.rs",
      "bytes": 5176,
      "sha256": "51281b59b332c472acb4a7fbe91d71d784ee164386ef4bd6e58fb89eab6c5e71",
      "git_blob": "a702abce92903e1c8e4c411baff1fa82ad8bcdf4",
      "actual_full_git_read_preceded_review": true
    },
    {
      "file": "material_owner.rs",
      "bytes": 20959,
      "sha256": "3acf8e3a56434b003fe68498f67ac1c93daaa98bfd23c5dc624736b8e2372e53",
      "git_blob": "be5a1bd1507c93b8ef62f83fba4baf3770738ca7",
      "actual_full_git_read_preceded_review": true
    },
    {
      "file": "material_binding.rs",
      "bytes": 14603,
      "sha256": "5488c7371b1813caabb4ca547cb122299bc663ca76a04e404fa68c691b404216",
      "git_blob": "c9c80876c1d5e8c589bbf1663a67f36c87f1937b",
      "actual_full_git_read_preceded_review": true
    },
    {
      "file": "material_wire.rs",
      "bytes": 12812,
      "sha256": "99097cce640dac0c0680fc475fc4effce380c21f8db65f267f115bfb00dc9bb3",
      "git_blob": "2319720bc255c2a12ab551092bb944b5a95f917f",
      "actual_full_git_read_preceded_review": true
    },
    {
      "file": "learning_checkpoint.rs",
      "bytes": 15797,
      "sha256": "6642ca9169cca03becbbe925edcdbf31c435ca937010d76b808979048ffeac0f",
      "git_blob": "ee8aeb1f072c7b8b44cee69ccf4622e87ce9ce90",
      "actual_full_git_read_preceded_review": true
    },
    {
      "file": "learning_checkpoint_codec.rs",
      "bytes": 20018,
      "sha256": "f2d003729bfdfd85cc1cb42841d0161b5f7df0a6a76221c05e912ef1dc3a70ac",
      "git_blob": "9564a0973714028d37484d84d3a8a1cab6e372b4",
      "actual_full_git_read_preceded_review": true
    },
    {
      "file": "signed_evidence.rs",
      "bytes": 15660,
      "sha256": "6b8f65d3324cd4531c0a5f94ac321068b4a2661132944472b8176838b335590a",
      "git_blob": "214cae5c9fc4e60598a572faeca5d92c87b0be7f",
      "actual_full_git_read_preceded_review": true
    }
  ],
  "checkpoint_codec": {
    "pure_entrypoints": [
      "encode_original_owner_snapshot_v1",
      "decode_original_owner_snapshot_v1"
    ],
    "opens_or_mutates_root_checkpoint": false,
    "maximum_bytes": 8192,
    "maximum_receipts": 7,
    "maximum_id_bytes": 128,
    "request_fields": [
      "operation_id",
      "principal_id",
      "agent_id",
      "cell_id",
      "source_run_id",
      "completed_task_receipt",
      "selected_artifact_digest",
      "evaluation_profile",
      "selected_bundle",
      "envelope",
      "budget"
    ],
    "owner_fields": [
      "evidence_trust_digest",
      "experience",
      "dataset",
      "trainer",
      "evaluator",
      "proposal",
      "selector",
      "next_use_observer"
    ],
    "other_data": [
      "complete selected bundle component digests, adapters, generation, rollback predecessor and training lineage",
      "complete envelope and budget",
      "receipt observations and original head digest"
    ],
    "decode_checks": [
      "original version discriminator; no upgrade of omitted evaluation profile",
      "original byte/count/string bounds",
      "no unconsumed trailing bytes",
      "original LearningIterationCoordinatorV1::from_snapshot validation",
      "outer canonical re-encoding must exactly equal input bytes"
    ],
    "authority_claim": "Pure complete snapshot integrity encoding; neither retained signatures nor original owner authority is created by decoding."
  },
  "scope": {
    "constructor": "FrozenLearningScopeV2::freeze(original request, original owners, original scope kind, original update-rule digest)",
    "binds": [
      "initial full request/owner digest",
      "original component boundary",
      "scope tag",
      "original update-rule digest"
    ],
    "rejects": [
      "BaseRelease in this medium-cadence owner",
      "zero update rule",
      "request/owner mismatch",
      "later candidate scope or update-rule change"
    ],
    "required_input": "Original trusted constructor inputs; original binding alone cannot reconstruct or grant scope."
  },
  "verifier": {
    "constructor": "LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1)",
    "trusted_inputs": [
      "scope_digest",
      "objective_digest",
      "authority_epoch",
      "all original principal and credential-chain fields",
      "controller_id",
      "verifying_key",
      "roles",
      "revoked_at"
    ],
    "canonical_digest_includes": [
      "scope/objective/epoch",
      "ordered full signer set",
      "credential chain",
      "controller",
      "verifying key",
      "authentication/expiration times",
      "roles",
      "revocation state"
    ],
    "checks": [
      "nonempty bounded trust and epoch/scope/objective",
      "complete principal scope/epoch/key consistency",
      "valid non-weak keys",
      "no duplicate roles or principal IDs",
      "complete supplied signer equality before enrollment readback",
      "original validity/revocation/role/context/payload/signature for each returned evidence"
    ],
    "cannot_be_chosen_by_remote_evidence": true,
    "same_key_versus_independence": "Controller collision is checked in signed actor separation; key difference alone does not establish all task-source/training-lineage/operator independence required by the evaluation contract."
  },
  "material_config": {
    "complete_inputs": [
      "initial snapshot",
      "frozen scope",
      "dataset rule",
      "freeze plan",
      "original signed freeze evidence",
      "two full original observer signer bindings",
      "trusted verifier",
      "maximum signature lifetime"
    ],
    "original_binding_includes_exact_freeze_signing_bytes_and_signature": true,
    "resigning_or_renewing_freeze_is_not_identity_preserving": true,
    "sources_require_exclusive_original_mutable_ledger_borrow": true,
    "recover_does_not_create_missing_owner_or_enable_fresh_commands": true
  },
  "integration_requirements": [
    "Retain a trusted host-owned trust clone at original fixture construction before consuming it into the verifier. Root keeps its own preexisting verifier; never let a child report select the Root trust state.",
    "Use the original 8192-byte canonical snapshot codec; bounded test control may carry original constructor data, not a new authorization grant.",
    "Reconstruct scope only from original trusted request/owners/rule/scope and require the same binding. Retain the exact original freeze and signer state.",
    "Serialize full typed trusted inputs through the child-control fixture only as needed; do not add serde or raw reconstruction accessors to production authority types merely to ease tests.",
    "Maintain the original exclusive LedgerWriter owner. Transfer/open only according to its original ownership lifecycle; do not open a second writer or substitute a read-only fake.",
    "Current material readback, independent B, full costs/hard gates, actual same-C execution and Root/daemon cold recovery still require actual original owner observations."
  ],
  "execution": {
    "formatter": false,
    "compiler": false,
    "tests": false,
    "H": false,
    "source_ref_update": false
  },
  "qualification": false,
  "real_qualified_task_chains": 0
}
