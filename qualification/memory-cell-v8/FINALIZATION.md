# V8 tested-source finalization

Commit `ci_finalize.py` and its workflow before the V8 verification run. Do not
create `FINALIZE_REQUEST.json` until that run has completed successfully and its
unaltered `hepta.memory.v8.product-ci-receipt.v1` receipt is available in the
checkout. The request declares its relative path, byte count and SHA-256:

```json
{
  "schema": "hepta.memory.v8.finalize-request.v1",
  "tested_commit": "EXACT_40_CHARACTER_SUCCESSFULLY_TESTED_COMMIT",
  "format_base": "0b0b041b6dd8121050c335cb3be73bb1d8cb7904",
  "packages": [
    "codex-hepta-cognitive-types", "codex-hepta-neuron", "codex-hepta-memory",
    "codex-hepta-cognitive-store", "codex-hepta-learning-artifacts",
    "codex-hepta-agent-protocol", "codex-hepta-agentd",
    "codex-hepta-context-compiler", "codex-hepta-infer-worker-host",
    "codex-hepta-plasticity"
  ],
  "verification_receipt": {
    "path": "qualification/memory-cell-v8/results/SELECTED_RUN/receipt.json",
    "bytes": 12345,
    "sha256": "EXACT_SHA256_OF_THE_ORIGINAL_RECEIPT_BYTES"
  }
}
```

The finalizer verifies the original receipt's hash, successful ordinary and
ignored native test commands, clean checkout, exact source commit and tree. It
then requires the tested commit to descend from the fixed V6 format base and
the finalization commit to descend from that tested commit. Protected Rust,
recipes, formatting tools, CI setup, runtime fixtures and the complete tracked
V6/V7/V8 Python inventory must still match the tested source. This includes
preflight, addressing, learning and CI Python files, not only package modules.
Evidence and request commits can follow testing; changes to protected source
require a new successful verification before finalization.

Only the ten listed Hepta packages are passed to `just fix --locked`. Clippy
compiles test targets because the existing recipe uses `--tests`; it does not
execute their tests. Fixes outside those packages' Rust files are rejected.
`just fmt --base 0b0b041b6dd8121050c335cb3be73bb1d8cb7904` follows, retaining the
earlier V6 base so cross-module formatting from V7 and V8 is included. Every
frozen Python file must retain its bytes and mode through both stages.

This workflow performs no test execution, fitting, candidate selection,
calibration, held evaluation, commit or push. Successful engineering verification
permits finalization even when a separately recorded research quality gate is
false; formatting cannot change that research conclusion. Do not rerun tests
after this stage's final fix/format. Review and apply the retained patch against
its recorded source tree, then preserve the distinction between the tested
source tree and the resulting formatted tree.

`memory-v8-finalize-output/` retains each command's original merged stdout/stderr
bytes and actual exit code, before/after file identities, each stage's tracked
tree and incremental/cumulative binary patches, and the final tracked tree and
patch. A private Git index computes trees without changing the checkout index.
Failed commands retain their partial changes. `PATCH_INDEX.json` and `SHA256SUMS`
bind the exact artifact bytes; `PATCH.tar.xz` carries the final original patch
plus its source and file identities. Raw patches over 512,000 bytes exist only
inside compressed artifacts, with no standalone raw patch or console/base64
payload. Retrieve those compressed artifacts rather than posting a large patch
as a Git blob. The workflow uses the V8 Cargo target/cache configuration and
uploads evidence even when finalization fails.
