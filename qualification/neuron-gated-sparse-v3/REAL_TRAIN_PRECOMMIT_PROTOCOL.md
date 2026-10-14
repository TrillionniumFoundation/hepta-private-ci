# Five-arm: physical training, future precommit and independent review (research-only)

This stack continues draft #1765. It is deliberately **not** a change to main,
production Neuron, Q24 V1/V2/V3 replay/wire bytes, model selection or the CNS
route. A real selected Cell owner, target host and independently provisioned
keys are NOT available to this code. Source tests and synthetic canaries can
verify mechanics and reject invalid evidence; they cannot invent A0 or A4.

## A0: first freeze the actual selected owner

Before a real trial, independently execute the existing
'a0_deployment_evidence.py' against the authenticated target Cell owner:
signed registry, every active Cell, selected manifests/weight bytes, committed
checkpoint/reopen, actual model invocations and host resource receipts.
Only use a real frozen V1 artifact selected at the authenticated snapshot.
'matched_train.py' checks its physical SHA256, but DOES NOT itself authenticate
deployment or read the owner; A0 remains externally blocking. If there is no
owner-approved baseline, do not replace it with a random model.

## A1/A2/A3: physically train four candidates, never train V1

The offline, CPU-only 'matched_train.py' accepts a SHA256-pinned **training
dataset only**, an externally selected V1 artifact, and positive common
optimizer steps. It rejects training events after the frozen cutoff, group
sequence/clock regressions, duplicate cases, extra fields, oversize features,
out-of-range Q24 inputs and non-binary labels. It never reads heldout, OOD or
future files. One invocation is for a single Cell scope.

Training uses a common generated source-group schedule, Torch AdamW CPU,
identical training steps/window/seed, and per-cap physical 'safetensors'
reloading. The arms are V2, V3, diagonal SSM, and low-rank minGRU. Budgets are
2K/8K/16K/64K/262K upper ceilings, NOT padded equality. Identity projection,
Head and trainable temporal factors are counted; miniGRU rank must fit the
complete private footprint. At 256 dimensions minGRU cannot fit the 2K
tier with a private projection/Head; choose smaller common width or an
independently justified cost profile instead of hiding parameters.
Independent optimizer-state estimate and process-wide RSS are recorded
separately and are NOT arm-isolated peak RSS or target-host measurements.

The floating-point learning kernel is a **restricted differentiable surrogate**.
It approximates V2 sparse local/global top-k with a fixed identity projection
and has no native production inhibition/homeostasis/eligibility or exact Q24
rounding. Candidate frozen gate/factor parameters are exported as int64 Q24;
Head weights are floating point. Structural tensor count/shape and physical
roundtrip are checked, but this code DOES NOT claim native Rust prediction
equivalence, learned performance or a complete production-selected model
bundle. The exact frozen projection and parameter inventory are experiment
specific, not a replacement for a registered native config.

Pinned training input JSON shape:

    {
      "schema": "hepta.neuron.frozen-q24-train-input.v1",
      "encoder_digest": "<64 lowercase hex>",
      "cell_id": "one-scoped-cell",
      "train_cutoff_utc": "2026-10-01T00:00:00Z",
      "samples": [
        {"case_id":"train-1","source_group":"train-group-1","sequence":1,
         "event_time_utc":"2026-09-30T00:00:00Z",
         "feature_q24":[<5..256 signed Q24 integer coordinates>],"label":0}
      ]
    }

Minimum two rows, each group at most 256 rows, at most 128 groups, all
source groups must have strictly increasing event clocks and sequences.
The Encoder digest is a *claim* until independently tied to an actual pinned,
physically executed frozen Encoder; do not call a synthetic feature generator
"pretrained" without a physical model load and bound final-use receipt.

    python qualification/neuron-gated-sparse-v3/matched_train.py \
      --train-data /frozen/train.json --train-sha256 "$SHA_TRAIN" \
      --selected-v1 /owner-selected/v1.safetensors \
      --selected-v1-sha256 "$SHA_OWNER_BASELINE" \
      --output /new/research-four-candidate-weights \
      --steps 64 --window 32 --seed 7347

The command writes **20 physically reloaded candidate weight files**, the
SHA/count/cost/no-authority 'training-receipt.json', and does not create a
synthetic no-change V1 artifact or fabricated baseline predictions.

## A3/A4: future forecast must precede outcomes

After training, the trusted Owner exports frozen V1 probabilities for the exact
future/OOD cases (including model invocation evidence). The independent
future feature stream is **unlabelled** and must use source groups excluded
from training. 'precommit_future.py seal' accepts no label/outcome argument.
It physically hashes all 20 candidate artifacts, reloads the weights,
runs the frozen surrogate, pairs every candidate with the owner V1 prediction,
and publishes an exclusive, fsynced forecast file. A local clock value is
recorded but is NOT a trusted timestamp.

    python qualification/neuron-gated-sparse-v3/precommit_future.py seal \
      --trained-root /new/research-four-candidate-weights \
      --receipt-sha256 "$SHA_TRAIN_RECEIPT" \
      --future-features /owner/future-unlabelled.json \
      --future-sha256 "$SHA_FUTURE" \
      --frozen-v1-predictions /owner/frozen-v1-probabilities.json \
      --frozen-v1-predictions-sha256 "$SHA_V1_PRED" \
      --seal-output /new/five-arm-forecast-seal.json

Future input schema has 'schema=hepta.neuron.unlabelled-future-q24.v1',
'encoder_digest', 'cell_id', and 'samples' with 'case_id',
'source_group', 'sequence', 'event_time_utc', 'feature_q24', and
'partition' = future or ood. No labels, test outcomes or unseen extra
fields are permitted.

The separate witness independently signs canonical JSON 'payload' with
'schema=hepta.neuron.five-arm-precommit-witness.v1', the sealed file SHA256,
'committed_at_utc', 'host_id' and 'operation_id'. Outcome signer uses a
**distinct trusted Ed25519 public key** and the payload:
'schema=hepta.neuron.five-arm-independent-outcomes.v1', 'cell_id',
'input_seal_sha256' and 'rows'; each row binds 'case_id',
'partition', 'source_group_sha256', binary 'label' and
'label_available_at_utc'.

    python qualification/neuron-gated-sparse-v3/precommit_future.py score \
      --seal-file /new/five-arm-forecast-seal.json \
      --seal-sha256 "$SHA_SEAL" \
      --signed-witness /independent/witness.json \
      --witness-pubkey /independent/trusted-witness.pem \
      --signed-outcomes /independent/outcomes.json \
      --outcome-pubkey /independent/trusted-evaluator.pem \
      --report /new/research-only-future-report.json

Score fails closed on tampering, signature/key mismatch, missing paired rows,
training/future group leakage, chronology reversal and missing OOD. It reports
binary Brier/ECE and an explicit confidence-threshold false-acceptance
diagnostic. A signed historical timestamp or same-sha comparison still does
not establish a trusted host clock, prospectively hidden outcomes, causal
NDU effect or model invocation. Both training and scoring always emit
'ndu_eligible=false' and 'production_qualification=false'.

## A4: production-scale end-to-end measurements remain blocked

Do not substitute this CPU-only training harness or the existing 20/40/120
process synthetic Q24 mechanism probes for real 64/256/1024/4096 Cell
requests. On the selected host freeze (host, device, runtime, commit, Encoder,
tokenizer, preprocessor, normalization, candidate weights, request trace);
measure per-request throughput, p50/p95/p99, CPU, process-tree RSS, GPU and
allocator peak, cold Encoder, feature-cache misses/revocations, worker queue,
signature/final-use, checkpoint CAS, WAL durability, CNS, recovery/replay and
generation fencing. Use independent signed owner evidence and compare matched
cohorts. The existing 'five_arm_budget_gate.py' plus A0 signed census and
paired A4 evaluator are the next formal gates. Independent Evaluator,
Selector and Executor must each approve a separate future-snapshot candidate
before production change. No data or physical target-host receipts are bundled
with this PR.

## Testing

    python -m unittest discover -s qualification/neuron-gated-sparse-v3 \
      -p 'test_*.py' -v

This stack adds standard-library/signature negative tests; a physical 20-file
Torch + safetensors synthetic canary executes only when those optional
dependencies are installed. Synthetic canary results may confirm training
mechanics, **never** task efficacy, trusted model residency, a real A0,
native Q24 parity, release CI or production A4.
