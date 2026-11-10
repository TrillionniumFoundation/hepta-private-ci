# MEM5 raw-evidence archival instrument and retained timeout

The real 108-episode run completed; its research result is published in
[PR #5676](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5676).
This package preserves the archival instrument, software checks and the original
raw-archive launch request. It does not establish complete real-run archival.

Both the v1 archive start and one exact same-key reconciliation returned MCP
timeouts. Job identity remains UNRESOLVED; no INDEX or asset inventory is bound.
The INDEX read reported a missing parent directory at that observation, which
does not prove the unknown original process failed. Registry reads also timed
out. Every observation and the exact original request remain preserved.

Stable key: `mem5-raw-archive-5fa0d0e-20261110-v1`. Stop additional start calls;
after connection recovery, resume only read-only identity/status/log/INDEX
retrieval for this key. Do not create another key, overwrite an output or rerun
actors. The retained request targets the original run and a fresh
`raw-archive-5fa0d0e-v1` directory.

Plaintext `archive-run-strict-v2.py` is the separately frozen strict verifier.
The preserved v1 creates bounded USTAR archives; v2 additionally rejects hidden
extensions, nonzero padding and nonzero trailers. Once the original archive is
recovered, run v2 verification against that archive without repeating the study:

```sh
python archive-run-strict-v2.py --verify --output /path/to/recovered/archive
```

Both versions preserve all regular logical files, including empty files,
duplicates and hardlinks, using ordered content-addressed chunks. The small
INDEX binds a complete file/object/chunk/asset manifest in bounded tar.xz parts.
Assets are measured below 450,000 bytes; chunks are at most 300,000 bytes.
Inode/metadata checks establish observed quiescence, not an atomic filesystem
snapshot or authenticated ownership.

Extract `validation-records.tar.xz` beside the plaintext tool to inspect and
repeat the software-only checks. Normal and optimized Python each passed 16
roundtrip checks plus three strict-tar checks. These crafted-file tests are not
successful archival or independent replay of the 4,000 actual run files.
v2 passes repository-default Ruff 0.15.13 formatting/lint; formatting preserved
its AST. v1 retains its exact executed source and custom-format receipt.
`INDEX.json` records every packaged member and asset byte/SHA/Git-blob binding.
No frozen experiment source, model, role, actor trace or original failure was
rewritten. Scientific qualification and production adoption remain HOLD/NoUpdate.

Final frozen-source CI subsequently completed successfully on source `5fa0d0e`
and tree `7b3431e`: 17+10+6+5+15+7+7 = 67 passed, zero failed or skipped.
Every command receipt records clean exact source before and after execution.
`CI_SUMMARY.json` and `exact-source-ci-records.tar.xz` retain the terminal job,
original receipts, historical queued observations and repository-job snapshots.
This closes the dedicated MEM source gate. Repository build/format also passed;
cargo-deny failed and its original logs could not be read, so its cause remains
UNKNOWN. Other required jobs/Architecture were still in progress at the retained
observation. This evidence does not qualify the new archival utility commit,
the whole repository, full raw archival, neural uniqueness or production use.
