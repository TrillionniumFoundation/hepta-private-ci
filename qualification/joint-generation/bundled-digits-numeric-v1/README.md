# Digits synthetic numerical qualification v1

This package preserves one successful, independently reviewed synthetic numerical qualification of four fixed full-size float32 networks. It is code and evidence, not real-data training, a model-quality study, statistical evidence of benefit, or authority for any later phase.

## What ran

Two hand-constructed 64-pixel arrays and fixed synthetic labels only. A/B each have35,658 parameters, C36,408 and L4,810. Four model instances were initialized; each made one batch2 forward/backward/Adam update. Two extra two-element optimizer fixtures exercised steps1 and2. There was no dataset loader, TRAIN export/access, raw-digits access, heldout access, real-data fitting, hyperparameter search, or checkpoint selection.

The frozen work made16 float32 forwards/20 examples,4 backwards/8 examples,52 forward and24 backward dense matrix products. Dense MAC counts are587,152 forward and445,840 backward. A separately coded float64 forward-loss reference made292 forwards/19,209,992 dense MACs. These counts omit scalar operations but their runtime is included in child wait4.

All72 preregistered gradient probes passed their fixed two-epsilon stability and float32 analytic comparison tolerances. Raw finite-difference losses and before/after Adam witnesses are saved. Independent saved review recomputed144 slopes from288 stored raw losses and verified76 sampled Adam coordinates with exact struct-float32 recurrence matches. It did not regenerate the model loss/gradient values or prove every parameter gradient. Initialization identities, zero-path operations and singleton serialization were asserted by reviewed source during the single run; full model tensors/checkpoints are not stored for independent reconstruction.

At the one synthetic singleton after one update, replacing A probabilities with uniform or cyclic values changed pixels by maximum0.005659520626068115 and0.00863504409790039. B outputs were byte-identical, with both changes0.0. This establishes only a local implemented numerical dependence. It does not establish useful class semantics, denoising improvement, accuracy, generalization, semantic multimodality or superiority over static functions. All four architectures are static functions.

## Evidence and bindings

- runtime/FREEZE.json is the exact executed source freeze, SHA256 9f4953db9e05651997b7597e3acc8e08e462e4f674ab0f87a5d535fed054d54c. Current kernel.py, reference.py, tests.py, worker.py and run_once.py are included byte-for-byte, together with current fixtures/runtime/documentary bindings. The exact original FREEZE.json is preserved, but its entries for PRIOR_V1/tests.py, PRIOR_V1/worker.py and PRIOR_V1/run_once.py are intentionally NOT published. It therefore cannot pass the original full-closure precheck using this package alone.
- runtime/SOURCE_PASS.json and runtime/INDEPENDENT_SOURCE_REVIEW.json preserve admission/source review. runtime/PRIOR_V1 preserves the earlier blocked freeze, review and documentary identities. Older defective Python implementations are intentionally omitted to prevent their reuse. Their hashes identify preserved local history; they do not make this a complete old or current executable archive.
- runtime/RUN_ONCE/RESULT.json SHA256 cf0fbe0a483c7772d0324cd4a53defc1af09782c0790ef3a32624453d89c14e5 contains synthetic numerical witnesses, not real images or labels.
- runtime/RUN_ONCE/WAIT4_RECEIPT.json SHA256 92bad886c56a2f94298477a3ca53a2bd50ae0a61e390e241a24a5a467c40be1b binds the successful single child and result inventory.
- runtime/INDEPENDENT_SAVED_REVIEW.json SHA256 5ace02873c312ffc69e5cebabec02f5d03590bc703c33c66783844b4ff8a6d42 is the separate saved-evidence review. Read its limitations alongside runtime/SAVED_FINDINGS.md.
- design_v2/ includes the current DESIGN.md, BUDGET.json, ADMISSION.md, FREEZE.json and independent design review. References from that design freeze to earlier designs or public partition evidence are identity references only, not a complete bundled design/evidence history. No real-partition artifacts or private data are included.

## Resource interpretation and portability

Child exit0, wait4 CPU0.6693549999999999s and peak RSS27,168KiB. Supervisor observed CPU prefix0.183775425s; observed subtotal0.8531304249999999s excludes unknown nonzero final tail, tools, preparation and review. Observed wall prefix0.7778080819989555s is not a strict global runtime guarantee. Each process had its separately specified4CPU-second limit; child wall30s, supervisor kill/reap32s, AS256MiB, file2MiB and retained-output4MiB. No all-in strict CPU or filesystem quota claim follows. The normal successful run does not qualify abnormal-signal behavior, malicious native code, transient threads or parent-death handling.

This package is current corrected source and saved-evidence reference, not a complete executable archive, portable rerun command or standing execution authorization. The intentionally omitted older Python files mean the original run_once full-freeze precheck cannot succeed from the package alone. Runtime paths and1131 source/native hashes bind the original installed Python3.12/NumPy2.3.5 environment, libc/libm and bundled BLAS. The original absolute benchmark lock identity and nonexistent absolute BYTECODE_DISABLED prefix are required. -I/-S/-B with startup -X pycache_prefix was used to bypass unbound bytecode caches. Relocating this package does not recreate that environment or authorization. RUN_ONCE exists and consumes the sole attempt; never delete it to rerun. A new attempt or environment requires separately authorized reviewed scope, not an automatic replay.

This qualification does not admit TRAIN Q, confirmation T, selection S or final F, and does not expand the proposed2,860-second later worker-budget sum into an approved budget. HOLD_NEW_TRAIN, heldout restrictions, prior Fashion/all-FIT/strict256 holds and all other data restrictions remain unchanged.

## Publication inventory

PUBLICATION_MANIFEST.json binds all payload files except itself. External CHANGES.json additionally binds the manifest and gives local materialization paths for publication tooling. Neither document is a remote-write receipt. All planned repository actions are additions under qualification/joint-generation/bundled-digits-numeric-v1/. No data, native library binaries, generated checkpoints, credentials or remote writes are included. RUNTIME.json contains installation file identities only, not the libraries themselves.
