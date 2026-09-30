# `learning.operator` compatibility, resource and shadow policy

The default admission path uses `TrainingProfileV1`, `WorldModelProfileV1` and
single-use final-use capabilities. The generic Agentd coordinator is implemented;
real owner ports and its default runtime caller remain integration work.
**Production activation remains false.**

## Compatibility

Raw structural fitters, caller-authored V2 verification inputs and direct V3
verify/fit functions are hidden behind the non-default
`qualification-unverified-input` feature and grouped in `compatibility`.
Existing V1 payload pins and immutable read-only predictors remain in the
explicit default allowlist for named owner-bound adapters. They establish
payload identity, not current selection, authorization or deployment acceptance.

A V3 owner receipt can enter the default capability path, but verified wrappers
are not durable bearer tokens. Current ledger membership, signer trust, stop
state and deadline are checked at actual use. Unknown payload schemas reject.

Migration is decode old → validate old → construct a canonical profile →
re-freeze under the current owner → issue a single-use capability → fit →
independently evaluate and select → persist create-only → fresh-process load →
shadow → exact predecessor rollback. There is no implicit downgrade.

Native V2 digest commitments bind complete source inputs and minimum-support
policy. Existing correctly pinned `HEPTTB01` bytes remain readable subject to
current owner admission. Native structs are separate from canonical-JSON
protocols; canonical wire adapters and round-trip tests remain work.

## Resource boundaries

Compatibility ceilings are 1,000,000 samples, 262,144 tabular cells, 4,096 sensors
and 128 actions. Owner-authenticated admission has its own 4,096 signed-row bound,
including the complete-grid minimum-support constraint. `OperatorResourceBudgetV1`
meters operations and estimated resident bytes before expensive work. Long loops
check elapsed deadlines and shared `WorkControlV1` cancellation; worker threads
must explicitly install the same fit context and token.

The regression matrix measures sensor designs of 1K/4K/8K/16K candidates and
fits of 100K/500K/1M compatibility rows. Two warm-ups and seven measured
observations per size report median/p90/max/MAD as a regression profile. They
do not estimate p95/p99 or target-host tails. The explicit nextest performance
profile has a ten-minute harness watchdog, which is not a product latency SLO.
Shipping capacity requires a fixed accepted host, warm-up, adequate sample size,
cold/warm separation and actual RSS/cgroup or allocator evidence. Structural
maxima and GitHub-hosted measurements do not supply that acceptance.

Above the configured exact sensor limit, deterministic fingerprint-stratified
reduction selects a bounded working set before exact farthest-point selection.
Canonical coordinate keys reject duplicates. Finite-design geometry receipts do
not prove continuous-domain coverage or universal geometric optimality.

## Mutation, coverage and evidence

Qualification executes named mutations of profile identity, cancellation and
final-use time fences. Each mutant must be killed by an executable test. Coverage,
strict lint, formatting, exact-source tests and an ordered-parent deterministic
merge have separate receipts. Failed, missing, cancelled or not-run required
stages prevent merge readiness; different attempts cannot be combined.

The manifest binds source SHA/tree, workflow/run attempt, synthetic merge and
ordered parents, lockfile, target, runner/toolchain, test set, implementation map
and evidence logs. Repository evidence keeps production qualification false.

## Shadow coordinator and current use

The coordinator contract sequences independent future-window evaluation,
selection, persistence, fresh-process loading, shadow observation, currentness and
exact rollback. Fixture ports currently test this state machine. Component E2E
separately exercises signed owners and the ranker; it does not close the missing
real-port coordinator integration.

An immutable `LoadedTabularOperatorV2` validates bytes and its complete pin once.
A selected wrapper also enforces its selection time window. Neither static value
can observe later registry movement, source withdrawal, trust rotation or stop
changes by itself. The host must refresh the actual owner witnesses at each final
use; the evaluated Agentd ranker checks its configured currentness providers.
The coordinator has no publish, canary or activation port. Promotion and model
family expansion require separate evidence; activation remains false.
