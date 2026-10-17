# V19 — original archive byte replay and publisher-bound reference files

**DRAFT / SHADOW_ONLY / HOLD_NO_GO / DENY_ALL. No selected model, NDU gain, Cell Split, main merge, or FinalUse.**

## Exact original archived material physically replayed (2026-10-16)

The original GitHub Actions artifact **11586991191** was downloaded through the existing installed GitHub connector as a **376,363,859-byte ZIP**. Its full SHA-256 **07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af** matched the historical expected manifest. The ZIP contains exactly one `memory-inputs.tar.gz`. The independent V19 reader streamed **56** TAR entries and **644,195,777** member-content bytes; selected SHA-256/length pairs for the original **135M Reader weights**, **Reader tokenizer/config**, and **original LoCoMo corpus** all matched the fixed earlier study. No raw corpus, original model tensors, per-case routes, generated answers, private labels or credentials are committed.

The included public `V19_ORIGINAL_ARCHIVE_BYTE_RECEIPT_20261016.json` has **digests and sizes only**. `v19_original_archive_preflight.py` reopens the real ZIP, verifies each original member is safe, bounded and non-duplicated, compares the selected pinned full file hashes, and emits this sanitized record. The source-only GitHub CI rechecks only the public aggregate, NOT the original heavy ZIP. **A public report self-consistency check is not an independent signed observation of an actual model forward.**

Local physical reproduction from a previously downloaded SHA-pinned original ZIP on an admitted machine:

```bash
export PYTHONPATH=qualification/stem-cell-v1
python qualification/stem-cell-v1/v19_original_archive_preflight.py \
  --original-zip PRIVATE/hepta-original-archive.zip --out PRIVATE/v19-physical-archive-review.json
python qualification/stem-cell-v1/v19_original_archive_preflight.py \
  --public-receipt qualification/stem-cell-v1/V19_ORIGINAL_ARCHIVE_BYTE_RECEIPT_20261016.json
```

## Previously unbound model material identity repaired

The V18 reference staging program previously verified a publisher SHA256 for the 1.5 GB LFS/Xet model weight file, but only **self-recorded local SHA256** for ordinary Git-tracked model files. Its improved frozen-roster validator now requires every registered file's official immutable revision, declared byte size and publisher Git blob OID; ordinary files must match `SHA1("blob " + decimal_length + NUL + bytes)`, whereas files with LFS metadata must match the publisher SHA256 over **actual payload bytes**, not the Git LFS pointer blob. The original separately pinned weight LFS SHA remains mandatory. Mixed, truncated, stale or modified files are denied before producing a selected private model manifest. Unknown directories/symlink entries inside the model snapshot are also rejected.

Source/mechanism tests exercise mutated non-LFS tokenizers, missing upstream size and OID, changed weight size, extra directories, symlinked directories and previously existing source boundaries. These tests involve synthetic fixtures and do not load a pretrained Qwen model.

## Physical model and scientific remaining blockers

- Actual original 128 Qwen reference calls have **NOT** been observed. The separate public-only Qwen one-question workflow is a smoke test, not a matched historical Reader result; any queued job must reach a terminal verified conclusion before a physical-forward claim.
- Original data comes from 10 historical LoCoMo families; the 32-case V16 comparator is an answer-dependent retrospective cohort from only four correlated roots, with **five missing publisher answer fields** in the selected panel. These cannot be treated as 32 independent families or five failures.
- Human-adjudicated evidence sufficiency, grounded task correctness, authenticated independent evaluator, official HF numerical parity, full matched lifecycle cost, source-disjoint future time windows, and V6 retention are not established.
- Never promote a Cell, enable automatic fission, attribute Qwen capacity to NDU/MemoryCell, bypass `blocking-ci`, or merge this Draft into production based on source-byte evidence alone.
