# PoN boundary repair, 2026-10-08

Source base: f4165797e3a96a0a9d2b566e84c48880d2dfff29 (PR1437).
Inherited bounded exchange: 32740b3662dcffdd905a1095d3ee7f402d9def13 (PR1434).

The existing Agentd host now uses the bounded asynchronous pipe exchange with
one original deadline and equal stdout/stderr bounds. Started-but-uncertain
work remains Unknown. Original exact effect/payload binding and signed
depth/work confirmation policy remain intact. Native observation parsing now
recomputes height depth, checks active-tip identity and requires positive
work distance for a distinct active ancestor. Oversized bytes reject before
adapter-owned copies. Tests cover full/blocked input, both output limits,
incomplete JSON, nonzero exit, inherited output pipes and contradictory
observation fields. Historical tests are adapted to the current v3 shape;
historical success is not inherited.

Validation must run on this delivered source: just fmt; just test -p
codex-hepta-agentd; just test -p codex-hepta-agent-protocol; scoped Clippy and
the ordinary architecture/required CI. Source materialization is not a test.

Remaining obligations are explicit: binary hash-to-execution object binding,
independently current artifact/withdrawal/selection/final-use checks, real
installation and three-generation consumer benefit. Chain owner_generation
is not a Hepta final-use generation and cannot be compared by casting them.
No second journal, supervisor, trainer, or registry is introduced. Model
parameter adoption does not authorize neuron code/topology replacement;
neither authorizes a consensus/verifier upgrade. Such upgrades require their
existing distinct authorities and fresh explicit protocol contexts.

Physical power loss, independent WAN operators, sustained public capacity,
and model efficacy are not claimed by these local pipe fixtures. No release,
production, branch protection or deployment setting is changed.

## Latest exact-pair convergence (no second authority)

The stacked Hepta integration source is PR #1444 at
`a36dfbb2dd09fec95751522b6e4fc96598b18f14`. Its installed PoN
process exchange, exact v3 observation parser, sealed immutable ELF
execution object and same-candidate pipe/height/work/effect tests are retained
unchanged. PR #1445 was developed separately against the older PR #1437;
its bounded-process fixes cannot replace the sealed execution owner. Both
sides were inspected; no historical or parallel PR pass is inherited.

The paired CI pins Chain PR #248 `560d44ac28fee7b073d1740e372839ab52f057b6` and the
matching GitHub prospective merge `6731581b65a6300e5c2bb73566d582227ee932b7` against its
base `bf2f6c72cb4881545f03b6ebe55a5e5e6a7af988`, in both x64/ARM64 and source/merge
lanes. That Chain PR fixes the *historical cost-report checker* after new
hostile/honest-arrival overlap screening without editing evidence or relaxing
current work admission. The pair still executes the actual Chain binary,
native growth-readback selectors, Agentd sealed submit/reconcile/reorg and
explicit negative process tests. Run results MUST be read from this final
Hepta head and its prospective merge, not PR #1444's earlier successful pair.

This is an exact-source integration increment only: no public-network hardness,
new native storage capacity activation, genuine third-party model training/
adoption, independently operated WAN campaign, physical power-loss, public
service SLA, final-use override, production consensus, or release is accepted.

## Current closed environment and actual main-target pair

The preceding sections retain earlier increments, not the current source tuple.
PR #1454 continues the sealed owner from PR #1449. The last pre-spawn boundary
in `automation_effect_host_pon_process.rs` clears inherited and explicitly
staged environment variables and installs only `LC_ALL=C` and `TZ=UTC`.
All supported runtime inputs are the existing pinned arguments and exact
stdin. There is no environment pass-through, PATH-based binary fallback,
new permission, or HTTP-provider change. Existing deadlines, output limits,
pre-entry refusal and post-entry Unknown semantics are unchanged.

Sealing only the ELF does not prevent ambient dynamic-loader injection.
The existing native ELF test fixture now enumerates the actual environment;
a separate compiled shared-library constructor proves that the same sealed
ELF is affected by an unisolated `LD_PRELOAD` positive control. The actual
hardened exchange must consume its payload, expose exactly the closed
environment and leave no injected marker. Both tests run through the existing
native pair lanes with nonempty selectors. System loader/libraries, working
directory, inherited file descriptors and the host kernel remain trusted;
this change is not a sandbox or a complete execution-dependency attestation.

The current pair workflow pins Chain PR #253 head
`df717d7fb21a368cb5b4a240ef6221eaba977bc9`, main base
`9fedf7ecbbe07177069c030592b4e03dcffebb81`, and actual main merge
`45fbc027cd3d6e89a2792dca73e36a70eae42cfd`. Hepta also targets main.
Read each repository's exact tested head/tree/ordered merge parents and actual
results from that run. All original sealed submit/reconciliation/confirmation/
reorganization and growth tests remain required; prior pair success does not
qualify the new environment or this source tuple.

A local compiled C/Linux sealed-object injection/refusal experiment was run;
that is not compiled Rust or a real Chain/Hepta acceptance run. Current hosted
native and full blocking gates remain separate. Public PoN work qualification,
independent prospective generations, physical power loss, long-term data
availability, independently operated WAN capacity and production remain open.

## Evaluated model consumption on the current owner path

The existing `AgentdConfig::with_cognitive_ranker` startup composition and ordinary
cognitive control consumption now keep the authenticated CURRENT owner trust digest
fixed for the loaded cache. A differently signed trust snapshot cannot replace that
owner even when registry namespace, head, manifest and payload bytes are unchanged.
A refresh failure leaves the cache closed; restoring its former CURRENT provider
does not revive it. A legitimate owner-trust rotation requires explicit reload.

`PinnedCognitiveRanker::load_evaluated` additionally reads the original bounded
snapshot and compares its eligible predecessor's identity, generation and payload
digest with the independently admitted evaluation predecessor. This extra native
snapshot read is load work; it makes no throughput claim. The consumer retains the
opaque independent selection and checks its original four-role validity windows
and already-known revocations before and after each bounded use. The actual ranking
permutation is copied back only after all checks succeed. The selected trust profile
uses Unix microseconds; artifact CURRENT keeps its existing owner time contract.
An evaluated rollback retains and rechecks its original selector/evaluator windows
as well; loading predecessor bytes cannot extend an expired rollback admission.
New revocations still require the owner's authenticated distribution, not a cached
token or a Chain work-distance observation.

This hardens an existing product caller rather than adding an unused Chain model
installer. The PoN adapter remains submission/reconciliation plus descriptive chain
observation. An ordinary Chain-to-artifact-to-selection-to-inference coordinator,
independent genuinely future tasks, three actually installed prospective generations,
target-host resources, and production qualification remain separate obligations.
Parallel RuleSlot/Stem Draft research cannot be substituted for this exact source or
its caller, and its uncommitted work is not imported. All tests on this increment
remain controlled source tests; no model benefit or production flag is promoted.

The added composition tests obtain an opaque selection through the public ledger
snapshot, dataset freeze, signed longitudinal prepare and independent selector
admission APIs, then load and exercise the real ranker. Parent substitution keeps
candidate bytes/manifest equal and the native CURRENT genuinely signed. A delayed
CURRENT response crossing selection expiry must leave items unchanged and the cache
closed. Test signers, source facts, intervals and chronological window claims are
controlled fixtures, not independently observed future benefit.

## Explicit process installation from complete evidence

The opt-in ordinary Agentd entrypoint accepts the paired arguments
`--cognitive-bootstrap-descriptor /absolute/descriptor.json` and
`--cognitive-bootstrap-descriptor-digest <sha256>`. The host independently pins
that digest, including its trust configuration and journal anchors. A descriptor
submitted by the candidate is not a source of trusted keys. Missing one argument,
an unsupported profile, or any configured verification failure stops startup.
With neither argument supplied, no learned ranking model is installed.

The new process schema is `hepta.agentd.cognitive-bootstrap.v2`, with the explicit
`published_product_qualification_v1` profile and a four MiB descriptor limit. Its raw material
types live in `cognitive_process_evaluation.rs`, `cognitive_process_evidence.rs`,
`cognitive_process_materials.rs`, and `cognitive_process_product_wire.rs`; all objects reject unknown fields. Digests,
keys and signatures use fixed-length hex strings, identifiers retain their native
bounds, generations use positive integers, and fixed-point values use raw Q32
integers. Descriptor identity and spawn generation must match the running Agentd.
Trust descriptors, mutable material owners, and recovery journals must remain
outside the Agentd home, run root and workspace. Immutable hash-pinned payload
and snapshot copies can reside in its local cache. This path separation does
not establish independent administrators or organizations.
The bounded file opener rejects symbolic links and, on Unix, multiple hard links;
it rechecks inode identity after opening. The host must still control directory
and file write permissions. Path separation alone is not an operating-system
security boundary against arbitrary writes by the same user.

Startup recovers the original learning ledger and fenced final-holdout CAS store
against separately retained nonempty anchors. The final CAS anchor must equal
the pinned anchor; the writer fence and an already recorded product plan must
match exactly before the original runner is called. A newer takeover fence or
an unrecorded plan cannot make bootstrap consume a new holdout.

The original `ProductEvaluationRunnerV1` recomputes estimator-derived metrics
from retained raw temporal inputs. The descriptor pins the complete material
manifest and the bounded 32 MiB released-input file by SHA-256. Input release
requires the original owner's exact idempotent replay receipt. Signed longitudinal
evidence is verified again at the installation clock. The original qualification
sink then performs a real, immutable-file durable retry; execution, full decision,
and publication digests must equal the independently pinned existing record.
Only this original runner can recreate the sealed product qualification. The
bootstrap does not deserialize a receipt or accept caller-supplied metric gates.
The selection owner binds that qualification, exact candidate and predecessor
bytes, dataset, signed evaluator attestation, and independent selector admission.
The full V2 material manifest must project to the exact V1 registry manifest;
its dataset provenance must match both the model and independently selected
dataset. Model generation and Agentd launch generation are separately bound.
Every new launch generation requires a newly authorized descriptor and digest.
The experiment's explicit reinstallation does not establish automatic restart
using unchanged registered release arguments.

The process CURRENT descriptor supplies an existing artifact root, verifier
trust, and a mandatory independently signed head floor. Its reader uses the
original owner's CURRENT verification and recovery rules. The publisher keeps
the single writer fence; a separate inode-pinned observation lock serializes
reads with publish, Revoke, and recovery. Acquiring the observation lock waits
at most 250 ms and fails closed on contention or uncertainty. This deadline
does not bound the later filesystem work. Durable ACK reconciliation includes
file and directory synchronization before a readable state can be accepted.
No fitting or payload generation occurs under the observation lock.

An external writer can revoke an artifact while the inference consumer remains
alive. Every selection checks CURRENT before and after computing its result;
a failed refresh closes the cached ranker. These observations do not establish
one atomic cross-process boundary with every later effect. Artifact Revoke
does not automatically distribute external dataset-withdrawal events or erase
learned parameters. All participating readers and writers must use this source
version; compatibility with older writers that lack the observation lock is
not qualified. Trust rotation or a new model requires explicit reload with fresh
complete material. The CLI does not infer installation authority from Chain
confirmation alone.

The live observation adapter currently supports Linux and macOS file identity,
nonblocking no-follow opens, and locking. The process bootstrap rejects other
platforms before opening or replaying any evidence owner.
Other platforms return an explicit unsupported-platform error for this profile;
the pre-existing Windows writer remains available and is not qualified by the
Unix runs. Low-level artifact Host publication mutators are now crate-private:
embedding publishers use the original `LearningArtifactOwnerService`, which
owns the complete publication and observation-fence lifecycle.

These interfaces are subject to the final exact-source local qualification.
The bounded three-generation study, when run, records its actual tasks, costs,
fitting, installation, no-update, and revocation results separately. Same-host
role processes do not establish independent organizations, general model
improvement, a multi-host learning deployment, or production readiness.
