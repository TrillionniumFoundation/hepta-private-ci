# Hepta SNG-R repository-evidence Reader diagnostic (shadow, source-bound)

This is a **read-only experimental harness**, not a trained FBSDE, a deployed Hepta System2, a live MemoryCell benefit, or a claim that Laya 421M can generate open-ended text. It tests a bounded **typed choice** task with a separately supplied *actual pretrained* local Laya checkpoint. Training a tiny synthetic encoder or using a unit-test stub does **not** qualify as Laya inference.

## Frozen benchmark and chain of custody

- Base commit: `f8c9419df6ddeb36ff8b522a50219981fb8d9345` (`main` observed for this study). Frozen corpus file: `hepta_sngr_reader_cases.json`, 16 manually reviewed binary-source facts covering six real GitHub files, four answer labels balanced 4/4/4/4. Each case binds an individual Git blob SHA-1, a source path, a line label, a supporting substring, a separate withheld-control substring and an externally fixed gold option. The executable harness pins the **entire raw corpus SHA-256**; changing a label requires a new reviewed source revision.
- Exact Git blob and substring identity of all six sources was verified against GitHub on October 17, 2026. The optional `--source-checkout` re-checks full Git blob hashes and all quote substrings against an actual local checkout; no network fetch or checkout modification occurs.
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
