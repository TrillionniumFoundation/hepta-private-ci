# Windows credential diagnostic evidence checkpoint

This packet preserves 140 selected files and 1,641,076 original bytes. Its 1 binary gzip parts are each at most 450,000 bytes.

Run `python -B restore.py /absolute/path/to/a-new-directory` with Python 3.12 or later. The destination must not exist. The fixed-index reader verifies every bounded gzip segment, both archive hashes, exact member names and every file hash before writing inert 0644 files. No recovered source executes.

Fixed INDEX SHA-256: `9e46a9a8ad3fcc63a19a3ecc301f1eb2e857c0200e616f6ab5c209845795859b`. The approved reader logic is unchanged: pinned Ruff formatted its layout with exact AST equality, then only its index seal changed. ROUNDTRIP.json records actual complete restoration and negative checks.

After restoration, read `round3_native/credential_checkpoint_inputs/HISTORY.md`. The original Windows attempt failed at Python setup, before preflight or account APIs. The corrected workflow was observed reaching its native composite step; its result and explicit account cleanup are still pending in this snapshot. No Windows probe pass or historical unique root cause is claimed.

The first job's full raw log remains local because the unchanged original scanner rejected its publication attempt. Only its identity, fixed stage classification and refusal receipt are preserved here. This packet is lossless for its explicit inventory; it does not contain or reconstruct excluded bytes. No rejected log was encoded or rewritten to bypass the gate.
