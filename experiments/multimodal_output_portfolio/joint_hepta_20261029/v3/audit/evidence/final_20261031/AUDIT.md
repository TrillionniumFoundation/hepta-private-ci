# Independent final evidence audit

Result: PASS.

Retained trajectories reopened: 12800; failures retained: 0.
Maximum independent media utility absolute difference: 1.09633865764e-07 (tolerance 2e-7).

The final return is reconstructed from TRAJECTORY events plus SEAL_COST, then checked against evaluation/diagnostic rows.
Actual PNG/WAV/GIF/text files are decoded independently; source namespace/id reconstructs the registered target.

## Sections

- matrix: {"analysis_trajectories": 2304, "completed_cells": [{"arms": 8, "result_sha256": "d45276c364674c8ac4fd2c5bceff3bed49f2c3bef3fee8ddf43aa3fdc13bd6ef", "seed": 17, "width": 32}, {"arms": 8, "result_sha256": "41f683ec20df339600cbb2ce2206e53cc921029bc91401d5c7638590d7391c3e", "seed": 17, "width": 64}, {"arms": 8, "result_sha256": "2ccc26654900de17e944b2ba089d09c8235c55820a810a85e7faad1de9c17669", "seed": 29, "width": 32}, {"arms": 8, "result_sha256": "ff96641adb619083ccbb34c68e691ae70f4600cfa0f01cf89a54760b5c3d306c", "seed": 29, "width": 64}, {"arms": 8, "result_sha256": "be63b3801c1ae04fb71a8e6902f49892ccf07e3a316b863573ce6e7b8fa5a2ae", "seed": 43, "width": 32}, {"arms": 8, "result_sha256": "d9a4ede90aa8f9ae1a21d48c8d006a6b5b73a227aed61d8c4a44e8e258087faa", "seed": 43, "width": 64}], "control_trajectories": 2304, "expected_cells": [[17, 32], [17, 64], [29, 32], [29, 64], [43, 32], [43, 64]], "frozen_source_sha256": "76bad74ff6a828fcea866f5fdc45b23060b6f986053b2d09d7aa018cdf55c199", "full_matrix_present": true, "training_trajectories": 6144}
- diagnostic: {"actual_trajectories": 2048, "checkpoint_sha256": "9032b0750ea07c9ad5f9d0fb657d0ce16fd67ccacde1a653908207cbfdb542dc", "critic_only_changes_verified": true, "failures_retained": 0, "groups": 64, "raw_summary_sha256": "940042624f7392cc98096bbf60e10d39b04faa54f73fff5458e0e44e78091842"}
- text: {"base_checkpoint_sha256": "9032b0750ea07c9ad5f9d0fb657d0ce16fd67ccacde1a653908207cbfdb542dc", "fixed_predicates": {"shuffled_state": 0, "state": 0, "zero_state": 0}, "full_vocabulary_decode_independently_verified": true, "generated_tokens": 544, "lm_runtime_immutability_scope": "reported before/after tensor identity plus independently verified local source weights; training not replayed", "report_sha256": "f88b467c8e31d079fa3e95077ac264974933b7bffa39ade2670294c3b93ca51f", "rows": 12}
- native: {"automatic_external_witness_service": false, "checkpoint_sha256": "9032b0750ea07c9ad5f9d0fb657d0ce16fd67ccacde1a653908207cbfdb542dc", "final_head": "0baf7bcf067c411fb8ed5439b6b837ff265050f1475313562c1dfc78e6a1227b", "fresh_native_full_replay": true, "journal_events": 16, "original_binary_sha256": "c0bdd8732fb582347cda08e0dc23bffb63dd52231f0f82a9622472280fe54bab", "production_owner_integrated": false, "recompiled_binary_sha256": "c0bdd8732fb582347cda08e0dc23bffb63dd52231f0f82a9622472280fe54bab", "results_sha256": "2cc1bf9f89bc7c5be05e3b67ac8ed3e9820ac283ecb262d1f5bc4b16abc459c7"}

## Limits

- No claim that physical CPU/wall timings are exogenous or have a modelled direct gradient.
- Recorded counters are reconciled; external physical time measurement is not independently reconstructed.
- Training and optimizer updates are not replayed; actual final parameter groups and retained rollout identities are checked.
- Synthetic namespaces and public document module roles are disjoint; foundation-model pretraining may overlap.
- No general NDU optimum, natural four-modality qualification, human semantic rating or production-owner integration is certified.
- Native replay checks local declared profile; no automatic external witness service or hardware power-loss qualification.
