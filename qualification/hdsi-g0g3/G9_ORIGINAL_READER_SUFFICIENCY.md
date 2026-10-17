# G9 — original-answer Reader sufficiency before further NDU/Circuit investment

**DRAFT / RESEARCH_ONLY / SHADOW_ONLY / HOLD_NO_GO / DENY_ALL.** No new model selection, `main` merge, native Neuron/NDU/Worker changes, signed FinalUse or physical Cell Split.

## Why this experiment follows G8

G8 found that 96/96 historical LoCoMo held-out questions have at least one evidence annotation somewhere in the full original source set, yet its best cheap Evidence Hit@5 was 48/96. The measured value of an NDU action is not the same thing as the ability of the final Reader to extract a correct answer. This experiment isolates Reader sufficiency before introducing a new learned FBSDE coefficient or spending additional compute on Cell topology.

The diagnostic deliberately stays on the **same already-public LoCoMo publisher family** and the exact G8 held-out question roster. It does **not** establish a new independent publisher or a prospective held-out window. Stronger Reader and out-of-publisher testing remain separately required.

## Frozen source and four diagnostic arms

- Original archival artifact: GitHub Actions artifact `11586991191`, outer ZIP SHA256 `07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af`.
- Original LoCoMo JSON SHA256 `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`.
- Native original SmolLM Reader 135M BF16 safetensors SHA256 `5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c`. Reference loads BF16 weights to **FP32 CPU**; tokenizer.json SHA256 `9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c`.
- Select exactly **the first four questions of the already-fixed 24-question G8 list per `conv-47` through `conv-50`**, in the same hash order. This is not selection by gold answer or model outcome. The independent reviewer re-derives that source-first selection rather than trusting supplied qids.
- Four arms receive exactly the same question and answer format: `none` (no evidence), `bm25` (top-five full-corpus lexical results), `oracle` (all registered original publisher evidence addresses, **not** a retriever), `lesion` (the oracle list with the first canonical evidence address removed). Lesion is not guaranteed to remove all sufficient information if there are multiple original supports.
- The source owner necessarily consults original publisher evidence IDs to build the diagnostic oracle and lesion arms. **It does not export the publisher answer field.** A separate model worker consumes only a sealed label-free panel and SHA-verified original Reader material; a different reviewer reopens publisher answers only after all 64 outputs are sealed.
- Each output is capped at 24 new tokens, every prompt bounded at 1024 tokens, `UNKNOWN` is legal, and every true forward (including one that produces EOS) is paid. Model weights, original conversation text, original questions/answers and case-by-case outputs are **not** committed to Git.

## Actual original physical execution in the authoring CPU container

The original four-root physical run completed **64 genuine Reader requests** (16 original questions × 4 arms). Their four distinct model-process counters sum to **1,066 completed full-layer forward calls, 64 prefill calls, 9,558 physical prompt token positions, and 1,020 actual visible generated tokens**. The local 4-process wall-clock total is **56.60605 seconds**, CPU time **224.15383 seconds**, highest self-reported Linux process maximum resident size **1,074,507,776 bytes**. These costs exclude the original archive download, model loading, independent validation and the cost of building full-corpus BM25; they are not hardware-signed target-host p95/p99/TCO values.

The source-first 16 questions include one publisher item with `adversarial_answer` but without the conventional `answer` key. That entry remains in all four paid arms and is reported **unscored**, not silently dropped or relabeled. The conventional original answer denominator is 15.

| Actual original arm | Literal complete original-answer phrase appears in output | Exact normalized whole output | Mean token overlap F1 |
|---|---:|---:|---:|
| None | **0/15** | 0/15 | 0.024410 |
| BM25 top 5 | **2/15** | 0/15 | 0.112080 |
| Publisher annotated evidence | **3/15** | 0/15 | 0.207714 |
| First annotated support removed | **0/15** | 0/15 | 0.085816 |

These are **retrospective lexical proxy metrics**, not human semantic adjudication, a causal NDU lift, independent source generalization, or a reader/model selection result. The full publisher evidence often fails to elicit the complete literal original answer with this small Reader. A failure with the oracle may reflect Reader capacity, prompt representation, tokenizer implementation, an ambiguous publisher answer, or the strict scoring proxy. It should prompt controlled stronger-Reader comparison, not bigger Cell Split or more FBSDE solver iterations.

A separate actual numeric regression compares complete-prefix forward logits against single-token KV-cache extension logits with the same original model: maximum absolute deviation about `0.0000190735`; the next-token argmax agrees. This is a **same-host internal implementation check**, not official Hugging Face Transformers/tokenizers byte parity. This custom native byte-BPE tokenizer and Llama reference must be independently compared with the upstream native tokenizer and logits before a general Reader-capacity claim.

## Engineering custody and original proof boundaries

- `g9_material_custody.py`: exact original archive SHA, safe allowlisted regular-member extraction, per-file SHA, two distinct caller scopes, no bearer token sent to a redirected archive download host. Source owner emits a SHA-sealed answer-free panel; model worker obtains only original Reader weights, config and tokenizer; independent reviewer reacquires only the original JSON.
- `g9_reader_panel.py`: original G8 frozen case IDs, all four complete source addresses and content SHA, strict unknown-field denial, create-only fsynced packet.
- `g9_native_reader.py` / `g9_physical_reader.py`: CPU reference with bounded 30-layer Llama, 9 attention heads/3 KV heads, prefix/KV continuation and 64 exact four-arm calls. Literal side-effects and product hooks are not available.
- `g9_independent_review.py`: new source-first G8 roster computation independent of producer, new BM25 score computation, same-source original oracle/counterfactual recheck, strict raw prediction seal, exact forward/EOS accounting and truthful optional evidence metrics; **does not import Torch or the producer**.
- `test_g9_reader.py`: adversarial source/authority tests; authentic original model and original public data tests are separate optional cases, not recorded as successes when material is absent.
- `.github/workflows/hepta-hdsi-g9-reader.yml`: four read-only exact-current-HEAD jobs. Original model execution is push-only and not allowed for untrusted PR/fork events; original reviewer runs on a separate Actions job only after complete prelabel seals. No workflow self-push or CI bypass.

The G8 inherited typo `pre-selected` → `preselected` is corrected in the additive G9 child tree because the G8 exact HEAD's `codespell` workflow observed a real failure. It does not modify any G8 algorithm or original-result JSON.

## Next conditional experiment

Before any Stem selection, NDU System 2 promotion or structural Cell change, compare a pinned stronger Qwen3-class Reader under the **same 16-case four-arm panel** with full tokenizer/operator upstream parity, source-owned gold, independent postseal human/semantic answer audit and actual token/CPU/GPU cost. Include unchanged cheap BM25 and avoid comparing a changed Reader's benefit to Cell/NDU training. Then run on genuinely separate source families and a future-time cohort.

**Nonclaims:** no production runtime integration, no certified probability of correctness, no global FBSDE solution, no NDU-specific improvement, no cross-host numeric identity, no Reader model winner, no action authority or automatic merge. The final position remains **HOLD_NO_GO / DENY_ALL**.
