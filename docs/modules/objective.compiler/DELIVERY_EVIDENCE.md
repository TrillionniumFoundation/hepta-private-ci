# objective.compiler: exact execution evidence

This is an execution-procedure supplement to `TECHNICAL.md` and `CURRENT_STATE.json`,
not a second canonical state manifest and not a pass receipt. Detailed architecture,
ownership, semantic limits, recovery requirements and existing tests remain in place.

## Source change and qualification are separate

Ordinary source commit `ac66d55320c2b512a3b6495035972da1eb683cfa` added the opaque
proof-bound protocol encoder to the existing intelligence/Agentd publication path.
It removed duplicate native compilation while retaining strict projection validation.
The source commit also added four Rust regression tests. Neither a source commit nor
the presence of these tests establishes that they compiled or passed.

Temporary development-edit and source-archive workflows introduced while preparing this
change were retired in that commit. The temporary source-mutating artifact job has also
been removed from `hepta-objective-admission.yml`; its normal exact-source, test, lint and
format checks are retained. New qualification must not execute source migration helpers,
regenerate golden fixtures, update source status, commit fixes or push a candidate.
Historical migration scripts are not current implementation evidence.

## Read-only exact-head and deterministic-merge procedure

`hepta-objective-exact-execution.yml` checks out the requested complete source SHA with
read-only repository permissions and no persisted credentials. A manual run uses its
`source_commit` input for checkout and requires an explicit `merge_base` SHA. A push run
resolves `origin/main` once after checkout and records that exact merge base before testing.
It does not follow a moving `main` during execution.

The recorder `scripts/hepta-objective-qualify-exact.py` requires a clean source and an
output directory outside the repository. It creates detached source-head and deterministic
synthetic-merge worktrees. Merge conflicts are recorded as errors, not automatically
resolved. Synthetic merge objects never move a branch ref. Source writes by tests make
the candidate fail its clean-source check.

Each declared command records its argv, working directory, start time, elapsed time,
exit code, execution status and SHA-256 of its actual combined stdout/stderr log. The
receipt includes source/merge commits and trees, fixed merge base, workflow identity,
run ID/attempt, runner image metadata and observed toolchain commands. The receipt is
updated atomically after each command. An interruption leaves an incomplete report with
`checksPassed: false`, rather than a manually completed success statement.

The declared native scope includes default and compatibility objective tests, all-target
compilation, focused durable journal/publication/Agentd/checkpoint tests, real-process
`objective_product_e2e`, strict package lint and format checks. `checksPassed` can become
true only when both candidates completed every declared check successfully with clean
source. This scoped result does not replace existing registry/implementation-map checks,
Lane-D conformance, target-host qualification or the release guard.

`complete()` is an internal completeness reduction over freshly recorded command results,
not a signature verifier for caller-supplied JSON. Consumers must authenticate the workflow
artifact's provenance and verify the actual log hashes before relying on an external copy.
Source-generated evidence cannot appoint itself an independent acceptance authority.

Example, from an exact clean checkout with the repository's native prerequisites:

```sh
python3 scripts/hepta-objective-qualify-exact.py \
  --source-commit "$(git rev-parse HEAD)" \
  --merge-base "<full-fixed-main-commit>" \
  --out "/absolute/path/outside/repository/new-evidence-directory"
```

## Interpreting results

| Evidence | Meaning | Not established |
|---|---|---|
| Source and test files exist | Implementation is inspectable | Compilation or test success |
| Recorder unit tests pass | Recorder rejection/logging/identity behavior was tested | Rust module correctness |
| A workflow is queued or running | Execution was requested or started | Any final pass |
| Both native candidate checks pass | Only the declared checks passed on the recorded identities | Full module acceptance or deployment |
| Selected-host resource measurement | Observed workload on the named host, if executed | Independent semantic acceptance |
| Independent acceptance and operator approval | Separate evidence issued by the appropriate owners | Automatic release authority |

The recorder always leaves selected-target-host acceptance, independent acceptance,
activation and release false. These cannot be derived from local command success. A
claim of current qualification in a status paragraph must reference the exact source,
run identity, result and artifact evidence; historical green checks cannot certify a new tree.

## Remaining work, not promoted to completed state

Full generation-local validated-profile reuse, consolidation of proof framing into one
owner helper, versioned durable admission-proof persistence/recovery, and complete
migration of planned typed semantics into the product source protocol remain separate
source tasks. Current per-request raw-profile validation has not been described as cached.

Selected-host measurement must distinguish cold profile setup, warm admission, native
compile, maximum-conflict extraction, encode/decode, durable append, checkpoint sync and
Agentd handoff. Record input class, repetitions, warmup, exact binary/toolchain identity,
latency distribution and measured resource use. Missing observations stay missing; neither
this procedure nor the removal of one repeated solve is a measured performance result.

Current exact-candidate source/merge passes, crash-cut/retry/revocation validation on the
selected deployment host, independent acceptance and operator approvals still require
actual execution and evidence. Do not change canonical accepted/activated/released flags
based on this document.
