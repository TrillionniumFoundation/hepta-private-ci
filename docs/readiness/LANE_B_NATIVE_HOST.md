# Lane B: native host implementation and remaining work

This page describes executable behavior in the source, including gaps that require implementation. It takes precedence over older statements that all repository-controlled Lane B source gaps are closed.

## Actual owners and reusable components

| Function | Runtime owner | New component disposition |
| --- | --- | --- |
| Agent admission and private memory context | `hepta-agentd` | `CognitiveContext` uses the attached canonical SQLite `CognitiveStore` |
| Hosted model execution | `hepta-infer-worker --profile native-app-server` | Calls the owning Agent's existing App Server provider |
| Local model driver contract | Host still required | `codex_hepta_infer_worker_host::model_worker` exposes the manifest/grant state machine |
| Inference reservation and settlement | The native worker calls `DurableInferenceControl` | One journal and lock own local slot admission, dispatch identity and real observed settlement; economic quota remains external |
| Automation | Agentd `AutomationScheduler` + `AutomationStore`/TaskFlow/step/effect ledger (version from `AUTOMATION_SCHEMA_VERSION` in `hepta-automation/src/lib.rs`) | Codex activity is source-composed through stable App Server reconciliation; Calendar V2 creation is capability-negotiated on the existing Agentd control plane; terminal recovery scans at most 16×100 turns per pass and durably CAS-persists the opaque continuation cursor so older known turns remain eventually reachable without unbounded history reads. The final-use external-effect seam is durable, but concrete downstream product callers/owners remain independent authority, activation and evidence gates. |
| Fleet lifecycle | Existing supervisor-owned `FleetRegistry` | `lease_ledger` remains an in-memory component pending durable grants and physical observations |
| Matrix transport | Existing `hepta-matrixd`, `MatrixDurableStore` and SDK sender | `send_observer` is a reusable state machine; no duplicate sender is started |

The standalone `hepta-taskflow-runtime`, `hepta-fleet-leased`, `hepta-infer-control`, and `hepta-matrix-send-observer` entry points exit 64 with the real owner or missing integration named. Their former empty mains returned success without doing work. Existing component tests now run as library tests, with sibling test sources.

## Canonical memory to actual model execution

`AgentdMethod::CognitiveContext { query, limit }` and `AgentdClient::cognitive_context` use the normal owner/generation-fenced local protocol. The host selects its own Agent identity and private scope; callers cannot supply another scope or a success receipt.

1. Obtain one authorized cut through `CognitiveStore::lane_c_snapshot`.
2. Retrieve the existing bounded SQLite candidate set.
3. Execute `read_ids_v1` for those exact candidate IDs and require live state plus exact revision/content digest.
4. Rank only records admitted by the cut, then apply the final response budget.
5. Revalidate the owner cut and runtime generation before Agentd response publication.
6. When cognitive context is requested, the native worker first requires the advertised `cognitive.context.revalidate@1` capability.
7. After App Server connection/thread creation, the worker first syncs the durable dispatch intent that binds the actual thread/provider/context digest. It then sends the unchanged context snapshot back to Agentd immediately before physical `TurnStart`; Agentd reacquires the current owner snapshot and verifies the exact snapshot digest, selected-ID read receipt, and every selected ID/revision/content digest. Any stale binding records a durable pre-`TurnStart` stop and fails before the model effect.

The query is 1–2048 bytes and the selected result limit is 1–4. The exact-ID port accepts up to 512 IDs and is not subject to the former globally sorted first-1,024-record prefix; that deterministic false-negative path is removed. The compatibility `omitted_records` field remains in the v2 Agentd response shape and is zero for the current exact-ID product path.

The complete cognitive context and the final model attachment share one exported `MAX_COGNITIVE_CONTEXT_BYTES = 8 KiB` serialized budget. Agentd reserves space for planning metadata before admitting items; oversized items are omitted rather than silently truncated. The native worker enforces the same constant, so a context that Agentd accepts cannot later fail merely because the consumer used a smaller independent cognitive-context ceiling.

The worker sends the context as **untrusted additional context** on the actual App Server turn. It checks ready/fenced state and generation through Agentd, verifies the App Server's owning home, requests the exact configured model without fallback, creates a fresh ephemeral read-only thread and declines approval requests. During execution it continues monitoring owner readiness. Only a matching terminal notification can establish provider completion.

Final-use cognitive revalidation is a freshness observation, not an atomic lock over the SQLite owner or provider. A write after the check remains possible; no read path blocks future owner corrections/deletions or claims a future-effect lease.

Build and invoke from the repository:

```sh
cargo build --manifest-path codex-rs/Cargo.toml -p codex-hepta-infer-worker-host --bin hepta-infer-worker
hepta-infer-worker --profile native-app-server --agentd-socket /absolute/owner/agentd.sock --agent-id UUID --generation 1 --model MODEL --journal /absolute/private/native-runs.journal --request-id run-001 --maximum-in-flight 1 --context-query 'optional memory query' < prompt.txt
```

The model must be configured and authenticated in the existing owning App Server. The worker does not install credentials, select hardware or grant itself tools. The native module and its dependencies compile by default in both Cargo and Bazel. The CLI requires explicit `--profile native-app-server` selection and rejects missing or unsupported profiles before reading the prompt or contacting the provider. The prompt limit is 32 KiB, observed output limit is 1 MiB, and bounded events cap at 256. `--timeout-ms` defaults to 120000 and applies to turn observation; connection/RPC calls have separate five-second bounds. Cancellation, deadline, event loss, disconnect and fencing trigger an actual interrupt request. Interrupt acknowledgement alone is insufficient: an unobserved outcome remains `indeterminate`. The CLI prints observed JSON and exits nonzero on provider failure, interruption, indeterminacy, lost/unverified owner authority, or failed final-use cognitive validation. It never automatically replays an uncertain turn/start.

## Measured context planning

Before publishing a context, Agentd passes the actual serialized context, verified record count, source/read digests, owner identity and current host generation to `control_plane::plan_observed_context`. That helper executes the actual CNS planner and NDU evaluator for the narrow objective of delivering verified records within the shared 8 KiB cognitive-context budget. It compares read-context with abstain; empty context, ties or infeasibility abstain. Its utility axis counts observed verified items and its resource axis measures bytes; neither predicts model quality or physical capacity.

The host reserves 1 KiB inside that shared 8 KiB limit for planning metadata, adds the sealed plan digest, then checks the complete encoded response again. `evaluated_context_digest` binds the context serialized with `plan: null` before the decision. If planning abstains, returned items are empty, so this field does not claim to hash that modified response. Errors fail closed and the canonical memory cut and host generation are revalidated before publication. The one-second planner expiry bounds the request-time calculation receipt. The returned digest records that read/abstain calculation; it is not a grant or a freshness assertion for later model dispatch. This is a real, request-local NDU caller; global adaptive module reconfiguration remains separate work.

## Durable inference journal

`DurableInferenceControl` acquires a persistent `<journal>.writer.lock` sidecar lock and a data-file lock before replay, validates a candidate transition before append, syncs the journal before publishing the in-memory state and fences its writer after any ambiguous write/sync failure. Reopening a corrupt or partial record fails rather than treating an unknown operation as safe to replay. The native profile now consumes additive `reserve_native`, `dispatch_native`, `native_started`, `cancel_native` and `settle_native` ports in this same owner and file; legacy journal records remain replay-compatible. New native records are versioned `native-v1`. An older binary cannot replay them and must not replace the new owner while such records exist.

The CLI requires an absolute `--journal`, stable `--request-id` and explicit `--maximum-in-flight` from 1 to 256. The first native admission pins that limit for the journal. This is a local concurrent-run budget, not a token cap, payment authorization, hardware discovery or a global limit across unrelated journals. The file lock serializes writers; a host can hold uncertain runs while admitting another only within its pinned budget. New journals are mode 0600 on Unix and native admission rejects a group/world-accessible journal. The journal contains observed model text; use the owning Agent's private storage and retention policy. The App Server thread remains ephemeral, so process-loss reconciliation cannot assume retained provider history.

Before any provider contact, admission binds the request ID to the exact Agent/generation/model and a digest of prompt, optional memory query, socket and timeout. Before `turn/start`, a synced intent adds the actual thread/provider and the exact serialized context digest. The stable request ID also travels as `client_user_message_id`; correctness does not assume this alone provides provider exactly-once execution. The actual returned turn ID is then synced. After dispatch may have happened, duplicates and restarts never submit a new turn. A reopened record without a terminal observation becomes indeterminate and retains its slot. A completed duplicate returns the stored observation without contacting Agentd or the provider, even if that generation is no longer live; it is a historical result, not a new authorization.

Provider terminality and `owner_authority` are independent. During execution, not-ready/fenced health, identity/generation errors, transport errors and health timeouts permanently mark that attempt `Lost`; this fact is journaled before interrupt grace. Late provider `Completed` and real token counts remain observable and can release the local run slot, but never clear lost authority or make the CLI succeed. After provider unsubscribe/shutdown, an observed terminal without prior authority loss undergoes one final exact-owner health check before return and settlement; a previously lost owner remains denied without another RPC. This covers `select!` choosing completion ahead of a health tick. `ObservedReady` means ready at that last check, not atomic protection against a revocation after it. Historical journal observations missing this field load as `Unverified` and cannot become successful through replay or a later token-only update.

Pre-dispatch cancellation or connection failure records a local stop and releases its slot without fabricating provider terminality or zero tokens. After dispatch, cancellation/timeout/fencing records interrupt intent and sends the real interrupt RPC; only a matching terminal notification releases the local slot. `observed_output_tokens` remains null if no matching usage event arrived, including on terminal failure or interruption. Observed u64 counts are retained even above a synthetic token budget; no economic settlement is inferred. The typed trusted-host settlement port can refine unknown execution/usage with later matching observations, but automatic provider recovery after restart is still absent. Deleting the journal, changing the request ID or treating a missing observation as zero is not a recovery procedure.

The journal has a 64 MiB total byte budget, an 8 MiB encoded-line budget and at most 16384 retained identities across legacy/native types. Each new admission reserves its own maximum terminal frame and state-dependent metadata; the configured in-flight limit is also constrained by available byte liability. `journal_capacity_status()` reports both actual and reserved capacity. `compact_journal()` and capacity-triggered maintenance publish validated current-state checkpoints under the same stable writer lock; no terminal identity or unknown-effect responsibility is dropped. Unix publication syncs both replacement and parent directory. A crash before rename leaves old state, and one after rename recovers the complete replacement. Older overcommitted journals can drain, but receive no retrospective headroom guarantee. Do not delete `.writer.lock`, mix old/new writers, or remove the journal to recover capacity. Archive retention, external rollback fencing and identity garbage collection remain unproved.

## Neural Circuit target: preserve the owning execution path

The current automation path remains the schedule/occurrence/TaskFlow/outbox owner
listed above. Its evolution to event-driven Neural Circuits is a design target,
not another standalone runtime binary or a claim of new product execution.
Automation timers supply wake-up; direct event starts require a typed ingress/run
identity rather than a fake schedule. The TaskFlow owner persists circuit choices
and progress, existing Neuron/inference owners perform decisions, and registered
downstream owners execute effects and report terminal observations.

Implement through the existing Agentd product composition with bounded joins,
feedback, subcircuits, cancellation, resource fairness and choice-before-effect
recovery. Do not turn the inert `hepta-taskflow-runtime` entry into a second executor
or treat checkpoint receipts as cross-owner atomicity. The authoritative target
contract is [TaskFlow/Neural Circuit](../modules/automation.taskflow/TECHNICAL.md#41-neural-circuit-target-and-legacy-boundary).
All current native implementation and external-qualification limitations remain.

## Shared-experience target and source limitations

The selected Memory/multi-Agent target is in `../hnmf/TECHNICAL.md`. Existing
Agent-local stores, read-only federation, inference serving and writer hosts are
reused; no shared SQLite file or duplicate executor is introduced. Agents retain
independent canonical workspaces, sessions, current objectives, credentials, Cell
state, caches and effects while submitting permitted source/learning contributions.
Actual context delivery is source- and recipient-bound. Shared-read admission does
not authorize training or wider model distribution. Durable snapshots use per-owner
cuts and dependency validation rather than an asserted global transaction.

Current in-process federation and private scope types do not implement a new shared
training/publication protocol. The target requires named contribution admission,
purpose-specific access, training-snapshot compiler, coherent model adoption and
revocation-through-descendants tests. Cross-host enrollment/transport still needs
its own authenticated versioned boundary. Documentation/reference success does not
establish clean-Agent transfer, OS isolation, target-host performance or unlearning.

## Bounded three-group convergence

Default Agentd uses RuntimeTasks, including real automation retirement and
shutdown. Canonical preparation is reached from authenticated ObjectiveStart;
host composition supplies current owner inputs and signed evaluation, not wire
profiles. `AgentdIntelligenceInvocationV1::authoritative_provider` composes
host-installed request and seven-owner readers, checks the exact Agentd/run
fence before reading, and validates the combined immutable RunStart bindings.
The shipped CLI still does not bootstrap these readers into a native profile.
Runner-only/provider-only daemon configuration is rejected before owner services
open; a complete pair also requires Objective profile, AuthBus trust and replay
checkpoint. An unconfigured compatibility profile remains distinct. Startup
validation is not evidence of a seven-owner invocation or Circuit execution.

Automation repair recognizes displaced histories by checksums, preserves SQL,
and rejects unknown/dirty/conflicting state. Real-store tests reopen cuts before
and after repair. Shared-use grants reserve a terminal revision, while training
support binds owner/Memory/revision rather than just text.

The native terminal Cell is one-state tabular. Its same-host Replay consumer
resolves bounded indexed source records, trains a candidate and uses existing
artifact persistence/loading. Independently signed selections and bounded versioned
recovery bundles now support owner-backed restore without retraining. Every use
checks the live artifact owner, not a supplied historical registry. Full V2
manifest bytes, declared source lineage and original expiry are part of recovery;
a valid selection over the lossy V1 index alone is insufficient. Withdrawal or
expiry closes a loaded consumer. The complete native API and rejection boundaries are in
[runtime.agentd](../modules/runtime.agentd/TECHNICAL.md#same-host-shared-replay-composition).
This is not Laya training, multi-source causal transfer, remote federation,
production model selection or physical erasure of trained information.

Immutable owner records use the same file-then-directory durability barriers
on creation and exact retry. An earlier complete write that lost either sync
acknowledgement is not accepted merely because its bytes can be read. The
`owner_record_io_tests` regressions inject file-sync and directory-sync failures
independently, preserve conflicting/partial records, and check retry without
file replacement. This does not certify storage hardware, power-loss behavior
or the complete filesystem-fault matrix.

The provider qualification workflow observes immutable source-head and canonical
prospective-merge identities. Formatting is check-only; the job has no repository
write credentials and never repairs, commits or pushes its candidate. Format,
provider-seam tests and strict lint report independently through the existing
execution recorder for every matching candidate, not one numbered PR. Its
minimum four behavior tests exercise actual owner-reader invocation, existing
canonical preparation, per-owner failure propagation, fresh registry reads and
cross-Agent/generation rejection. These fixture-backed tests do not establish
that the ordinary daemon bootstraps the readers or consumes a Circuit.
Neither a failed nor an interrupted qualification can be relabeled as completion.

Dataset freezing now uses a replay-built objective-local record index and the
unchanged global revocation/unlearning cut. Unrelated ordinary records do not
force a full scan on each warm freeze. Matching-objective history, global
withdrawals, dataset output size and all cold replay still have real costs; the
independent full-scan signing-byte regression is not a sustained-load SLO.

The history workload reports append p50/p95/p99, fit/reload, indexed dataset reads
and full recovery at explicit Agent/history points. Recovery still replays full
authenticated history; the log says `not_cold_compaction=true`. Checkpoint/cold
compaction and sustained-history SLOs remain unfinished. Exact-ID lookup and
bounded pages do not certify them. Bind results to an exact committed candidate.

## Remaining implementation work

- Connect economic quota and device-capacity authorities, and implement authenticated provider reconciliation after process loss. Native local-slot reservations and observed usage settlement are wired; hosted execution does not prove local model artifacts, memory/device grants or process isolation.
- For each activated TaskFlow external effect, bind the already source-complete final-use/durable-reconciliation seam to that module's concrete provider and trusted terminal observer; do not use another module's incomplete observer as synthetic terminality. Qualify authentic/current IANA tzdb profiles, DST cases, multi-scheduler races and restore/capacity on the selected host.
- Persist resource leases under the existing Fleet owner and use real capacity/pressure observations; caller-provided capacity is not hardware discovery.
- Keep Matrix send state in the existing durable outbox with its stable transaction identity. Do not introduce a second writer around the in-memory observer.
- Supply the actual Servo/browser host, UI service integration, physical embodiment drivers and measured hardware qualification where absent.
- Wire F pipeline stages only when each stage calls its actual owner. Hashes of fabricated port receipts would not constitute learning, calibration or dispatch.

Source checks exercise real SQLite memory retrieval and withdrawal, event identity, terminality, output bounds and journal ownership/rejection. They do not establish a paid provider run, local GPU behavior, launchd deployment, homeserver behavior or long-term learning benefit. The six restored cutover/watchdog scripts pass shell syntax checks; their macOS physical scenarios require that target environment.

## Historical validation (not current-head qualification)

The results below are retained historical observations. They do not identify a
current committed candidate and must not be used as current-head receipts.

The six changed runtime libraries were built with the native App Server implementation using `just test` (the original feature-selected test build; that same implementation now compiles by default): 97 tests ran, 96 passed. The one failing pre-existing Matrix control-socket test returned `EPERM`; an independent AF_UNIX bind probe returned the same error in this execution environment. No socket restriction or test was bypassed. The new real SQLite → Lane C → NDU read/withdrawal test, worker event/terminal/output tests and durable journal locking/replay/rejection tests passed. The first high-debug link exhausted the 32 GiB workspace; after clearing generated build files, the same scoped test set completed with incremental compilation disabled and dev/test debug information disabled.

The subsequent native reservation/run/settlement increment passed all 31 inference-control and worker-host library tests with no retries or skips. These include real journal reopen/size-limit failures, duplicate driver paths against a nonexistent socket, pre-dispatch cancellation/connection failure, and matching observed usage/terminal events. Scoped `just fix`, `just fmt`, and pinned `cargo shear --deny-warnings` validate the source/build mapping. The tests do not claim an authenticated paid-provider run or post-crash provider reconciliation.

The owner-authority correction passed all 36 tests in the two inference libraries. New regressions cover readiness loss, fencing, generation/protocol errors, transport failure, health timeout, completion winning the health-tick race, late completion with retained usage, sticky journal replay and historical observations lacking authority fields. These exercise the production health/notification reducers and real journal files; they do not claim a paid-provider end-to-end run.

## Explicit learned read ranking

`AgentdConfig::with_cognitive_ranker` attaches an externally selected
`PinnedCognitiveRanker` to the existing `cognitive_context` control read path.
The host supplies owner/body generation, complete artifact/model pins and a
`CurrentCognitiveRegistry` implementation. That interface no longer returns a
bare file/receipt pair: it must return `VerifiedCurrentRegistryViewV1`, an
opaque value issued only after `learning.artifacts` verifies signed CURRENT and
the exact backing snapshot. There is no implicit CLI selection, trusted file
generator or evaluator self-authorization. The operator and artifact registry
retain their existing owners.

The ranker can only permute records already admitted by the current memory
retrieval path. Query sensors are exact query hashes; actions bind memory ID,
revision and content hash. When HNMF retrieval is configured, HNMF first narrows
the owner-generated legal set and the learned ranker then permutes that selected
set before response-count and JSON-byte limits. A missing/revoked current model
view closes the ranked read instead of falling back to a stale model. Registry
I/O runs on the blocking pool; the trusted host must bound it. The memory cut and
artifact view are rechecked before returning context.

A product adapter cannot fabricate artifact currentness from a RegistrySnapshotReceipt: only the independent artifact authority/verifier issues the opaque VerifiedCurrentRegistryViewV1. Missing, unauthenticated or revoked current views fail closed.

The fitted-model/SQLite tests prove changed control-read ordering, not improved
task utility. The deterministic HNMF assignment propensity is not the propensity
of this separately learned reranker; causal claims about learned ranking require
their own selected-policy propensity and independently observed outcomes.

## Explicit HNMF memory retrieval composition

`AgentdConfig::with_cognitive_retrieval_context` attaches an externally supplied
`CurrentMemoryRetrievalContext` for one Agent/body generation. The provider
must return a current Lane C generation vector, objective/context/cue bindings,
retrieval policy, immutable engram snapshot and dynamics policy. Agentd does not
invent missing generation fields, and `RetrievalExecutionContextV1::validate`
requires the actual retrieval policy digest to equal the Lane C
`retrieval_profile_digest`.

For this opt-in path, `cognitive_context`:

1. acquires the authorized Lane C SQLite cut;
2. calls `CognitiveStore::observe_memory_retrieval` so ranking sees the bounded
   owner generator output before legacy top-four truncation;
3. converts only owner-observed rows into generator batches, preserving exact
   revision/content/source bindings, channel rank and
   `Exhausted`/`LimitReached` completeness;
4. requires every positive-weight policy channel to have its actual owner batch
   and rejects policy-external batches;
5. runs bounded HNMF union, local engram expansion, recurrent settling and
   sparse competition;
6. intersects HNMF selections with the coherent read cut, optionally applies the
   separately selected learned ranker, then enforces response count/byte limits
   and NDU context planning;
7. revalidates the Lane C cut, exact selected memory/source support, current
   retrieval context and optional learned model before returning.

If a `CognitiveRetrievalLearningSink` is configured, the durable
`learning.ledger` owner receives the full generator-relative enumerated/legal
set, HNMF-selected set and the final delivered subset after downstream packing,
planning and final currentness checks. An empty delivered subset is recorded as
`context_exposed=false`; this prevents an HNMF selection that was later
abstained or omitted from being mislabeled as exposure.

This is a named product-host source candidate, not automatic activation. The
real Agentd process accepts the explicit `HEPTA_COGNITIVE_RETRIEVAL_MODE`
profile selector; `hnmf-required` fails startup unless an authenticated current
retrieval context has also been composed. The ordinary binary does not synthesize
an HNMF generation/current-context provider, vector encoder/vector-index owner,
learned model or release decision. The durable SQLite KG
owner supplies typed causal, procedural and contradiction-support channels; generic
graph evidence remains separate. Target
host timing/resource measurements, independent semantic review, longitudinal
outcomes, canary/promotion and release remain separate gates.
