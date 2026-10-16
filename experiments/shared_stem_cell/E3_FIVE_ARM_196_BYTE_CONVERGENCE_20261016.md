# E3 Original ScienceQA: 196-byte-bound model-input ledger convergence (2026-10-16)

**RESEARCH ONLY · DRAFT · DENY_ALL.** Exact parent #2461 head:
`751ab11dcb7ff3c20d895c698633e7b2d5ada2b8`. Original upstream #2227
model source `1fc1c87b8490cae2eb48b7fd464827f57278750e`.
This child changes **only research Python source/test/workflows/docs**; no selected
production Stem, Worker, Agentd, CAS, NDU, FinalUse, CNS, Q24, WAL,
generation fence, split executor, or protected `main` changes.

## Failure of a path-only inventory

Earlier research used a directory inventory hash of filenames. A
byte-different source/fit receipt or corpus metadata could change while
the same path-only identity falsely appeared unchanged. Even SHA-bounded
source and fit inputs do not automatically bind every original image byte
and the two other original metadata files into the *same* complete
source-tree identity.

The source-only TEST-target redaction from #2461 is necessary but not
sufficient. A mutation **during** an audit must not be missed merely
because the audit already completed its initial directory walk.

## Integrated exact original audited implementation (not recreated)

Exact source files ported from #2348 at fixed SHA
`d1afb5885d7faa2002b8e080b9d0d27d6bec501b`:

- `e3_model_entry_ledger.py` Git Blob
  `aa66c2096ca454c34ac2879f025f3bce1965aeab`.
  Its source-tree identity is SHA256 over sorted
  `[relative_path, SHA256(original file bytes)]` for **all 196 admitted
  paths** (192 original JPEG/PNG blobs + four source/fit/cohort/receipt
  files), not the path inventory alone.
- `e3_model_entry_resnapshot.py` blob
  `756a9542cbed62bf4b44f2b7cc9bd6a92e44ab8c`.
  Rewalks and rereads all source bytes after semantic validation; rejects
  late source mutation, new hidden label files, symlinks, source aliases,
  hardlinks, oversized unregistered material.
- `test_e3_model_entry_ledger.py` blob
  `fd2472f49946f3b488ecb18c1ac9ab5c8fd04fc5`.
  16 mechanism-only synthetic source tests, including late changed
  receipt contents and inserted TEST-label material.
- `test_e3_model_entry_resnapshot.py` blob
  `b9180e839c604cf219ea0704c484aee4f9e0a210`.
  6 second-directory-pass synthetic tests, no original media or weights.
- Two inherited source-design documents maintain original scope and
  change ledger.

No source is modeled as independently publisher- or human-attested merely
because its SHA matches; no original TEST labels are read by these
pure-stdlib tests. All normal and `python3 -O` hosted assertions must
still pass at **this branch's own exact source SHA**.

## Mandatory physical execution ordering

For **each** original physical producer, independently:

1. Stage exact original 96 TRAIN + 32 CAL + 64 TEST ScienceQA source,
   but **never** invoke TEST-label callback nor emit its answer or SHA.
   The producer gets only 128 TRAIN/CAL fit labels.
2. Complete the isolated original publisher Parquet/Arrow cache cleanup.
3. Run the 196-file source, image-content, source/fit SHA, scope,
   original prelabel, source receipt and TEST-target absence ledger.
   Require create-only `e3-{ocr|native}-pre-view.json` with
   `tree_fingerprint_profile=hepta.e3-path-byte-sha256.v2`.
4. Execute the **actual pretrained** OCR+Granite and Gemma2 owners,
   preserving pinned revisions, actual weight/tensor verification,
   8,192-token native context preflight and 769-param same-head
   paired train-only constraints.
5. Independently rerun the complete 196-file source input audit;
   `cmp` pre/post report bytes and preserve both nonauthorizing,
   small **numeric metadata** reports in each producer's existing
   artifact. Raw media, raw Parquet and held labels are never uploaded.
6. The separate original five-arm independent evaluator downloads
   both physical numeric sources and first verifies its two full
   pre/post byte-identical receipts. It also requires the two producers'
   entire input byte-tree identities match, including image byte count
   and receipt SHA, **before any original held TEST target reopening**.
   Missing reports or changed source always refuse five-arm scoring.
7. Only then sealed five-arm results and TEST-independent label
   acquisition can proceed. This is original public retrospective TEST,
   not true future1/2/3.

Additional new source-only `test_e3_byte_ci_convergence_20261016.py`
contains eight fail-closed workflow order, source target-visibility,
artifact upload and independent evaluator prerequisites, run in both
normal Python and optimized mode.

## Scientific/operational limits and owner decisions

The new source identity is a **local original input-byte consistency
check**, not a cryptographic proof of remote publisher signing, a
sandbox against malicious concurrent user-level file rewriting, a
true independent test-label authority or a guaranteed race-free
filesystem. The two directory snapshots reduce but cannot eliminate
arbitrary adversarial TOCTOU; a future production owner must enforce
immutable CAS-backed handles, fs-verity/namespace protection and
signed FinalUse/Generation Fence as appropriate.

Physical OCR from the older #2227 lineage is a genuine successful
**but historically target-visible** research run. It cannot establish
the new TEST-redacted predictor's independent label discipline.
Older #2349 PR contract green had native/OCR job **skipped** on the
pull_request event, so does not validate real physical pretrained
forward. The child must obtain its own physical exact-SHA **push**
run, TEST-label owner, source-tree pre/post receipts, five-arm true
predictions, CPU/RSS and held scoring before model efficacy decisions.

Even a physically successful historical five-arm result never
authorizes selected Stem, Cell Split, NDU, FinalUse or production
deployment. No `blocking-ci` waiver or automatic `main` merge.
