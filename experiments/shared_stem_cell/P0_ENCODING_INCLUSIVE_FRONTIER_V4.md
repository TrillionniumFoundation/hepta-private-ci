# P0 Encoding-Inclusive Cost Frontier V4 — research-only

**Draft / DENY_ALL / no automatic Stem selection.** Continue `research/hepta-p0-matched-question-only-20261015` with an **additive**, evidence-only P0 cost reviewer, not another Encoder owner or parallel controller. The existing original-human-label MultiRC, learned Evidence Head, separately learned Question-only Head, Laya frozen native reference and independent label-audit implementations remain the owners. No modification to training labels, optimizer seed, steps, candidate/source selection, model weights, tokenizer, final-use or production route is authorized.

## Scientific question

The Evidence Head and independently fitted Question-only Head have exactly the same *trainable Head* dimensions, initialization, original training targets, update schedule and per-model pretrained base. They do **not** necessarily consume equal Encoder tokens, compute or input-conditioning. It is therefore incorrect to translate equal Head parameters and SGD updates into equal full-stack resource cost. This reviewer explicitly distinguishes two resource comparisons:

1. **Joint research campaign:** one physical pretrained Encoder load, all original- and no-evidence Encodings, both actual Head training jobs and all frozen/learned Head inference/control calls. Count each originally observed physical call once, never pad cost to match budget.
2. **Standalone counterfactual deployment lower bounds:** an Evidence-only strategy loads its model once, encodes original task views, trains its own Head and serves held original tasks. A Question-only strategy separately pays its model load, encodes only no-evidence task views, trains its own Head and serves those original-task targets. The two standalone strategies must not claim that a zero-cost additional Encoder or model load is provided by the paired research campaign.

We recompute both from **original immutable per-case physical token count**, per-case Encoder elapsed milliseconds, separately metered SGD, held inference calls, and the observed process lifetime. Training and calibration samples are still part of the resource denominator. Only the original labeled MultiRC candidate owns the human binary truth. The question-only arm estimates *that original human label*; no new human truth is invented for an empty passage.

The source reviewer requires a complete `(case_id -> integer tokens in [1,512])` record and its SHA-256 bound to the original Encoder report, exactly the same source IDs as the complete `(case_id -> encode_ms)` record and equal copies of the registered timer field. A changed token count even with a new self-consistent claimed digest is not authenticated against real upstream model bytes; the record is explicitly **claimed physical observation**, not cryptographically signed model provenance. The reviewer independently replays the entire original label and Head audit and refuses altered matched-score bytes.

## Numerical cost convention

Let `L` be the single observed pretrained model load, `E_o/E_q` be sums of actual original/no-evidence Encoder time across **training + calibration + held**, `H_o/H_q` be measured individual Head SGD training times, `I_o/I_q` be each trained Head's held original-target inference time and `A` be original process wall time.

- Evidence-only standalone **lower bound**: `L + E_o + H_o + I_o`.
- Question-only standalone **lower bound**: `L + E_q + H_q + I_q`.
- Joint campaign paid-work **lower bound**: `L + E_o + E_q + H_o + H_q + all original frozen/trained inference calls + all prior frozen/trained calls`.
- The residual `A - paid_work` is reported without assigning it to a favored arm or asserting it is zero; sums greater than original wall beyond a fixed 5ms measurement tolerance fail closed.

All costs are untrusted reported **lower bounds**: calibration evaluation, tokenization outside the recorded region (if any), serialization, scheduler and queuing, energy, GPU memory, original Worker/CAS/FinalUse and recovery remain unmeasured. One CPU trial and eight held passages are underpowered. Even a positive observed Brier gain, a favorable lower-bound CPU cost or all local tests passing must **not** issue a model winner, 95% superiority certificate, production admission, future-window claim or authorization. Histories of failures and null effects are not filtered.

## Workflow

One further `Independent source-bound encoding-inclusive cost frontier` step runs in the **existing** P0 four-job workflow **after** the matched original-human-label independent review. It reopens the original pinned MultiRC files and all four model receipts, replays the exact matched score and writes a *separate create-only* research JSON. Missing one model, altered token counts, missing encoder calls, changed Head training lineage or dishonest costs fail. It is never substituted for the original source/head/architecture/`blocking-ci` and does not require privileged model-loader or external-effect access.

## Locally reproducible tests

```bash
PYTHONPATH=experiments/shared_stem_cell python -m unittest discover \
  -s experiments/shared_stem_cell -p 'test_p0_encoding_cost_frontier.py' -v
PYTHONPATH=experiments/shared_stem_cell python -O -m unittest discover \
  -s experiments/shared_stem_cell -p 'test_p0_encoding_cost_frontier.py' -v
```

No actual new pretrained Granite/mmBERT/Gemma/Laya runs or original host evidence were produced by the local tests. The 20 new tests include **actual PyTorch SGD on a declared synthetic Encoder feature bank** plus cross-source/parameter/cost/tamper refusal. All model-selection, CNS/Worker, NDU/System2, Artifact CAS, Evidence WAL, FinalUse and `main` state remain unchanged.

## 2026-10-15 local execution and regression boundary

Newly created independent cost code and fault tests were executed against the same exact prior P0 MultiRC source slice as #2137. **172/172 unique unit test methods** passed in one complete standard Python 3.13.5/Torch 2.10.0 CPU invocation and **172/172** passed independently with `python -O`; zero errors, failures or skips. These 172 are the 152 inherited tests plus **20 new** accounting, physical-token and adversarial replay tests. Source compiles with CPython, strict YAML duplicate-key rejection passes, the same four workflow jobs remain in order, and all 13 shell `run` blocks passed `bash -n`. The raw normal/optimized logs and source hashes are retained in the separate delivery bundle; a successfully compiled or syntax-checked workflow is not a hosted CI pass.

The initial complete-test attempt failed 15 tests because a newly added fixture used `patch.dict(sys.modules)` while the native PyTorch initialization was lazy; the mock cleanup discarded Python `torch._inductor` submodules while leaving native `TORCH_LIBRARY` registrations loaded. We replaced that broad snapshot with an exact one-name loader replacement and restoration, then reran both entire suites successfully. The failure diagnosis and its exact error class are retained here, **but the transient first-run raw log was overwritten when the complete suite was rerun**; no preserved original raw failure log is claimed, and the failed attempt is not counted as passing. This was a test-only artifact, not a physical pretrained inference or production runtime failure.

All new physical token and timing rows in unit tests are **synthetic fixtures**. No original Granite/mmBERT/EmbeddingGemma/Laya task accuracy, authenticated model-origin signature, target GPU energy, longitudinal NDU, FBSDE global optimum, learned multimodal generator or Compiled Skill Cell efficiency is established. Exact-HEAD and prospective-merge GitHub CI results must be reviewed separately. Preserve `DENY_ALL`.
