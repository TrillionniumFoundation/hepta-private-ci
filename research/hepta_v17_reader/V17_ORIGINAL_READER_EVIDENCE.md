# V17 — physically executed source-first original Reader sufficiency diagnostic

**Research-only · DRAFT · SHADOW_ONLY · HOLD_NO_GO · DENY_ALL · NO MAIN MERGE.**

Stack on V16 HotpotQA source-only Cell Group PR #2470 at exactly `8473feb05c03efeb54851a64533844e62bc66133`. This research is a **separate original LoCoMo Reader capacity diagnostic**, not a new HotpotQA model or NDU control. V16 HotpotQA is still awaiting its own original 7,405-item hosted run. No native Worker, model selection, NDU, Cell Split, CNS/CAS/FinalUse or production owners are changed.

## Why LoCoMo, and exact original provenance

The physically executed 135M original Reader was already SHA-locked in Hepta's V12/V14–V16 investigations. The complete original Actions artifact **11586991191** (ZIP SHA256 `07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af`) has been reopened. Its `memory-inputs.tar.gz` contains genuine LoCoMo source conversations, the exact frozen BF16 30-layer Llama-style 135M Reader, tokenizer and config. Extracted byte checks:

| Material | Original SHA256 |
| --- | --- |
| `locomo.json` | `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4` |
| `reader/model.safetensors` | `5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c` |
| `reader/tokenizer.json` | `9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c` |
| `reader/config.json` | `8eb740e8bbe4cff95ea7b4588d17a2432deb16e8075bc5828ff7ba9be94d982a` |

The original archived weights are loaded into a manually reimplemented FP32 Torch Reader with real 30-layer attention, KV cache and ByteLevel BPE. This is **not** certified numerically identical to the official Hugging Face tokenizer, operators or GPU paths; cross-host/official parity is unverified. The experiment reuses a single loaded Reader across the study; no pretrained weights, original conversations, prompts, labels, output tokens or raw original answers are committed.

## Frozen source-first experiment, not retrospective answer selection

1. Read the **ten complete original conversation roots**. Generate a *public* question/utterance corpus and separately store all original publisher answer/evidence annotations.
2. Select the SHA256-lowest **three question IDs per root**, before looking at publisher answers or evidence. Total **30 questions** (10 correlated roots, not 30 independent future samples).
3. An annotation-only stage emits at most three **publisher-cited original utterance IDs** for each selected question, without the publisher answer string. Publisher utterance IDs are *not independent human certification of sufficient evidence*.
4. Generate four exact Reader input arms: `none` (no evidence), `retrieved` (question-local lexical Top-3), `annotated` (publisher-cited utterances), `lesion` (remove first annotated utterance). Truncate each included original utterance to 240 characters; no tokenizer truncation. No publisher answer enters the inference prompt.
5. Before physical inference, validate the exact public source, model tensor bytes, all prompt-bytes digests and token caps; journal every **distinct physical prompt SHA** with `fsync` *before* invoking the real Reader. Equivalent prompts reached by multiple logical arms reuse the same physical output. Never give identical frozen model inputs different policy-dependent answers.
6. An independently authored numerical/source reviewer reopens the original corpus **after inference**, reconstructs every question, literal evidence ID, BM25 ranking, prompt, BPE tokens and output text/token SHA, and verifies the original forward journal, costs and publisher-answer text proxies.

No run-time gold, correct-answer labels or trained Cell Head is used by the Reader, ranker or adaptive selector. This is not an intervention proving the witness is semantically adequate. Because publisher labels reside on the same local machine during experiment preparation, process separation is **not OS/cryptographic independence**. The model forward itself is only an observational answer result; independent signed host provenance and human evaluation are missing.

## Actual original CPU outcome — 2026-10-16

The locally run original SHA-pinned model finished without synthetic substitutes:

| Cost/outcome | Observed |
| --- | ---: |
| Original questions / source families | 30 / 10 |
| Logical arm requests | 120 |
| Physically distinct prompt inputs | 96 |
| Actual counted original model forward calls | 1,777 |
| Actual model CPU time | 245.773 s |
| Actual model wall time | 127.172 s |
| Output strict whole-string publisher answer equality | 0/30 in every arm |

Weak **publisher answer substring occurrence in original model output**, *not independently human-judged correctness*:

| Arm | Weak substring occurrence | Whole-string equality | Valid `[E#]` citation mentions |
| --- | ---: | ---: | ---: |
| none | 0/30 | 0/30 | 0 |
| retrieved | 3/30 | 0/30 | 10 |
| annotated | 5/30 | 0/30 | 4 |
| lesion | 0/30 | 0/30 | 1 |

The original Reader also fails to emit a literal `unknown` / `not enough information` response on this panel. These are descriptive text proxies and **not** verified hallucination diagnoses. A tiny annotated-support contrast suggests changing evidence can change model outputs, not that the Reader is sufficient. Token and evidence budgets differ among arms and no full lifecycle equal-cost success claim is made.

The independent source+token+forward reviewer reproduced **all 96 original physical SHA/inputs, all 120 logical condition bindings, every answer/token SHA and exactly 1,777 original model forwards**. A second fresh model process executed **12 deterministically SHA-lowest distinct prompts**, **265 new real forwards**, reproducing **12/12 generated token arrays and raw-answer bytes exactly**. The latter does not make the 12 questions independent nor certify official tokenizer parity.

Local source-contract test suite: **20/20** ordinary `python -S` and **20/20** under `python -O -S`, with no network, weights or Torch import. Hosted exact-HEAD source-only CI and any independent physical host still need their **own** terminal check; GitHub Actions queue is not a completed run.

## Reproduction (no simulation substituting original weights)

From repository root, with Python >= 3.12, installed `torch`, `regex`, `safetensors`, and the independently SHA-verified original archive unpacked privately:

```sh
D=research/hepta_v17_reader
python -S -m unittest discover -s "$D" -p 'test_v17_original_reader.py' -v
python -O -S -m unittest discover -s "$D" -p 'test_v17_original_reader.py' -v
python "$D/source_first.py" prepare --source "$PRIVATE/locomo.json" --out "$PRIVATE/owned"
python "$D/source_first.py" plan --public "$PRIVATE/owned/public.json" --owner "$PRIVATE/owned/owner.json" --out "$PRIVATE/owned/plan.json"
python "$D/source_first.py" annotate --public "$PRIVATE/owned/public.json" --owner "$PRIVATE/owned/owner.json" --hidden "$PRIVATE/owned/hidden.json" --plan "$PRIVATE/owned/plan.json" --out "$PRIVATE/owned/annotation.json"
python "$D/source_first.py" requests --public "$PRIVATE/owned/public.json" --owner "$PRIVATE/owned/owner.json" --plan "$PRIVATE/owned/plan.json" --annotation "$PRIVATE/owned/annotation.json" --out "$PRIVATE/owned/requests.json"
python "$D/physical.py" --public "$PRIVATE/owned/public.json" --owner "$PRIVATE/owned/owner.json" --plan "$PRIVATE/owned/plan.json" --annotation "$PRIVATE/owned/annotation.json" --requests "$PRIVATE/owned/requests.json" --reader-dir "$PRIVATE/reader" --private-output "$PRIVATE/owned/physical.json"
python "$D/independent_review.py" --original "$PRIVATE/locomo.json" --public "$PRIVATE/owned/public.json" --owner "$PRIVATE/owned/owner.json" --hidden "$PRIVATE/owned/hidden.json" --plan "$PRIVATE/owned/plan.json" --annotation "$PRIVATE/owned/annotation.json" --requests "$PRIVATE/owned/requests.json" --physical "$PRIVATE/owned/physical.json" --starts "$PRIVATE/owned/physical.json.starts.jsonl" --reader-dir "$PRIVATE/reader" --output "$PRIVATE/owned/review.json"
python "$D/repeat.py" --requests "$PRIVATE/owned/requests.json" --physical "$PRIVATE/owned/physical.json" --reader-dir "$PRIVATE/reader" --output "$PRIVATE/owned/repeat.json" --n 12
```

Raw original material is private. Only sanitized numeric observation and source SHA receipts may go into Git or public Actions artifacts. A failed or interrupted execution retains its `.starts.jsonl` and must never be counted as a completed physical inference.

## Strict next gate / current decision

**HOLD_NO_GO**. Missing: a genuinely stronger Reader with original physical same-questions performance, independent human-certified sufficient evidence, semantic answer + citation entailment, comparison under equal full input/model/training cost, source-independent future windows and V6 retention repair. Only after the Reader adequacy gate passes should any System 2 NDU/FBSDE benefit or automatic Cell split be considered. Do not promote this Reader, modify selected models, merge into main or authorize effects based on these results.
