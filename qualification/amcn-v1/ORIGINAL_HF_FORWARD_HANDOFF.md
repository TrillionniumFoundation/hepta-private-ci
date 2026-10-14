# Original archived MiniLM: genuine Hugging Face forward handoff (shadow)

**Capability claim:** research-only, source-checked HF BertModel forward **if and
only if the exact hosted source run succeeds**. This path does not assert that
a native Hugging Face execution was performed in the authoring environment:
`transformers` / `tokenizers` are absent there, and only the four
source/isolation regressions were locally executed (4/4 passing).

## Physical material and feature contract

Source: the exact original GitHub Actions artifact `11586991191`, ZIP SHA256
`07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af`.
The isolated hosted action downloads the **unchanged archive**, verifies the
outer ZIP before untarring only the original Encoder and LoCoMo files, and
revalidates original JSON/model/tokenizer/WordPiece SHA values before inference.
Unreachable/expired archive, missing weights, geometry drift and HF fast/slow
disagreement all fail; no surrogate learned features or model-card-only data
are permitted.

`amcn_real_hf_smoke.py` extracts exactly one label-blind pair of an original
question and a real first-session source turn from each of the original 10
LoCoMo conversation families. The choice is a fixed lexical-hash ordering,
not publisher support or answer lookup. On the original pinned file it yields
10 unique source-family hashes, 10 cases and 10 bounded question/source
payloads (largest 196 bytes). The original case inventory JSON SHA256 is
`1fd0803d5c9ae38f8764979f83705a4b535ccc0ecba93045b89449c0037d3578`
under the exact `case_sha256,input_sha256` list canonicalization.

The actual HF `BertConfig/BertModel` is initialized with the original
nreimers/MiniLM-L6-H384-uncased configuration and **all** original
safetensors tensor bytes. The historical `embeddings.position_ids` tensor is
validated exactly as `arange(max_position_embeddings)` before allowing
the modern nonpersistent-buffer difference. Missing/unexpected learned weights
remain fatal. Pinned `BertTokenizerFast` and `BertTokenizer` must produce
identical input IDs and attention masks, with no invisible truncation. CPU
`BertModel` produces a bounded 10×384 FP32 masked-mean L2-normalized feature
matrix saved using create-only safetensors and fsync with hashes and manifest.

The source/feature/snapshot digests and false-acceptance fields are retained
in the exact-head Action's artifact if the actual model forward succeeds.
The entire Python research implementation does not dispatch Codex, grant
FinalUse, load the selected production model, contact a memory writer or
modify a Cell lifecycle generation.

## Explicit limits

This is a *new, small physical native-HF smoke* on 10 original source-family
cues, not a rerun of the 1,472 historical manual BERT features, nor a Head
classification/RAG/Reader model trial. **It does not prove numerical parity
with the historical custom MiniLM implementation**, semantic citation,
parametric memory compression, future efficacy, independent labels or
production use. Genuine future calendar windows remain **zero**, and effective
independent sources cannot exceed the ten original conversations.

Source files and hermetic negative tests are committed, but the original model
weights and raw user conversations are not committed to Git. The exact hosted
workflow is `.github/workflows/hepta-amcn-original-hf-forward.yml`. Inspect
the actual workflow run ID, SHA, logs and source zip digests; an uncompleted or
failed job is not a physical success claim. Keep the parent PR Draft,
`blocking-ci` intact, and `production_accepted=false`.
