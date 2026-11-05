# Product convergence target and acceptance contract

## Direction and authority

The target is a governed, recoverable, auditable AI cognition and execution
runtime. Adaptive capability advances only when independent evidence supports
it. Dependable task completion is the first product milestone; adding another
learning mechanism does not establish that milestone.

This engineering record applies the existing [architecture invariants](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/732e934ba496d90fbe042b8d41d479ef901643e5/docs/architecture/ARCHITECTURE.json).
It grants no runtime, writer, model, tool, effect, selection, promotion or
release authority. The lifecycle stages below are an acceptance model, not a
claim that the complete Control owner has been implemented.

- App Server remains the only model, session, thread, turn and tool spine.
- Agentd hosts lifecycle and composition; it owns no durable product fact.
- Each durable domain retains one schema owner and authoritative writer.
- Candidate generation, observation, evaluation, selection and promotion use
  distinct identities and independently verifiable evidence.
- Hard objectives, source truth, authority, privacy, deletion and writer ownership remain
  outside learned parameters. Each active request uses one frozen generation.
- Uncertain effects remain unresolved until the current owner reconciles them.
  Queue or dispatch acknowledgement cannot establish terminal effect success.

## A. One dependable product task

The first release slice must demonstrate the complete chain on one actual
implementation and retain the same identities across process loss.

| Boundary | Existing responsible component | Required observable evidence |
| --- | --- | --- |
| Goal and objective admission | Objective ingress, objective.compiler and current authority | Original signed request, immutable objective revision, budgets and stop conditions |
| Context and memory | context.compiler and existing source/memory owners | Bounded provenance, source freshness, deletion checks and the frozen artifact generation |
| Cognitive preparation | intelligence.control and its seven composed owners | Exact candidate, completeness, context and policy identities; abstention remains valid |
| Durable pre-execution handoff | Learning-ledger owner, through an additional typed handoff record/reader that still needs implementation | Original typed signed Decision request, immutable RunStart binding and verified readback; no rewrite of immutable RunStart |
| Execution | App Server through Agentd composition | Owner-issued operation/thread/turn identity for lookup and reconciliation after restart |
| Effect admission | kernel.operations and checked effect adapters | Current final-payload-bound VerifiedUse, local intent/outbox, destination dedupe and acknowledgement |
| Terminal confirmation | Execution/effect owner and independent observer | Applied, not applied or quarantined status tied to the original operation; authenticated Outcome |
| Evidence and restart | Existing durable owners, witnesses and recovery order | Exact fact replay without a second event/effect, source-ledger recovery before projections |

The existing RunStart journal durably preserves original claims and signatures;
Agentd's `require_current_run_start` performs current cryptographic, epoch and
fence revalidation. `LedgerWriter` owns typed Decision/Outcome appends. A
post-preparation handoff still needs a new typed record and reader under the
declared owner; the immutable RunStart cannot be rewritten to add it later.

The current canonical Agentd path stops at owner preparation and transient
run/context admission. Its `canonical_ready` result does not establish App
Server execution or authenticated Decision/Outcome composition. The optional
legacy pending-append carrier is in memory and cannot close this default path.
The [recovery review](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ebdf792c076c1d516ae9f96eec079921ccd1588f/qualification/runtime-convergence-20261105/product-recovery-review.md)
identifies the existing owners and the missing producer, durable carrier,
operation correlation and observer integration.

Acceptance must kill the process after RunStart, after the durable handoff,
across uncertain dispatch acknowledgement, after an actual terminal effect,
and between ledger sync and witness acknowledgement. Recovery must load the
original persisted signatures and operation identity. Reconstructing fixture
requests, keeping a prepared object alive, or starting a replacement turn does
not prove recovery. Expiry, revocation, changed generation, corrupt history and
payload mismatch must retain historical identity while refusing new admission.

## B. Replaceable adaptive candidates with a valid no-update outcome

NDU, Neuron, parameter memory, prompt optimization and plasticity enter as
replaceable candidates. Existing models, structured planners, typed KV,
retrieval and the unchanged predecessor remain valid baselines and fallbacks.
Every selection includes no change. Failed admission retains the predecessor;
it does not silently promote a best-of-failed-candidates result.

| Question before promotion | Required evidence |
| --- | --- |
| Better than what? | Named strong baseline, unchanged predecessor and a prespecified decision rule |
| Same information and budget? | Comparable source access, observations, model/tool permissions, latency and resource budgets |
| Controller or generator effect? | Feasible controller-by-generator comparisons and ablations; separately report interaction and unsupported combinations |
| Complete cost? | Log chosen and unchosen candidates, failures, retries, execution, planner, critic, evaluation and training costs |
| New-sample benefit? | Independent future-time holdout, frozen plan, one-use ownership, complete outcome provenance and support diagnostics |
| Safe retention and rollback? | Current authority, retention, deletion non-resurrection and an independently accepted predecessor/rollback identity |

The current source changes authenticate both complete temporal plans before
holdout release, seal the complete public decision, and require that sealed
qualification at the three identified consumers. Current-use verification
rechecks the original evidence with current host trust/time and binds the
qualification/publication identities downstream. None of these structural
checks is a measured efficacy result.

A production data provider, publication sink, full sealed-receipt persistence
and verified readback remain required. A durable digest commitment alone is
not recovery of the complete receipt. Changing trust, signing domains or use
commitments requires the appropriate current-owner issuance/signature; it does
not permit old-signature fallback or reuse of an already consumed holdout.

## C. One recoverable Control lifecycle for all topology changes

Add, replace, split, merge, retire and rewire each produce a bounded
next-generation candidate. They must pass the same lifecycle, with operation-
specific migration evidence. The active graph is never edited in place.

| Stage | Required owner decision and durable evidence |
| --- | --- |
| Propose | Content-addressed source/build manifest, exact module/edge delta, capability/resource bounds and rollback predecessor; activation remains forbidden |
| Validate | Acyclic typed graph, one writer per domain, bounded resources, compatible protocols, no optimizer-to-effect or qualification-to-writer edge |
| Qualify | Independent shadow/fault/ablation evidence, exact candidate identity, migration and rollback witnesses |
| Select | Independent signed immutable next-generation snapshot and current Control authorization |
| Prepare handoff | Owner-local durable intent, old-writer fence, migration digest, drained outboxes, consumer cutover plan and new-writer readiness |
| Commit and observe | Authoritative generation/CNS compare-and-swap plus readback; complete owner handoff receipt proves fencing, migration, drain, actual consumer cutover, new-writer readiness and rollback viability before handoff or activation is considered complete |
| Canary and accept | Bounded observation under current authority and independent acceptance of actual results |
| Recover or roll back | Resume the recorded transition using current generation/revocation floors; reconcile uncertainty and preserve deletion/non-resurrection rules |
| Retire | Revoke old reach, complete drain/reconciliation and preserve auditable history after consumers have cut over |

Control records its own lifecycle intent and decisions. Each domain's existing
writer owns its handoff facts, outbox and acknowledgements; Agentd does not
become a second writer. A shared lifecycle coordinates these records without
pretending that distributed effects form one atomic transaction.

Interrupted transitions must survive process loss at every stage. They must
not activate two writers, reuse a stale generation, synthesize authority or
restore deleted artifacts during rollback. Degraded central control still
permits bounded local stop, revoke, drain, reconciliation and last-known-good
operation.

The public topology apply/recovery boundary currently refuses admission because
the complete durable Control owner is unavailable. This refusal remains until
current-generation checks, revocation/recovery floors, authoritative CAS and
readback, handoff witnesses and physical recovery evidence are present.

## Release decision

Native package tests and behavioral mutation controls establish specified
source properties. Exact-head and ordered merge-candidate CI, original Windows
attacks, real provider/effect acceptance, restart trials and independently
signed efficacy/release evidence remain separate gates. Use the timestamped
validation records for actual results; a queued, skipped or build-failed job
does not satisfy a gate.

The next coherent product implementation is the owner-backed A-line handoff
and execution/observation composition. B-line publication/readback and C-line
Control handoff can advance in parallel under their existing owners. Candidate
quality never substitutes for execution authority or terminal effect evidence.
