# Exact combined-dependency hosted evidence

This checkpoint preserves 23 complete original artifact ZIPs from combined
dependency commit `0b9da54535a7795b2433947a479e6d9e71525e0a`, plus one separate
V8 Windows artifact from `bede07d3050d897a505020215a46a3ec8d66020d`.
It does not advance either tested source branch.

The original ZIPs occupy 8,576,845 bytes and contain 226 files. Ordered gzip
parts encode at most 384,000 raw bytes each and preserve every original ZIP byte while
respecting the unchanged repository blob-size policy. `archives.json` binds
archives, parts and extracted members. `FILES.json` binds this checkpoint.

## Verified combined-source scopes

| Component | Actual original result |
| --- | --- |
| Lock | Committed lock checked first; original regeneration and postcheck pass; bytes unchanged |
| YAML | 820 native cases across five complete packages, zero skipped; 1 Bazel target; 1,517-package all-features graph |
| Matrix | 336 native cases, zero skipped; 3 Bazel regression targets |
| AWS DPoP | 39 native case executions across three platforms, zero skipped; original Bazel consumer checks |
| Operator | 24 macOS and 24 Linux cases with native sandbox execution, zero skipped; original RBE compilation and Clippy |
| Fleet | 42 macOS and 42 Linux original cases, zero skipped |
| Keyring | 15 secret-store cases, 12 original real-service operations, 17 encrypted sessions and zero plaintext sessions/fallbacks; original native DBus identity and provider build |

The combined-source independent verification checks 1,936 unique exact Git
input paths. Native case executions total 1,342; repeated platform execution
is counted separately. The 12 real-service operations are additional.
Each original artifact and each narrower report retains its actual input
scope. The provider's original driver records its after-state check, but
does not include a separate after-hash file.

The separate V8 Windows artifact proves the fresh-process parallel case and
all 115 original consumer cases, including both original sandbox assertions
and three Clippy binaries. It applies to the exact `bede` source and does not
establish V8 acceptance on the combined dependency graph.

## Independent replay

Use Python 3.11 or later and a Git checkout containing exact `0b9`, `1ef` and
`bede` objects. Run against a new empty output location:

```sh
python3 qualification/joint-hosted-0b9-20261103/restore_and_verify.py \
  --repo /path/to/hepta-private-ci --output /path/to/new-evidence-directory
```

The script reconstructs each original ZIP, validates all member bytes, then
runs seven read-only verifiers. They compare original logs, XML or nextest
per-case records, lockfiles, command arguments and immutable Git source.
Every regenerated report must equal the preserved report. Archived source
and test executables are never executed. Optimized Python is rejected because
two inherited independent verifiers use assertions.

Original negative attempts remain in their existing immutable qualification
commits; success does not erase those records. Complete original blocking CI,
later stacked production fixes, V8 source-build deadlines, private-state,
scientific, performance and original archive/history obligations remain
separate gates. Status remains Draft / HOLD_NO_GO / DENY_ALL.
