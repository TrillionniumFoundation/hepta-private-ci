# MEM5: source-exact fixture import (candidate; no promotion)

Date: 2026-11-10 UTC. Candidate parent: `8a51d5d552bc4f4a8fc7c4af28a12ec93bf56f4a` (#5710). Frozen actor execution remains `5fa0d0e462cd1393f4f9e95565ff5993e9bad29a`, not rerun or modified. Research decision: HOLD/NoUpdate.

This proposed source-only integration imports the **five Automation fixture patches** already reviewed in [ACT-2 #5618](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5618), onto MEM5's own exact inherited source. Each patch hunk's old context matched the parent exactly once; there are no production changes, dependency/lock edits, sandbox relaxations or changes to assertions. Only temporary-directory roots in these test fixtures are canonicalized before calling the unchanged owner store. The two other fixture source files from VERIFY #5700 (`circuit_admission_tests.rs` and `circuit_store_tests.rs`) **already contain canonicalize calls in this MEM5 parent**, so are intentionally untouched. Strict `AutomationStore::open_root` remains unchanged (the production requirement for a canonical root still applies).

The original frozen-source macOS ARM and Windows shard-1 logs, preserved in #5684, report `AutomationStore::open_root: Invalid` for 12 overlapping Automation tests. The matching uncanonicalized fixture input is a concrete defect class, but those logs do **not** prove every failure has the same cause. Other failures, including Windows sandbox process write refusal and additional suites, remain separately OPEN. #5628 demonstrates a red/green macOS contrast on a different ACT-2 source, **not** on this MEM5 candidate. No test result is transferred across source identities.

## Exact parent-preimage audit

```json
{
  "schema": "hepta.mem5.exact-five-fixture-import.v1",
  "parent_commit": "8a51d5d552bc4f4a8fc7c4af28a12ec93bf56f4a",
  "source_pr": 5618,
  "unchanged_production_store_blob": "176b5c7200bea7d07d6642440d1f03c37209cef3",
  "previously_canonicalized_files": [
    {
      "path": "codex-rs/hepta-automation/src/circuit_admission_tests.rs",
      "sha": "4b3110ebb4095a28e26f30227add7de0fde470d5"
    },
    {
      "path": "codex-rs/hepta-automation/src/circuit_store_tests.rs",
      "sha": "c651287c2180cf6f916a5f7f0323158632352419"
    }
  ],
  "reused_patch_preimages": [
    {
      "path": "codex-rs/hepta-automation/src/circuit_drain_tests.rs",
      "base_blob_sha": "c63c4757cf7e61715856a974b5cd242164e10d09",
      "patch_hunks": 2,
      "match_count_for_each_hunk": 1,
      "new_bytes": 4810
    },
    {
      "path": "codex-rs/hepta-automation/src/circuit_expired_recovery_tests.rs",
      "base_blob_sha": "605dacc1fa363158204af33703e054f37ffc882d",
      "patch_hunks": 1,
      "match_count_for_each_hunk": 1,
      "new_bytes": 12679
    },
    {
      "path": "codex-rs/hepta-automation/src/circuit_learning_outbox_tests.rs",
      "base_blob_sha": "434b7e51f857291b93a6368a6d4ffd00a5a3b689",
      "patch_hunks": 1,
      "match_count_for_each_hunk": 1,
      "new_bytes": 6498
    },
    {
      "path": "codex-rs/hepta-automation/src/circuit_recovery_budget_tests.rs",
      "base_blob_sha": "6ec5515761cc071f91589697d13f68f0dc98c27d",
      "patch_hunks": 1,
      "match_count_for_each_hunk": 1,
      "new_bytes": 11266
    },
    {
      "path": "codex-rs/hepta-automation/src/circuit_task_readback_tests.rs",
      "base_blob_sha": "05067ee9a2d1a0757d2adb25afa5300ef64043ee",
      "patch_hunks": 1,
      "match_count_for_each_hunk": 1,
      "new_bytes": 3775
    }
  ]
}
```

## Acceptance limits

Patch applicability is a deterministic source-preimage check, **not** a native pass. Required same-head Automation tests, macOS and Windows Bazel, cargo-deny remediation (four advisories), Architecture aggregate and full repo CI remain OPEN. No owner authenticated cross-version transition, independent sealed confirmation, full physical cost accounting, full owner cold recovery, PR merge or production adoption is claimed. Preserve original failures and strict security checks.
