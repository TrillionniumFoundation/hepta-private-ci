# Native research owner

This directory implements the six-action `digital-read-before-public-v1` task in
Rust. Decisions execute through the pinned Hepta `NeuronModelPort` inside the
actual `NeuronRuntime`; the owner then samples the exported finite cell and
executes a content read only when a pending request reaches its due boundary.

The deployment is a hard-sampled, 17-state finite projection. It does not claim
exact continuous-path Brownian simulation, qualified calibration, or production
activation. The runtime uses an explicitly named research worst-case calibration
placeholder and always reports `production_activation=false`, `authority=DENY_ALL`.

## Ordering and observation boundary

Every decision receives the same 36 public features, including the complete
future schedule. The four cell families add twelve features from the current
hard cell state; `raw_history` instead adds twelve completed-history features.
All five use the same 48 → 32 → 7 MLP: six action values and one learned belief
logit. No label, posterior, oracle value, pending payload, or future observation
is accepted by the native policy schema.

For `WAIT`, `READ`, or `REPAIR`, the cell consumes exactly one SplitMix64 draw
using the **pre-action** last observation. The due content operation follows that
propagation. A new completed observation can influence only the next decision.
`STOP` and both `SUBMIT` actions advance neither the task clock nor the cell RNG;
they cancel pending requests and retain all previously charged costs. The raw
history arm has no cell sampler and keeps its index-7 sentinel and RNG unchanged.

Packet paths are single basenames. The due read opens the file once with
`O_NOFOLLOW`, reads at most 32,769 bytes, checks the bound and the public digest,
validates the packet, and then calls the frozen FullHX decoder. Audit counters
separately record open attempts, successful opens, bytes read, and actual decoder
executions. Missing, malformed, changed, oversize, and symlink payloads retain
time and read fees and set `broken`; only an explicit legal `REPAIR` clears it.

## Source and dependency identity

The three inherited runtime crates are pinned by all 60 Git blob identities in
`UPSTREAM_SOURCE_IDENTITY.json`, from commit
`732e934ba496d90fbe042b8d41d479ef901643e5`. The original repository `justfile`,
`scripts/format.py`, `scripts/run-nextest.py`, and `scripts/just-shell.py` are
verified and copied without changes from PR #4509 head
`6c6f25f736df040e0d447e0242fb9819e15b3022`.

The FullHX decoder derives from that head's
`tools/hcsn/round9_20261031/native/src/content.rs`, Git blob
`3cba4036c10b908bb5ded4fc836a08c1c49355d6`. Changes instrument its file access and
decoder-call counters; the valid-packet numerical calculation is preserved.
Its original checkpoint and table identities remain validated by `content.rs`.

`build_native.py` verifies the inherited source bytes, creates a temporary
four-crate Cargo workspace, runs the original `just fmt` and `just test` entry
points, and builds an optimized executable. The included Cargo lockfile fixes
registry versions and checksums. The binary's `source_digest` binds the Rust
sources, inherited Git identities, generated workspace manifests, and lockfile.
Every snapshot additionally binds the exact public file, policy/table file,
FullHX model, controller, seed, and experiment/qualification mode.

The environment was reset before this work. The recorded build used a newly
recovered, official checksum-verified Rust 1.95.0 toolchain and real Cargo
compilation. Later offline rebuilds reuse that actual local Cargo cache. They do
not attest to any unavailable pre-reset dependency cache. The scoped temporary
workspace has a `local` nextest profile with retries disabled; unrelated product
package overrides do not apply. This is not a full-repository CI result.

## Durable state and recovery

The atomic JSON snapshot contains task state, pending source/due boundary,
last observation and history, elapsed time and charges, the finite cell index,
SplitMix64 state and draw/event counts, the last FullHX receipt, and an action
ledger. On recovery the owner replays the ledger without reopening content to
verify the task, cell/RNG, costs, and successful observations.

An external `--ack` equal to the stored snapshot digest is mandatory for every
resume. The Hepta append-only journal and separate witness must match the same
acknowledged native checkpoint and sequence. An incomplete `.pending` file,
stale frontier, mismatched identity, or missing/incorrect ACK is rejected. A
failure after a native commit poisons the in-process owner; it cannot silently
retry the action or replay a content effect.

## CLI

```sh
hepta-digital-read-before-native \
  --public public.json --content-model fullhx.json --policy policy.json \
  --controller value --snapshot owner.json --seed 818 --steps 7
```

Resume the same files and identity with `--ack <previous acknowledged_sha256>`.
`--steps 0` inspects a checkpoint, or creates an acknowledged genesis for a new
owner. Forced controls are available only with explicit `--mode qualification`
and `--forced-actions READ,WAIT,...`; there must be one supplied action for each
requested step. Unknown or illegal actions never publish a successor snapshot.
Formal experiment code rejects forced receipts.

The CLI emits one JSON object containing before/after snapshots, every receipt,
source/model identities, ACK, process CPU time and wall time. Per-action receipts
include public and representation features, learned outputs, legal mask,
selected action, cell/RNG state, actual read counters and paths, completion,
costs, and native checkpoint. `persistence_bytes` counts serialized checkpoint
payload writes and append-only journal/witness growth, including genesis. It
does not measure storage-device write amplification or filesystem metadata.
The formal runner also measures external wall/child CPU time, including process
startup and JSON serialization outside the owner's internal timer.

## Verification evidence

The scoped native gate ran 176 tests successfully, including eight new task,
RNG, legality and path tests. One inherited test is explicitly ignored by its
source: the bounded real-filesystem history measurement. Its ignored status is
reported; no test filter was added to suppress it.

`qualify.py` ran 49 actual CLI invocations using untrained development fit 90731,
which is excluded from formal fitting and confirmation. It checks all five
families and both controllers against the independent NumPy deployment path,
delayed reads, pending cancellation, charged failure and repair, malformed input,
ACK recovery and refusal cases, and public-before-content invariance. The maximum
observed learned-score difference was approximately `2.22e-16`. Raw receipts,
development fixtures, and build logs accompany the evidence manifests. These
checks validate implementation and observation boundaries; they do not establish
that any family improves task utility.
