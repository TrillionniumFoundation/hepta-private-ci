# V5 repository CI repair and retained failure evidence

The isolated repair verification passed all four jobs at commit
`ccdb7ea7cb9c4adecf6f6607ea1570cb81ae0f78`:
[run 40473598389](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40473598389).
This closes three specific CI findings. The dependency advisory gate remains
failed, and the V5 scientific qualification remains failed.

## What changed and what was verified

| Finding | Change | Actual verification |
| --- | --- | --- |
| Encoded evidence was scanned as prose, and valid technical words were flagged | The existing Codespell workflow excludes six exact encoded files and accepts three valid technical terms | The actual reusable Codespell job passes in both verification runs |
| A nested workflow path was truncated to a root path; a missing nested file could also borrow a root file's identity | The verifier checks the complete nested repository path and keeps the existing root, URL and relative-link checks | Seven new filesystem behavior tests and two existing tests passed before formatting; the complete development documentation check passes |
| The pinned Ubuntu snapshot returned HTTP 502/503 before compilation | Add an official Launchpad fallback for identical bytes, retaining the original URL, version and SHA-256 | Fresh-cache Bazel 9.0.0 strict module resolution and the real toolchain library build both pass; the module lock remains byte-identical |

The first verification run retained its actual failure: archive member names in
the new diagnostic inventory were interpreted as live repository references.
The member inventory now lives inside the archive that it describes. The
original failed receipt and all diagnostic bytes remain available.

`first-run/source.zip` retains the original nine-test and formatting receipt.
`second-run/source.zip` retains the complete successful documentation check,
formatting commands, Ruff checks and six formatted source files. The formatted
files were applied only after exact before/after SHA-256 and AST comparisons.
The second verification did not repeat unit tests.

## Dependency download evidence

The original package and the successful official download are both 62,850 bytes
with SHA-256
`7074b6a2f6367a10d280c00a1cb02e74277709180bab4f2491a2f355ab2d6c20`.
`second-run/bazel.zip` contains every command status and output from the actual
Bazel check. The build log records HTTP 503 from the snapshot source and then a
successful toolchain build. The downloaded cache payload matches the existing
pin. The extracted library is 113,000 bytes with SHA-256
`9b64150b28505a33d6bc3ecf709c279f6de97a1c184dbda65d06ee4537f6d286`.

Strict module resolution took 19.15 seconds and the toolchain build took 33.49
seconds. The 1,658,169-byte module lock had the same SHA-256 before and after:
`94f6143d2e1f68d59fa9cbfd223a676a8dddf61fe8ec92b5219ecd0ac67f29d0`.
The successful final download host is not printed by Bazel; using the fallback
is an inference from the configured two-source list, fresh cache, primary
source failure and matching downloaded bytes.

## Remaining dependency advisory failure

The original cargo-deny job reports 22 distinct advisory IDs affecting 16 crate
versions: 16 vulnerability errors and six unmaintained-package errors. Bans,
licenses and sources pass. The workspace manifest, Cargo lock, advisory policy
and cargo-deny workflow have identical Git blob IDs in the PR base, research
head and tested merge. These are baseline dependencies, and the failed gate
still applies to this PR.

[The diagnosis](cargo-deny-evidence/DIAGNOSIS.md) lists all 22 records, the first
displayed dependency paths, the run identities and the limits of the CI's
reported upgrade ranges. A reported safe version is not proof that the full
workspace can resolve it or that its API migration has passed tests.

The read-only collector succeeded in
[run 40473598340](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40473598340).
The entire original 19,295,233-byte log is retained, including the terminal
failed advisory result. The collector's original ZIP is stored as five
individually valid gzip-wrapped byte chunks, each below the existing blob-size
limit. Their local reconstruction was byte-exact. Recover the original ZIP
from the repository root with:

```sh
python3 - <<'PY'
import gzip
import hashlib
import json
from pathlib import Path

root = Path("qualification/memory-cell-v5-ci/cargo-deny-evidence")
manifest = json.loads((root / "MANIFEST.json").read_text())
parts = []
for part in manifest["parts"]:
    encoded = (root / part["name"]).read_bytes()
    assert hashlib.sha256(encoded).hexdigest() == part["encoded_sha256"]
    decoded = gzip.decompress(encoded)
    assert hashlib.sha256(decoded).hexdigest() == part["decoded_sha256"]
    parts.append(decoded)
raw = b"".join(parts)
assert len(raw) == manifest["artifact"]["bytes"]
assert hashlib.sha256(raw).hexdigest() == manifest["artifact"]["sha256"]
Path("/tmp/hepta-memory-v5-cargo-deny-original.zip").write_bytes(raw)
PY
```

## Frozen research and prior native verification

The complete 217-file V5 inventory is unchanged. Its Git subtree is
`e46a25ab3c26763acb7b4fb8231943a15594c625` both before and after the CI repair.
`FROZEN_TREE_PROOF.json` records both root and qualification tree identities;
the successful recheck independently compares every V5 file's size and SHA-256.
The source, held corpus, selected models, raw results and qualification flags
were preserved.

The prior research head `332d8156d081e22405450dd607023689f68f03e1` also completed
[architecture run 40470653075](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40470653075)
successfully, including the source-head native service lifecycle and actual
process restart checks. The base-merge job skipped its native steps; it is not a
second independent native execution.

The scientific result remains the one in
[the V5 qualification](../memory-cell-v5/QUALIFICATION.json): oracle parameter
readout passes 20 of 20 cases, while actual semantic and combined graph-ablation
gates each pass zero of 20. The six-stage memory-system objective and production
admission remain open. `STATUS.json` separates these research obligations, the
three repaired CI findings and the remaining dependency advisory failure.
