# objective.compiler exact execution and delivery evidence

**Normative execution contract:** `docs/modules/objective.compiler/NORMATIVE_EXECUTION.md`

This document defines how implementation observations are produced, retained and
interpreted. Architecture, semantic support and authority boundaries remain in
the normative contract, `TECHNICAL.md` and `SEMANTIC_SUPPORT.md`.
`CURRENT_STATE.json` contains static source/policy truth only; it intentionally
contains no hand-maintained dynamic pass state.

## 1. Evidence classes are not interchangeable

The module distinguishes:

1. source declarations and test definitions;
2. unprivileged authoring diagnostics;
3. exact source-head execution;
4. deterministic synthetic-merge execution;
5. selected target-host measurement;
6. storage durability and destructive-recovery acceptance;
7. independent semantic/security review;
8. canary, rollback, promotion and release authority.

A later class may depend on an earlier one, but no class can be inferred from a
lower class. A source file, green unit test, queued workflow, artifact upload or
measurement template is not independent acceptance or release authority.

## 2. Static source truth

`docs/modules/objective.compiler/CURRENT_STATE.json` remains fail closed:

```text
productionImplementation = false
accepted = false
activated = false
released = false
```

`scripts/hepta-objective-current-state.py` projects that static truth into the
implementation map and generated document blocks. Dynamic fields such as
source-head qualification, synthetic-merge qualification and target-host
measurement are forbidden in the checked-in manifest and exist only in an
artifact-bound evidence projection.

## 3. Authoring and qualification are separate

Normal authoring commits source and documentation before execution. The
unprivileged authoring workflow may:

- regenerate the objective implementation map;
- synchronize static source-state blocks;
- run normative consistency tests;
- compile and test Rust packages;
- run strict default and compatibility Clippy;
- retain a bounded source archive, generated patch and logs.

It has read-only repository permission and no persisted credential. Its generated
map and logs are diagnostics for the next source commit. It does not modify the
branch, qualify the candidate or issue a release receipt.

Source qualification workflows may not regenerate source fixtures, patch status
files, commit repairs or push a candidate. Any source repair creates a new commit
and invalidates earlier execution evidence for the changed head.

## 4. Exact source and deterministic merge recorder

`.github/workflows/hepta-objective-exact-execution.yml` checks out one complete
source SHA and fixes one complete merge-base SHA. The recorder
`scripts/hepta-objective-qualify-exact.py` requires a clean source checkout and an
output directory outside the repository. It creates detached worktrees for:

```text
source-head
synthetic-merge(base, source)
```

The synthetic merge is generated deterministically with a fixed commit identity.
Merge conflicts are errors and are never auto-resolved, filtered or patched. No
branch ref is moved.

Both candidates execute the same declared inventory:

- exact implementation-map verification with candidate commit/tree;
- static current-state verification;
- normative execution consistency;
- fail-closed release-source truth;
- toolchain capture and formatting;
- all-target product-package compilation;
- default objective tests;
- `qualification-legacy-compile` tests;
- durable RunStart/proof/recovery tests;
- intelligence publication tests;
- Agentd admission/checkpoint/product E2E tests;
- strict owned-package Clippy;
- strict compatibility-feature Clippy;
- clean-source verification.

Every command records its name, exact argv, working directory, start time,
elapsed time, status, integer exit code and SHA-256 of actual combined
stdout/stderr. The receipt is atomically updated after each command. An
interruption retains an incomplete receipt with `checksPassed=false`.

`complete()` is a reduction over freshly observed command records. It does not
authenticate arbitrary caller-supplied JSON. Missing, duplicate, failed,
timed-out, unavailable or log-drifted commands cannot pass.

## 5. Trusted verifier separation

Candidate-owned code may execute tests and produce raw evidence only on an
unprivileged GitHub-hosted runner or an externally provisioned ephemeral target
runner. Protected decisions use a separate trusted-control checkout from
protected `main`:

```text
trusted-control checkout at immutable workflow SHA
+ separate candidate checkout/data workspace
+ digest-bound raw logs/artifacts
-> trusted parser/projector/release verifier
```

A protected workflow must not execute a release verifier imported from the
candidate workspace. Candidate and trusted-control workspaces must be distinct and
clean, and their complete commits/trees are retained in the output.

A development push may produce an untrusted exact-execution artifact. A trusted
qualification claim requires the protected-main workflow definition and trusted
verification path. This distinction is explicit in retained envelopes; a raw
artifact is never silently relabelled as trusted.

## 6. Evidence projection

`scripts/hepta-objective-evidence-project.py` consumes:

1. exact candidate commit and tree;
2. static `CURRENT_STATE.json`;
3. an exact-execution receipt, target-measurement receipt or both;
4. retained artifacts and their actual content digests.

It emits `hepta.objective-evidence-projection.v2`. The projector rejects:

- source or tree mismatch;
- incorrect deterministic merge identity;
- missing or duplicate declared commands;
- changed argv;
- Boolean values masquerading as integer exit codes;
- missing, changed or symlinked retained logs;
- inconsistent aggregate pass state;
- absent workload or artifact identities;
- attempted promotion of production, acceptance, activation or release truth.

Every observed claim carries its artifact SHA-256 and available workflow run,
attempt and trusted-control identity. Missing observations remain missing.

## 7. Target-host measurement V2

The target-host recorder distinguishes:

- cold validated-profile construction;
- warm request-local authenticated admission;
- deterministic native compile;
- proof-bearing protocol encode/decode;
- maximum conflict extraction;
- signed Agentd product ingress;
- destination append, checkpoint CAS and handoff as one observable atomic phase;
- physical execution only where explicitly enrolled.

Build, discovery and hashing occur outside fixture resource sampling. Cargo JSON
compiler-artifact messages identify the exact executable. The recorder hashes
emitted artifacts, resolves exactly one test name from `--list`, invokes it
through direct `--exact` execution, and verifies executable hashes before listing,
before execution and after execution. Missing, ambiguous, symlinked or changed
artifacts fail closed.

Each fixture runs under a fresh helper process. Resource evidence includes the
OS-reported waited-child peak RSS, user/system CPU, wall time, page faults and
context switches. Peak RSS is not represented as simultaneous process-tree sum or
an internal allocation profile.

## 8. Ephemeral selected-host boundary

The selected-host workflow routes candidate execution only to a runner carrying
all of:

```text
self-hosted
objective-target-host
ephemeral
```

The candidate job receives read-only repository permission, no persisted
credential and job-local Cargo home/target directories. It uploads raw observations
and removes the candidate workspace and job-local caches. A separate
GitHub-hosted trusted-control job downloads, verifies and projects the raw
measurement.

The label set is a routing precondition, not proof that the runner was actually
created for one job or destroyed afterwards. The host infrastructure authority
must issue an independent lifecycle/host attestation before selected-host
acceptance. Persistent shared runners, shared writable caches or reusable
credentials cannot satisfy this gate.

## 9. Provenance and artifact integrity

Retained bundles bind:

- candidate commit and tree;
- fixed merge base and deterministic merge commit/tree;
- trusted workflow commit/tree where applicable;
- workflow run and attempt;
- runner image/profile identity;
- toolchain commands;
- command inventory and log digests;
- native executable and test identity;
- evidence bundle digest.

Protected-main verification may create a GitHub build-provenance attestation for a
verified manifest or bundle digest. Such attestation proves the workflow produced
those bytes under the recorded identity; it does not establish semantic
acceptance, target-host suitability, canary success or release authority.

Unsigned templates remain templates. An external acceptance receipt is valid only
when its exact candidate, policy, dependency chain, issuer independence and
required provenance fields are verified by the protected release gate.

## 10. Storage qualification is separate

Ordinary append/reopen tests and target-host latency do not establish storage
acceptance. The selected storage authority must separately exercise and retain
receipts for:

- segment rotation under the writer lease;
- concurrent writer rejection at every rotation cut;
- external checkpoint acknowledgement loss;
- missing checkpoint with existing local history;
- checkpoint rollback and checkpoint-ahead-of-local state;
- torn active tail;
- removed or rewritten sealed segment;
- compaction crash cuts before and after checkpoint advance;
- storage-full and sync failure;
- long-running capacity/backpressure;
- recovery without duplicate physical execution.

The resulting storage qualification digest is an input to, not a consequence of,
target-host measurement.

## 11. Interpreting common observations

| Observation | Established | Not established |
|---|---|---|
| Source/test files exist | implementation is inspectable | compilation or test success |
| Recorder unit tests pass | recorder rejection and identity behavior | Rust module correctness |
| Workflow queued/running | execution requested/started | final pass |
| Authoring workflow passes | source compiles/tests in unprivileged development scope | trusted qualification |
| Exact source and merge pass | declared commands passed on recorded identities | selected-host or independent acceptance |
| Target measurement observed | bounded workload/resource facts on named host | resource/storage approval |
| GitHub provenance attestation exists | recorded workflow produced exact bytes | semantic correctness or release approval |
| Independent receipts complete | named external gate was issued | automatic promotion unless dependencies also complete |

## 12. Historical evidence

All observations created before the final convergence candidate remain historical
and retain their original source/tree, workflow and artifact identity. They are
useful for regression comparison but cannot qualify a later source head.

In particular, the focused September 29 objective runs belong only to their
recorded candidates. The September 30 proof/preflight/publication refactor and all
subsequent normative, workflow or source changes require new exact-source and
synthetic-merge execution. PR descriptions and closeout documents must not present
an older artifact as current-head success.

## 13. Release order and authority

The protected release gate evaluates the dependency-ordered receipts declared by
`RELEASE_POLICY.json`:

```text
exact source head
-> deterministic synthetic merge
-> selected target-host measurement
-> storage durability acceptance
-> independent semantic/security review
-> canary
-> rollback authority
-> promotion
-> release authority
```

Required independent issuers remain distinct. Source authors and CI jobs cannot
self-issue external review, canary, rollback, promotion or release authority.

Until all required receipts bind the same immutable candidate and policy, the
checked-in source truth remains false for production implementation, acceptance,
activation and release.
