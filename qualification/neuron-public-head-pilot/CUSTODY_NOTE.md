# Custody-only correction after the public Head pilot

## Finding, not a new efficacy result

This correction follows a read-only comparison with [#3592](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3592), exact head a33764693a98231ee0879064b5f8424ef098fbcd. It neither copies that historical multimodal experiment nor accesses its blocked WIT/CLIP sources.

The same pre-freeze label/split/archive-reseal bypass was **not** reproduced in #3588. The original extraction and analysis hardcode the entire plan SHA; that plan binds row labels, source row identities, split membership, selected text hashes and source archive/CSV identity. Independent checks rejected 12 row mutations, including resealed variants, four source-plan mutations, and selected-text drift at extraction. Preparation could previously emit a plan from an altered adjacent CSV, but unchanged downstream execution rejected that different plan. Preparation now fails earlier on either original CSV member hash before creating any frozen output.

A different analyst-stage weakness was reproduced: change one real held-out feature vector to its negative, preserving float32 shape and unit norm, then update both the feature-file hash and tensor hash in the editable local extraction receipt. The exact original analysis preflight AST accepted those mutually consistent local files because it did not compare against the separately published original tensor identity. This was a **preflight-only proof**, not a full altered-data Head run: the current environment has no Torch runtime. No new result receipt was produced, no encoder loaded and no Head retrained. Original feature arrays, source, freeze receipts and results were left unchanged.

## Fix

- Pin the independently reviewed original extraction record SHA256 1bd5364c1851c238f4c2cb22c12bba5baa08019f763c86b14ff9874f5456e248 in the source.
- Check frozen plan, row manifest, original model snapshot/SDK identity, split metadata and recognized extraction driver identity.
- Load NumPy archives with pickle disabled, require exactly the four named splits, expected float32 dtype and shapes, finite/unit vectors, and compare the **actual C-order tensor bytes** of every split to the pinned original hashes.
- Reject a joint feature-plus-receipt substitution before importing Torch, training, or emitting Head/results files. Also reject a receipt that lies about tensor hashes while presenting different arrays.
- Pin the train/test CSV member hashes, independently verified against the original author archive, before preparation emits any derived files.
- Keep all head fitting, temperature, LAC/APS and scoring mathematics unchanged. Future analysis receipts add the custody helper's source hash. The original observation receipts still identify their original generating code, not this corrected source.

This intentionally defines **exact historical-feature replay**. A newly generated vector matrix with different bytes needs a separately reviewed feature freeze/profile, even if the numerical change is tiny. It must not be accepted by merely rewriting its local receipt. Different NPZ packing of the same exact tensors is allowed with a matching container-file receipt. The guard is not a cryptographic signature or proof of an independently witnessed run; someone able to change the trusted source can change its constants. It is not a sandbox, quota control, blind label custodian or future-data qualification.

## Verification and unchanged conclusions

24 focused tests pass in ordinary Python and with the test runner under `python -O`; analysis itself intentionally rejects optimized execution. Tests cover joint substitution, dishonest metadata, plan/label drift, altered trusted anchor, dtype/extra arrays, repacking identity and pre-training/no-receipt failures. The existing source-only CI discovers these tests with NumPy only; it downloads no model/news data.

Separately, original-material checks accepted all four retained arrays (960×640 overall), rejected the actual changed-vector/changed-receipt pair, reconstructed the exact original plan and row bytes from the original source archive/CSVs, and rejected an altered CSV before any freeze output. These custody checks used the currently available NumPy 2.3.5; original model/Head evidence retains its original pinned NumPy 2.2.6/Torch runtime and is not relabeled as rerun.

The original results SHA256 remains 3826aa6cc18d6c62687074e673f383d43764c9e7bbd6ec91d42afe0a60643226. Logistic adaptation still has no demonstrated benefit over centroid; temperature improves sampled NLL; primary LAC utility still fails. No model, threshold, seed, labels, splits, or reported score was changed to improve an outcome. Scientific and CI gates remain unqualified until their own evidence exists.
