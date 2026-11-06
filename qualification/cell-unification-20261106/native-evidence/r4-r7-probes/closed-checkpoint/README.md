# Closed checkpoint verification

These files preserve the original checkpoint namespace and hashes. The same original logs are also available as individual gzip files in the parent directory.

To reproduce the recorded read-only source/log checks, unpack `checkpoint-through-r7-probe.tar.gz` in this directory, then run `python verify_checkpoint.py`. The supplemental `evidence/native-supervisor-red-production-tree-binding.json` remains alongside the extracted evidence. This validates existing records; it does not rerun Rust tests.

The original `production_before.sha256` fields in the RED source receipts describe the saved candidate before the temporary reversion; `original_sha256` and the supplemental exact Git tree proof identify the code actually used by both RED attempts. The original receipts have not been rewritten.
