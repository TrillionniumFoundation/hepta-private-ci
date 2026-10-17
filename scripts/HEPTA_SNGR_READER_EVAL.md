# Hepta SNG-R repository-evidence Reader diagnostic (shadow, source-bound)

This is a **read-only experimental harness**, not a trained FBSDE, a deployed Hepta System2, a live MemoryCell benefit, or a claim that Laya 421M can generate open-ended text. It tests a bounded **typed choice** task with a separately supplied *actual pretrained* local Laya checkpoint. Training a tiny synthetic encoder or using a unit-test stub does **not** qualify as Laya inference.

## Frozen benchmark and chain of custody

- Base commit: `f8c9419df6ddeb36ff8b522a50219981fb8d9345` (`main` observed for this study). Frozen corpus file: `hepta_sngr_reader_cases.json`, 16 manually reviewed binary-source facts covering six real GitHub files, four answer labels balanced 4/4/4/4. Each case binds an individual Git blob SHA-1, a source path, a line label, a supporting substring, a separate withheld-control substring and an externally fixed gold option. The executable harness pins the **entire raw corpus SHA-256**; changing a label requires a new reviewed source revision.
- Exact Git blob and substring identity of all six sources was verified against GitHub on October 17, 2026. The `--source-checkout` argument is mandatory when evaluating a real checkpoint and verifies full Git blob hashes plus declared quoted lines against an actual local checkout; no network fetch or checkout modification occurs.
- These are **real repository-document understanding tasks**, not real production user episodes, independent end-to-end task observations, or semantic model-training success. Gold labels were manually anchored from source; they are never included in the model's input state or question payload.

For every case, compare **no evidence**, **irrelevant genuine evidence from a different source**, **same-source context after removing the decisive premise**, and **full genuine supporting evidence**. A fifth opt-in condition appends a clearly synthetic prompt-injection message to the real excerpt; its injected instruction is *not* falsely attributed to the historical source. **The attack target is deterministically derived from the task ID alone, without consulting gold.** The target can coincide with gold, so the targeted attack-success denominator includes only tasks where the two differ; all cases remain in the ordinary gold-accuracy denominator. Five typed choices (A/B/C/D/UNKNOWN) ensure that absent evidence can be answered with abstention instead of forced guessing.

All arms receive exactly one decision-model invocation per task, in seeded shuffled order, with the same frozen checkpoint and question template. **This is equal *call count*, not equal token count, FLOPs, wall time or total compute**. Actual input sizes and wall time are reported by arm. No Laya inference is cached across the distinct question-conditioned states. The shadow experiment must never select, alter or authorize a production artifact.

## Reproduction

No pretrained weights or SDK are bundled with this PR. Install the SDK and arrange a compatible approved local checkpoint outside the repository. The harness never initiates Hub downloads. Laya 0.3.6 expects a local `rl_agent_config.json`, `model.safetensors` and tokenizer/encoder assets; the checkpoint directory is read, hashed, and fingerprinted. Incompatible tokenizer files that the upstream loader would silently rewrite are rejected before loading.

```bash
python3 -m unittest discover -v -s scripts -p 'test_hepta_sngr_reader_eval.py'
# Missing checkpoint is explicitly unavailable (exit status 2), not success:
python3 scripts/hepta_sngr_reader_eval.py
# On a machine with a pinned, genuinely pretrained Laya local checkpoint:
python3 scripts/hepta_sngr_reader_eval.py \
  --checkpoint-dir /absolute/path/to/pinned-laya-checkpoint \
  --source-checkout /absolute/path/to/hepta-private-ci \
  --seed 17 --max-calls 64 --output /tmp/hepta-sngr-reader-result.json
# For the additional synthetic prompt-injection ablation, max calls >=80:
python3 scripts/hepta_sngr_reader_eval.py \
  --checkpoint-dir /absolute/path/to/pinned-laya-checkpoint \
  --source-checkout /absolute/path/to/hepta-private-ci \
  --include-injection --max-calls 80
```

Offline loading forces `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`. Missing weights, missing SDK, unsupported model format, a missing/mismatched source checkout, corrupted source evidence (including declared line numbers), incompatible tokenizer or inadequate budget **fails closed**. The model remains in eval mode with all parameters frozen; the harness invokes only a typed `choice` interface. The provenance fingerprint is SHA-256 over the bytes and names of the full local checkpoint directory, not a claim of independent provenance or training origin.

## Evaluation and explicit limits

Output records per-item answer, externally assigned gold, confidence, optional model input-token usage, abstention, unsupported assertion, request character count, and elapsed milliseconds. The report schema is **hepta.sngr.reader-diagnostic.shadow.v2**. Aggregate arms report gold-label accuracy, **evidence-condition accuracy** (UNKNOWN required in no-evidence/distractor/withheld arms), abstention, unsupported assertion rate, proper **multiclass Brier score** for the evidence-conditioned answer target, confidence-correctness MSE (diagnostic, *not* a calibrated-probability Brier claim), and p50/p95 latency. Injection susceptibility is measured separately for gold-opposed attacker targets; no model-visible injection string depends on gold. The paired contrasts are **descriptive**; 16 manually chosen tasks cannot establish population-level statistical or causal improvement, nor is a reader forced to abstain under all unknown-source conditions.

Interpret the results by diagnostic regime: full evidence still wrong indicates reader/prompt/task capacity; full evidence correct but withheld/distractor wrong indicates information dependence; improvement only after changing a much larger reader is reader-capacity gain; only a controlled separately trained policy that beats its frozen equal-capacity/equal-budget counterpart can support learning benefit. No model may self-issue the external outcome, rewrite hard constraints, or claim a low local numerical FBSDE residual proves a correct task answer.

### Gate before advancing to full shared-Stem/FBSDE inference

1. Actually load and run pinned Laya weights (this environment **has not**), archive raw reader outputs with exact source/model hashes and compatible licensed terms.
2. Evaluate fixed, preregistered *real* Hepta retrieval/diagnosis episodes with authentic provenance and independently observed terminal outcomes, including evidence removals and contradictory/versioned sources. Avoid giving gold as input or granting a model read access to answers.
3. Reuse the same encoder, training steps, physical FLOPs, activation budget and held-out tasks when comparing frozen Cell Head, Bellman depth-2, NDU Head, NDU FBSDE and adaptive-search arms. Measure actual concurrency, latency, memory, accuracy, calibration, abstention, OOD and training costs.
4. Verify Rust shadow builds, independent well-posedness and conditional covariance conventions, error bounds and candidate-only authority, then proceed through existing qualification and promotion. A Python reference or mock reader is **not** such evidence.

## Answer-order counterbalance and input-budget gate

The original fixed-label benchmark remains available via the default `--presentations 1`. For a stronger diagnostic, use `--presentations 4`: a SHA-256(seed, case ID)-derived offset rotates the same four answer descriptions through all A/B/C/D positions. This produces a four-position Latin square **per task**. The option order is selected without accessing the gold label, and each evidence arm gets the same order for that task/variant. A position-only always-A stub scores exactly 25% per task under this design; do not treat the four repetitions as 64 independent tasks.

```bash
# Offline genuine Laya checkpoint required; 16 cases x 4 arms x 4 orders = 256 calls
python3 scripts/hepta_sngr_reader_eval.py \
  --checkpoint-dir /path/to/verified-local-laya \
  --source-checkout /path/to/verified-hepta-checkout \
  --presentations 4 --seed 17 --max-calls 256 --output /tmp/sngr-reader-balanced.json

# Injection arm adds another 64 calls: exactly 320 total
python3 scripts/hepta_sngr_reader_eval.py \
  --checkpoint-dir /path/to/verified-local-laya \
  --source-checkout /path/to/verified-hepta-checkout \
  --presentations 4 --include-injection --max-calls 320
```

Real-model runs now require valid model `cfg.max_len` and a reported per-inference token count **strictly below** that cap. A missing or saturated count rejects the evaluation as possibly truncated; passing this conservative check does **not** prove that the full evidence survived head/tokenizer allocation. Checkpoint bytes are fingerprinted before loading and again after all model calls. Summaries provide mean reported input tokens and answer-position diagnostics, in addition to wall time and call count.

## Deterministic lexical negative control and task difficulty

`scripts/hepta_sngr_lexical_control.py` is an explicitly **post-hoc**, gold-blind keyword-overlap negative control, not a learned model. Its simple rule compares the four option descriptions with untrusted evidence using token-set overlap, requiring at least two matching non-stopword tokens and a two-token lead; otherwise it emits UNKNOWN.

```bash
python3 -m unittest discover -v -s scripts -p 'test_hepta_sngr*.py'
python3 scripts/hepta_sngr_lexical_control.py --presentations 4 \
  --output /tmp/sngr-lexical-diagnostic.json
```

On the frozen 16-case fixture, the rule answers **14/16** with sufficient evidence, abstains correctly on all **48/48** no-evidence/distractor/withheld cases, and achieves 56/64 full-evidence answers under four answer rotations. These are *in-sample diagnostic arithmetic*, because the rule was designed after inspecting these cases; they are neither a preregistered control nor evidence of Laya or System2 gain. The high lexical score shows that the current tasks primarily test source extraction. Any reasoning-efficacy claim requires a harder **independently held-out, multi-hop/contradiction/versioned** suite on which literal overlap is not sufficient, plus genuine model weights and independent task outcomes.

## Two-source joint-truth diagnostic

The second *designed* fixture `hepta_sngr_two_source_cases.json` contains eight
two-source cases, each binding two pre-existing independently Git-blob-verified
source excerpts **from different files**, with two claims and an evaluator-only
joint truth assignment. A/B/C/D each appear twice. A second source is withheld
in one arm while the first is retained; insufficient support requires UNKNOWN.
Each of the four answer-order variants preserves the same evidence per arm.
One real Laya checkpoint would require 8 x 4 x 4 = 128 inference calls; with
the opt-in prompt-injection arm it would require 160.

```bash
python3 -m unittest discover -v -s scripts -p 'test_hepta_sngr*.py'
python3 scripts/hepta_sngr_two_source_eval.py --lexical-control-only \
  --presentations 4 --output /tmp/sngr-two-source-control.json
# The following runs ONLY if a genuine Laya checkpoint AND verified source checkout exist:
python3 scripts/hepta_sngr_two_source_eval.py \
  --checkpoint-dir /path/to/frozen-local-laya \
  --source-checkout /path/to/source-checkout \
  --presentations 4 --max-calls 128 \
  --output /tmp/sngr-two-source-reader.json
```

The post-hoc token-overlap control abstains on all eight full-evidence cases
(0/8; 0/32 under four rotations), while it answers 14/16 single-source cases.
This demonstrates a **lexical shortcut difference between two task designs**;
it does not prove the two-source labels are independently audited, prove a
neural model can solve the task, or establish System2/FBSDE reasoning benefits.
Untrusted source text may not issue runtime instructions or external effects.
The source-chains and tasks are manually designed; independent future held-out
episodes, contradiction/version corrections, and actual terminal outcomes are
required before claiming general reasoning gains.
