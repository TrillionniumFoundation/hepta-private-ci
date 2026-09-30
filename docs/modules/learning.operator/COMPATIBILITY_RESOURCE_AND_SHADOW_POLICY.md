# `learning.operator` compatibility, resource and shadow policy

The authoritative path is defined by `TrainingProfileV1`,
`WorldModelProfileV1`, the single-use final-use capabilities and
`coordinate_learning_operator_shadow_v1`. **Production activation remains
false.**

## Compatibility

V1 structural plans, V1 pins and V2 raw bounded fitters are qualification-only
and hidden behind the non-default `qualification-unverified-input` feature.
V3 owner receipts may enter the authoritative path, but a verified wrapper is
never a durable bearer token: ledger membership, trust, stop state and deadline
are rechecked at actual use. Unknown payload schemas fail closed.

Migration is decode old → validate old → construct a canonical profile →
re-freeze under the current owner → issue a single-use capability → fit →
independently evaluate and select → fresh-process load → shadow → rollback.
There is no implicit downgrade or fallback.

## Resource boundaries

The compatibility ceiling remains 1,000,000 samples, 262,144 tabular cells,
4,096 sensors and 128 actions, but admission additionally enforces
`OperatorResourceBudgetV1`. Before expensive allocation or sorting, the fitter
accounts for operation count and estimated resident bytes. During long loops it
checks an absolute elapsed deadline and `WorkControlV1` cancellation.

The authoritative performance gate executes sensor-core candidate sets of
1K/4K/8K/16K and tabular fits of 100K/500K/1M samples, three observations per
size, and emits p50/p95/p99. Until those measurements pass on the exact
candidate, a structural maximum is not a shipping capacity claim.

Sensor-core selection uses an exact path only up to the configured exact limit;
larger candidate sets use the bounded streaming working set. Duplicate
coordinates are rejected by canonical keys rather than quadratic pairwise
comparison.

## Mutation, coverage and evidence

The qualification job runs source mutations that remove error/runtime fields
from canonical profile identity and disable cooperative cancellation; each
mutant must be killed by a named test. It also enforces an operator-specific
line-coverage threshold, strict Clippy, formatting, exact-head tests and a
deterministic ordered-parent synthetic merge. A skipped job is not success.

The immutable receipt binds commit, tree, workflow blob and run ID, synthetic
merge commit/tree/parents, Cargo.lock, compiler target, runner fingerprint,
test-set hash, implementation-map hash and every gate log.

## Shadow-only default

The default Agentd loop performs independent future-window evaluation,
selection, fresh-process load, shadow observation, currentness/revocation
verification and exact rollback. It exposes no publish, canary or activate
method. Canary promotion, drift-based rollout and model-family expansion remain
post-qualification work; activation remains false.
