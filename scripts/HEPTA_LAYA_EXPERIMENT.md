# Pinned Laya retrieval experiment

This is an experimental leaf of the existing Neuron/inference learning work,
not a second execution owner, source ledger, global plan, evaluator authority,
or production organ. The canonical ownership and development policy remain in
`docs/DEVELOPMENT.md`. No model installation, caller activation or promotion is
performed by these scripts.

## Implemented boundary

`hepta_laya_retrieval.py` verifies a local CPU/fp32 bundle, Laya SDK 0.3.20 and
runtime package versions. The initially observed upstream model revision is
`convaiinnovations/laya@55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851`.
A local hash records actual bytes; it does not authenticate their origin.
The five mandatory artifacts and every optional file under `encoder/` and
`tokenizer/` are hashed. Symlinks, altered files, silent tokenizer rewriting,
CPU mixed-precision mode and token truncation reject. The private encoding API
is intentionally SDK-version-bound. Runtime package versions are not binary
attestation: immutable, independently verified package installation is still a
host responsibility.

An input binds operation/workspace/generation, objective, observation, bundle,
query and exact source revisions/bytes. The output can only select an input
source or abstain. It binds the complete ordered candidate set and predictions,
plus a separate deterministic behavior policy and propensity. Model confidence
and `act_probability` issue no authority. Exceptions, timeout and withdrawal
produce no valid result and never trigger an automatic model retry.

`hepta_laya_experiment.py` compares lexical ranking, a four-parameter classifier,
frozen Laya (the no-change baseline), and a trained four-parameter head over
frozen Laya/lexical features. It does not fine-tune Laya weights or implement
organ credit, general recursive NDU, LoRA or structural plasticity. The local
head uses bounded deterministic cross-entropy descent and held-out temperature
selection. Insufficient training data leaves the Laya head unchanged.

Training, calibration, future-event evaluation and retention partitions must all
be present. Task groups and normalized queries cannot cross partitions. Training
labels must predate calibration events, and calibration labels must predate
future events. Separately supplied annotations never enter model input. These
checks do not detect every semantic duplicate or authenticate the observer.
Source text may be shared when legitimately needed across different tasks.

All comparisons use one declared resource ceiling, not equal observed cost.
Worst-case input-token capacity is reserved before each experiment call; the
observed token total cannot reset between rows. Collection is physically shared
once, while each Laya arm reports the inference cost it requires. Training,
calibration and scoring times are retained separately. CLI bundle verification
and loading time are measured separately from the steady-state budget. Memory,
power, asynchronous provider reconciliation and native migration are unmeasured.
A deadline check is not hard process preemption; the native inference worker must
enforce isolation and interruptibility when this becomes a product path.

## Run locally with explicitly provisioned weights

Use a separately provisioned environment with Laya 0.3.20 and dependencies. Nothing
here downloads a model. Materialize the reviewed checkpoint locally, including
`model.safetensors`, `rl_agent_config.json`, `encoder/config.json`,
`tokenizer/tokenizer.json` and `tokenizer/tokenizer_config.json`. Normalize any
SDK-incompatible tokenizer configuration into a **separate candidate bundle**,
then hash that effective bundle rather than claiming unchanged upstream bytes.
Set offline flags before loading Python dependencies:

```sh
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
python3 scripts/hepta_laya_retrieval.py --model-root /absolute/model \
  --revision 55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851 > /tmp/laya-bundle.json
python3 -c 'from pathlib import Path; from scripts.hepta_laya_retrieval import digest,strict_json; print(digest(strict_json(Path("/tmp/laya-bundle.json").read_bytes())))'
python3 scripts/hepta_laya_experiment.py --model-root /absolute/model \
  --bundle /tmp/laya-bundle.json --bundle-digest <PRINTED_SHA256> \
  --dataset /absolute/dataset.json --annotations /absolute/annotations.json \
  --budget /absolute/budget.json > /tmp/laya-experiment.json
```

Missing weights/dependencies, incompatible pins, invalid splits, unavailable
inference and budget exhaustion are failures, not skipped successful experiments.
The caller must retain stderr/nonzero exit diagnostics; no incomplete JSON report
is evidence of improvement. Output files should be outside the repository tree.

Dataset fields:

- Top level: `schema="hepta.retrieval.dataset.v1"`, `workspace_id`, nonzero
  SHA-256 `objective_digest`, and `rows` (1..10000).
- Each row: `row_id`, `group_id`, `split` (`train`, `calibration`, `future`, or
  `retention`), positive `event_at_ms`, `query`, `sources` (1..15).
- Each source: `source_id`, positive `revision`, `content_sha256` of its exact
  UTF-8 text, and `text`. Query and individual text are bounded to 2048 bytes.
- Separate annotations: `schema="hepta.retrieval.annotations.v1"`, canonical
  `dataset_digest`, `observer_id`, `labels`. Each label contains `row_id`,
  `correct_source` (admitted source ID or null), and `observed_at_ms`.
- Budget: `per_request_ms`, `max_total_input_tokens`, `max_elapsed_ms`,
  `minimum_train`, `epochs`. Defaults are 5000, 131072, 600000, 32, 40.
  A supplied budget JSON may omit defaulted fields; unknown fields reject.

Digests use UTF-8, sorted keys, compact JSON, preserved array order and no NaN or
Infinity. Untrusted JSON duplicate keys reject. The tests construct small
**synthetic** datasets demonstrating the schema; they are not training evidence.

## Verification and remaining product integration

```sh
python3 -m unittest -v scripts.tests.test_hepta_multiscale_scope \
  scripts.tests.test_hepta_laya_retrieval scripts.tests.test_hepta_laya_experiment
cd codex-rs
just test --locked -p codex-hepta-automation --test convergence_recovery
```

The workflow `hepta-multiscale-regressions.yml` binds source-head and deterministic
base-merge checks to the actual Git event. It uses read-only permissions and the
existing exact-execution recorder. Ordinary prose does not select native recovery
work. This workflow does not replace `CI required` or `Architecture required`.
Python tests use explicit doubles; Rust tests exercise the existing owner store
across close/reopen. Neither is a real-model, live-browser, power-loss or kill-9
qualification. A missing/failed native result remains missing/failed.

The native semantic input/output boundary below is now source-implemented.
Existing `NeuronFeatureRequestV1` still carries numeric features and is unchanged.
Current `PinnedCognitiveRanker` loads an independently selected tabular artifact.
Do not bypass that selector or instantiate this script as an unrestricted Agentd
model server. Product integration still needs a qualified concrete transport,
durable reservation and exact-result replay, source/registry currentness at final
use, artifact approval/revocation, then real task data on fixed hardware. The
advisory callback here is not a sealed capability and cannot supply permissions.

Controlled computer effects and stateful topology cutover remain with their
existing owners. No arbitrary process-memory writes, automatic computer actions,
writer replacement, force merge, evaluator change or production activation are
added. Full five-stage completion requires their separate executable evidence.

## Native semantic data profile and worker extension

`codex-rs/hepta-infer-core/src/semantic_retrieval.rs` owns the new bounded
`SemanticRetrievalRequestV1` and reply decoder. `hepta_retrieval_wire.py` is the
matching leaf codec. Requests use magic `HPTARQ` followed by version byte 1 and
zero; replies use `HPTARS` with the same version bytes. Integers are big endian,
strings have u32 byte lengths and digests are raw SHA-256. There is no native
pointer, machine code, command line, authority token or arbitrary JSON field in
the wire. The whole frame is bounded to 64 KiB; query/source text is bounded to
2048 UTF-8 bytes, with 1..15 distinct sources and positive bounded revisions.
The request binds the exact supplied source order. Probabilities have a distinct
canonical order: abstain, then source IDs sorted by ASCII. Their integer ppm
mass is exactly one million. Neither a prediction nor its wire hash authorizes
an action or independently proves the model ran.

The request carries operation/workspace/generation, objective/observation/bundle
identities and an absolute Unix-millisecond deadline. The loaded model manifest's
model digest must equal the selected bundle digest for this profile. The result
binds the exact full request bytes, bundle, complete prediction vector and
observed token/latency values; request/bundle/shape drift rejects. Existing JSON
experiment digests retain their old meaning and are not replaced by wire hashes.

`InferenceWorker::run_semantic_retrieval` calls an explicitly supplied
`SemanticRetrievalDriver` through the existing loaded handle, grant validation,
active-request map and per-model active count. Its maximum_tokens is a total
input-plus-output token bound. Error, malformed output, missing measurement or
observed budget overrun retains the active identity instead of permitting replay
or unload. Pre-entry cancellation has a distinct error and is checked only after
an existing unknown request has been ruled out. The driver trait is not a
sandbox or durable result store. No production implementation of its transport
or Agentd startup selection is supplied by this profile.

The Python leaf entry point reads one complete binary frame from stdin, checks
it before loading a pinned model, scores once and writes one binary reply. It
has no retry/fallback loop. For a separately admitted request/model environment:

```sh
python3 scripts/hepta_laya_worker.py --model-root /absolute/model \
  --bundle /tmp/laya-bundle.json --bundle-digest <PRINTED_SHA256> \
  < /absolute/request.bin > /tmp/reply.bin
```

The host must close stdin, bound wall time, isolate/terminate the process, measure
resources and revalidate current sources/artifacts before consuming the result.
The Python currentness callback only describes immutable supplied bytes; it is
not a live revocation oracle. Startup/loading costs, device attestation, token
reservation persistence, authenticated negative outcomes and cross-process
reconciliation remain host work, not claims inferred from a successful frame.

Focused checks (native execution must actually succeed before claiming a pass):

```sh
python3 -m unittest -v scripts.tests.test_hepta_retrieval_wire
cd codex-rs
just test --locked -p codex-hepta-infer-core --lib semantic_retrieval::tests
just test --locked -p codex-hepta-infer-worker-host --test model_worker_lifecycle
```

The Python suite has 23 tests, including exhaustive frame-prefix truncation,
Unicode/byte limits, scope/ordering drift, mutation, expiry, no retry and three
actual subprocess pre-model rejection cases. The Rust suites add nine native
wire conformance cases and twenty worker lifecycle cases using deterministic
fixtures, not weights. Execution of one language is not proof that the other
compiled or that real model/device/retention performance was measured.
