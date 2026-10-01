# intuition.policy: resource-bounded exact execution and merge acceptance

<!-- intuition-source-state:begin -->
## Canonical source-state projection

Source: `docs/modules/intuition.policy/CURRENT_STATE.json`; content SHA-256: `67a6ddb0dd58e6e6a1fcbb2ce184f3e35d0a7d725df586c28dce12d9005995ce`.

These are inspected source facts, not compilation, runtime, independent acceptance or release receipts.
All four production completion predicates remain false. Current execution identity belongs only to immutable command artifacts.

| Requirement | Source state | Scope |
| --- | --- | --- |
| `native_policy` | `source_present` | Explicit native profile risk routing and 1..128 candidate preflight before commitment hashing; historical encoding preserves prior receipt digests. |
| `authenticated_roles` | `source_present` | Generator, evaluator and observer signatures; pairwise verified controller separation. |
| `host_commit` | `source_present` | At most 127 product candidates plus abstain; complete pins, fresh owner clock and retained three-party/root-signed trust-lease revalidation under sole LedgerWriter lock. |
| `admission_receipt` | `source_partial` | Canonical final use rechecks seven owners, RunStart authentication and deadlines; selected runs retain evaluation proofs; launch and lifecycle generations remain distinct; Compiled retries require reconciliation, while stored compiler ExplicitAbstain can replay without provider/policy/run/context; outward V1 is unchanged. |
| `authority_read` | `source_present` | Owner files use bounded checked-handle reads; full fences and evaluator-session construction bind one immutable authenticated seven-owner manifest to the request snapshot; live stages still reread current input. |
| `startup_profile` | `source_present` | Strict typed profile resolved at AgentdState startup, included in configuration identity and enforced before compatibility returns. |
| `telemetry` | `source_partial` | Existing Codex metrics and tracing with bounded static reason codes; no deployed audit/exporter acceptance. |
| `source_qualification` | `source_present` | Read-only qualification workflows; source/merge/independent lanes validate source-state and all plans retain final-use and trust-distribution tests. |
| `source_projection` | `source_present` | Canonical source state generates document blocks, implementation-map projection and contract/requirement traceability. |

Remaining closure requirements:

- **durable_handoff**: For Compiled canonical requests, persist exact authenticated request, policy/evaluation material and prepare/commit/run/context/delivery progress through Agentd; idempotent replay must reconcile original intent and known receipts without rebuilding provider inputs or automatic redispatch. Stored compiler-terminal ExplicitAbstain has no policy handoff. Tracing and in-process receipts are not a durable journal.
- **transport_receipt**: Introduce and migrate a versioned outward admission/acknowledgement contract that binds the policy receipt; do not silently redefine ObjectiveRunAdmission V1.
- **generation_recovery**: Implement and execute restart reconciliation, current-authority revalidation, monotonic generation fences and process-kill/concurrent/disk/corruption cases.
- **typed_domains**: Complete distinct sequence, wall-clock, assignment-counter and generation types at all owner boundaries without changing historical wire meanings.
- **legacy_consumers**: Migrate and qualify remaining V1/V2 advisory consumers; native V4 routing does not itself retire them.
- **exact_execution**: Obtain complete real source-head, deterministic merge, independent and ledger passes and current artifact agreement; a source-authoring or portability run is insufficient.
- **operator_acceptance**: Exercise real identity/entitlement, audit/exporter delivery, combined request p50/p95/p99/capacity/witness lag and backup/restore/rotation/rollout/rollback; obtain external evaluator and operator approval.

Version and requirement-to-test/artifact mappings: `docs/modules/intuition.policy/CONTRACTS.md`.
<!-- intuition-source-state:end -->


This supplements `TECHNICAL.md` and `OPERATIONS.md`; it does not replace their
runtime, trust, ledger or recovery contracts. A source change is not an execution
receipt. The commands below require a clean, complete checkout and the repository
Rust toolchain. Local Python fixture tests are not Rust or target-host acceptance.

## Resource failure remediation

The historical selected-only writer job failed while writing a Rust incremental
query cache with `No space left on device (os error 28)`. That failure is not a
passed writer test and does not establish a policy assertion failure. Both
intuition workflows now disable incremental compilation and development/test/
release debug information, bound Cargo compilation to two jobs, and use a fresh
external target directory. No system directory, source file, test, or ledger is
deleted to obtain disk space. Whether this is sufficient for a particular runner
is determined by its new execution, not inferred from the configuration change.

`scripts/intuition_ci_exact.py` invokes the existing exact qualifier or ledger
qualifier, records target-filesystem capacity before and after execution, and
retains the original command/exit/log information. Timeout, missing executable,
interruption and compiler ENOSPC remain failures (`infrastructure_invalid`), not
successful tests. Assertion and other compilation failures remain separately
classified. Filesystem snapshots are not a product capacity measurement.

```bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
export CARGO_TARGET_DIR="$(mktemp -d)"
evidence_parent="$(mktemp -d)"
python3 scripts/intuition_ci_exact.py \
  --source-commit "$(git rev-parse HEAD)" \
  --evidence "$evidence_parent/source"
```

The original `python3 scripts/intuition_qualify_exact.py --source-commit ...`
entry point remains available. CI uses the resource-bounded entry point because
aggregate acceptance also requires its Git-object, runner and binary evidence.
Local users must not invent `GITHUB_*` variables to imitate a CI run.

## Receipt identity and retained files

Each enriched command record binds the actual source/base/tested commit, tested
tree, exact serialized Git commit object and ordered parents; workflow SHA/ref;
repository, run, attempt and job; runner OS/architecture/image; toolchain log;
Cargo.lock digest; build environment; command arguments, working directories,
exit codes, timings and log digests. Existing exact qualifiers still test an
unchanged checkout and reject stale or in-tree evidence directories.

Cargo's release-binary JSON messages identify the actual executables. The
collector only accepts regular executables inside the isolated Cargo target
directory, copies their bytes into the artifact bundle, and checks their digests
against the compiler record. An executable outside that directory, a duplicate
name or a binary changed after compilation rejects collection. A digest string
without a retained binary is insufficient for aggregate acceptance.

The bundle manifest is sealed after all generated projections and binaries are
written. There is no self-referential record/manifest hash cycle. On successful
collection, `CURRENT_STATE.json` supplies the execution status; the implementation
map, technical-status fragment and dossier are generated alongside the command
record. The aggregate produces a new canonical state binding its input manifests.
These files live in Actions artifacts outside the checkout; a qualification job
never rewrites tracked documentation or pushes a new candidate commit.

## Source, independent and merge verification

The existing independent mode runs in a distinct job with its own checkout and
target directory. The aggregate downloads named artifacts from the same workflow
run only. It verifies the prescribed ordered commands, actual nonzero test output,
all file hashes, source/tree/lock identity and distinct job identity. It additionally
checks the serialized Git object against the tested SHA and tree, workflow and
runner metadata, generated state, and retained release-binary bytes.

For pull requests, the aggregate must also download the synthetic-merge artifact.
It independently recomputes `git merge-tree --write-tree BASE_SHA SOURCE_SHA`
without switching the source checkout. The reported merge object must contain
exactly the pinned source and base parents, and its tree must equal that recomputed
tree. Missing merge evidence, a stale base, wrong parents, substituted tree or
changed run attempt rejects agreement. A source-only push can receive source-only
agreement, but its `mergeTreeVerified` remains false and cannot replace PR merge
qualification.

Source-authoring workflows and encoded source transports are removed from this
candidate. Retained historical autoformat/source-apply/serving-compose stubs are
manual-only, read-only and reject execution; their old implementations remain in
Git history. Source edits are ordinary reviewed commits followed by new immutable
qualification runs. The full and independent command plans both run the read-only
source-state projection check. Final-use races execute through the existing
mandatory `intuition_policy_commit_boundary` target; no absent test target is
substituted for that evidence.

## Release gates deliberately not minted by CI

Independent execution is not an independent semantic evaluator signature. A
compiled and retained release binary is not a running-product E2E or deployment
receipt. The four production completion predicates remain false until separately
required runtime/failure, evaluator, target-host and release evidence is admitted.
No workflow approves itself or marks the PR ready merely because fixtures pass.

The remaining operator gates in `OPERATIONS.md` still apply: real entitlement
and identity-authority deployment; mandatory operational audit delivery; actual
Prometheus/OpenTelemetry exporter wiring and exercised alerts; process-kill,
concurrent/disk/corruption/replay recovery on the selected host; combined
request-path p50/p95/p99 and capacity; and witnessed backup/restore, rotation,
rollout and rollback. The existing durable-ledger benchmark must never be renamed
as the combined Agentd request baseline. This change does not certify those gates.

## Regression entry point

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s scripts/tests -p 'test_intuition*.py' -v
```

Regression cases include forged Git objects, wrong merge base/parents/tree,
missing or changed release bytes, stale generated state, duplicate JSON keys,
symlinks, boolean exit-code substitution, incorrect workflow/image identity,
ENOSPC versus assertion classification and mandatory-merge omission. Test bundles
are explicitly synthetic and cannot authorize production.
