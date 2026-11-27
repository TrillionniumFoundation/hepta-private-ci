# Maintained time dependency: local presentation compatibility

This change closes local calendar regressions in the reviewed Rust integration
at `a4d8e4ba3a203a2437351cb478d131d5ca618266`. The earlier dependency repair
removed Chrono in response to
[RUSTSEC-2026-0543](https://rustsec.org/advisories/RUSTSEC-2026-0543.html).
Its `time` implementation preserved UTC timestamp storage, but using Jiff for
local presentation narrowed the supported year range and changed some time-zone
configuration and leap-second behavior.

The repair keeps the maintained `time` implementation for persisted timestamps
and uses maintained `tz-rs = 0.7.3` for Unix time-zone data. It does not add an
advisory exception, change dependency policy, or import any HIA source or ref.

## Resulting behavior

The seven layouts used by the existing protocol, core, cloud-task and TUI
callers are explicit enum variants. They preserve signed expanded years, local
date extraction and raw leap-second residue across the original timestamp
range. UTC serde and parser code is unchanged.

Unix discovery preserves explicit `TZ`, file search order, invalid configuration
fallback through IANA discovery and UTC, and the original per-thread cache
policy. A missing file and an opened file that fails while reading have distinct
outcomes. Once file discovery finishes, POSIX parsing cannot perform a second
file lookup after trimming whitespace.

Compatibility adapters cover the narrow parser differences found by comparison
with Chrono 0.4.45: unused legacy TZif indicator values, neighboring-year DST
rules, final-transition footer consistency, absent extrapolation footers and
explicit offset-hour limits. Explicit standard/DST offsets remain limited to
23 hours at configuration time. Binary TZif offsets, implicit one-hour DST
increments and transition clocks retain their separate original boundaries.

Windows keeps the OS year-information query, clamps only that query to
1601 through 30827, and resolves recurring rules in the original timestamp year.
The patch includes an OS comparison test for native Windows CI. Android and
OpenHarmony retain their system TZif database lookup; WebAssembly retains the
JavaScript Date offset path.

## Verification

| Check | Observed result | Scope |
| --- | --- | --- |
| `codex-utils-time` package tests | 29 passed, 0 skipped | Final substantive source before final lint/format |
| `codex-protocol` package tests | 301 passed, 0 skipped | Updated caller; precedes final Unix parser review fixes |
| Broad Chrono comparison | 371,070 cases, 18 configurations, 7 layouts, 0 mismatches | Broad candidate before final parser review |
| TZif indicator/truncation matrix | 198,431 checks, 0 mismatches | Legacy parser acceptance boundary |
| Review regression comparison | 63 mismatches before, 0 after, across 98 cases | Final three configuration fixes |
| Windows GNU, wasm32 and Android ARM64 checks | All passed | Cross-compilation; no native OS execution claim |
| `cargo deny --all-features --locked check` | Advisories, bans, licenses and sources passed | Exact final dependency graph |
| Canonical Bazel update and lock check | Both passed | Fresh native dependency graph |
| Bazel time-package `cquery` | Passed; 4 targets, 46,312 configured targets | Analysis only; no Rust build actions |
| Final scoped `just fix` | Passed with no warnings or source edits | Time utility and protocol |
| Final `just fmt` | Passed | Formatting followed the completed tests |

No tests were rerun after the final lint/format sequence. The independent review
also checked the resulting formatting changes and retained the native Windows
and complete integration CI requirements.

## Dependency and evidence provenance

The canonical Bazel commands ran in a new native checkout and new caches. Its
dependency base was `db0757eca20bbeaf7840bf162ebfb6ccb4824e57`; the candidate
overlay was applied only after preimage verification. All 243 captured workspace
manifest/module inputs and three additional argument-linter package inputs were
checked against the integration. This establishes dependency graph provenance;
it is not a claim that the entire integration source ran natively.

The resulting `MODULE.bazel.lock` adds only the `tz-rs_0.7.3` metadata entry.
The exact final hashes are:

- `codex-rs/Cargo.lock`:
  `77b97b277e334533fafeedc0dd5294ee0adaf71b8890e56adf3cf68d54370cc8`
- `MODULE.bazel.lock`:
  `5336311a0fa5c53fd5b3f5ef966d661afed27453a69d84ff3dd55dbc431ff501`

`source-manifest.json` records all 27 changed source/lock paths before and after
formatting. `validation-summary.json` distinguishes each check's source scope.
`evidence-index.json` hashes every member of the original `evidence.tar.gz`,
which retains the complete logs, diagnostic sources, source snapshots, native
receipts and independent review. The archive is stored as five exact ordered
byte chunks of at most 400,000 bytes. Their concatenation has the original
1,916,937-byte length and SHA-256
`a5a8f1df733f402a1a415f14b0f0ea2a15fa5fde5208cde814ae2694609feb81`.
The index also pins every chunk and the original commit/blob identity.
`blob-size-before-chunking.log.gz` preserves the original 512,000-byte policy
failure; the policy and its allowlist are unchanged. Initial validation
failures remain present, including the missing
offline cache, temporary compile error, missing Clang header, sparse-checkout
Bazel error and the differential failures that motivated the final fixes.

To reconstruct the archive, run from this evidence directory and choose an
output path outside the repository:

```sh
python3 - /tmp/hepta-time-evidence.tar.gz <<'PY'
import hashlib
import json
import pathlib
import sys

index = json.loads(pathlib.Path("evidence-index.json").read_text())
parts = []
offset = 0
for chunk in index["chunks"]:
    data = pathlib.Path(chunk["path"]).read_bytes()
    assert chunk["offset"] == offset and len(data) == chunk["bytes"]
    assert hashlib.sha256(data).hexdigest() == chunk["sha256"]
    parts.append(data)
    offset += len(data)
archive = b"".join(parts)
assert len(archive) == index["archive_bytes"]
assert hashlib.sha256(archive).hexdigest() == index["archive_sha256"]
pathlib.Path(sys.argv[1]).write_bytes(archive)
PY
```

Native Windows execution of the OS comparison test and the complete final
integration CI remain required before merging to main or deleting source
branches. No remote ref was changed while preparing this patch.
