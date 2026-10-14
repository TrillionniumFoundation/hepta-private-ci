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
'matched_train.py' verifies the existing A0 signed registry and matching scoped
V1 Cell evidence with an independently provided trusted Ed25519 key, current
host ID and fresh owner snapshot. This verifies signed-file consistency, NOT
independent physical host execution. Without these, normal training refuses
to run. The opt-in '--synthetic-canary' permits unit-test fixtures only and
explicitly labels them as not A0 or selected production weights. If there is no
owner-approved baseline, do not replace it with a random model.

## A1/A2/A3: physically train four candidates, never train V1

The offline, CPU-only 'matched_train.py' accepts a SHA256-pinned **training
dataset only**, an externally selected V1 artifact, and positive common
optimizer steps. It rejects training events after the frozen cutoff, group
sequence/clock regressions, duplicate cases, extra fields, oversize features,
out-of-range Q24 inputs and non-binary labels. It never reads heldout, OOD or
future files. One invocation is for a single Cell scope.

Training uses a common generated source-group schedule, Torch AdamW CPU,
identical training steps/window/seed and an enforced common per-candidate
CPU ceiling (default 300 seconds), and per-cap physical 'safetensors'
reloading. The arms are V2, V3, diagonal SSM, and low-rank minGRU. Budgets are
2K/8K/16K/64K/262K upper ceilings, NOT padded equality. Identity projection,
Head and trainable temporal factors are counted; miniGRU rank must fit the
complete private footprint. At 256 dimensions minGRU cannot fit the 2K
tier with a private projection/Head; choose smaller common width or an
independently justified cost profile instead of hiding parameters.
Identical ceilings and optimizer steps do NOT mean identical FLOPs or actual
CPU consumed; all real work/cost observations must be retained. Independent
optimizer-state estimate and process-wide RSS are recorded
separately and are NOT arm-isolated peak RSS or target-host measurements.

The diagonal SSM research profile pins a 1,000,000-microsecond time quantum (one second); this is not the existing fixture's 100-microsecond quantum. The floating-point learning kernel is a **restricted differentiable surrogate**.
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
      --a0-evidence-root /owner/frozen-a0 \
      --a0-trusted-public-key /independent/a0-owner.pem \
      --a0-expected-host-id "$HEPTA_HOST_ID" \
      --output /new/research-four-candidate-weights \
      --steps 64 --window 32 --seed 7347 \
      --max-train-cpu-seconds 300

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
and publishes an exclusive, fsynced forecast file. Real 'seal' execution
refuses training receipts missing the signed-format A0 V1 current-owner
census. A test fixture requires an explicit '--synthetic-canary' flag, which
remains unqualified and can never become owner evidence. This extra A0
requirement changes the research seal profile to
'hepta.neuron.five-arm-research-forecast-seal.v2'; older v1 seals are refused. A local clock value is
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

'score' also refuses any synthetic A0 seal unless given the explicit
'--synthetic-canary' test-only flag. Score fails closed on tampering,
signature/key mismatch, missing paired rows,
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

## Strict 100-slot signed target-host telemetry (A4 structural gate)

The additional 'a4_end_to_end_gate.py' refuses a partial experiment. Supply
an independently provisioned and trusted host signer, frozen exact host ID,
Git commit, Encoder bundle SHA, host-profile SHA, current signed-format A0
training receipt, 20 physical private candidate files and selected V1 blob.
The signed payload schema is 'hepta.neuron.a4-end-to-end-host-100-slot.v1',
with 5 parameter caps x (frozen V1 + 4 candidates) x 4 requested
Cell scales = **100 distinct receipts**. Each scale receipt reports the
**actually measured distinct Cell identity count** (exactly 64/256/1024/4096,
not just a claimed configured count), with a corresponding bounded Cell scope
coverage assertion from the host Owner.

Each target-host sample must report the *complete request*, not just the Q24
tick: actual source model-load/worker/CAS/WAL/final-use/signature/CNS/fence/
revocation receipt digests; host-observed Encoder forward rows and calls;
request and batch latency distributions; real CPU, process-tree peak RSS,
GPU peak allocation/total use, throughput, cold load, WAL writes, recovery,
lost acknowledged replay, and successful scope-bound reopen, fence, revoke
and model deduplication checks. All 20 candidate safetensors are re-opened,
structurally parsed, compared with recorded parameter counts and pinned SHA;
minGRU tensor geometry is independently rechecked. Every host row binds the
physical weight SHA. The selected V1 is always the same frozen baseline.

    python qualification/neuron-gated-sparse-v3/a4_end_to_end_gate.py \
      --signed-host-receipts /host/frozen-signed-a4.json \
      --trusted-host-public-key /independent/trusted-host.pem \
      --host-id "$HEPTA_HOST_ID" \
      --training-receipt /study/training-receipt.json \
      --training-sha256 "$SHA_TRAIN_RECEIPT" \
      --trained-root /study/ \
      --selected-v1 /owner-selected/v1.safetensors \
      --selected-v1-sha256 "$SHA_OWNER_BASELINE" \
      --expected-commit "$EXACT_GIT_SHA" \
      --expected-encoder-bundle-sha "$ENCODER_BUNDLE_SHA" \
      --expected-host-profile-sha "$HOST_PROFILE_SHA" \
      --report /review/a4-host-structural-review.json

This CLI does **not** execute the workload. It rejects incomplete/tampered
resource claims and always emits 'trusted_host_execution_independently_attested
=false', 'ndu_eligible=false', 'production_qualification=false' even when all
100 slots and their signatures/physical source hashes are structurally valid.
A genuinely independent operator must verify the host signer, time/order,
actual inference and recovery, causality and NDU before any production cutover.
No target-host receipts are included in the source or CI.

## A3/A4 physical artifact geometry and Q24 admissibility (2026-10-14)

The additive `candidate_inventory.py` independently opens each of the 20
private physical safetensors files. At A4 and immediately before forecast
sealing, it enforces a closed-world tensor inventory and exact tensor geometry
for all four trained arms, including the frozen identity projection, private
binary Head, and the arm-specific temporal parameters. It refuses altered SHA,
unexpected or missing tensors even if the **total parameter count stays
identical**, overlapping/unclaimed file bytes, symlinked artifact paths, wrong
dtype, floating non-finite Head weights, and Q24 values outside each native
parameter's validity range. In particular, V3 gate bias and SSM decay must be
nonnegative and at most Q24 unity. The training surrogate projects **every temporal parameter** into
the signed Q24 range after each optimizer step and additionally enforces
nonnegative V3 gate bias and SSM decay, rather than exporting silently
incompatible parameters. It refuses any subsequent implicit export clamp.
A4 also rejects cross-arm state-width drift, invalid A0 checkpoint identities,
and target-host measurement windows starting before the frozen train cutoff.

The file reader holds one bounded physical file descriptor and validates the
same loaded bytes against the separately supplied SHA. This does **not**
authenticate the source of the training, validate an independently trusted
model-load receipt, or prove equality between Torch surrogate predictions and
Rust Q24 nonlinear/top-k/state-replay outputs. The study remains fail-closed
until exact native Q24 replay against physically selected trained weights
and independent outcome evidence are available.

Run the focused physical artifact suite on an isolated researcher host:

    cd qualification/neuron-gated-sparse-v3
    PYTHONDONTWRITEBYTECODE=1 python -m unittest \
        test_candidate_inventory test_real_pipeline test_a4_host_gate -v

`test_candidate_inventory.py` exercises actual saved safetensors bytes and
negative cases; it is required (not silently skipped) in the read-only pinned
CPU canary workflow. No real host or selected Cell artifacts are shipped.

## Testing

    python -m unittest discover -s qualification/neuron-gated-sparse-v3 \
      -p 'test_*.py' -v

This stack adds standard-library/signature negative tests; a physical 20-file
Torch + safetensors synthetic canary executes only when those optional
dependencies are installed. Synthetic canary results may confirm training
mechanics, **never** task efficacy, trusted model residency, a real A0,
native Q24 parity, release CI or production A4.
