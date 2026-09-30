# runtime.supervisor qualification suite

This directory documents the repository-controlled qualification added for the
native supervisor. It does not claim deployment, release, or independent
operator acceptance.

## 1. 256-instance head-of-line qualification

Run from `codex-rs`:

```text
cargo test -p codex-hepta-supervisor --features qualification \
  --test supervisor_hol_qualification -- --nocapture
```

The test creates exactly 256 registered Agents and records one JSON line named
`runtime_supervisor_256_instance_qualification`. It covers:

- an all-healthy fleet;
- simultaneous status readers while periodic tick executes;
- a bounded slow process driver;
- synchronized filesystem work while the global owner lock is held;
- concurrent drain, status, and tick requests;
- 10%, 50%, and 100% crash waves.

The receipt contains tick duration, status-reader p50/p95/p99/max, fault count,
and mutex acquisition/wait/hold counters. `MeasuredMutex` also emits bounded
`slow_wait` and `slow_hold` events in the production daemon and one aggregate
summary when the daemon stops.

## 2. Crash-consistency matrix

Run:

```text
cargo test -p codex-hepta-supervisor --features qualification --lib
cargo test -p codex-hepta-supervisor --features qualification \
  --test sigkill_crash_matrix -- --nocapture
```

The library matrix injects one-shot failures at the actual durable writers for:

- file write / disk-full;
- file synchronization;
- atomic rename or replacement;
- parent-directory synchronization;
- process-lease hard-link publication;
- truncated process lease, restart record, signed intent, and release transaction.

Fault injection is thread-local and compiled only for tests or the explicit
`qualification` feature. Default product builds always execute the real
filesystem operation and have no runtime fault switch.

The SIGKILL integration test starts a second process, publishes the real process
lease, restart record, release transaction, and signed intent, synchronizes a
ready marker, sends actual `SIGKILL`, then validates all four records in a fresh
process.

## 3. Authority distribution and rotation

`ProductionAuthorityBundle` is a bounded, digest-pinned public-key bundle. It
contains no signing material and cannot issue grants. The external release-policy
owner distributes it; `hepta-supervisord` consumes it through:

```text
--authority-bundle ABSOLUTE_PATH
--authority-bundle-sha256 SHA256
```

The bundle path is mutually exclusive with the legacy six verifier arguments.
Tests cover signer rotation, predecessor-epoch rejection, wrong signer identity,
expired grants, and daemon authority-epoch rollover. Fleet allow/revoke state
continues to be resolved at final use; the bundle does not transfer release
selection to the supervisor.

## 4. Actionable recovery diagnosis

Run:

```text
hepta-supervisor-recovery-diagnose RUN_ROOT \
  [--live-process-present] \
  [--observed-release RELEASE] \
  [--authority-epoch N] \
  [--admission-frontier-sha256 SHA256]
```

The read-only command emits bounded JSON blocker classes and operator actions:

- `process_ambiguity` → fence the exact process and observe exit;
- `release_state_ambiguity` → reconcile the Fleet release CAS;
- `intent_mismatch` → inspect exact intent and transaction digests;
- `frontier_drift` → refresh the current admission frontier and reject stale authority;
- `authority_epoch_change` → obtain a decision under the current epoch;
- `durability_failure` → preserve bytes and repair storage before retrying.

Exit status is `2` while recovery remains required. The command never mutates a
journal, release state, process, or authority record.

## 5. Lock-refactor decision boundary

The suite intentionally preserves the single owner lock. Synthetic slow-driver
and slow-filesystem cases prove that contention is measurable; they do not by
themselves authorize a concurrency rewrite. A collect → effect → apply or
per-Agent serialization change requires target-host receipts showing unrelated
Agents missing a documented correctness deadline or an accepted latency SLO,
plus explicit generation/Fleet-CAS ordering rules. See
`docs/modules/runtime.supervisor/HOL_REFACTOR_DECISION.md`.

## 6. Pinned authority distribution

The release-policy owner remains outside `runtime.supervisor`. It distributes only
public verifier material as an exact-digest bundle:

```text
hepta-supervisor-authority-bundle \
  --grant-verifier-key /absolute/grant.pub \
  --grant-signer-id release-policy --grant-signer-epoch 4 \
  --h7-verifier-key /absolute/h7.pub \
  --h7-signer-id h7-policy --h7-signer-epoch 9 \
  --output /absolute/runtime-supervisor-authority.json
```

The command prints the bundle SHA-256. `hepta-supervisord` then requires both
`--authority-bundle` and `--authority-bundle-sha256`. A
rotation changes the pinned key/epoch/digest tuple; predecessor, wrong-signer,
expired and stale-daemon-epoch grants reject in the authority-distribution test.
The bundle contains no signing key and does not make the supervisor a release
selector or grant issuer.
