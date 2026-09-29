# objective.compiler: exact execution evidence

This is an execution-procedure supplement to `TECHNICAL.md`. Architecture,
ownership, semantic limits and recovery requirements remain in the technical
guide and implementation map. `CURRENT_STATE.json` is the canonical static
source/policy manifest; it intentionally contains no hand-maintained dynamic
pass state.

## Source authoring and qualification are separate

The normal product path remains:

```text
Agentd ObjectiveRuntimeHost
-> validated intelligence façade
-> destination-owned RunStartJournal
-> current runtime/final-use owners
```

The compiler does not own a private objective database and this closure adds no
parallel demo or qualification-only caller. Agentd freezes one
`ValidatedAdmissionProfileV1` during host open. Only static profile validation,
indexes, collision proofs and the exact profile digest/revision/compiler-contract
identity are reused. Each submission still authenticates the signed source and
rechecks source identity, scope, intent/schema/normalization binding, freshness,
deadline and selected profile. Current trust, revocation, generation, fence and
final-use authority remain live owner checks.

Source changes are committed before qualification. Exact-source workflows may
not execute migration helpers, regenerate source fixtures, update status files,
commit fixes or push a candidate. Historical source-authoring workflows and
migration outputs are not execution evidence.

## Read-only exact-head and deterministic-merge procedure

`hepta-objective-exact-execution.yml` checks out the requested complete source
SHA with read-only repository permissions and no persisted credentials. A manual
run uses its `source_commit` input for checkout and requires an explicit
`merge_base` SHA. A push run resolves `origin/main` once after checkout and
records that exact merge base before testing. It does not follow a moving branch
during execution.

The recorder `scripts/hepta-objective-qualify-exact.py` requires a clean source
and an output directory outside the repository. It creates detached source-head
and deterministic synthetic-merge worktrees. Merge conflicts are recorded as
errors, not automatically resolved. Synthetic merge objects never move a branch
ref. Source writes by tests make the candidate fail its clean-source check.

Each command records argv, working directory, start time, elapsed time, exit
code, execution status and SHA-256 of its actual combined stdout/stderr log. The
receipt includes source/merge commits and trees, fixed merge base, workflow
identity, run ID/attempt, runner image metadata and toolchain commands. The
receipt is updated atomically after each command. An interruption leaves an
incomplete report with `checksPassed: false`.

The declared native scope includes default and compatibility objective tests,
all-target compilation, focused durable journal/publication/Agentd/checkpoint
tests, real-process `objective_product_e2e`, strict package lint and format
checks. `checksPassed` becomes true only when both candidates completed every
declared check successfully with clean source.

`complete()` is a reduction over freshly recorded command results, not a
signature verifier for caller-supplied JSON. Consumers must authenticate the
workflow artifact and verify its log hashes before relying on an external copy.
Source-generated evidence cannot appoint itself an independent acceptance
authority.

Example:

```sh
python3 scripts/hepta-objective-qualify-exact.py \
  --source-commit "$(git rev-parse HEAD)" \
  --merge-base "<full-fixed-main-commit>" \
  --out "/absolute/path/outside/repository/new-evidence-directory"
```

## Target-host measurement and resources

The target-host recorder distinguishes:

- cold profile validation;
- warm request-local authenticated admission;
- native deterministic compile;
- proof-bound protocol encode and strict decode;
- maximum conflict extraction;
- signed Agentd product ingress and execution phases.

The destination-owned durable append, external checkpoint CAS and Agentd
handoff remain one atomic observable phase. The harness does not fabricate
separate completion or latency claims for internal operations that are not
independently committed.

Each ordinary, maximum-conflict and product fixture now executes below a fresh
helper process. Its receipt contains an isolated command-process-tree peak RSS,
user/system CPU time, wall time, page faults and context switches. This replaces
the previous cumulative `RUSAGE_CHILDREN` peak that could include earlier
fixtures. Internal phase latency distributions remain separate. The process-tree
peak includes the test executable and descendants and is not represented as a
per-internal-phase allocator profile.

The target receipt binds source commit/tree, workflow/run identity when
available, host profile, filesystem identity, toolchain, workload/sample counts
and the resource observations. A GitHub-hosted runner is development and
qualification evidence only. Selected deployment-host storage, crash/restart,
backpressure and resource-policy acceptance remain external gates.

## One evidence projection, no manual dynamic status

`scripts/hepta-objective-evidence-project.py` consumes:

1. the static `CURRENT_STATE.json` manifest;
2. an exact-execution receipt, a target-measurement receipt, or both;
3. the exact candidate commit and tree.

It emits `hepta.objective-evidence-projection.v2`. Dynamic source-head,
synthetic-merge and target-host-observation fields exist only in this projection.
The projector rejects source/tree mismatch, inconsistent aggregate success,
missing workload identities, missing isolated resource observations and any
static manifest that attempts to embed a dynamic pass field.

Each observed claim carries its artifact SHA-256 and available workflow/run
identity. Missing, queued, interrupted or failed execution cannot be rewritten
as passed. The checked-in manifest continues to force production implementation,
acceptance, activation and release false. Selected deployment-host acceptance,
independent review and operator approval remain unverified until their own
authorized evidence exists.

## Interpreting results

| Evidence | Meaning | Not established |
|---|---|---|
| Source and test files exist | Implementation is inspectable | Compilation or test success |
| Recorder unit tests pass | Recorder rejection, identity and projection behavior was tested | Rust module correctness |
| A workflow is queued or running | Execution was requested or started | Any final pass |
| Both exact candidates pass | Declared checks passed on the recorded identities | Full module acceptance or deployment |
| Target-host measurement observed | Bounded workloads and resources were recorded on the named host | Selected deployment-host approval |
| Independent acceptance and operator approval | Separate evidence issued by the appropriate owners | Automatic release authority |

Proof framing and durable admission-proof persistence/recovery now have source
implementations and focused regressions. Broadening Source V1 beyond its Q32
contract remains a versioned feature decision. Selected deployment-host destructive
crash/backpressure qualification and independent acceptance remain separate
work. Missing observations stay missing; source optimizations are not measured
performance results until their corresponding artifacts exist.

## V2 native-artifact measurement evidence

`hepta.objective-target-host-evidence.v2` separates `cargo test --no-run` from
resource sampling. The recorder selects exactly one libtest executable from
Cargo's compiler-artifact messages, hashes the emitted package executables,
resolves exactly one test name from `--list`, and samples a direct `--exact`
invocation. It verifies executable hashes before listing, before execution and
after execution; the receipt binds build command, source commit/tree, artifact
content identities, test list, exact invocation and output digest. No target
folder glob or caller-supplied pass flag can select an alternative binary.

Each fixture still uses a fresh resource helper. RSS means the OS-reported
waited-child high-water value, not the sum of simultaneous process RSS and not
per-phase allocation. Builds, hashing and discovery are outside that resource
sample. Phase timing remains inside the real fixture; durable append, checkpoint
and handoff remain atomic. These artifacts do not prove an unrelated FFI or a
selected deployment target. Older V1 measurements remain historical evidence,
but are not accepted by the V2 native-artifact projection. Missing binding,
source mismatch, changed artifacts, failed execution and build-in-sample output
fail closed. Selected-host policy/storage/destructive acceptance remains external.

The release source guard now recognizes the canonical V2 static manifest and
rejects manual dynamic claims or true release flags in it. This removes the
schema mismatch that blocked selected-host setup without waiving any receipt
kind, distinct-issuer check, resource policy, review, canary or release approval.
