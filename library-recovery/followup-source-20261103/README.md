# Source-only followup custody - 2026-11-03

The 168 original source objects are preserved as data in source-custody.tar.gz. Their original objects/ names, bytes and Git modes are unchanged inside the container. The original README, SOURCE_MANIFEST.json and prior verifier are included as original controls.

SOURCE_MANIFEST.json remains byte-identical beside the container. ARCHIVE_MANIFEST.json maps every original repository path to one member and records its source commit, mode, Git blob ID, size, SHA-256 and original provenance row. The container does not provide a Cargo workspace for these mixed historical packages.

Run the maintained hash-only reader from the repository root:

    python3 library-recovery/followup-source-20261103/verify_projection.py

The source-companion document reader also resolves its 30 affected peer references (25 unique original paths) through the same verified container. Missing, ambiguous, linked, unsafe or modified members fail validation. Validation reads bytes in memory without extracting or executing source.

Original DRAFT, SHADOW_ONLY, DENY_ALL and HOLD records remain original evidence. No scientific/runtime acceptance, deployment activation, historical program replay or new source ownership is claimed. The data container follows the existing host-source custody pattern; no formatter or check exclusion is introduced.
