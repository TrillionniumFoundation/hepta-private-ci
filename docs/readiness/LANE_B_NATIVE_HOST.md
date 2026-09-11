# Lane B: native host implementation and remaining work

This page describes executable behavior in the source, including gaps that require implementation. It takes precedence over older statements that all repository-controlled Lane B source gaps are closed.

## Actual owners and reusable components

| Function | Runtime owner | New component disposition |
| --- | --- | --- |
| Agent admission and private memory context | `hepta-agentd` | `CognitiveContext` uses the attached canonical SQLite `CognitiveStore` |
| Hosted model execution | `hepta-infer-worker` with `native-app-server` | Calls the owning Agent's existing App Server provider |
| Local model driver contract | Host still required | `codex_hepta_infer_worker_host::model_worker` exposes the manifest/grant state machine |
| Inference reservation and settlement | Host still required | `codex_hepta_infer_core::durable_control` exposes a single-writer journal; no reservation authority is invented |
| Automation | Agentd's existing `AutomationScheduler` and `AutomationStore` | `effect_executor` is an in-memory component; durable TaskFlow effect wiring remains work |
| Fleet lifecycle | Existing supervisor-owned `FleetRegistry` | `lease_ledger` remains an in-memory component pending durable grants and physical observations |
| Matrix transport | Existing `hepta-matrixd`, `MatrixDurableStore` and SDK sender | `send_observer` is a reusable state machine; no duplicate sender is started |

The standalone `hepta-taskflow-runtime`, `hepta-fleet-leased`, `hepta-infer-control`, and `hepta-matrix-send-observer` entry points exit 64 with the real owner or missing integration named. Their former empty mains returned success without doing work. Existing component tests now run as library tests, with sibling test sources.

## Canonical memory to actual model execution

`AgentdMethod::CognitiveContext { query, limit }` and `AgentdClient::cognitive_context` use the normal owner/generation-fenced local protocol. The host selects its own Agent identity and private scope; callers cannot supply another scope or a success receipt.

1. Obtain a read transaction cut through `CognitiveStore::lane_c_snapshot`.
2. Execute the new bounded `ReadRequestV2` port on that cut.
3. Rank with the existing SQLite retrieval provider and accept only exact record ID, revision and content digest matches admitted by the cut.
4. Return the original verified memory text, then revalidate the owner cut and runtime generation before response publication.

The query is 1–2048 bytes and the requested result limit is 1–4. The Lane C read admits at most 1024 records and 1 MiB of canonical encoding. Intersecting that bounded record prefix with search candidates can omit relevant records outside the prefix; `omitted_records` reports the read truncation. The complete context payload is bounded to 24 KiB of JSON encoding, including escaping and its envelope. Oversized items are omitted, not silently truncated. This is verified memory retrieval, not evidence of learned model weights or complete recall.

The worker uses this context as **untrusted additional context** on the actual App Server turn. It checks ready/fenced state and generation through Agentd, verifies the App Server's owning home, requests the exact configured model without fallback, creates an ephemeral read-only thread, and declines approval requests. During execution it monitors owner readiness. It observes matching thread/turn output and usage events; only a matching terminal notification can establish completion.

Build and invoke from the repository:

```sh
cargo build --manifest-path codex-rs/Cargo.toml -p codex-hepta-infer-worker-host --features native-app-server --bin hepta-infer-worker
hepta-infer-worker --agentd-socket /absolute/owner/agentd.sock --agent-id UUID --generation 1 --model MODEL --context-query 'optional memory query' < prompt.txt
```

The model must be configured and authenticated in the existing owning App Server. The worker does not install credentials, select hardware or grant itself tools. Without the feature, the binary exits 64. The prompt limit is 32 KiB, observed output limit is 1 MiB, and bounded events cap at 256. `--timeout-ms` defaults to 120000 and applies to turn observation; connection/RPC calls have separate five-second bounds. Cancellation, deadline, event loss, disconnect and fencing trigger an actual interrupt request. Interrupt acknowledgement alone is insufficient: an unobserved outcome remains `indeterminate`. The CLI prints observed JSON and exits nonzero on failure, interruption or indeterminacy. It never automatically replays an uncertain turn/start.

## Durable inference journal

`DurableInferenceControl` acquires an exclusive file lock before replay, validates a candidate transition before append, syncs the journal before publishing the in-memory state and fences its writer after any ambiguous write/sync failure. Reopening a corrupt or partial record fails rather than treating an unknown operation as safe to replay. This improves the component's storage integrity; a production caller still must supply real reservation, assignment and terminal observations from the respective owners.

## Remaining implementation work

- Connect durable inference control to authenticated reservation/worker authorities, durable operation identity and actual usage settlement. Hosted App Server execution does not prove local model artifact, memory/device grants or process isolation.
- Connect TaskFlow's existing durable step outbox to a real final-use-authorized effect provider and crash reconciliation. Queue acceptance must remain distinct from effect completion.
- Persist resource leases under the existing Fleet owner and use real capacity/pressure observations; caller-provided capacity is not hardware discovery.
- Keep Matrix send state in the existing durable outbox with its stable transaction identity. Do not introduce a second writer around the in-memory observer.
- Supply the actual Servo/browser host, UI service integration, physical embodiment drivers and measured hardware qualification where absent.
- Wire F pipeline stages only when each stage calls its actual owner. Hashes of fabricated port receipts would not constitute learning, calibration or dispatch.

Source checks exercise real SQLite memory retrieval and withdrawal, event identity, terminality, output bounds and journal ownership/rejection. They do not establish a paid provider run, local GPU behavior, launchd deployment, homeserver behavior or long-term learning benefit. The six restored cutover/watchdog scripts pass shell syntax checks; their macOS physical scenarios require that target environment.
