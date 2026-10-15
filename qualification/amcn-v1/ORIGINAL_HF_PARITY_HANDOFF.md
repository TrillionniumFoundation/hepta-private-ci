# AMCN: original archived HF tokenizer / pretrained Reader parity and six-case natural diagnostic

**Research-only, DRAFT / DENY_ALL, not a new MemoryCell qualification or a nine-arm outcome.**

This increment goes beyond fixed numeric token IDs while retaining all existing owners in `qualification/amcn-v1`. It does not train new Heads, alter Q24 journals, replace cognitive.store, change a production selector or modify `blocking-ci`.

## Original source inventory

The source is the **unchanged archived original** GitHub Actions artifact `11586991191` in `TrillionniumFoundation/hepta-private-ci`: outer ZIP SHA-256 `07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af` (376,363,859 bytes).

| Pinned original file | SHA-256 |
| --- | --- |
| `reader/model.safetensors` (30-layer BF16 Llama 135M class) | `5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c` |
| `reader/tokenizer.json` (GPT-2 ByteLevel/BPE, Digits pretokenizer) | `9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c` |
| `encoder/model.safetensors` (six-layer MiniLM/BERT) | `53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db` |
| `encoder/tokenizer.json` | `be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037` |
| Original publisher LoCoMo JSON | `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4` |

## Offline physical execution and critical qualification distinction

`amcn_original_text_reader.py` implements a bounded **candidate** offline GPT-2 ByteLevel BPE from the original tokenizer JSON and a real 30-layer BF16 original-checkpoint Llama forward using FP32 PyTorch and causal KV caching. It runs without Transformers installed, but **this must not be called the official Hugging Face implementation**. Its fixed-original-token numeric Logits SHA-256 reproduces prior physical probe `0e213cba29020f3140dee7e72d5b8737ebcb2ce0e0189e5662b8415a09f71776` exactly. Cached incremental/uncached full sequence Logits on that four-token input differ by `~1.86e-5` maximum absolute FP32 tolerance; ArgMax/Top-5 agree.

**Official parity remains pending.** `amcn_original_hf_parity.py` **requires genuine** `transformers==4.46.3`, `tokenizers==0.20.3` and CPU PyTorch. It verifies actual Hugging Face fast Tokenizer IDs for multiple real English/multilingual/chat snippets; reloads the original six-layer `BertModel` and 30-layer `LlamaForCausalLM`; independently compares FP32 BERT CLS and pooler and Llama Logits/tokens with numerical tolerance and agrees on original greedy generated IDs for a real natural-language evidence question. Any missing package/source, changed model/tokenizer bytes, numeric difference, Top-5 change or divergent natural greedy tokens is **a failing gate**; there is no manual fallback. The separate source-only local container had no `transformers`/`tokenizers` installation and DNS package installation failed. Therefore no valid `real_official_fast_tokenizer_parity` or `real_official_model_forward_parity` result is claimed until the exact-HEAD job has succeeded.

See `.github/workflows/hepta-amcn-original-hf-parity.yml` for the read-only SHA-pinned physical replay. The job uploads source/results/negative caveats **not** model bytes. A successful parity check alone does not establish QA correctness, strong RAG, model promotion, semantic citation accuracy, provenance trust, independent future-time windows or any production authority.

## Original LoCoMo six-case, two-family preliminary Reader diagnostic

`amcn_original_locomo_trial.py` **prepares** a create-only source-first public request file with no gold answers or publisher evidence, and separately writes the withheld publisher target file. A distinct Reader process receives only the externally SHA-256-pinned public file and original Reader directory; a separate post-seal scorer opens withheld targets **after** original raw answers are persisted. It uses whole source-dialogue BM25 (no gold), immutable top-3 evidence snippets and the archived 30-layer pretrained Reader at `max_new_tokens=24` with greedy decoding. All inputs are historical, not prospective, and no independent issuer signature exists.

In an isolated analysis container **not the user's dot host**, on 2026-10-15 the source first process successfully produced six physical natural-language answers from two original conversation families. **Only these 6 sealed attempts count**; an attempted 12 × 48-token parent batch exceeded container execution limits and has no completed answer seal.

| Historical diagnostic (not production acceptance) | Observed |
| --- | --- |
| Complete source-first questions / families | 6 questions / 2 published conversation families |
| Total final Reader input tokens | 1,416 |
| Original BF16-reader FP32 generated tokens | 106 |
| External publisher weak-support evidence in lexical Top-3 | 3/6 |
| Exact **literal** output equality to publisher answers | **0/6** |
| Original responses reaching 24-token generation ceiling | 3/6 |
| Independent semantic answer success | **not evaluated** |
| Strong hybrid RAG/typed Cell/graph/9-arm comparison | **not executed** |
| True future calendar windows | **0** |

The zero literal-match count is a **negative descriptive observation**; it must not be reclassified as the natural-language task success rate because semantic entailment, answer sufficiency, citations and judge independence have not been assessed. Of the questions with recorded weak publisher support in the retrieved context, no parameter-learning attribution is possible because the Cell Head comparator was not executed.

Original immutable input/output SHA-256 identities, with gold kept in its own file:

- Public source-first requests (6): `60593b01bddd1e7c39acd0f94c269e1d113d6eaedbe83d087527c612cc454e53`.
- Separate publisher-gold envelope: `e22268bc250f5d938a25290cf29ac787456ef2618fac5fa7251ba3425e3871cf`.
- Original full Reader answer receipt, bound to the exact public payload: `21ace00e57d8a24d3a68f4543ac01a296a8676c6954e1fcd8a9536388923ad22`.
- Post-seal descriptive-only scoring: `9b993c74269616de34b0c318fa21cb2790b2a6f945a292e0a47799feae63d59a`.

Those exact digests describe one isolated runtime, **not** an independently verified upstream model/Reader execution. The source and raw answer bytes must be retained and reviewed separately; do not pretend these hashes are model-owner signatures.

### Reproduction (requires independently supplied, original SHA-pinned archive)

```sh
PYTHONPATH=qualification/amcn-v1 python3 qualification/amcn-v1/amcn_original_locomo_trial.py prepare \
  --source-root /local/original \
  --public /new/public-requests.json \
  --withheld /isolated-evaluator/withheld-publisher-targets.json \
  --question-indices 0,1,2

PYTHONPATH=qualification/amcn-v1 python3 qualification/amcn-v1/amcn_original_locomo_trial.py generate \
  --public /new/public-requests.json \
  --public-sha256 "$EXTERNALLY_FROZEN_PUBLIC_FILE_SHA256" \
  --reader /local/original/reader \
  --output /new/original-reader-answers.json \
  --max-new-tokens 24

PYTHONPATH=qualification/amcn-v1 python3 qualification/amcn-v1/amcn_original_locomo_trial.py score \
  --answers /new/original-reader-answers.json \
  --answers-sha256 "$EXTERNALLY_FROZEN_ANSWER_FILE_SHA256" \
  --withheld /isolated-evaluator/withheld-publisher-targets.json \
  --withheld-sha256 "$EXTERNALLY_FROZEN_WITHHELD_FILE_SHA256" \
  --output /new/publisher-weak-descriptive.json
```

The public envelope / immutable original-answer envelope are cross-bound to the same public payload SHA. Unknown fields, duplicate JSON fields, altered model answer bytes, swapped source-family claims or missing answers are rejected. The diagnostic does not synthesize better evidence to make a model look capable. No deployment, main merge, automatic Cell fission or FinalUse is authorized by this increment.
