# AMCN original LoCoMo ten-family source-first retrieval — observed NO-GO

**Authority:** SHADOW / DENY_ALL. This is original archived pretrained MiniLM retrieval with real CPU tensor forwards, **not** whole-task Reader completion, independent strong hybrid RAG, parameter-learning evidence, or a production MemoryCell. Do not merge to `main`, authorize FinalUse or relax `blocking-ci` on this basis.

## Why this experiment exists

Earlier #2085 diagnostics compared BM25 to original MiniLM/BM25 on **six natural-language questions from two original LoCoMo families**; the final Top-3 retrieval publisher weak-support was tied 3/6 and literal Reader answer match was tied 0/6. That cannot support general memory-system claims. This increment expands only the *retrieval* axis to the **entire original source census: 5,882 real dialogue turns; 1,986 original questions, 10 historical families**. It does **not** retroactively produce 1,986 Reader answers.

The original source is immutable GitHub Action artifact `11586991191`, outer archive SHA-256 `07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af`, containing LoCoMo original JSON SHA-256 `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4` and physically executed six-layer MiniLM BERT safetensors SHA-256 `53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db`.

## Three distinct execution phases

`amcn_original_full_family_retrieval.py` exposes `prepare → rank → score`. **Prepare** accepts only the exact original archive, writes a complete source+question packet, and writes publisher weak evidence IDs **to a separate create-only file**. Composite publisher references (such as `D8:6; D9:17`) and zero-padded IDs are parsed explicitly instead of scored as single nonexistent sources; unresolved labels remain counted. **Rank** consumes only a caller-SHA-pinned source packet; it uses the actual archived MiniLM BF16 pretrained tensors in FP32 CPU PyTorch through the existing experimental WordPiece+BERT adapter. The source-first BM25 index caches original per-source token counts once per family and has been checked against the prior unoptimized original BM25 Top-16 ordering. Ranking precommits four candidate algorithms, never sees publisher gold, outputs all 1,986 question records, and writes exactly one create-only sealed rank packet. **Score** runs separately and opens weak publisher support only after the exact rank packet is sealed; every case, source, split, original rank and ranking arm stays in the denominator. Changed bytes, duplicate IDs, missing cases and label-smuggling are rejected.

Frozen arm definitions (not selected from heldout labels): original full-source BM25, original MiniLM cosine retrieval, a 50/50 normalized BM25+dense rank mixture, and RRF(k=60) over the full BM25+dense source orders. No type-specific fine-tuning, extra Head bank, learned graph or trained Router is present. The MiniLM pooling and WordPiece implementation are **not** authenticated as numerically identical to the official Hugging Face Transformers/Tokenizer implementations. The separate #2085 official-HF parity action must independently pass; a hash alone does not prove parity.

To avoid inflated statistical sample counts, the 10 independent original conversation-family roots are disjoint. Six families are marked TRAIN (only a cohort label, no training performed here), two SELECT, and the final two original families are called `retrospective_heldout_a/b`. These are **not** new future calendar windows. The heldout thresholds and mixture weights are precommitted; the two holdout groups are not used to fit or select hyperparameters. We do not pretend 400 questions from two correlated roots are 400 independent experiments.

## Actual isolated-container physical observations (2026-10-15)

Original local process: Python 3.13.5, CPU PyTorch 2.10.0, NumPy 2.3.5, safetensors 0.7.0, **not** user's dot host. Loaded original 90.9 MB MiniLM model, performed **257 physical Encoder batches totaling 307,714 tokenizer input positions**, and scored all **1,986 questions over 5,882 original source turns**. The first unrestricted all-family run timed out because it re-tokenized entire source inventories per question; no sealed result was claimed for that attempt. After an indexed BM25 optimization, the complete source-first rank was sealed and scored. All source family partitions were preserved, including unsupported and ambiguous publisher citations.

Two *retrospective* heldout families (`conv-49` and `conv-50`, 400 questions total):

| Original-weights retrieval arm | Weak Hit@1 | Weak Hit@3 | Weak all-support@3 | Weak Hit@16 | Weak all-support@16 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Original BM25 | **120/400** | **182/400** | **155/400** | 263/400 | 217/400 |
| Frozen original MiniLM cosine | 51/400 | 91/400 | 70/400 | 194/400 | 150/400 |
| BM25 + MiniLM 50/50 rank blend | 91/400 | 156/400 | 126/400 | 259/400 | 211/400 |
| BM25 + MiniLM RRF(60) | 95/400 | 156/400 | 126/400 | **276/400** | **227/400** |

RRF discovered publisher-labelled support in **36 questions BM25 missed at Top-16**, but lost labelled support for **23 questions BM25 found**: net **+13/400**. However at the **actual current Reader Top-3 frontier**, BM25 still led RRF by **26/400** on any publisher support and **29/400** on *all* annotated support. RRF's 16-evidence improvement cannot be treated as a superior three-evidence Reader context; expanding to 16 changes total evidence and compute budgets. Across the 10 families the pattern is not uniformly positive; strong observed MiniLM cosine ranking is **not** established. Two heldout questions have no matching publisher annotation in the admitted original source census, and two source questions have unresolved publisher-reference strings.

**No causal-memory-system conclusion:** The true strong RAG, physical supervised typed Heads, physically trained graph associations, one exact original Reader task pipeline under matched evidence/token/compute budget, independent semantic QA, original source-issuer authentication and prospective future windows are all absent from this experiment. Original retrieval Hit@K is a *publisher weak-support proxy*, not full-answer success, model compression or qualified long-term retention. These negative and budget-dependent outcomes must be retained without cherry-picking Top-16.

### Immutable local result identities

- Label-blind original source packet: `ac5f95085e5b223f81e888236e2c162f1ef45a3d1f52ad3e903fde48a629a633`.
- Label-blind physical model retrieval packet: `25bd9754e1da4ee5ddf620e7f3c734f06650568278c6aab51916d55046baef99`.
- Separately withheld original publisher support: `758d951c2fb296c3ba23ef539e3f243fb8464d52ed0d42c8d0981943ac907a06`.
- Complete, separately scored raw publisher weak-label aggregate: `48f2e19ac691a0bbf4ab5be4d1a995758b1f7c36b8ee8274ad20bae2d580960c`.
- `ORIGINAL_TEN_FAMILY_RETRIEVAL_20261015.json` stores only grouped counts, hashes and negative flags; neither original model bytes nor raw dialogue text nor publisher per-question gold is committed.

### Exact reproduction (research, not production)

Prerequisite: independently provided and SHA-verified exact original archive, safe-selected `locomo.json` and original `encoder/model.safetensors`, `encoder/tokenizer.json`, `encoder/config.json`, `encoder/vocab.txt`; CPU `torch`, `numpy`, `safetensors`, `regex`.

```sh
# Source and publisher labels are written once; rank gets only source input.
PYTHONPATH=qualification/amcn-v1 python3 qualification/amcn-v1/amcn_original_full_family_retrieval.py prepare \
  --archive-root "$ORIGINAL_ROOT" --public "$PRIVATE/public-sources-only.json" \
  --withheld "$PRIVATE/withheld-publisher-weak-labels.json"
SRC=$(sha256sum "$PRIVATE/public-sources-only.json" | cut -d' ' -f1)
PYTHONPATH=qualification/amcn-v1 python3 qualification/amcn-v1/amcn_original_full_family_retrieval.py rank \
  --public "$PRIVATE/public-sources-only.json" --public-sha "$SRC" \
  --encoder "$ORIGINAL_ROOT/encoder" \
  --output "$PRIVATE/ten-family-real-original-minilm-rank.json" --batch 32
PRED=$(sha256sum "$PRIVATE/ten-family-real-original-minilm-rank.json" | cut -d' ' -f1)
GOLD=$(sha256sum "$PRIVATE/withheld-publisher-weak-labels.json" | cut -d' ' -f1)
PYTHONPATH=qualification/amcn-v1 python3 qualification/amcn-v1/amcn_original_full_family_retrieval.py score \
  --public "$PRIVATE/public-sources-only.json" --public-sha "$SRC" \
  --ranked "$PRIVATE/ten-family-real-original-minilm-rank.json" --ranked-sha "$PRED" \
  --withheld "$PRIVATE/withheld-publisher-weak-labels.json" --withheld-sha "$GOLD" \
  --output "$PRIVATE/score-complete.json"
```

The exact-head workflow `.github/workflows/hepta-amcn-original-full-family-retrieval.yml` physically reruns the model on isolated CPU and retains **only** tests/source identities/sanitized score receipts in GitHub Actions; it never publishes raw dialogue, individual publisher target, original weights or raw query predictions. CI may take time or fail. Do not borrow a historical green run, disable `blocking-ci` or merge while unqualified.
