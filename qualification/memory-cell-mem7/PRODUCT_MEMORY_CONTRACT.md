# MEM7 ordinary product memory integration contract

Status: **NOT SATISFIED / HOLD**. This is an implementation and execution
contract, not an integration receipt. New real model episodes in this audit: **0**.
The inspected source base is `39d895547fa7a50c45d580d3e30236c87f99d322`.

## 1. Reuse the actual product path

| Existing owner or entry | Relevant behavior |
| --- | --- |
| `codex-rs/hepta-infer-worker-host/src/native_run_control.rs` | `AppServerModelDriver::run` reserves an exact request in `DurableInferenceControl`; an uncertain dispatched request is reconciled, never replayed under a fresh identity. |
| `codex-rs/hepta-infer-worker-host/src/native_app_server.rs` | Creates a fresh retained `ThreadStart`, checks Agent generation/home and requested model, obtains `cognitive_context`, attaches it as `AdditionalContextKind::Untrusted`, and revalidates it before final-use entry and `turn/start`. |
| `codex-rs/hepta-agentd/src/cognitive_context.rs` | Resolves the owner cut, selected identities and bounded content; revalidates snapshot, read receipt, ranking and current retrieval context. |
| `codex-rs/hepta-agentd/src/cognitive_retrieval_context.rs` | `CurrentMemoryRetrievalContext` requires a host-authenticated current generation; caller-supplied digests do not supply that authority. |
| `codex-rs/hepta-agentd/src/production_writer_host.rs` | `remember_with_kg`, `correct_with_kg` and `forget_with_kg` use the retained production mutation capability and original writer. |
| `codex-rs/ext/hepta-memory/src/extension.rs` | Installs memory attachments and cognitive tools from trusted per-thread feature state. |
| `codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs` | Existing product tests cover owner restart, provider request contents, correction/tombstones, and an opt-in real local-provider smoke. Mock-response tests establish wiring, not learned behavior. |

`scripts/ndu_real_runtime/episodic_retrieval.py::read_memory` currently has no
ordinary Rust product caller. Its caller in `run_episodic_qualification.py`
explicitly reports `model_calls=0`. The receipt actor in `actor.py` runs the
numeric OCR-candidate `ReceiptPortfolioModel` in `neural.py`; it has no language
context input for episodic JSON. Running that network after an unrelated read
would not establish use of episodic memory.

## 2. Smallest coherent implementation

1. Keep the Rust cognitive owner authoritative. A bridge may propose Python
   episodic records, but must admit their actual source bytes and versions through
   the existing original-owner mutation path. Do not copy Python SQLite tables
   into the cognitive store or promote a hash/provenance string to verified fact.
2. Bind imported record IDs to canonical owner memory IDs/revisions, source
   receipts, dependencies and tombstones. Commit corrections and revocations in
   that owner before allowing a subsequent model read. Recheck this mapping on
   reopen; an old import cannot resurrect a tombstoned canonical record.
3. Use the existing model driver and its untrusted context attachment. A Python
   retrieval baseline may rank only currently admitted candidates. It must not
   bypass the final owner revalidation or inject memory as developer instructions.
4. Capture actual provider input/output and native dispatch/terminal receipts.
   Preserve exact prompt, model/provider identity, source/tree/config identity,
   owner generation, memory revision/cut, thread/session and effect-readback IDs.
   For hosted models, record observed provider identity without claiming a local
   weights hash. For local models, bind verified weight/tokenizer/runtime bytes.
5. Keep the frozen public selector experiment separate. These steps do not reuse
   its success counts as episodic-memory gains and do not require a new synthetic
   actor. A source-owner bridge plus its live acceptance is a separate stage;
   this document does not claim that bridge has been implemented.

## 3. Startup and genuine persistence-off

Both arms require the same frozen source, base model/provider, prompt, tools,
initial task world, budget and grader. Start a new thread for each successor;
keep its retained journal for reconciliation, but never resume the learning
thread or forward its transcript/KV state. Run each arm in a separately scoped
owner home/workspace with the same allowed initial assets.

The keys in `codex-rs/features/src/lib.rs` and the resolver in
`codex-rs/ext/hepta-memory/src/extension.rs` are:

```toml
[features]
hepta_governance = true
hepta_memory = true
hepta_memory_read_only = true
hepta_cognitive_write = false
```

This is the intended read-only evaluation configuration, not proof that a host
honored it. `codex-rs/hepta-agentd/src/app_runtime.rs` can impose required feature
states after request overrides; inspect the effective host configuration and
actual provider tool inventory. Learning writes require the authenticated writer
profile separately. Never disable its authority checks to make the run proceed.

For persistence-off, `hepta_memory=false` disables this extension's thread state;
also supply `context_query=None` to the native driver. Neither switch by itself
establishes full off. Deny all earlier-family state through automatic cognitive
attachments, recall/explain tools, session search, history notes, ordinary file
tools, summaries, skills, shared caches, other memory plugins and the workspace.
Use an empty scoped owner home for family-produced state and verify actual
provider payloads and tool reads. Do not mount the learning store in off actors.

The matching on arm exposes only admitted state through the selected path.
No grader/reference files, audit receipts, owner credentials or hidden labels
enter either actor's context. `context_query=None` merely skips the explicit
attachment in `native_app_server.rs`; it does not disable the App Server's other
memory contributors. Fail the paired run if any bypass cannot be accounted for.

## 4. Existing real-provider startup smoke

After the authorized host supplies a live loopback Responses-compatible endpoint
and its exact model ID, run from the repository root using the existing test:

```bash
export HEPTA_LOCAL_PROVIDER_BASE_URL='http://127.0.0.1:PORT/v1'
export HEPTA_LOCAL_PROVIDER_MODEL='EXACT_VERIFIED_MODEL_ID'
just test -p codex-hepta-agentd --test cognitive_product_e2e \
  --run-ignored only \
  -E 'test(=real_agentd_loopback_provider_read_only_smoke)'
```

Replace placeholders with observed host configuration; they are not a deployed
endpoint. The test requires Rust, just, nextest and repository dependencies.
It creates a fresh temporary fleet and invokes a real provider; its current
assertions check lifecycle/provider wiring, not memory benefit, independent
effects, exact weight identity or even the semantic quality of an answer.
Record the requested/observed provider and model before any research run.

## 5. Owner, effect and causal acceptance

- Learning/update/delete operations need source-owner evidence, original writer
  custody, current generation and committed mutation receipts. A same-process
  Python namespace string is not an independent trust domain.
- New-session evaluation must exercise actual model inference and produce an
  answer or proposed tool action. The authorized effect owner independently
  executes/reads back the allowed task effect. A copied `delivery.json` is not
  an independent effect readback. Reconcile lost ACKs without duplicate effects.
- Test memory on/off and retrieval/delivery interventions on identical successor
  tasks, plus current/old/deleted/wrong-source states. Keep exact KV, BM25/RAG,
  ordinary ICL and uniform replay under matched information and cost budgets.
- Restore the original memory/version owner, runtime registry, task/effect owner
  and outstanding request identities in a cold environment. Validate new reads
  and no duplicate effects. An archive restore alone closes none of these gates.
- Require a preregistered source-group estimand and uncertainty calculation on
  new source sequences, source-correct answers, deletion propagation, interference
  checks and complete write/read/inference/effect costs before adoption.

## 6. Observed execution availability and retained paths

This audit inspected the current task workspace and predecessor workspace
`/workspace/scratch/484c2ed46043`. No `.pt`, `.safetensors` or `.gguf` model was
found there by the scoped file search. No `*/target/*/hepta*` runtime binary was
found; `codex-hepta-agentd`, `hepta-authority-host`, `llama-server`, `ollama`,
`just` and `cargo` were not on PATH.
`/opt/codex/bin/codex` exists but is not verified as this repository's exact build.
Presence-only inspection found no configured `HEPTA_LOCAL_PROVIDER_BASE_URL`,
`HEPTA_LOCAL_PROVIDER_MODEL` or `HEPTA_EXTERNAL_CODEX_AUTH_JSON`. No secret content
was read. These checks are scoped observations, not a claim about every machine.

Predecessor `reference/RUNTIME_INPUT_AVAILABILITY.json` identifies these ai395
assets; they still require current host readback before use:

- Material root: `/home/qq/ndu-real-materials-20261107-audit-bffe40c2`.
- Python: `/home/qq/hepta-smollm2-weight-research-20261103/ci-env/bin/python`.
- OCR root: `/home/qq/ndu-real-runtime-20261107-bc2efaf10cd0/portable-ocr-v1/root`.
- OCR actor weights: `/home/qq/cell-causal-abcde-20261108-cf0/evaluation-b-v1/cloud-return/results/b/models/independent/s104729/hepta/reset/content/weights.pt`.
  Expected size 72,247 bytes; SHA-256
  `313743619c25f7449c30982d5f2dcc96e574a9bc41730eb5c9551fb568fb57ac`.

Those assets are a receipt/OCR model, not an observed language-model endpoint.
No endpoint, production owner socket, source-owner grant or effect authority was
verified by this audit. The ordinary-product episodic benefit gate remains HOLD.
