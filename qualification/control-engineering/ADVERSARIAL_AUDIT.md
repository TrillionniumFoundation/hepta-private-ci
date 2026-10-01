# control.engineering adversarial audit

This is a repository engineering report, not an acceptance receipt. The retained
local execution summary is [ADVERSARIAL_AUDIT_LOCAL.json](ADVERSARIAL_AUDIT_LOCAL.json).
Historical hosted evidence is retained in [HOSTED_EVIDENCE_C2837627.json](HOSTED_EVIDENCE_C2837627.json). Current hosted execution belongs to the exact head of
[PR #1175](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1175).
Results from an earlier head must not qualify a later candidate.

## Scope and evidence

The audit reviewed the SQLite v10 owner, public product composition and CLI,
orchestration and worker lifecycle, candidate isolation, mutation evaluation,
integration queues, external evidence, key rotation, readiness manifests,
qualification tooling, exact source mappings and the current development guides.
Independent reviews covered durability, sandbox boundaries, evidence admission,
qualification, architecture/documentation and orchestration. Follow-up reviews
reproduced additional defects after the first fixes; those defects received
behavioral regressions before the final source mapping was refreshed.

Integration provenance includes the main baseline `a126987`, the existing
bounded-owner candidate `f920179`, and readiness convergence source `3686369`.
Their source and commit ancestry are retained. Historical failed CI or author
assertions are not reused as successful execution evidence.

## Documentation and completion assessment

Detailed technical development documentation **exists**. The relevant companions
are `TECHNICAL.md`, `IMPLEMENTATION.md`, `OPERATIONS.md`,
`SANDBOX_SECURITY.md`, `BOUNDED_OWNER_CONTRACT.md`,
`IMPLEMENTATION_BINDING.md`, `EXTERNAL_ACCEPTANCE.md` and their generated
status/API/source maps under `docs/modules/control.engineering/`.
They describe ownership, public interfaces, persistence, recovery, resource
limits, sandbox admission, evidence, key rotation and deployment prerequisites.
The audit corrected contradictions rather than creating a parallel specification.

| Dimension | Evidence-backed state | Remaining completion boundary |
| --- | --- | --- |
| Development documentation | Detailed guides and generated contract/API/source navigation exist | Keep them tied to exact source and real execution |
| Bounded coordination owner | SQLite v10 persistence, signed admission, deterministic planning, leases, claims, queues and startup reconciliation implemented | Exact final source/merge CI must pass |
| Repository product composition | Named Python product and real CLI/lifecycle integration tests exist | Repository fixtures do not establish deployed product adoption |
| Candidate qualification | Bounded Git, evaluator-owned mutation checks and strong-sandbox lanes implemented | Strong execution requires a capable host and exact-candidate receipts |
| Whole-project integration | Engineering-plane coordinator depending on `kernel.evidence`; owner of assignment/integration projections | Registered adaptive iteration/golden-fixture targets and native Agentd consumption are not established by this Python owner |
| Production deployment | Typed external provider and deployment/recovery/rollback/operator verification ports exist | Live fence, immutable external audit, HSM/KMS custody, independent semantic review and target/operator receipts remain externally supplied |

An overall completion percentage would conflate implemented source with deployment
acceptance. The module has a substantial implemented coordination owner, while
product adoption and production acceptance remain separate unfinished deliverables.
Canonical `STATUS.json` deliberately retains false activation, release, external
acceptance and authority claims.

## Reproduced findings and repairs

Severity here describes the affected invariant within the authorized module; it
does not imply that runtime, merge or release authority was obtained.

| Area | Failure reproduced | Repair and verification |
| --- | --- | --- |
| High: nested durability | A caught nested transaction error could leave inner mutations in an outer commit | SQLite savepoints roll back nested work; transaction regressions |
| High: lifetime containment | Leases, renewals or claims could exceed their enclosing work-envelope lifetime | Bound every admission/renewal to the persisted envelope; expired and legacy-overlong cases |
| High: completion identity | Caller-supplied envelope variants could widen persisted completion context | Bind completion to the exact durable envelope digest |
| High: integration queues | A copied plan digest could accompany substituted assignments/order/queue | Compare exact persisted plan material and queue projection before effects |
| High: signed admission | Zero identities/digests, malformed principals or negative observations could enter evidence paths | Strict typed, nonzero, bounded admission with adversarial fixtures |
| High: key separation | Distinct role labels could still share actual key material | Reject public-key digest collisions across roles and rotation sets |
| High: retained readiness | Required jobs and readiness projections could be altered consistently with a recomputed unsigned digest | Persist required job names; reconstruct projections; enforce distinct job IDs and expiry; consumers may pin the required set |
| High: rotation expiry | A retiring reviewer remained effective through a manifest after its dual window ended | Cap only retiring-reviewer manifests at the dual-window endpoint; current-reviewer TTL regression |
| Medium: CI pairing | Same run/attempt receipts could use different workflow refs or another PR's merge ref | Require one workflow ref across lanes and bind pull refs to the expected PR |
| High: Git boundary | Ambient Git selectors/config or local callbacks could affect evaluator reads | Hermetic Git environment, disabled fsmonitor/replacement/lazy-fetch behavior and bounded output |
| High: pre-sandbox work | Existing source, command streams or mutation preparation could consume unbounded host work | Stat/read limits, streaming count/byte bounds and subprocess budgets before effects |
| High: mutation verdicts | Infrastructure/resource failures could be counted as killed mutants | Separate failed infrastructure from evaluator verdicts; validate check provenance and tree identity |
| High: assimilation consent | Malformed authority/copy flags or expired consent could survive later reads | Strict booleans, scope/target/live identity binding, bounds and lifetime rechecks |
| Medium: planner admission | Malformed envelope/worker fields caused raw exceptions or wasted scarce workers | Typed normalized inputs and deterministic demand-aware matching; no global-optimality claim |
| Medium: worker identity | Semantically equal multi-skill profiles differed solely by skill ordering | Canonical profile skills at planning and claim admission; retain compatibility with immutable prior plans |
| High: concurrent writes | Separate generations could reuse one worker's lease for overlapping live package writes | Atomic active-claim write-path admission, bounded frontier and terminal release regressions |
| Medium: CLI input | Encoded/deep JSON could bypass a byte-only or UTF-8-only depth check | Bounded depth before allocation with UTF-8/BOM/UTF-16/UTF-32 handling and structured failures |
| Medium: qualification host | Copied campaign setup could invoke host Git hooks or follow source symlinks | Hermetic temporary Git and isolated Python; reject special/symlink source paths; real baseline/mutant execution |
| Medium: false promotion | Caller JSON booleans could appear to certify production readiness | Legacy production exit gate fails closed; explicit non-authoritative readiness projection |
| Medium: exact source verification | New identity policy existed only in unused authoring patches | Implement policy in the actual verifier, complete sourceObjects and current blobs; retain immutable provenance and v1 rules |
| Medium: source mutation | Historical helper/workflow could rewrite and self-push an alleged closure | Remove unreferenced materializers/self-pushing authoring workflow; retain read-only collection |
| Medium: documentation drift | Python/Rust descriptions, canonical owner and native/adaptive target claims disagreed | Correct source placement, contract inventory and implementation-versus-deployment meaning |
| Medium: type enforcement | Product/readiness boundaries were outside the existing strict gate | Resolve 11 typing gaps through typed validation and include both modules in the CI gate |
| Medium: capacity-renewal acknowledgement | A valid capacity-only renewal made an already committed claim fail its original profile replay | Permit only the same durable claim to replay against current capacity; preserve all other profile, reservation and lifetime gates |
| High: external fence context | A valid signature for a substituted source/owner could reuse a persisted envelope ID and lease | Match the complete durable envelope before admitting a fence |
| High: external counter types | JSON `true` compared equal to integer fence epoch/token and lease/envelope revisions | Require positive exact integers before signature/context comparison |
| High: external evidence consistency | A second connection could release a lease between fence verification and audit verification, while the aggregate still passed | Verify all owner-bound external controls at one timestamp in one owner transaction |
| High: SQLite automatic rollback | Disk-full aborted an outer transaction; caught failure then allowed a later nested operation to commit independently | Track active owner scopes and abort state; retain the original error and prohibit further effects until scope exit |
| Medium: schema identity | Startup normalization lowercased SQL string literals and accepted changed CHECK semantics | Preserve quoted token bytes while normalizing only SQL tokens; verify changed literals fail on reopen |
| Medium: elapsed sandbox budget | Successful final checks followed by expensive identity/postcondition work could emit success beyond the total wall budget | Enforce the remaining total budget through preflight, execution and final evidence formation |
| Medium: worker registration input | Signed negative observations could persist; oversized timestamps and unhashable skills raised raw exceptions | Bound registration timestamps to SQLite signed integers and validate skill element types before deduplication |
| High: admission time cut | Waiting for the owner write lock could preserve a default timestamp and admit expired registrations, leases, source/completion/seal evidence or claims | Sample default time after lock acquisition; preserve explicit logical time and historical ACK semantics; real second-connection waiting regressions |
| Medium: hosted collector setup | Both command lanes passed but strong tests skipped, correctly failing the collector's no-skips gate | Prepare the same disposable namespace host profile as the strong lane; require native admission and retain bounded failure diagnostics |
| Medium: owner scalar admission | Oversized envelope/lease/time/audit integers raised raw SQLite overflow; malformed collections/text raised raw errors; boolean lease comparisons could release a revision-1 lease | Bound actual SQLite scalars, require exact integer CAS, reject malformed text/collections with typed errors, and roll back exhausted lease revisions; preserve valid maximum values and JSON-only priority |
| Medium: signed fence scalar admission | Signed oversized leader/frontier counters overflowed SQLite and a signed negative fence observation persisted successfully | Bound only persisted counters and fence times, reject negative observation windows, and preserve JSON-only external frontier expiry |
| Medium: canonical owner type gate | The canonical store/path owner had legacy typing gaps and was absent from the selected strict gate | Resolve real helper/return types and include the owner, path policy and existing product/registration boundaries in the same 14-file quality/collector gates |


Regression tests cover real Git repositories, signed fixtures, persisted/reopened
SQLite state, public CLI composition and independent evaluator boundaries. Fixture
signatures establish test behavior only; they are not external provider attestations.

## Position in the whole project and optimization decisions

The module coordinates engineering work; it must not become the runtime authority,
merge authority or a second learning control plane. Keeping assignment/integration
ownership inside the durable owner, and consuming externally owned evidence at
typed boundaries, fits that role. The repairs strengthen those boundaries instead
of promoting fixture success into product or deployment claims.

The planner remains a deterministic bounded heuristic. Demand-aware worker choice
reduces avoidable starvation of scarce skills without introducing a global solver
or claiming optimality. Cross-generation reservations and claim-level path checks
carry correctness beyond a single plan snapshot.

Further whole-project adoption should use concrete integration packages for
registered adaptive producers or native consumers when those use cases are required.
Production deployment requires governed provider identities, target-host operation,
independent review and deployment/recovery/rollback/operator receipts. Inventing a
local provider or filling readiness booleans would weaken the project's architecture.
These deliverables are tracked as gaps rather than simulated.

## Verification interpretation

Local execution runs in a root-only container that cannot supply the unprivileged
owned-service profile or real Bubblewrap namespaces. Its supported-suite exclusions
and skips are explicit in the retained summary. The ordinary hosted quality gate
runs the full owner test discovery; separate strong lanes require actual isolation.
The 80% branch-inclusive coverage threshold is retained, not lowered.

Exact-map verification is source identity, not execution acceptance. The full
candidate sourceObjects and operation blobs are refreshed after code commits.
Shared-verifier drift in `cognitive.read` is corrected by one witness OID only;
that module's behavior, provenance and claims are unchanged.

The final review stopping condition is no additional reproducible defect in the
reviewed repository boundaries after fixes and repeat qualification. It is not a
claim that every possible optimization or deployment issue has been exhausted.

## Continued review and hosted evidence

The exact historical source `c2837627d18979c0f28921a3134d8de358b8531c`
and tree `9aba17b8b37d3fcf87893752f10cfbd42bb8e6c8` received real hosted
execution. Quality ran 453 tests (451 passed, two strong-host skips) and measured
80.371969445367% branch-inclusive coverage. The separate source and base-merge
strong lanes each passed all 453 tests with no skips and measured real namespace
isolation, backup matching and controlled disk-full rollback. Both development
verification lanes passed. Seven archive digests and the internal command/profile
bindings were checked; their immutable identities are retained in the historical
manifest. Product receipt jobs were still queued at that observation, so no paired
product or production acceptance is inferred.

The independent read-only collector correctly rejected that historical candidate
because two strong-host tests skipped, even though all 15 commands in both lanes
passed. Its namespace host preparation differed from the dedicated strong lanes.
The bootstrap repair preserves the no-skips rule, requires the native owner probe
and retains setup/admission diagnostics. Local checks of this workflow cover real
host rejection and success/failure control flow; they do not establish strong
hosted admission. Later source changes require new exact-candidate hosted evidence.

A repeated adversarial pass reproduced the additional failures listed above using
public product calls, signed context substitutions, a real concurrent owner connection,
a real SQLite disk-full failure and real Git execution exceeding its budget. These
are repairs within the existing engineering owner. They do not create an external
provider, independent reviewer, native adaptive producer or deployment controller.

The final continued local owner snapshot `2b1a3f9fc82b2d563d6764ac3509b593386a0440`
passed 480 discovered supported tests (478 passed, two host-admission skips),
with 31 unprivileged-host cases explicitly excluded from this root-only host.
All 58 newly added regression methods are included. Branch-inclusive coverage
was 81.39258298194399%; Ruff and the aligned 14-file owner/product/evidence type
gates passed. The 160 source-mapping regressions, all 40 strict current-source
module maps, module documentation, status/API checks and gap inventory passed.

Whole-repository document verification now also passed on the exact recorded local
source. The legacy baseline and its required ancestor path were restored from real
Git objects with SHA checks; the retained graph is explicitly partial, not a full
historical checkout. The global verifier still reports 54 readiness documentation,
22 CNS reference and 18 HNMF reference gaps. Passing inventory/identity verification
does not close those unrelated project-wide deliverables or promote this owner.

The last input review closed persisted scalar overflow, boolean lease comparisons,
malformed text/collections and signed fence time/counter gaps. Independent repeat
checks retained the maximum valid stored values, JSON-only larger integers,
context/signature gates, atomic rollback and acknowledgement replay. No further
reproducible defect was found within those reviewed boundaries after the repairs.
[CONTINUED_AUDIT_LOCAL.json](CONTINUED_AUDIT_LOCAL.json) retains exact scope and
log digests. Full 511-test discovery, paired product receipts and strong source/merge
qualification belong to the new hosted candidate. `just fmt` could not execute
because this environment has no `just`; this change does not modify Rust.
