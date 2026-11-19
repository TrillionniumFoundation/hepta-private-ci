# Reviewed Rust integration checkpoint

This is an incremental source checkpoint. The requested full audit, main merge
and retirement of all other Rust branches are not complete. Main remains
`732e934ba496d90fbe042b8d41d479ef901643e5`; no branch was deleted in this pass.

## Scope and branch graph

The frozen GitHub inventory at 2026-11-15 14:39:59.563 UTC contains 7,256 branch
names: main, 34 newly added HIA branches, and 7,221 other candidates. HIA
exclusion follows descent from `f02bb9f3344cdff4e361cca4353540ca0193bd21` and
includes four branches whose names do not contain HIA. These branches have not
been modified or merged. The complete exclusion list and original tips are in
`hia-exclusions.json` and the frozen branch manifest.

Every one of the 2,276 maximal unmerged non-HIA tips was examined with ordinary
recursive merge-tree processing against the original candidate. Results:
261 clean textual merges (6 unchanged trees, 255 changed trees), 2,015 actual
content conflicts, and zero unresolved missing-object or infrastructure cases
in the completed matrix. A clean textual merge is not semantic approval.

The complete matrix is compressed into two ordered parts described by
`all-maximal-merge-matrix.json.gz.parts.json`. Concatenate its parts in recorded
order, verify their lengths and SHA256 values and the complete gzip SHA256,
then decompress to recover the exact 11,562,546-byte original JSON.

At local source checkpoint `8da08916d628b1d58ebbf759580dc750919afc87`, ordinary
ancestry includes 833 of the 7,221 candidate branch names, plus main, and none
of the 34 excluded HIA tips. This leaves 6,388 candidate names outside that
ancestry. Counts describe the frozen snapshot, not a deletion lease or full
semantic approval. A new live inventory is required before any retirement.

## Reviewed source and history included

- Continuous-time credit and existing discrete online-prefix APIs coexist.
  Both original timing and future-feedback fences are retained. The associated
  Python suites passed 129 tests; Rust compilation of the combined increment
  is being run separately and is not yet reported as passing here.
- Three historical research tips were merged with both parents preserved.
  The NDU native build helper now follows production and target dependency
  paths instead of assuming a fixed crate list. Its four added closure tests
  pass. Model download and training jobs require explicit manual opt-in.
- The PRED cached replay gate now verifies result SHA256, child exit status and
  source-closure readback before accepting a completed wrapper record. Its
  complete suite passed 183 tests without skips. Original archives, twenty
  byte parts, 799 archive members and 22 recorded inventory files were checked.
- PERC source and original native fixture bytes are retained. Its suite ran
  90 tests: 84 passed and 6 explicitly require external weights or datasets.
  No skipped model execution is counted as qualification.
- Eleven evidence or already-applied histories were merged through normal
  merge previews. The MEM12 archive conflict retains the previously verified
  original bytes in ordered parts, with explicit per-file resolution.

## Repairs from actual predecessor CI

The published `9b8de495b169486910a6a1da30690ac42306ae98` predecessor fixes the
AtomicBool/Mutex witness mismatch, duplicate Bazel crate annotations and the
three original over-limit archives. Its fresh native learning job executed
2,211 tests: 2,210 passed and one failed. The failed child requires the real
`codex` executable but its workflow prepared only the inference helper.

This checkpoint adds matching CLI preparation and verification to the shared
framework workflow. The separately audited Learning branch carries the
corresponding daemon-learning workflow repair; that branch is still being
integrated and is not claimed included by this document.

The prepared-context test observer now matches poisoned mutex errors
explicitly while retaining failure semantics, satisfying the actual Clippy
`expect_used` failure. The persistent-uncertainty fixture keeps its original
five-second readback bound and assertions, then observes original shutdown
until acknowledgement within the existing fixture bound. It no longer treats
one 30 ms scheduling delay during cleanup as a completed shutdown. Production
shutdown code is unchanged. Native regression execution is pending.

All seven changed workflows passed pinned Prettier 3.5.3 formatting and checks;
parsed YAML values before and after formatting are equal. The reviewed active
Rust source was transferred with a verified patch hash to an isolated ROG
checkout. Normal `just fmt --base 9b8de495b169486910a6a1da30690ac42306ae98`
exited zero and produced an empty formatting patch. This is scoped formatting,
not a full-workspace compilation or test claim.

Two newly introduced neuroscience records are now stored as byte-identical
ordered parts within the unchanged blob limit. Full reassembly, original Git
blob comparison and no-overwrite restoration checks passed. See
`neuro-evidence-storage.md` for original hashes and restoration commands.

## Remaining validation

Learning and HCSN ordinary merges are being reviewed separately. New HCSN
cryptographic dependencies still require a real complete Cargo resolution,
Bazel lock regeneration and native validation. Initial native resolution
attempts failed on registry network timeouts; an isolated production closure
diagnostic is not a substitute for the original workspace gates.

The original strict namespace failure and E0 out-of-range feature failure are
not relabeled or bypassed. Windows and macOS CI failures require exact current
source diagnosis. CodeQL alert detail remains unresolved. The earlier
21-alert count is not asserted to be 21 newly introduced vulnerabilities.

Required `CI required` and `Architecture required` checks must pass on the
eventual combined published head. The full branch/source review, live-tip
reconciliation, main merge and verified ref cleanup remain outstanding.

`ci-checkpoint-9b8.json` records the observed predecessor checks. Historical PR
descriptions are retained in `pr-body-before-update.md`; their head-specific
claims must not be applied to this checkpoint.
