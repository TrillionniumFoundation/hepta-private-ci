# Hepta Neuron — five-arm, five-budget qualification (research only)

This directory adds **Low-rank minGRU**, without replacing the selected
Sparse V1 Cell or its journal. The study does **not** qualify an encoder, train
an upstream model, authenticate a target host, or authorize physical splits.
All outputs remain shadow-only. The actual selected Cell population is unknown
until the A0 deployment census is signed by an independent owner.

## Exact arms and resource ceilings

| Arm ID | Temporal mechanism | Existing implementation |
|---|---|---|
| `no-change-v1` | Frozen Sparse V1; **zero experimental optimizer steps** | `sparse.rs` |
| `v2` | Separate temporal/activation dimensions and local/global Top-K | `population_v2.rs` |
| `v3` | Input-/change-dependent Q24 retention gate | `gated_sparse_v3.rs` |
| `ssm` | Per-channel stable diagonal SSM with elapsed-time quantum | `diagonal_ssm_shadow.rs` |
| `min_gru` | Low-rank input-only update gate + candidate; frozen Q24 factors | `low_rank_min_gru_shadow.rs` |

Every arm competes under exactly these ceilings, independently:
`2048`, `8192`, `16384`, `65536`, `262144` private **model
parameters**. Do NOT pad smaller models to claim equal parameter count;
the equivalence criterion is the **same maximum budget**, and the realized
parameter count must be reported. State/checkpoint/optimizer/worker bytes are
additional ceilings, never free simply because the trainable parameter cap
passes.

The current low-rank comparator uses two factored input projections and two
channel bias vectors. With equal input/state width `w` and rank `r`:
`P_temporal = 4*w*r + 2*w`. At `w=256`, ranks `1/7/15/62/255`
have respectively `1536/7680/15872/64000/261632` **temporal-only**
parameters. A model with any extra Head or private projection must reduce
its rank to remain within its total tier. These are exact tensor arithmetic,
**not proof of trainability, quality or performance**.

## Separate three types of evidence

1. **Mechanism expressive capability**: exact Q24 outputs, lossless original
   input binding, Q24 signed nearest/ties-to-even, deterministic Top-K, bounded
   temporal state, replay, corruption and sequence/scope/generation fences.
   Current Rust native smoke is a synthetic, untrained fixture. It cannot
   answer which model learns or generalizes better.
2. **Actual learned quality**: on one pinned shared encoder, identical raw
   features and data, identical optimizer/training/tuning allowances, physically
   reloaded model weights, paired independently observed future/held-out/OOD
   outcomes, and a *frozen no-change* baseline. Compare task success, sample
   efficiency, long-horizon retention, negative transfer, Brier, ECE, OOD false
   acceptance and genuine abstention. The A1–A4 paired analyzer currently
   reports binary Brier/ECE when present; full abstention/OOD calibration is
   an **open blocker**, not inferred from Q24 prediction residuals.
3. **Actual system cost and trust**: CPU, peak RSS, accelerator allocation
   *and* total device usage, sustained throughput and p95/p99 at 64/256/1024/4096
   logical Cells. Include cold Encoder, shared-feature cache, projection, Head,
   queue, WAL, CAS, signature verification, snapshot recovery and split/migration.
   Match the same host, concurrent load, resource reservations and randomization.
   The mechanism-only fixture does not measure all of these.

## A0 → A4 hard dependencies

- **A0 census**: real selected Cell identities/generations, signed artifact
  manifests and exact model weights, active checkpoint/journal, owner and
  live host resource receipts. Without independently authenticated enrollment,
  **BLOCKED**.
- **A1 frozen studies**: preserve immutable no-change and signed training,
  validation, OOD and future groups; preregister ceilings, candidate optimizer
  steps, hyperparameter trials, token/feature budgets and dated windows. No
  future labels enter feature selection, calibration or training.
- **A2 Q24 parity**: V1 historical wire/replay stays untouched. V3, diagonal
  SSM and minGRU retain separate domain-separated digests. The minGRU pure
  shadow checkpoint is **not a durable owner or its own signed WAL**.
- **A3 training**: use actual task labels and independently pinned shared
  Encoder features, fit *all five* model variants within their private
  parameter and measured training-work limits, save/reload real weights and
  compare same-case predictions. `rank` is an experimental capacity choice,
  not evidence of measured learning. No actual fitted minGRU is shipped here.
- **A4 independent future-NDU acceptance**: fully paired held-out/OOD/future
  labels and future utility, signed owner provenance and checkpoint readback,
  confidence intervals clustered by Cell, negative-transfer limits,
  20 target-host scale receipts, and independent Evaluator / Selector /
  Executor. Strict A4 rejects absent slots; even complete signatures are not
  themselves trusted host attestations.

## Structural and signed paired evaluation CLI

The new `five_arm_budget_gate.py` accepts **one study manifest**, five
independently signed evaluator envelopes and 25 physically staged Cell-private
`.safetensors` files. The study manifest schema is
`hepta.neuron.five-arm-matched-budget-bundle.v1`:

```json
{
  "schema": "hepta.neuron.five-arm-matched-budget-bundle.v1",
  "tiers": [
    {
      "parameter_cap": 2048,
      "signed_evaluation": "2048/evaluation.json",
      "models": {
        "no-change-v1": {"path": "2048/v1.safetensors", "sha256": "<64 hex>", "architecture": {}},
        "v2": {"path": "2048/v2.safetensors", "sha256": "<64 hex>", "architecture": {}},
        "v3": {"path": "2048/v3.safetensors", "sha256": "<64 hex>", "architecture": {}},
        "ssm": {"path": "2048/ssm.safetensors", "sha256": "<64 hex>", "architecture": {}},
        "min_gru": {"path": "2048/min_gru.safetensors", "sha256": "<64 hex>",
                    "architecture": {"width": 256, "rank": 1}}
      }
    }
  ]
}
```

The example shows **only one tier** and non-hex placeholders, so it is
intentionally **invalid** until the other four tiers and real weight
digests are supplied. It is NOT a runnable substitute for genuine evidence.
For this research format, the signed `artifact_digest` of each paired arm
must be the exact SHA-256 of its physical private weight file; this is NOT
an equivalence assertion about production Artifact CAS manifests.
`min_gru` must export six `temporal.*` tensors with exact rank/width
shapes, **plus any private Head tensors** in the same file. A frozen shared
Encoder is not counted as 25 private copies; record physical shared
Encoder memory and compute once at service level.

```sh
python3 qualification/neuron-gated-sparse-v3/five_arm_budget_gate.py \
  --bundle /frozen-study/bundle.json \
  --evaluation-root /signed-evaluator/ \
  --model-root /read-only-private-weights/ \
  --trusted-evaluator-public-key /independent/evaluator.pem \
  --report /review/five-arm-report.json

# Research diagnosis for signed, incomplete A1–A3 (still NO_PROMOTION):
python3 qualification/neuron-gated-sparse-v3/five_arm_budget_gate.py \
  --bundle /frozen-study/bundle.json \
  --evaluation-root /signed-evaluator/ \
  --model-root /read-only-private-weights/ \
  --trusted-evaluator-public-key /independent/evaluator.pem \
  --allow-pre-a4
```

The verifier reads and hashes actual safetensors bytes, checks tensor geometry,
count, no alias/gaps/undeclared bytes, every tier, exact joined evaluation
cases, frozen baseline across all tiers and the signed evaluator's
same-encoder/training-data/optimizer-step assertions.

**Important limits:** this still cannot independently know whether a model
file contains *every* selected parameter, whether it actually ran on the
owner's host, whether optimizer/tuning CPU was fairly allocated, or whether
source and future outcomes were independent. These require external owner
and evaluator receipts; no digest alone can manufacture them.

## Untrained native mechanism smoke

```sh
cd codex-rs
cargo fmt -p codex-hepta-neuron -- --config imports_granularity=Item
cargo test --locked -p codex-hepta-neuron --all-targets
cargo clippy --locked -p codex-hepta-neuron --all-targets -- -D warnings
cargo build --locked -p codex-hepta-neuron --bin neuron_shadow_mechanism_probe
python3 ../qualification/neuron-gated-sparse-v3/run_shadow_probe_matrix.py \
  --binary target/debug/neuron_shadow_mechanism_probe \
  --trace ../qualification/neuron-gated-sparse-v3/fixture_q24_trace.json \
  --report /review/untrained-five-arm-fixture.json
```

The probe reports **20** arm/scale runs, always
`trained_model=false`, `all_model_parameter_budgets_matched=false`,
`ndu_eligible=false` and `production_qualification=false`.
One process per arm/scale gives *mechanism* CPU/RSS observations, NOT actual
trained-model serving cost or resource equivalence.

## Promotion decision

**Permanent fail-closed until independent A0/A4, production owner and real NDU
criteria pass.** Never rewrite V1 selected artifacts, historical journal or
active routes in-place. If a future model is measurably better, first publish
a separately signed candidate, shadow state migration, independent final-use
authorization, generation-fenced CAS cutover and rollback with real receipts.
