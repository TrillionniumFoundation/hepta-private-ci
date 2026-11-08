# PERC-1 implementation and qualification

PERC-1 now has a native dual-channel observation contract, a consumer in the
existing Cell inference path, advisory acquisition proposals, a four-arm
experimental trace validator, and a paired terminal-answer replay diagnostic.
Scientific qualification remains **HOLD** until a frozen, independently evaluated
real-task experiment demonstrates final task benefit.

Read [PROTOCOL.md](PROTOCOL.md) for the experiment and
[SOURCE_AUDIT.json](SOURCE_AUDIT.json) for research sources and source identities.
Machine-readable execution records are retained beside this document. Engineering
tests and synthetic fixtures do not count as real model training or task confirmation.

## Implementation

| Component | Entry point | Behavior |
| --- | --- | --- |
| Actor source and exact evidence | `hepta-neuron/src/perception_source.rs` | Captured bytes and source coordinates are checked against the host's bounded actor-visible source window. Image/video regions use the pinned raw layout. |
| Dual-channel observation | `hepta-neuron/src/perception.rs` | Evidence and local latent values bind by digest. Global/dense modes retain the same evidence. Decoder rejects unknown fields, bad links and bounds. |
| Native Cell consumer | `PerceptionCellEncoderV1` | Implements the existing encoder interface, preserves latent order, checks scope/frontier/encoder/model, and consumes the complete bounded input. |
| Acquisition proposal | `PerceptionObservationProposalV1::assess` | Binds the observation, predictor, NDU snapshot, target source extent and task cost ledger. The result is advisory and grants no execution authority. |
| Four-arm experiment | `scripts/perc1` | Validates shared initial observations, fixed schedules, actor prefixes, costs, source groups, four-arm/seed pairing and exact final answers. |
| Native interchange | `scripts/perc1/native.py` | Exports bytes-only native observations; a shared JSON fixture verifies Python/Rust agreement. Other modalities require explicit capture/decoder adapters. |
| Extra-observation diagnostic | `scripts/perc1_marginal.py` | Compares terminal answers after identical prefixes differing by exactly one new captured observation, with matched scope and frozen continuation identity. |

The native adapter is exercised through the actual existing
`prepare_cell_step -> infer_cell -> InferenceControlModelPort -> decide_cell ->
commit_cell_step -> enter_cell_step` library path. The test uses a capture control
port and hand-authored latent values; it does not run V-JEPA or a newly trained
encoder. Completed operation replay avoids re-encoding and redispatch. Altered raw
evidence with a reused operation identity is rejected.

## Run the engineering checks

From the repository root:

```bash
python3 -m unittest discover -s scripts -p 'test_perc1*.py' -v
PYTHONPATH=scripts python3 -m perc1 smoke --output /tmp/perc1-smoke
PYTHONPATH=scripts python3 -m perc1 report \
  /tmp/perc1-smoke/manifest.json \
  /tmp/perc1-smoke/dataset.json \
  /tmp/perc1-smoke/traces.json \
  /tmp/perc1-smoke/evaluator.json \
  --output /tmp/perc1-report.json
```

The source-pinned local run passed **24 Python tests**. The smoke creates **32
paired traces**: four task-family descriptors, four arms and two declared seed
receipts. These are synthetic descriptors, including text stand-ins for media.
There are no independently trained models behind those seed receipts. The smoke
and report must retain `status=HOLD` and `scientific_qualified=false`.

The full native library gate passed **190 tests, with zero failures and zero
skips**, including **16 new perception tests**. Its tested commit is
`6745ba2c4da1657ab44b462857a9d010903b9d62`, tree
`6369cd9417437fb7ac20225f28d165c115f55125`.
The existing joint helper was rebuilt and hash-pinned before the tests. Later
maintenance/source records distinguish tested source from formatting and evidence
commits; do not substitute a later HEAD for the recorded test subject.

Native verification uses the repository's `just test` entry point:

```bash
cd codex-rs
just test --locked -p codex-hepta-neuron --lib
```

The crate's existing joint-process tests require the built `hepta-joint-propose`
helper. The retained execution record identifies that actual build and executable.
The qualification run also uses scoped Clippy and the repository formatting entry
point; their exact outcomes belong in the execution record.

## Bring real experimental traces

`scripts/perc1/example_manifest.json` is an intentionally incomplete template.
It rejects execution until actual identities and a registered dataset are supplied.
Do not turn placeholders into arbitrary hashes: bind the real artifacts, independent
training runs, actor-only inputs, held-out source groups, evaluator and budget.

The frozen input and output files are separate:

| File | Role |
| --- | --- |
| Manifest | Model/controller/preprocessor identities, dataset hash, training receipts, budget and thresholds |
| Dataset | Actor-visible task/inventory, captured-view paths, hashes, lengths, coordinates and availability times |
| Traces | Actor prefix hashes, proposals, reservations, outcome, complete phase charges, admitted evidence and terminal answer |
| Evaluator | Sealed targets, required evidence, exact critical fields, canaries and separate evaluation cost |

Every cost receipt lists acquisition, encoding, communication, decision, planning,
inference, waiting, training, evaluation, failure and cancellation. Training and
evaluation are charged once in separate receipts. Unknown acquisition outcomes retain
pending reservations and require owner reconciliation. A source alias with identical
capture content and locator is not counted as new evidence.

The reporter computes dense and active main effects, their interaction, and the
joint contrast. It uses source-group and seed resampling, paired across arms, and
reports unadjusted diagnostic intervals. A complete paired matrix is required.
The report validates structure and computes descriptive thresholds; it does not
authenticate model execution, billing, training independence, preregistration time
or original-media transformations, and cannot grant scientific adoption authority.

## Audit a single extra observation

The marginal input is a `perc1.marginal-pair.v1` record containing `without` and
`with` traces, the frozen dataset snapshot hash, continuation identity and inference
seed. The `without` steps must exactly equal all but the last `with` step. The last
step must deliver one genuinely new capture and charge its cost. Both terminal
answers are scored against the sealed evaluator.

```bash
PYTHONPATH=scripts python3 scripts/perc1_marginal.py \
  manifest.json dataset.json evaluator.json pair.json \
  --output marginal-report.json
```

The result reports changes in final correctness and critical-field fidelity plus
incremental cost. It leaves net utility unset until a cost-value rule is frozen.
Caller receipts do not prove that the continuation model actually ran with the
declared seed; the result is a static-replay diagnostic. Real online causal claims
need controlled continuations or the randomized design in the protocol.

## Remaining qualification work

1. **Real encoder execution.** Register and run a learned encoder and its exact
   checkpoint/preprocessor. Bind the produced local latent values to the actual
   inference-worker receipt. A declared model digest alone does not do this.
2. **Input and context admission.** Connect real document, GUI and video capture
   organs with authenticated provenance and availability. Use the existing
   `context.compiler` V2 admission/revocation/delivery verification before presenting
   raw evidence to a model. This change does not activate that production wiring.
3. **Runtime acquisition ownership.** Connect advisory proposals to the current
   source permissions and runtime budget owner. Recheck current policy, reserve,
   execute, settle or reconcile. Proposal assessment is not a reusable admission.
4. **Real PERC-1 confirmation.** Register four real task panels, match full training
   opportunities, freeze the practical benefit and field-fidelity thresholds, and
   evaluate independent source groups and training seeds once. Full costs and final
   task benefit determine qualification; probes remain diagnostic.

The public candidate is an extension of Cell candidate `6ddfca24`; main is separately
pinned at `732e934b`. Source publication, main integration, production activation and
scientific qualification are distinct observations.
