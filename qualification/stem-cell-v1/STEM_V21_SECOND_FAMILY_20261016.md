# V21 — Independent second task-family source audit (BANKING77 vs AG News)

**2026-10-16 · Research-only · SHADOW_ONLY · DENY_ALL.** Additive to original V20 PR #2541: no selected model, new Encoder, autonomous Cell split, production FinalUse, Worker, CAS/CNS, NDU or main merge. Scientific scope: **original source/label identity and scoring**, not prospective efficacy.

## Why a second public family matters, but does not establish transfer

V18–V20 have evaluated the same AG News-family source-locked 128×384 **mmBERT-small** cached feature packet repeatedly across folds/seeds. Those are not independent task families or future time windows.

A distinct previously executed Hepta experiment used **ModernBERT-base** to encode four BANKING77 intents, training Dense16 and Sparse Top-2 Cell banks. These two studies differ in model, tokenizer, data, task, Head and compute. V21 only validates the second study's original source identities and numerical results. **It does NOT test V20's 4-step mmBERT policy on BANKING77.**

## Original publisher and physical model identity

- PolyAI original `task-specific-datasets` commit `57ec275d8078af65b7731c2a98be812d844a6d6b` (CC BY 4.0). Unmodified source `banking_data/train.csv` SHA256 `b06e26ac675513959a63135f11b94ea7786ed02da65db93a5650d8838cbc664b`; `banking_data/test.csv` SHA256 `d12d6e3bc4c3103966ae786dc435913c0c563dfa328f5a3646d0e62cfeeb474d`.
- Hepta original GitHub Actions [run 38523539731](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38523539731), artifact **11877613315**, original ZIP SHA256 `fd89f174057d98bd2d4f03447d5d5dd9372723e70128ccdf2dcbe73f67a0a03a`. The original physical Encoder is ModernBERT-base, **not** V20's mmBERT-small.
- Four registered intents, 16 TRAIN and eight original test rows per intent (64 fit / 32 heldout). Reconstruct label-free source selection with the original CSV text, normalization (NFKC/casefold/whitespace), duplicate and train/test overlap rejection, prespecified SHA256 ordering and exactly 32 original heldout IDs. Publisher labels are derived from the source CSV, never copied from the model prediction report. The original source and recorded sample IDs have been independently cross-matched.
- The original repository source author claims neither independent issuer signature nor perfect pretrained-tensor provenance; a source hash is not a publisher signature.

## Original source-bound logits audit (historical, not future)

A separate read-only Python numerical path reopened the authentic original ZIP and recomputed heldout multiclass softmax, per-class correctness and Brier from physical original logits. The results below matched the source's original published aggregates:

| Original BANKING77 profile | Correct before | Correct after | Historical Brier after | Paired rescues / harms |
|---|---:|---:|---:|---|
| Dense16 | 8/32 | **23/32** | **0.3820432499** | **16 / 1** |
| Sparse16 Top-2 | 9/32 | 17/32 | 0.5770228329 | 16 / 8 |

Dense16 minus Sparse Top-2 *after* training has 10 rescues, 4 harms, 18 ties on the same 32 original heldout cases. These 32 outcomes are **not 32 independent source families**, and comparison of Dense16 against Sparse Top-2 is not matched full-lifecycle compute. There is no new task success, target-host throughput, numerical encoder parity or new future observation.

## Code, tests, and strict scientific boundary

- `v21_banking77_cross_family_audit.py` recomputes original source cohort **from both publisher CSVs** before opening the original archived model logits, refuses changed full CSV/material ZIP hashes, wrong input identity, skipped/duplicated cases, changed original source labels, false original score, invalid/nonfinite probability and missing research-only authority flags. No raw publisher source, original logits, trained weights, per-case labels or source text are written to the Git tree.
- `test_v21_banking77_source.py` checks 14 mechanism/malformed-sample cases under normal and `python -O`; original material-backed `test_v21_banking77_original.py` refuses running without original pinned publisher CSV and experiment ZIP, and tests original audit and seven adversarial/boundary cases.
- `hepta-stem-v21-original-cross-family.yml` is a source-locked, read-only PR-head workflow that fetches the original published GitHub Action Artifact without forwarding the GH token to a signed cross-host redirect, and independently fetches original PolyAI public train/test CSV without credentials. It verifies full SHA256 bytes and re-executes the source-label/score audit twice. It uploads **no** original source/logits/label data.
- The local isolated CPU numerical recount and separate public-GitHub-source selection reconstruction are concrete descriptive evidence, but **the exact V21 PR-head hosted workflow must itself finish successfully**. Opening a PR and 14/14 mechanism tests are not hosted original-material acceptance.

## Next actual science

For genuine transfer, use **the same pinned Encoder, tokenizer, preprocessing, Head and original source-group-independent training budget** on new independently authored task families. Freeze a no-change plus fixed4/fixed8/fixed80 and TRAIN-only-OOF comparison before exposing independent publisher labels, seal the predictions before the separate label-owner reviews and measure full task utility, old-task negative transfer and real total cost. Only independently registered future calendar windows and signed final-use evidence can justify any promotion; independent source-family labels alone cannot.

**Scientific decision: SECOND_FAMILY_DESCRIPTIVE_NOT_CROSS_MODEL_TRANSFER.** Automatic Cell split, NDU-selected model promotion, production serving, target-host 64/256/1024/4096 Cell RSS/p99/WAL/crash recovery all remain **DENY_ALL / NOT QUALIFIED**.
