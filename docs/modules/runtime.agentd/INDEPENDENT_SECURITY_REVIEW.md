# runtime.agentd independent security review contract

This checklist is for a reviewer who is independent of the implementation and
release decision. It defines review evidence; it does not itself approve,
activate, promote or release `runtime.agentd`.

The review must bind an exact Git source commit and tree, the exact retained
Agentd and worker artifact digests, the qualification-contract digest, the
source/merge CI run identities, the target-host aggregate receipt and the
release-candidate provenance attestation. A branch name, pull-request number,
latest workflow label or mutable tag is insufficient.

## 1. Reviewer independence and decision form

The reviewer identity must differ from the authors and committers of the reviewed
candidate. The final decision must be one of:

- `accepted_for_named_artifacts`;
- `changes_required`;
- `rejected`.

An acceptance applies only to the named source/tree and artifact digests. A source,
workflow, dependency, configuration, authority, schema or artifact change
invalidates it. The review record must state that operator activation, promotion
and release remain separate decisions.

## 2. Composition and authority boundary

Verify that the canonical profile cannot be partially installed and that the
single typed bootstrap binds:

- canonical intelligence runner and owner-input provider;
- current durable Neuron owner/frontier;
- runtime.codex executor and physical input provider;
- final-use authority configuration digest;
- bounded queue, concurrency and recovery policy.

Confirm that request or wire bytes cannot replace those owners, construct the
Neuron invocation seal, mint the final-use token or select an alternate physical
executor. Confirm the adapter consumes an operation-, final-payload-, expiry-,
epoch-, purpose- and revocation-bound token immediately before effect entry.
Review claim/enter and post-claim fence races, including generation change,
revocation, endpoint replacement, deadline expiry and cancellation.

## 3. Admission, dispatch and terminal semantics

Verify the ordered boundary:

1. current RunStart trust and Fleet fence revalidation;
2. queue-capacity reservation;
3. canonical preparation and exact context attachment;
4. durable native dispatch intent;
5. newly committed Agentd dispatch transition;
6. final health/context/authority entry checks;
7. physical turn start;
8. exact terminal observation and immutable receipt publication.

A failure before physical entry must be locally abortable. A missing acknowledgement
at or after physical entry must be reconcile-only. No timeout, process exit,
interrupt acknowledgement, queue acceptance or handler return may be converted
into external success or a fabricated negative outcome. Exact duplicate requests
must return the frozen result or conflict on semantic drift; they must never
create a second physical dispatch.

## 4. Persistence, archive and recovery

Review manifest, dispatch fence, native journal, terminal receipt, terminal witness
and archive publication as one crash matrix. At every file-write, fsync,
directory-fsync, link and rename cut, recovery must observe either the durable
predecessor or a complete successor and must not infer fresh dispatch authority.

Verify that:

- active and archived copies cannot coexist silently;
- a witness without the archived operation fails closed;
- an archive without a matching witness fails closed;
- witness, manifest or receipt drift is rejected;
- corrupt, partial, oversized, symlinked or unsafe-permission state is rejected;
- bounded archive maintenance cannot drop terminal identity;
- cleanup/retention cannot resurrect a historical run ID;
- an older binary cannot reinterpret newer records as replayable work.

## 5. Concurrency, ownership and shutdown

Confirm that different run identities use bounded concurrent execution while
exact duplicates and reconciliation share one keyed lock. Verify queue permit,
active-registry and semaphore lifecycle under success, cancellation, panic,
spawn failure and shutdown. Check that keyed-lock and active-job registries are
bounded or reclaimed.

Review all owner stop paths:

- normal drain;
- supervisor generation fence;
- SIGINT/SIGTERM;
- control accept failure;
- runtime.codex required-task failure;
- worker crash or orphaned descendants;
- automation or other required-owner failure.

Admission must close before drain. Every accepted task and acquired process must
be joined, reaped or left as an explicit recovery responsibility. Timeout is not
retirement success. Active workers must be cancelled on drain/fence, but their
physical effects remain terminal only when the execution owner supplies evidence.

## 6. Local OS boundary and secrets

Review UDS peer-credential enforcement, owner-only directories/files, canonical
path and symlink checks, same-UID replacement threats, executable/config digest
revalidation immediately before spawn and process environment inheritance.

Confirm prompts, model output, credentials, tokens, private Memory and authority
material are absent from debug output, general logs, CI receipts, metrics and
learning datasets. Validate log and response bounds and label-cardinality bounds.

## 7. Adversarial tests and physical evidence

Require successful exact source-head and deterministic base-merge matrices on
Linux and macOS, with no skipped applicable suite. Review the complete target-host
scenario set from `QUALIFICATION_CONTRACT.json`, including:

- drain under load and backpressure;
- Agentd and worker crash cuts;
- ENOSPC, read-only, fsync and rename failures;
- journal corruption;
- stale generation and authority revocation/substitution;
- capacity, latency, leak and faulted soak/recovery.

Each physical scenario must bind the exact artifact and configuration digests and
must report owner-observed invariants. Source inspection, mocks and unit tests do
not substitute for these receipts.

## 8. Supply chain and release-candidate provenance

Verify all third-party workflow actions are pinned to immutable commits, checkout
credentials are disabled, workflows have least permissions and evidence cannot be
silently overwritten or accepted after a skipped/failed dependency.

Validate the retained Agentd and worker bytes, manifest, Cargo.lock/compiler/
workflow digests, deterministic bundle and GitHub build-provenance attestations.
The security review must name the exact attested bundle digest. Digest-only runner
receipts are not release artifacts.

## 9. Required review output

The signed or otherwise independently authenticated review record must include:

```text
reviewer identity
review timestamp
source commit and tree
Agentd binary digest
worker binary digest
release-candidate bundle digest
qualification-contract digest
source-head and base-merge run IDs
main-baseline receipt digest
target-host aggregate digest
provenance attestation identities
findings with severity and disposition
final decision
explicit production_activation=false
```

Unresolved critical or high findings prohibit promotion and activation. Accepted
risk must name an owner, expiry, compensating control and rollback trigger. A
self-authored checklist completion or workflow-generated statement is never an
independent security decision.
