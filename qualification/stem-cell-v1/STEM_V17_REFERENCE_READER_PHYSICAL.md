# V17 — stronger Reader source-first physical experiment

**RESEARCH / DRAFT / SHADOW_ONLY / HOLD_NO_GO / DENY_ALL. No main merge, no selected model, no FinalUse, no automatic Cell Split.**

## Research question and strict predecessor

PR #2429 V16 physically executed 128 original 135M Reader requests over four original evidence arms for 32 retrospectively selected LoCoMo questions, comprising four correlated historical families. The cohort where a publisher-answer string literally occurred in an annotated source produced 8/16 target substrings in the witness arm; the no-evidence, BM25-only and witness-lesion arms each produced 0/16. Exact whole answers matched 0/16. This **does not certify human-reviewed sufficient evidence or semantic reasoning**.

V17 adds an **executable real reference Reader path** for the same 128 previously frozen question/evidence combinations, plus an independent model-free replay/reviewer. A real original-source/model execution is a distinct task from adding executable research code; no authentic Qwen forward or new human judgment was executed in this authored slice.

## Model and source custody

- Frozen original 135M candidate: exact existing V16 source/Reader results, not rerun.
- Reference candidate: Qwen/Qwen3-0.6B at exact public revision **16706fc57485378d4ffaf54139b29ccc66ae08fa**. Parameter count does not establish actual reader skill. The deployed exact checkpoint files must be physically SHA-256 authenticated before any inference.
- Four arms: no evidence, original BM25 Top-3, original publisher-witness plus BM25 Top-2, lesion without that witness. Cases, ordered source IDs, prompt source text, root identities, original request SHA256 and 24-new-token cap are frozen.
- Different model chat templates yield different input-token IDs and counts. Match *actual question and evidence content*, not a fictional identical tokenizer/computational budget.
- Qwen runs with enable_thinking=false and greedy generation for a bounded diagnostic. This can disadvantage this particular reference policy; report the actual result and cost without claiming universal 0.6B model incapacity.
- V16 cases were selected retrospectively using publisher answers. They are not independent prospective task families, and a literal target string in a witness is not independently verified sufficient evidence.
- Private source, BM25 routes, question text, publisher answer labels, model weights, prompt bytes, raw model answers and tokens stay in operator-local private files. Source-only Actions never upload or download them.

## Model material and prelabel manifest

Stage a local *flat* snapshot containing all relevant allowed files from the exact public revision. Model files MUST be regular, SHA-verified, and immutable across loading. The required files are config.json, tokenizer_config.json, tokenizer.json, model.safetensors. Optional allowlisted files are generation_config.json, vocab.json, merges.txt. No pickle weight formats, symlinks, unregistered extra files, unsafe remote code, on-demand mutable model tags or network fallback.

Before the first model call, freeze a manifest such as the following, replacing placeholder hashes with SHA256 of **actual files**, recording every optional file present:

~~~json
{
  "schema": "hepta.stem.v17.physical-reference-reader.shadow.v1.frozen-model-v1",
  "repo_id": "Qwen/Qwen3-0.6B",
  "revision": "16706fc57485378d4ffaf54139b29ccc66ae08fa",
  "files_sha256": {
    "config.json": "<physical sha256>",
    "tokenizer_config.json": "<physical sha256>",
    "tokenizer.json": "<physical sha256>",
    "model.safetensors": "<physical sha256>"
  },
  "thinking": false,
  "decoding": "greedy-24-new-tokens",
  "production_authorized": false
}
~~~

Self-reported hashes alone do not replace third-party publisher identity or model-host attestation. Verify against the official pinned revision/source before granting evidentiary weight. This implementation never makes such authority claims.

## Physical local execution with original private source and weights

~~~bash
export PYTHONPATH=qualification/stem-cell-v1
python qualification/stem-cell-v1/v17_reference_reader_physical.py \
  --plan PRIVATE/v16-plan.json \
  --source PRIVATE/source-only.json \
  --bm25 PRIVATE/original-bm25-private-routes.json \
  --model-dir PRIVATE/qwen3-0.6b-pinned-flat \
  --model-spec PRIVATE/v17-model-spec.json \
  --output PRIVATE/v17-reference-answers.json
~~~

The producer independently invokes the original V16 full source+BM25+plan validator. It rejects changed original prompts, question/evidence order, model revision/files and incompatible tokenizer geometry before output. Each original request start is fsynced to an owner-private 0600 file before the physical model generation. A full answer file is create-only and sealed after all 128 calls; a crashed or partial run is ineligible.

Use a separate process to re-open model materials and independently tokenize/decode and review all 128 actual reference outputs, *without model generation*:

~~~bash
python qualification/stem-cell-v1/v17_reference_independent_review.py \
  --plan PRIVATE/v16-plan.json \
  --source PRIVATE/source-only.json \
  --bm25 PRIVATE/original-bm25-private-routes.json \
  --model-dir PRIVATE/qwen3-0.6b-pinned-flat \
  --model-spec PRIVATE/v17-model-spec.json \
  --answers PRIVATE/v17-reference-answers.json \
  --starts PRIVATE/v17-reference-answers.json.starts.jsonl \
  --candidate PRIVATE/v16-original-answers.json \
  --review-output PRIVATE/v17-byte-review.json
~~~

Only after **both** original candidate and reference answers are sealed, a separate private label-holder may add:

~~~text
--original-gold PRIVATE/locomo.json --gold-output PRIVATE/v17-postseal-literal.json
~~~

The label scorer only computes *descriptive exact/literal string counts*, case paired between models. Its outputs do not establish source entailment or semantic correctness. Independent human evaluation is still mandatory.

## Scientific status and next hard gates

The new source modules and 30 adversarial/synthetic tests have been compiled and physically executed in isolated local Python, both normal and python -O. Fake tokenizer/model fixtures are **not** original pretrained inference or natural-task efficacy. Dedicated GitHub Actions are read-only source-only CI and do not access the private 135M/Qwen models. Exact remote HEAD tests/global blocking-ci remain separate requirements.

Still **unverified**: actual reference-model 128/128 physical calls, original source/model publisher signatures, human-certified sufficient evidence and grounded answer/citation entailment, real Qwen tokenizer/operator compatibility, matched full lifecycle costs, future-date independent families, V6 seed41 retention, Cell Split learning effects, NDU/FBSDE gains, multimodal generation and 10T/100T capability equivalence.

Even a genuine reference improvement would diagnose **Reader capacity**, not prove that shared Stem, cell fission or NDU caused the gain. Production authorization remains false.
