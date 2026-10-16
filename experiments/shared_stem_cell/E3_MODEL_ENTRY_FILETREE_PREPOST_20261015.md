# E3: exact model-entry file-tree audit before and after actual pretrained inference

**Research only / SHADOW / DENY_ALL.** This is an isolated additive child of the more advanced label-redaction owner [PR #2304](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2304) at frozen parent `02aab3fc2859dec9410695a94da203fc57358a51`. No model weights, original dataset/model pins, original five-arm source/score, TEST labels, native Neuron/NDU, CAS/WAL/FinalUse, or protected main changed.

## Why not cross-job raw-media handoff?

The original E3 experimental contract prohibits uploading raw model/media inputs in GitHub Actions artifacts. Physically separating data preparation into a different Actions job by uploading the 192 source JPEG/PNG bytes would break that retention boundary. **This increment therefore does not upload the source images, nor claim operating-system/container isolation between producer and original Parquet acquisition.**

Instead, the existing per-model hosted process follows an explicit three-phase *same-runner* protocol: (1) an isolated source preparation Python process selects the immutable public cohort and produces a local model-facing tree without TEST labels/digest; (2) it removes the actual pinned HF/Parquet/Arrow staging cache, then a **separate, stdlib-only Python interpreter** independently checks the entire prepared file-tree before the model loader; (3) actual OCR/Granite or Gemma2 CPU model runs; an independent stdlib interpreter checks the **same** file tree after inference and requires byte-for-byte identical pre/post summary JSON. No success callback, root-trust assumption, source mutation, or missing cache fallback is permitted.

### Original model-facing files accepted by the independent gate

Only these files are allowed under `$RUNNER_TEMP/e3-original-sources`:

- `source-seals.json`: fixed publisher/revision, source/train-cal SHA, null `private_test_labels_sha256`, false model/production/independent-label flags.
- `inputs/cohort-before-labels.json`: the source-first full cohort identity and absence of future/promoted claims.
- `inputs/sources.jsonl`: **96 TRAIN + 32 CAL + 64 TEST source-only cases**, unique source/image groups, exactly the eight declared public fields (never `answer`, `label`, `solution`).
- `inputs/fit_labels.jsonl`: precisely **128 TRAIN/CAL-only** original labels, each source/split/group-ID matched.
- `images/<sha256>`: exactly **192** JPEG/PNG original source blobs, each filename equal to its observed bytes' SHA-256; raw media remain on the ephemeral runner and are **never uploaded**.

Reject symlink/hardlink, unknown directory/file, raw Parquet/Arrow, missing image, extra TEST label file, label-field smuggling even when a manifest is rehashed, duplicate source, altered bytes, incomplete split, noncanonical/duplicate/nonfinite JSON, oversized input and changed pre/post tree. The source and TRAIN/CAL SHA are **also pinned externally** to original E3 constants `a561916c7d56b6677c5511c329a49bbeec94879f019d29f159ff59be83359202` and `e8506bc65f96501b6b2fa4e4ae04c094c2b6b17b353de528a051136569e2849e`; self-rehashing input cannot replace those real external pins. All tests remain source-model material and not task efficacy.

## Concrete execution and independent scoring

The existing `.github/workflows/hepta-e3-five-arm-original-physical.yml`:

1. Executes `test_e3_model_entry_ledger.py` in normal and `python -O` alongside inherited E3 withheld-target tests.
2. After **cache deletion and before** each original OCR/Granite or Gemma2 model entry, executes `e3_model_entry_ledger.py` and writes a sanitized, bounded `e3-{ocr,native}-pre-view.json`.
3. Replays the original identical file view after model output and requires `cmp` equal to a separately generated `e3-{ocr,native}-post-view.json`. Raw labels/media/model bytes are not uploaded.
4. Binds `tree_fingerprint` to SHA-256 of canonical sorted
   `[relative_path, SHA-256(file bytes)]` pairs for the 196 admitted files
   (four metadata and 192 source images), not just path names. The
   postseal independent reviewer requires profile
   `hepta.e3-path-byte-sha256.v2`, the 196-file count and pre/post
   plus cross-producer exact parity. Metadata whitespace rewrites now
   change the fingerprint; original source/fit pins stay unchanged.
5. Adds **only the four sanitized source-view receipts** to the previously existing *numerical prediction* output artifacts. The independent five-arm scoring job reopens both pairs **before** sealing combined prediction metadata, checks local before/after parity, same original source/fit hashes, same image/file-tree fingerprint and no TEST label or authority flags. It downloads original withheld TEST labels on its own independent job **only after** the seal.

The existing separate small source-contract workflow also runs the twelve new tests in both modes. All pre-existing OCR/Granite/Gemma2 model loaders, 769 Head train-only updates, original E3 five-arm scorer, checksums and postseal original-human outcome gates remain unmodified. No new model efficacy can be inferred from a passing input tree.

## Actually executed local source evidence

- **12/12** original new tests normal Python 3.13 and **12/12** optimized `python -O`, no failures/skips, using *physically constructed 192 unique small PNG files* and 128 synthetic TRAIN/CAL labels. These prove the tree-audit mechanism but **not** original model loading or Source/Host authentication.
- The newly pushed exact Python files are byte-identical to tested local source at Git blob IDs `9cdcd9e88b43bb3ade250b0bb2a79df53f168e68` (auditor) and `d9075194f5c694c048b6233d2e480a72c9c7343c` (tests).
- Source and workflow must be independently executed on the **latest GitHub Actions SHA**, including physically loading original OCR, Granite97, Gemma2 and independent five-arm label owner, before any claim that this extra barrier actually protected an original pretrained run.

### Explicit remaining limitations

A byte-bound filetree SHA is not a signed publisher receipt, operating-system
isolation, a secure-deletion certificate, or evidence of neural task benefit.

The same GitHub-hosted runner's earlier acquisition process did download original TEST-bearing Parquet to a temporary cache. That cache is removed before model entry, and this independent gate checks the *model input tree*, but this is not a mount-namespace sandbox or proof that all kernel caches, arbitrary network calls, third-party dependency side effects and human source publishers were isolated. It cannot authenticate original dataset rights, human visual necessity, true independent source families, future generalization, total energy/p99, a 421M baseline, a production FinalUse token, NDU System 2 gain or any 10T/100T equivalence. Model input integrity and scientific held-label validity remain distinct.

**DRAFT / DENY_ALL / NO_MAIN_MERGE / NO_MODEL_PROMOTION / NO_PRODUCTION_EFFECT.**
