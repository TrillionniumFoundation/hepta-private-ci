# memory.retrieval accepted baselines

This directory stores reviewed, immutable qualification receipts and threshold profiles. Files are additive. Never replace an accepted receipt in place.

`github-hosted-v1.json` is a conservative gating profile derived from the earlier Ubuntu GitHub-hosted qualification sample. It is not a named production-host acceptance receipt. A production baseline must add source commit/tree, hardware identity, operating-system/toolchain identity, raw-log digest, complete end-to-end metrics and independent reviewer identity.

The workflow parses raw logs with `scripts/verify_memory_retrieval_slo.py`, emits a combined receipt and fails when a hard threshold is exceeded or a required phase is missing.
