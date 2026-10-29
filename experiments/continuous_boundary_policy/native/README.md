# Original NDU score host for continuous policy controls

This research-only executable evaluates three caller-supplied Q24 action scores
with the original `codex-hepta-ndu` evaluator from commit
`5898cd8b0f724c3152b6cc52856721f72e5e08be`. It never calls the sparse neuron
kernel and grants no production authority. Neural inference occurs in Python;
its model, observation, state, and resulting scores require independent replay.
The host binds those declared inputs to an actual native NDU evaluation receipt.

## Build

Reuse the verified isolated native workspace produced by the preceding study:

```sh
python -m experiments.continuous_boundary_policy.native.build \
  --repository /path/to/repository \
  --native-build /path/to/original/native-build \
  --output-dir /path/to/new/score-build-receipt
```

The helper verifies original crate bytes, generated manifests, lockfile identities,
vendor file checksums, and compiler identity before using the existing cache.
It adds a separate `boundary_policy_score_host` example and checks the original
`continuous_host` executable remains unchanged. Original study source, build
receipts, and evidence are not overwritten. The new output directory must not
already exist. Each build receives a separate source manifest and build receipt.

## Python API

```python
from experiments.continuous_boundary_policy.native.bridge import ScoreBridge

bridge = ScoreBridge(binary, root, expected_binary_sha256=binary_hash)
try:
    result = bridge.decide_batch(rows)
    receipts = result["rows"]
finally:
    cost = bridge.close()
```

Each row has exactly `row_id`, `model_sha256`, `objective_sha256`,
`observation_sha256`, `state_sha256`, and `scores_q24`. All digests are nonzero,
64-character lowercase SHA256 strings. Scores are integer `[keep, repair, stop]`
values in `[-8 * 2**24, 8 * 2**24]`; stop must be exactly zero.

The NDU receives one maximizing task-value axis, with exact Q24-to-Q32 conversion.
Its tied frontier is resolved in the registered order **stop, repair, keep**.
Stop is internally named `abstain`, matching the existing task evaluator.
The host accepts at most 4,096 rows per batch and 16 MiB per request line;
unknown fields, duplicate batch row IDs, and invalid domains are rejected before
any candidate evaluation. Identity and Shutdown also reject extra fields.

Each receipt includes the row, action, tie/frontier, native evaluation digest,
executable hash, `actual_ndu_calls=1`, `actual_kernel_calls=0`,
`owner_authority="DENY_ALL"`, `durable_owner_execution=false`, and
`model_inference_executed=false`. Support and receipt SHA256 bindings use sorted,
compact JSON with integer values. The receipt hash excludes only itself.
The bridge independently checks input echoes and both hash bindings.

The transport measures request/response bytes and round-trip time. On closing,
POSIX `wait4` returns exact CPU usage for this host process; no subtraction of
unrelated child counters is used. This accounting bridge currently requires a
POSIX research host. These costs do not constitute hardware energy measurements.

## Focused validation

```sh
python -m experiments.continuous_boundary_policy.native.test_native \
  --binary /path/to/boundary_policy_score_host \
  --output-dir /path/to/new/score-test-evidence
```

The tests execute the original evaluator for extrema and all tie forms, verify
that each changed score/provenance binding changes native and receipt digests,
reject malformed whole batches, verify exact replay in a fresh process, and
check recovery after an oversized native line. Build and validation receipts are
retained under `preflight/`. No `cargo test` is required for this example.
