# DecisionCell split acceptance matrix

This matrix is the strict acceptance boundary for the typed `CellSplitV1`
implementation. A source owner seam is evidence that the repository rejects
incomplete transitions; it is not evidence that a production target host ran
the transition.

| Criterion                       | Repository owner now present                                                                                                                                                                                                                                                                                                        | Evidence still required for full 8/8                                                                                                    |
| ------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| Replicate parameter inheritance | `CellParameterBundleManifestV1`, component-level materialization receipt, create-only CAS payload receipt, cloned registry commit, predecessor and rollback binding                                                                                                                                                                 | Signed writer lease, durable `CURRENT`, directory sync, and restart/reopen receipts from the deployment host                            |
| Copy/partition cell state       | Q24 sparse/population projection plus `CellStateMigrationV1`; all children must match one committed parent anchor and one batch fence                                                                                                                                                                                               | A real child journal/CAS owner must atomically commit all children and publish an independently retained witness                        |
| Give children identity          | `CellSplitV1` binds child identity, generation, scope, lineage, objective, bundle and route predicate                                                                                                                                                                                                                               | The target host must reload and compare those fields after restart                                                                      |
| Division of labor and routing   | Dataset/task partitions, route predicates, fallback revisions, CNS route selection and concrete port/ABI digests                                                                                                                                                                                                                    | A live router must emit retained dispatch receipts for the deployed circuit                                                             |
| Nutrition and energy            | Resource budget contract, target-host-only resource evidence gate, and ten-metric long-horizon adapter                                                                                                                                                                                                                              | Independently signed measurements from the actual CPU/GPU/NPU, including communication and migration cost                               |
| Death and rollback              | Quarantine, rollback, tombstone, terminal lifecycle replay, old-route fence and no-resurrection checks                                                                                                                                                                                                                              | Power-loss/restart and fault-injection evidence proving the parent cannot return                                                        |
| Tissue coordination             | CNS generation cutover, child activation ordering, parent-route rejection, route fence receipt and replay payload                                                                                                                                                                                                                   | Durable route/registry persistence and a production runtime callsite after governance admission                                         |
| Survival selection              | Signed no-change baseline, retention, coverage, negative-transfer, cost, failure and rollback evaluation; deterministic `CellSplitProposalSourceV1` plus `run_cell_split_automation_v1` driver; telemetry-triggered `CellSplitProposalSignalV1` and governed `CellSplitV1` planner; fenced `CellSplitTaskFlowJournalOwnerV1` replay | Independent future-window observations plus a target-host commit/restart evidence chain and externally retained learning-ledger witness |

The role-contract roadmap for Representation, MemoryRead, Predictor, Value,
Evaluator and the later Planner/Router/ActionProposal/Plasticity profiles is
maintained in [`learning/CELL_ROLE_CONTRACTS.md`](learning/CELL_ROLE_CONTRACTS.md).
That document defines the P0/P1 source gates and keeps source qualification
separate from target-host production activation.

The implementation deliberately rejects `LocalSimulation` resource evidence at
the production evaluation entrypoint. The target-host harness is therefore a
source qualification fixture and sets `productionEvidence` and
`productionActivationAuthorized` to `false`.

## New source qualification owners

The repository now contains the following replayable source owners. They make
the missing production boundary explicit; they do not turn a local test into a
deployment receipt.

- `CellSplitTelemetryObservationV1` validates unit-bearing utility, coverage,
  latency, resident-memory, communication, training and migration counters.
  `cell_split_signal_from_telemetry_v1` applies a deterministic, governed
  trigger priority (utility regression, task-coverage opportunity, then
  resource pressure).
- `CellSplitGovernedPlannerV1` binds the signal to an immutable policy and
  parent registry context, derives child identity/generation/lineage,
  inheritance modes, state transforms, route ports, resource budgets and
  rollback references, and runs the complete `CellSplitV1` validator.
- `CellSplitTaskFlowJournalOwnerV1` registers an immutable TaskFlow definition,
  creates and fences a run, writes each lifecycle event as a TaskFlow
  `Wait`/`Resume` pair, persists terminal disposition, and reconstructs the
  lifecycle journal from the verified event chain after reopen. A stale owner
  generation or a rewritten prefix is rejected.
- `CellSplitTargetHostEvidenceAdapterV1` verifies a host-signed and
  independently observed canonical JSON envelope. Its production receipt is
  issued only after artifact load, route cutover, restart, power-loss
  recovery, rollback, tombstone, no-resurrection, and non-simulated
  CPU/GPU/NPU resource events are present and replay cleanly.

The target-host envelope is an ingestion protocol, not a claim that this
repository has already run on the deployment device. The deployment owner
must still supply the host and observer keys, actual artifact/router calls,
fault-injection receipts, hardware counters, and an independent future-window
evaluation; those values cannot be derived from the planner digest or a unit
test.

## Strict conclusion

At repository source level, all eight contracts have typed owner boundaries,
including a deterministic machine-driven proposal/evaluation/canary driver, and
negative-path tests. Under the user's strict rule that every item must also
have real target-host evidence and durable automatic long-horizon selection,
the production result remains **0/8 fully complete** until the external
evidence column is supplied. The missing evidence is intentionally represented
as typed gates rather than inferred from a digest or a unit test.

## First-party CNS kernel execution bridge (opt-in, not production-complete)

The non-default `codex-hepta-runtime` feature `cell-split-cns-port` now
provides `CellSplitCnsKernelRuntimePortV1`. It invokes the real
`HeptaRuntime::apply_governed_topology`, not a simulated route or an
advisory file swap. Every attempted cutover requires an independently pinned
`FinalUseAuthority`, an accepted successor, the runtime's genuine transition
receipt, fresh challenge-signed old-writer/route observations, and matching
Artifact/generation/fence identities. A candidate cannot supply or replace
the trust root. The separate source must persist the original runtime
commit and retain an independently witnessed monotone owner sequence.

Source tests cover missing final-use refusal, signer/challenge mismatch,
actual generation replacement, fsynced original cutover attestation, and
restart safety. A fresh process-local runtime at its predecessor generation
cannot claim that a prior signed successor receipt makes it current.
Recovery must fail closed until the canonical serving owner is restored.
None of the fixture credentials are production keys or NDU/Selector grants.

Still required: authenticated startup rehydration under an external minimum
checkpoint, independently signed migration/Selector/NDU preflight readers,
a real persistent CNS runtime witness, target-host fault injection,
the real Supervisor finalization call connected to the same coordinator,
and independent Observer confirmation. The strict production result stays
**0/8 fully accepted**. Native tests do not authorize physical splitting.

## Exact-owner readback concurrency and ledger namespace

The source-side CellSplit RPC owner now double-samples its monotone durable
frontier and re-reads the original operation after the first live-state check,
before it signs any positive or negative nonce-bound readback. A commit that
appears during a previously negative lookup, a changed original receipt, or
a changed frontier returns an error. The coordinator also rejects unknown
write-once `cell-split-*` ledger frames (including fabricated fifth steps or
alternate replay markers), and caps each private execution directory scan at
32 entries. These are bounded fail-closed checks, not a substitute for a
production owner lock, true atomic snapshot, signed minimum checkpoint or
independent Observer witness. Source regressions inject both readback races,
unexpected frames and namespace exhaustion.

**Qualification status:** these changes are committed to the Draft PR, not
validated by a new exact-HEAD native CI and not deployed on the target
machine. No physical split or production acceptance follows from them.

Global cargo-deny is separately blocked by `RUSTSEC-2026-0318` for
`matrix-sdk-crypto` 0.18.0 (patched in 0.19.0) and `RUSTSEC-2026-0319`
for the unmaintained `anymap2` crate. Matrix SDK 0.19.1 still depends on
`anymap2`, so bumping the SDK without migrating that dependency cannot
make the security gate green. Neither advisory may be ignored for release.


## Execute causality versus read-only recovery (additional P0 gate)

The signed effect service now refuses a **new Execute** if its original real
owner already has a committed effect for the same idempotency key. A negative
preflight may race another owner mutation before dispatch; a fresh readback of
a previously existing effect must **not** be presented as proof that this
specific Execute caused the effect. The source regression exercises: signed
negative preflight, a competing durable write, rejected new Execute, and
continued read-only reconciliation of the independently committed bytes.

This defense deliberately does not change recovery semantics: once the
coordinator has written a one-shot prepared intent, it never repeats Execute.
If its acknowledgement was lost, it queries the original owner by ReadBack.

**Remaining strict production gate:** a successful signed ReadBack does not,
by itself, prove that the effect happened *after* this coordinator's prepared
intent, only that the original owner durably committed these exact bytes and
that its state is still current. Deployments must enforce a single authoritative
writer per scope/intent, bind the preparation and current independently issued
Selector/NDU/final-use authority to the operation, and retain an external
anti-rollback witness. A competing writer with the same key cannot be
disambiguated by an idempotency hash alone. Until origin causality is enforced
at the authoritative owner, this source check is not production acceptance.

## Independent Observer join of real owner and host evidence (source gate)

The new CellSplitSignedObserverJoinV1 addresses a distinct evidence-laundering
failure mode: four independently signed CellSplitExecutionTranscriptV1
receipts and a host/observer-signed target lifecycle report can each be
valid yet concern unrelated actual operations.

The verification-only verify_cell_split_observer_join_v1 therefore:

1. Validates all four original effect signatures against independently pinned
   keys, their exact coordinator predecessor chain and transcript digest.
2. Verifies the host's canonical lifecycle evidence and independent Observer
   signatures under externally supplied trust keys.
3. Requires the real host and an Observer to sign the same domain-separated
   join of the frozen plan, target host ID, NDU/route fence, all four original
   effect receipt digests, target evidence digest, and actual artifact-load
   and route-cutover event digests.
4. Refuses shared signing keys across the host, Observer and all four
   effect owners, and refuses any mutated lineage before contacting owners.
5. Revalidates each original operation against its current external owner.
   The public verification entry accepts only the actual Unix signed RPC port,
   and rejects any readback key set that differs from the frozen original
   four-owner trust pins. The generic injected-port validator is crate-private
   for fault-injection tests only. No user-supplied allow-all readback can
   produce a public joined result.
   There is no execution, prepared intent, recovery mutation or promotion
   API in the join verifier.

The returned CellSplitObserverJoinReceiptV1 explicitly sets
productionActivationAuthorized=false. Independent real-world host
observation, atomic or witnessed multi-owner freshness, independently
retained anti-rollback frontiers, NDU/Selector final-use and target-machine
resource/fault measurements still require separate production gate evidence.

The new exact-source regression gate invokes the operator-acceptance
observer_join tests, including valid binding, refused revoked CNS owner,
false host/owner combinations, tampered Observer signature and host/owner
key reuse. These tests use synthetic signing keys and do not claim
production evidence. Their exact-HEAD CI status is not yet verified.


### Exact Artifact/CNS owner-event linkage and original-runtime signer separation

The signed Observer join now refuses independently valid lifecycle reports
unless ArtifactLoaded carries the exact Artifact CAS owner **idempotency key
and signed receipt digest**, and RouteCutover carries the exact CNS owner's
idempotency key and signed receipt digest. A shared split ID, identical model
digests, a correctly rehashed event chain or a host/Observer signature over
that chain cannot substitute for these exact operation identities. The
source tests deliberately re-sign four unrelated-but-otherwise-valid host
events and require rejection before any owner RPC read.

The additional Unix-only
\`verify_cell_split_observer_join_deep_v1\` requires two more deployment-pinned
trust roots: the original CNS runtime signing key and the original Supervisor
journal signing key. They must be distinct from each other, all four outer
effect-owner keys and every host/Observer key. It checks the typed original
CNS runtime attestation against the same frozen split and witnessed
predecessor/successor routes, then checks the domain-separated original
Supervisor journal signature and its terminal \`retired\` checkpoint,
generation, domain, authority epoch, revision and absence of unknown effects.
Only then does it perform the existing four fresh, nonce-bound signed owner
readbacks. No signature is minted by this verifier.

### Full Supervisor original-checkpoint verification (source gate)

The deep Observer now parses the original Supervisor journal bytes using the
exact version-1 persisted WriterHandoff checkpoint fields, rejects unknown
or missing fields, and requires the Supervisor's own ordered JSON encoding.
It independently reconstructs the checkpoint content SHA-256 using the
writer-handoff domain, length-prefixed writer identities, big-endian
generations/epoch/revision, exact digest fields, phase tag and drain watermark.
Only a verified terminal `retired` record with the canonical tenth revision,
zero unknown effects, a retained outbox watermark, and a correct self-digest
can match the original signed Supervisor cutover acknowledgement.

Regression fixtures now use the complete native checkpoint encoding rather
than a structurally plausible short JSON record. Native tests cover a fixed
independent SHA-256 vector, rehashed invalid states, noncanonical encoding,
missing/unknown fields and altered journal identity/generation/epoch.

This protects offline structural verification, **not** cross-process
linearizability, independent checkpoint minimum, actual journal custody,
or protection against whole-directory rollback. The real Supervisor must
still recover its fsynced history against an independently retained minimum
and expose fresh nonce-bound live state before final-use or promotion.
A valid deep join is **still read-only** and explicitly sets
\`productionActivationAuthorized=false\`: it does not create a globally
atomic four-owner snapshot, issue NDU/Selector final-use authorization,
supply target-host measured CPU/RSS/p99/negative-transfer evidence or
prove power-loss recovery on deployed machines. Its corresponding
cross-language and native exact-HEAD CI qualification must still be obtained.


### Independent Observer-signed Supervisor minimum (source gate)

The deep Observer verifier now refuses a bare caller-supplied Supervisor
checkpoint digest. Its original-runtime trust binding must also carry a
separately pinned Observer's detached signature over a domain-separated
minimum-checkpoint statement. That statement binds the frozen CellSplit plan,
signed host evidence digest and nonce, exact Supervisor domain, idempotency
key, authority epoch, journal revision, original checkpoint bytes and minimum
checkpoint digest. The verifier accepts only a key already present in the
independent host-evidence Observer trust policy, rejects signer reuse across
the host, four effect owners and original runtime owners, and confirms the
signature before conducting four fresh current-owner reads.

The read-only deep receipt records both the accepted minimum checkpoint
digest and the signed minimum-witness digest for later audit. Regression
cases reject an attacker-signed minimum and replay of a legitimately signed
minimum against a different host nonce, even where the original Supervisor
checkpoint still has an otherwise valid signature.

**This is NOT an independently monotonic witness store.** A signature from
the Observer must be issued only after it has consulted its separate,
authenticated, rollback-resistant minimum checkpoint service. A captured old
minimum signature may still be replayed together with a completely rolled
back host/owner history without a fresh authoritative store read. The
production startup and final-use owner must verify live monotonic retention
and retain its own authenticated checkpoint minimum. This source gate does
not permit physical split, promotion, or a production completion claim.

### Fresh online minimum-store readback (P0 source boundary)

A detached Observer signature and a matching historical checkpoint digest
are **not** evidence that a separately retained monotonic minimum is still
current. The strict public deep-verification entry now requires an online
minimum source and an externally pinned **separate** source verification key.
The key must be independent of the two original runtime signers, the four
effect-owner signers, the target host, and every evidence Observer signer.

The source implementation introduces a narrowly scoped
`CellSplitSupervisorMinimumOnlinePortV1` and the concrete
`CellSplitSupervisorMinimumFileStoreV1` qualification owner:

- Create-only canonical Supervisor minimum record in a private isolated
  root, with file/directory fsync and an exclusive owner lock;
- Independent original journal/Selector admission before durable first
  publication, with the admission repeated immediately before the write;
- Read-only `open_existing` recovery, no missing-record regeneration,
  hardlink/symlink and mismatched original signing-key rejection;
- A fresh 256-bit challenge signed by the separately pinned minimum owner;
- Two online minimum challenges, **before and after** rechecking four original
  signed effect owners. The underlying durable record digest must match
  across both reads or the deep verdict fails closed.

The resulting read-only deep receipt includes a digest of both fresh signed
minimum readbacks and continues to set
`productionActivationAuthorized=false`. Regression tests cover missing
record, untrusted publication, duplicate publication, restart/reopen,
concurrent writer, corrupted record, changed original epoch, stale nonce,
different host, and external minimum deletion while four owners are checked.

This does not grant global five-owner atomic linearizability. An isolated
ordinary filesystem still cannot detect restoration of its **entire** root
to an older, internally valid snapshot. Production must keep the minimum
and signer under independent rollback-resistant custody, retain an external
minimum against which the store itself recovers, and prove live target-host
and NDU/Selector final-use. The filesystem implementation is not a complete
hardware-backed remote witness service. Current exact-head CI is not yet
qualified; no physical split, route promotion, or merge is authorized.

### Independent signed monotonic high-water frontier (production gate)

The public `verify_cell_split_observer_join_deep_v1` now requires **two
separately pinned online signing roots**: the original per-split minimum
checkpoint store and an additional monotonic high-water store. Both keys must
be distinct from each other, the original CNS/Supervisor runtime keys, the four
outer execution-owner keys, the host keys and all Observer keys.

The `CellSplitSupervisorMonotonicFrontierPortV1` is queried **by the
authoritative journal domain alone**; the caller must never provide the expected
revision or digest as search parameters. Its fresh signed answer binds domain,
authority epoch, committed revision, minimum checkpoint digest, original
minimum-store record digest and a verifier-generated 256-bit challenge.
The verifier rejects a correctly signed local minimum if an external domain
frontier reports a later revision or a different checkpoint/record. It repeats
**both independent challenges after** the four owner readbacks, compares their
underlying identities across reads, and preserves hashes of both proofs in the
read-only Observer receipt. A source-only test simulates a still-valid revision
10 minimum with a separately signed revision 11 high-water and requires
rejection before the live effect owners are queried; another moves the
high-water during the four reads and must fail afterwards.

A concrete read-only `CellSplitSupervisorMonotonicUnixPortV1` now connects
this trait to a separately administered Unix socket using an externally
pinned Ed25519 verification key. The transport sends **only domain and a
fresh challenge**; no caller-selected epoch, revision or checkpoint hash is
transmitted. It rejects symlinked endpoints, malformed or contradictory
responses, wrong signer/domain/nonce and slow or incomplete frames with
a bounded whole-frame deadline. The six associated socket regressions are
wired to the exact-source architecture CI. This is client-side authentication
of an *existing external service*, not a hosted monotonic service or
deployment proof.

The separate high-water port intentionally has **no local filesystem
implementation or allow-all default**. It must be connected to a real
independently managed, rollback-resistant service whose signer key is not
controlled by the local minimum/host/Supervisor writer. A mock signed high-water
in a unit test does NOT qualify that service. Even two fresh independent
signatures do not implement one globally atomic transaction. Production
activation remains false pending deployment-owned monotonic custody, exact
HEAD CI, fault recovery, independent NDU/Selector final-use and measured
target-host evidence.

### Process-lifetime monotonic signer ratchet (source hardening)

The read-only Unix frontier signer now retains a bounded in-process
high-water per authorized journal domain. A new signed observation must
either exactly match the last acknowledged source record or advance
epoch/revision with a **strictly newer durable source sequence**. It
rejects a lower epoch/revision, a same-revision record with changed
checkpoint/store digest, and an epoch rollover with a reused source
sequence. The map is limited to 4,096 domains and never evicts an old
high-water to accept an untrusted new domain. Regression tests inject
rollback, source equivocation and epoch rollover across separate signed
Unix requests served by the same owner.

This does **not** survive whole-process or whole-directory restoration:
the production high-water service must still enforce monotonic custody
in its own independently persistent source. The ratchet cannot confer
physical-split authority, promotion, or a CI pass.

### Read-only monotonic frontier Unix signing service (source boundary)

The existing externally pinned \`CellSplitSupervisorMonotonicUnixPortV1\`
has a corresponding read-only \`CellSplitMonotonicRpcServiceV1\` serving
the exact four-field domain-and-challenge protocol. The service delegates
all high-water observation to an independently administered
\`CellSplitMonotonicAuthoritativeRegistryV1\`, which must read real durable
domain state and validate that state independently. It reads and verifies
the same epoch, revision, checkpoint digest, immutable record digest, and
source sequence repeatedly, signs only the freshly supplied verifier
challenge, and checks the source again before returning positive proof.
Absent/tampered/revoked state and requests containing a caller-supplied
revision are denied. Source-only disk fixtures test the signed socket,
revocation and malformed request; they are not production registry owners.

**Not production-qualified:** The independent monotonic registry still
needs a real separately deployed, rollback-resistant persistence owner,
key provisioning, endpoint access controls, current-domain high-water
advancement and exact-HEAD CI. A locally signed fixture, local fsync or
advisory lock is NOT a substitute for external anti-rollback custody.
Neither service nor client grants split authorization.

### Independent custody signing gate for the Monotonic RPC server

The read-only `CellSplitMonotonicRpcServiceV1` now requires a distinct,
externally pinned custody verification key as well as its own RPC signer.
Before it signs the current high-water response, it obtains three fresh,
random-challenge-bound custody signatures from the separately retained
`CellSplitMonotonicAuthoritativeRegistryV1::read_independent_custody`
backend method. Each signed custody frontier must equal the actual
committed Domain, authority epoch, revision, checkpoint digest,
original store-record digest and durable source sequence. No default
allow-all implementation exists. A missing, differently signed or newer
custody record fails closed, including after restart when the server's
process-memory high-water map is empty.

Source-only disk-backed regressions exercise a valid two-key signed Unix
exchange, an independently advanced custody floor after local Registry
rollback, a substituted custody signer and a missing custody record.
The fixture intentionally keeps both files under a disposable test root
and is **not** a production custody implementation.

Deployment still needs real independent and rollback-resistant storage,
an out-of-process custody signer and original Registry ownership with
fresh monotonic cross-read. This source gate cannot supply those guarantees
or issue promotion/physical Cell Split authority. Rustfmt, Cargo, cross-
platform Bazel/Clippy and cargo-deny on the final combined SHA remain
mandatory.

### Monotonic frontier checkpoint-lineage fence (source gate)

The read-only monotonic signer now refuses any revision/authority-epoch
advance that only increments a local source sequence while retaining the
previous signed checkpoint digest or immutable minimum-store record digest.
A genuinely newer journal revision must bind a new committed checkpoint
and an independently retained minimum record before it can be signed as a
current domain frontier. Regression tests deny each incomplete transition
and allow only a fully changed tuple. This is process-lifetime defense in
depth, not a replacement for independently operated monotonic custody
across crashes or whole-directory rollback.

### Unix client lifetime high-water ratchet (source defense in depth)

The read-only `CellSplitSupervisorMonotonicUnixPortV1` also retains bounded
per-domain signed epoch/revision and checkpoint/record digests for the
lifetime of its process. An old-but-valid signed response received after
the remote service restarts is rejected if it regresses a previously
observed high-water; a later revision must change both committed digest
identities. No entries are silently evicted when the bound is reached.
Native Unix RPC tests exercise both a signed rollback and a genuinely
advanced signed frontier.

This is **not durable anti-rollback**: client restarts erase the local
ratchet. The separately administered monotonic backend, independent
signatures, live minimum readback and protected external custody remain
mandatory. No physical Cell Split or activation is authorized.

The read-only Monotonic RPC service also denies an otherwise signed
frontier if its independent registry/custody checks exceed the configured
request wall-clock budget. Socket frame timeouts do not cover those external
calls. Source failure injection introduces an intentionally slow custody
read and requires refusal *before* any positive RPC frame is sent. This
limit does not interrupt indefinitely blocked backend I/O; production
workers must enforce separate deadlines/cancellation and supervisor health
fences.

### Retrospective rollback evidence is not a live successor route

The signed target-host lifecycle also includes rollback, tombstone and
no-resurrection checks. After a genuine route rollback the current CNS
may correctly serve the parent, so a fresh read of the *current* child
route will no longer verify the former successor cutover. Neither
\`CellSplitObserverJoinReceiptV1\` nor the deep-origin verifier may turn
that legitimate historical transition into a positive live-serving
assertion. Production retrospective acceptance must distinguish:

- Authentic immutable **historical** CAS/migration/CNS/Supervisor receipts,
  bound to independently retained monotone checkpoints;
- A freshly authenticated **current** parent route, writer generation and
  retired child/tombstone proof following rollback;
- An independent Observer-signed, ordered bridge between those histories,
  with no resurrected authority and real power-loss fault receipts.

The current source-side live-RPC join deliberately fails closed when the
former child route is no longer current. A new historical-owner read port
and independent anti-rollback witness are required before an end-to-end
post-rollback target-host acceptance can be granted. Do NOT relax the
current-owner check or substitute the locally reconstructed transcript.


### Signed target-host evidence is write-once, not a replaceable cache

`CellSplitTargetHostEvidenceStoreV1::persist` now creates the original
host/Observer-signed evidence file with create-new + file/directory fsync.
An exact-byte replay is idempotent; a second independently valid signed
report with different bytes is **rejected** at the same witness path rather
than replacing the original. A path symlink, corrupt existing evidence, or
modified historical report cannot authorize an overwrite. The regression
test keeps the original verifiable after a rejected replacement.

This protects the local evidence write boundary only. Restoring an older
whole directory, replaying an old signed report at another path, or asserting
the current CNS/Supervisor state still requires a separately held monotonic
anti-rollback witness and live owner attestation. The historical
`productionGatePassed` receipt is **not** a production-activation grant,
and this source change is not target-host qualification.


### External policy pin for host/Observer evidence verification

The `hepta-operator-acceptance target-host-evidence verify`, `ingest` and
`store` CLI operations now require an additional
`<externally-pinned-policy-sha256>` argument, positioned immediately after
`<trust-policy-json>`. They validate the private trust policy's exact bytes
against that independent lowercase SHA-256 **before reading the report**.
The legacy unpinned `from_json_file` loader now denies access; library
callers with externally supplied trusted bytes may use `from_json_bytes`,
while production file loading must use `from_json_file_pinned`.

The external pin must come from the deployment's independent trust policy
authority, never be computed from the same host-provided file or evidence.
A well-formed policy substituting different host/Observer verification keys
cannot make its own evidence trusted merely by residing at the expected path.
Even a correctly pinned policy and immutable historical evidence file do
not provide current CNS state, anti-rollback across whole-directory restore,
real NDU/Selector final-use or production activation. Exact-head CI remains
required before interpreting this source change as validated.
