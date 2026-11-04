# V5 source binding and current installed-lane wiring

Date: 2026-11-01. **All PN0–PN6 strict exits remain HOLD.** This record reports
source changes and executed controls, with separate results for source identity,
native execution, installation authority and learning benefit.

## Fixed source identities

This companion is prepared on Hepta
[`f0f1f16898c2f9737461a28752b421fe52e65ee7`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/f0f1f16898c2f9737461a28752b421fe52e65ee7),
tree `81d52b6ea085a2b4e913cbea027d8198febc3046`, and continues
[PR #4497](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4497)
on `fix/hepta-pn-cell-closure-20261031`. Its final Hepta source is the Git commit
containing these seven source changes and this evidence directory. That containing
commit and tree must be recorded after publication; their hashes cannot be
embedded inside their own tree.

V5 and the existing `cell-installed-host-v3` job both bind the actual Chain
[`acd8f79f2dcc22ecdee1d1a5fd88d619d06f37c9`](https://github.com/TrillionniumFoundation/Trillionnium-Chain/commit/acd8f79f2dcc22ecdee1d1a5fd88d619d06f37c9),
tree `4e83d2d4ba6b15ddd962ef08652dbeb24858c533`. The V5 manifest SHA-256 is
`cc914a114f6216be856eb983c3326ea37e030cbea3c8e2535d2266c76d001dcf`.
Its 42 execution/data files were checked against the final remote Git tree, the
local actual bytes and the original restored bytes. All three agree. The Git
commit object independently names the expected tree and the original cea95
parent. This is a closed source record; it grants no model compatibility change
or installation permission.

The Chain source report is retained once, in
[the exact paired Chain evidence](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/acd8f79f2dcc22ecdee1d1a5fd88d619d06f37c9/evidence/pon-pn-convergence-next-20261101/README.md),
under [PR #559](https://github.com/TrillionniumFoundation/Trillionnium-Chain/pull/559).

## What was implemented

This V5 is a new implementation from the published f0f1 baseline. It is **not
recovery of the previously described but unpublished V5 source**, and does not
inherit its claimed test counts or manifest identity.

The execution-source registry adds an explicit V5 selection with a new manifest
schema requiring both the exact commit and tree. Digest, shape, selected file
bytes and historical V2 identities are checked before Chain module imports.
The diverse training consumer binds both runtime and training to that same
source only when V5 is explicitly selected. The evidence reader requires all
four Chain roles to match the frozen V5 identity and their original before/after
snapshots. Legacy defaults stay unchanged.

All 18 previous string constants, all 10 locally restored historical profile
artifacts and all five other workflow jobs retain their baseline identities or
YAML structure. In particular, the old c165 source-head/base-merge x64/arm native
gates remain historical and unchanged. Their earlier results do not qualify the
new source.

Only the existing `cell-installed-host-v3` job receives current-source wiring,
under its original **60-minute** job timeout. The existing installed controls
retain their owner and admission semantics. New workflow commands use selectors
present in the actual paired Chain:

| Current job command group | Required direct successes | Execution in this record |
| --- | ---: | --- |
| PQ startup library controls | 14 | Not run natively |
| Durable History import/recovery controls | 15 | Not run natively |
| Growth CLI and public growth CLI controls | 3 + 4 | Not run natively |
| Original current from-zero wrapper and driver | Five exact native cases, enforced by the original driver | Not run natively |

The History selector skips only the ignored kill-child fixture. Its ordinary
parent test remains mandatory and starts that child at all five original
SIGKILL cuts; the child is not counted as a direct successful test. The
from-zero command retains the actual four-argument wrapper interface and the
original build and case limits. No substitute selector or fallback is added.
The real PQ-enabled Node binary is compressed and hashed before later
default-feature builds can overwrite its shared target path.

These are separate component executions to be observed by CI. Adding them to
one job does not establish simultaneous PQ/growth/continuous behavior or a
complete authorization migration.

## Executed observations

After the final Chain commit/tree and manifest digest were written, the following
four commands were actually executed. Exact command arrays, times, return codes,
raw log hashes, gzip files and source snapshots are in `final-controls.json`.

| Controls | Actual tests | Result |
| --- | ---: | --- |
| Execution-source V1–V5 controls | 51 | PASS, exit 0 |
| Diverse training and evidence controls | 32 | PASS, exit 0 |
| Original current from-zero owner controls | 20 | PASS, exit 0 |
| Original current from-zero reader controls | 86 | PASS, exit 0 |
| Total | **189** | All passed; seven source files unchanged during execution |

The separate `before-final-pin/` directory preserves the four original raw
control logs from the temporary cea95 binding, also totaling 189. They are
retained as earlier observations, not counted again as new test coverage.

The actual V5 CLI was also invoked against the local Chain repository after its
HEAD was advanced to the final source commit. It returned exit 0 and verified
the 42 selected files, with product qualification and installation authority
false. The local repository has **4,645 skip-worktree entries** and missing
historical archive blobs. A clean-looking index is therefore not a complete
checkout-integrity claim. `source-check/actual-v5-verifier.json` records this
limitation, all selected-file flags and the unmodified stdout/stderr bytes.
The independent final-tree comparison in `closure-42.json` covers the selected
42 files directly.

The repository-required **`just fmt` ultimately passed**, using the real baseline
commit/tree and restored original blobs. Earlier attempts are retained: the
selected-file restoration initially had no Git HEAD; after restoring the real
HEAD it exposed a missing original blob; after restoring those blobs the default
uv cache was read-only. The first failure was observed but its raw log was not
saved. A later actual replay of that same failure is preserved as
`format/just-fmt-replay.log.gz` and explicitly identified as a replay.

The final original command used `UV_CACHE_DIR=/tmp/hepta-ci-uv-cache` and
`UV_OFFLINE=1` with the existing frozen cache. It returned **exit 0** and changed
none of the seven tested source files. Its exact receipt and all intermediate
raw logs, including the empty successful log, are preserved under `format/`.
The exact lockfile Ruff version, **0.15.13**, also passed a scoped check of the
five Python files. Successful changed-file formatting does not make this a
complete Hepta checkout. No source bytes changed, so the final 189 controls were
not needlessly rerun after formatting.

The independent reviewer inspected all seven source files, compared the
historical gates and manifests, checked all ten installed-job shell blocks,
and independently ran 83 source/diverse Python controls. Its original receipt
and logs are preserved without rewriting their temporary-pin identity. The
final binding-only review separately binds those findings to the final source
bytes and confirms that inverse substitution of the three changed source
bindings reproduces all seven previously reviewed file hashes. Neither source review is an independent administrator
WAN acceptance campaign.

## Acceptance boundaries and remaining work

| Acceptance question | Status from this record |
| --- | --- |
| Published source selection, closed manifest, historical isolation | Source implementation and Python controls complete; final containing Hepta Git identity must be read back after publication |
| Actual paired native build, startup and ordinary execution | UNQUALIFIED: new native commands have not been executed successfully here |
| Complete Cell release retrieval and original-owner mechanical loop | UNQUALIFIED for this pair; no new complete release or ordinary post-install task was run |
| Installation eligibility and legitimate no-update | Existing admission path retained; no new installation authority is granted, and no-update remains valid |
| Actual learning benefit | UNQUALIFIED: no new real-model training or measured subsequent-task improvement |
| Whole PQ authorization and migration | HOLD: ordinary Cell final-use still follows the published V1 Ed25519 path; the separate ML-DSA authority API needs trusted clock/frontier integration |
| Independent administrators, 72-hour WAN, real funding and activation | Not executed or established by this record |

The ordinary model study workflow still records its historical multi-source
configuration. Explicit V5 consumer support is groundwork for a future actual
run, not evidence that that workflow has already trained, fetched, installed or
improved the model. Earlier three-object observations must not be presented as
the full eleven-object release. No native result, historical model result,
independent acceptance result, funding event or activation decision is inherited.

## Evidence index

- `source-changes.json` and `source-changes.patch.gz`: exact seven-file delta,
  baseline blobs and final source hashes. The patch is gzip-compressed with
  `mtime=0`, preserving all 32,008 original bytes. Its uncompressed SHA-256 is
  `83a888d50b962f89f599a120079602d7e864faeaa53decfd434b836ff9d080a6`.
- `source-check/closure-42.json`: final commit/tree readback and exact 42-file
  byte/Git-blob comparison.
- `source-check/historical-invariants.json`: immutable historical artifacts,
  original constants, five unchanged jobs and unchanged 60-minute budget.
- `source-check/actual-v5-verifier.json` and its raw logs: executed local source
  verification with restoration limitations.
- `final-controls.json`, `final-controls/`, `before-final-pin/`: actual final
  and earlier control observations kept separate.
- `independent-review/`: exact original review and its logs, plus the final
  binding-only review.
- `format/`: actual project command failures, final successful original
  `just fmt` with unchanged source bytes, and successful scoped Ruff.
- `MANIFEST.json`: byte identities of every evidence file except the manifest
  itself, with explicit acceptance fields false.
