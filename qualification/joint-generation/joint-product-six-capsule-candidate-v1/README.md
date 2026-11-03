# Six separate, byte-exact product qualification capsules

This package preserves six previously scoped local Actor-selected Fashion versions. It does not combine their implementations or establish an aggregate model PASS. The new code only checks and materializes existing bytes. No capsule runner, model, training operation or scientific test is executed by materialize.py or the packaging qualification.

Each original runner version remains separate under files/<original-candidate>/. All 173 original frozen entries and all six original FREEZE.json files are byte exact. Reviews, findings, complete outer wait4 receipts and enumerated prior-failure provenance are also available under files/ at their original relative paths. COPIED_PROVENANCE.json identifies the exact selection. OMITTED_RAW_EVIDENCE.json explicitly identifies raw records that are hash referenced, not copied or newly audited. Do not mistake this package for a complete raw experiment archive.

## Materialize exactly one version

Use an existing trusted, nonsymlink parent directory and choose a destination that does not exist. For example, from the workspace containing this package:

    python -I -B joint-product-six-capsule-candidate-v1/materialize.py \
      --capsule joint-policy-reconnect-candidate-v1 \
      --output /absolute/existing-parent/new-reconnect-workspace

The six allowed names are the six keys of capsule-manifest.json. The materializer reads only this package. It verifies the entire exact manifest, source/provenance/input storage, all 79 contiguous raw ZIP records and the whole content.npz SHA256 before creating the output. Source bytes are retained after validation and all written bytes are checked before the completion receipt is renamed into place last. Only the selected target's frozen members, its original FREEZE.json and its 7 or 13 INPUTS paths are written. Its own RUN_ONCE is absent. The later five versions include selected delivery-v2/RUN_ONCE files as historical input data, not a runnable delivery-v2 job.

MATERIALIZATION_RECEIPT.json means byte reconstruction completed, not that a scientific run is authorized or passed. Existing or partial destinations are always refused. A storage/OS failure may leave an incomplete new directory without this receipt; it is not repaired or silently reused. The caller must select another destination only under the applicable authorization. Trusted local, non-concurrent filesystem parents are required. There is no hostile filesystem race, owner-authentication, signature, power-loss transaction or universal API guarantee.

## Caller-provided runtime environment

A materialized workspace is a fixed entrypoint runtime-data closure, not a self-contained execution environment. A separately authorized original run must be launched **from that materialized workspace root**, with compatible existing Python/NumPy and Linux flock, resource, fork, wait4, affinity and /proc facilities. For example, only after separate original-run authorization:

    cd /absolute/existing-parent/new-reconnect-workspace
    python -I -B joint-policy-reconnect-candidate-v1/run_once.py /absolute/existing/shared/benchmark.lock

The shared benchmark lock must already exist and be the caller's actual lock shared by all relevant concurrent work. This package never creates a lock or substitutes a private per-workspace lock. Do not copy a lock into the capsule and claim shared exclusion. Original runner budgets, identities and run-once behavior are unchanged. Installation, permission/security changes, production-owner authority and deployment are out of scope. The legacy RGB8 serve surface in multimodal_contract.py is excluded; only the six fixed Fashion run_once-to-supervisor/worker paths are supported.

## Structural NPZ storage

The original content.npz is 1,560,407 bytes with SHA256 64806d1b67b3b071e8b35246a77412e3da76ccf1cd283306f49290296a634150. It is stored as 78 exact local ZIP records plus one 4,960-byte terminal central-directory-plus-EOCD record (4,938 + 22). Each record is named only by its SHA256 in objects/. The largest is 401,600 bytes. No archive member is extracted or executed, no NPZ/NPY value is interpreted, and no recompression, dtype conversion or serialization change occurs. All package blobs are at most 511,999 bytes. Expanded local output content.npz is intentionally larger and is not a remote storage blob.

## Review and packaging qualification

FREEZE.json binds every prepared package artifact except itself and later independent review/run evidence. Source-review admission must bind that exact freeze before the single packaging qualification. The provided run_once.py takes the existing shared lock with rb + nonblocking exclusive flock and never creates it:

    python -I -B joint-product-six-capsule-candidate-v1/run_once.py /absolute/existing/shared/benchmark.lock

Do not execute this command until independently reviewed and admitted. The runner requires SOURCE_REVIEW.json with source_freeze_sha256 equal to FREEZE.json's SHA256 and qualification_admitted: true. It performs 7 positive byte-materializations and 46 negative fixture cases, never any original runner or model. Frozen limits are child CPU 3 seconds, child wall 15 seconds, address space 256 MiB and per-file FSIZE 8 MiB. CAPACITY.json gives exact package/object/workspace counts, expected retained bytes and explicit terminal output bounds. FSIZE is not an aggregate disk quota. The total bound is inventoried prospectively for the fixed successful schedule and checked again at the end; OS failures or unexpected output can fail that check and are not claimed bounded by FSIZE. No automatic rerun follows failure.

Preparation prefix costs, full child wait4 rusage, consumer hash/read/write counters and unknown outer tails stay separate. Earlier scientific costs and failed-run evidence are not refunded or relabelled. SOURCE_CLOSURE_AUDIT.json is a static census supported by the copied design/source reviews, not model execution. The current package was prepared without running its qualification.

Remote publication is separate. It requires independent source and saved-result review, the actual repository incremental size policy, and independent remote Git-size/identity and downloaded-record whole-NPZ reconstruction checks. No remote writes have been made here. Historical 67 oversized blobs against main, scientific data403, denied App Server reads, strict256 and production-authority restrictions remain unchanged.
