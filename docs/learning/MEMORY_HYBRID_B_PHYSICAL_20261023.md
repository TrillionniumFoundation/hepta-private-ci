# Source-separated physical A/B hybrid retrieval baseline (2026-10-23)

**Status:** `DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO`. This is a research-only candidate stacked on PR #3438 (`97a4bd088ed296da68ae8fa4deb49913e68e6ce4`), not a complete A–I experiment or proof that learned MemoryCells beat RAG.

## Why B must be physically original

The existing LoCoMo A/C/D experiment on the same historical corpus executes source-only retrieval. It does **not** run a frozen original dense Encoder and cross-Encoder reranker, so calling it a strong hybrid RAG control would be invalid. `memory_hybrid_b_physical.py` adds two **paired** per-question arms:

- **A_FTS5:** real SQLite FTS5 BM25 over original turns, with no neural forwards.
- **B_FTS5_DENSE_RERANK:** the identical BM25 lexical pool, pretrained all-MiniLM-L6-v2 dense embeddings over every original turn and query, RRF candidate union with lexical candidates, and an independently pretrained MS MARCO MiniLM-L6 cross-encoder reranking up to 32 candidates per question. Final output uses exactly eight original turns and at most 4,096 UTF-8 bytes.

The pair here is *not* the exact JS BM25 A arm in PR #3438; the difference is explicitly labeled. A third-party semantic Reader is **not invoked**; B presently tests only evidence retrieval, not full-answer accuracy. The original LoCoMo questions are historical and not blind prospective cases.

## Revisions and physical boundaries

- Dense model: `sentence-transformers/all-MiniLM-L6-v2`, exact Hugging Face revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` (Apache-2.0).
- Reranker: `cross-encoder/ms-marco-MiniLM-L6-v2`, exact revision `233902d25c440f23af6f7d6e94d2946bac0bee0a` (Apache-2.0).
- Original LoCoMo: SHA-256 `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`, source commit `3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376` (CC BY-NC 4.0).
- The exact local safetensors, configuration and tokenizer file byte inventories are computed **before** inference and compared to the submitted original-model inventory. The runner forbids remote code and pickle weights, rejects symlinks in input directories, uses a CPU batch-only inference path, and retains a per-query positive neural forward census.
- The protocol retains exactly the six historical evaluation groups and their 1,331 questions; the full paired A/B journal is 2,662 rows. Gold answers, evidence IDs, categories and authored observations cannot enter the B job's worker input.

The GitHub Actions pipeline runs three separate jobs: source-only `prepare`, physical `run` without original source/gold, and postseal `audit` which reacquires the original source **only after** original-model predictions are sealed. `prepare`/`audit` verify the original bytes via pinned source SHA. Predictions, model revisions, local model inventories, forward counts and resource estimates remain available as create-only workflow artifacts. A SHA is byte integrity, not an authenticated publisher identity or model-execution signature.

## How to reproduce

The dedicated workflow `.github/workflows/hepta-memory-real-hybrid-b.yml` uses exact source-head checkouts, frozen pip versions, exact model revisions, and workflow-local artifacts. Tests may run without downloading original neural models; those fixture checks are not a physical original-model result.

For manual execution in an isolated environment containing the exact original source and pinned safetensors:

```bash
python3 qa/stem-bakeoff/memory_hybrid_b_physical.py prepare \
  --source locomo10.json --worker worker.json --manifest plan.json

# Download pinned original model revisions, copy approved safetensors+config+tokenizer
# into dense-model/ and rerank-model/, then compute SHA-256 inventories.
python3 qa/stem-bakeoff/memory_hybrid_b_physical.py run \
  --worker worker.json --manifest plan.json \
  --dense-dir dense-model --rerank-dir rerank-model \
  --dense-inventory FULL_64_HEX --rerank-inventory FULL_64_HEX \
  --predictions physical-AB.jsonl

# Only in a separate reviewer process, after prediction-file sealing:
python3 qa/stem-bakeoff/memory_hybrid_b_physical.py audit \
  --source locomo10.json --worker worker.json --manifest plan.json \
  --predictions physical-AB.jsonl --report independent-A-B.json
```

## Scientific and production blockers that are NOT closed by this patch

The actual full original inference workflow must reach terminal success on its exact commit SHA; local fixture tests are not a substitute. Even if it passes, B only provides a stronger physically executed **retrieval** baseline, not a full RAG Reader. Complete same-Reader A–I answer generations, blind semantic citation checking, prospective family-level power (200 independent future families, two independently collected windows), authenticated source deletion, real equal-total-cost costings, E–I evidence-specific local training and NDU-mediated split/merge qualification remain open.

No Brain/Cell production model selection, neural weights, source permissions, topology or FinalUse authority is modified. Research workflows must not waive Cargo/Bazel/architecture CI. `HOLD_NO_GO` is unconditional here, including when B retrieval happens to beat A on support recall.
