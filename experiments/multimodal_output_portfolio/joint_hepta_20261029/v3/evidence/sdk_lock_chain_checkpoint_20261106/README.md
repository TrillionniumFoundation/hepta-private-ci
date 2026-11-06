# SDK native lock proposal evidence

This packet preserves 136 selected files and 3,446,869 original bytes. Its 5 binary gzip parts are each at most 450,000 bytes.

Run `python -B restore.py /absolute/path/to/a-new-directory` with Python 3.12 or later. The destination must not exist. The fixed reader verifies bounded gzip segments, archive hashes, the exact member set and every byte hash before writing inert 0644 files. No recovered source executes.

Fixed INDEX SHA-256: `395f747ee9a023f059bf3f5f63e489348b6bfe2d1630d904708a9f8b4f84443a`. Only the approved reader's index seal changed. ROUNDTRIP.json records actual exact restoration and nine negative checks.

After restoration, read `round3_native/sdk_chain_checkpoint_inputs/HISTORY.md` and `RUN_STATUS.json` in the same directory for the exact native result and its limits. The recorded run conclusion is `success`. Restoring evidence does not qualify native generation, SDK Windows behavior or product CI.

The packet retains the source chain, original local failures and their repairs, independent internal reviews, and verified native evidence only as explicitly listed. Private full metadata, signed transfer URLs, and unaccepted raw job console are excluded. All previous frozen SDK and credential packets remain unchanged.
