# Four original branch histories and complete CodeQL source review

This record accompanies candidate
`25423ca656d1890b54cf4674ddedd8c867932b53`, tree
`33a2b576be461dd4d7ee51e1754cc14cadd5fcd5`.
Its base is published integration head
`6de3bb36d80f4a1c92f83e9cde7f8b0f496f5e5f`.
The recorded work retains four original ordinary branch tips as ordered second
parents and fixes one independently observed CI workflow path error.

## Original histories and source decisions

| Original tip                               | Canonical merge                            | Source decision                                                                                                           |
| ------------------------------------------ | ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------- |
| `ae8d1db1745112552b560ddabe75547b4553903e` | `f6f744821e18d45655a01e483c4605ac3217fe5b` | Keep current complete rustls records and the stronger Fleet result assertion.                                             |
| `2c33d6c3d10079290b8b3088a3003885af8710a2` | `15bc0145b3227ca75ca9b5488ed093d1e3ed6baa` | Keep current explicit Q24 assertion imports and stronger NextUse audit checks; preserve the original negative cases.      |
| `a870d8a5a1d8bfa61b1e2a6fd353b3645ca7028f` | `45c1d1bf45ae4207fd08aea6f41b210fb98ca06c` | Retain this distinct terminal parent as well as its shared original history; keep the reviewed current source resolution. |
| `155902ab12acf7f2fa163e84c98c8126221b5341` | `960818448eb34c364c4142412be68030495cce4e` | Retain the current owned-file-descriptor PTY helper and compose the original Node/Python regression and workflow intent.  |

Seven previously unretained original commits are included by those four merges.
Every ordinary merge preview, explicit conflict and selected resolution is
retained. The first three resolved trees are unchanged; the fourth changes
exactly these three paths:

- `apps/hepta-control-ui/test/generated-workspace-patches.test.mjs`
- `scripts/test_run_nextest.py`
- `.github/workflows/ui-product-foundation.yml`

The following single-parent commit changes only
`.github/workflows/hepta-shared-cell-ruff.yml`.
Its three substitutions point to the actual tracked security test under
`scripts/tests/`. The original hosted job exited with code 2 because the old
path did not exist. The original selector, diagnostic and failing check are
retained with the corrected path; versions, budget, permissions and source
identity checks remain intact.

## Executed checks and their limits

The three-source union passed **14 actual regressions**: two new Node cases,
one existing Node case exercising real Cargo and a negative path, and the
complete eleven-case Python suite. None was skipped. All 29 declared source and
control inputs remained unchanged. This original UI validation used its own
Rust 1.95.0 and verified nextest 0.9.146 pins; it is not a product-workspace Rust
1.96 native test claim.

The Ruff proposal passed the original frozen Ruff 0.15.13 diagnostic and check
commands over the three real input files. Codespell 2.4.3 and Prettier 3.5.3
checks passed for the reviewed source proposals. The local uv environment used
Python 3.13.12; this does not claim execution of the complete hosted Python 3.12
workflow.

A separately retained **full PR-base blob policy run** passed on the exact
published base head `6de3bb36d80f4a1c92f83e9cde7f8b0f496f5e5f` against main
`732e934ba496d90fbe042b8d41d479ef901643e5`.
It checked all 22,945 added or modified paths, found no missing objects and no
violations, and recognized the existing 288 allowlisted large files. Its ten
original policy tests passed. The 512,000-byte limit, allowlist and original
30-minute workflow budget were not changed. This result is pinned to that
published head; it is not silently relabeled as a full-base run on a later
candidate.

No product Rust, whole-workspace native, Windows capability, B4, caller or whole
CI qualification is granted by this evidence bundle. The separate AuthBus,
memory diagnostic and learning-artifact proposals are not included here.

## Complete CodeQL review

The complete saved analysis contains **194 Rust and 4 Python results**. All
198 original results and full traces are retained, including similar traces.
The thirteen complete review groups and twenty-one source annotations are
indexed without dismissal or suppression.

| Source-level classification                                                              | Results |
| ---------------------------------------------------------------------------------------- | ------: |
| Explicit test or fixture, with real entry and boundary checked                           |     160 |
| Reported flow excluded under the recorded type, validation, initialization or API bounds |      32 |
| Runnable owned Windows experiments with checked native outputs                           |       2 |
| Intentional sensitive interactive or human output                                        |       3 |
| Account metadata output needing policy and producer-field evidence                       |       1 |
| **Total**                                                                                | **198** |

No confirmed security defect was established for these particular reported
flows. This is not a claim that the repository is secure or that a new scanner
run passes. All 116 trace source paths and all 176 distinct trace/context paths
were compared by mode, type and Git object across the analyzed head, the
original review baseline and candidate `25423ca656d1890b54cf4674ddedd8c867932b53`.

The remaining output boundaries are explicit. Browser authorization URLs and
device verification codes are sensitive instructions needed for login.
Human-output mode echoes the effective user prompt to stderr. Account quota
diagnostics include free-form limit and reset-credit metadata, not only numbers.
Their destination, access and retention policies are not established by source
inspection. Existing rejection guards and all positive and negative assertions
remain intact.

## Required checks and recorded branch scope

Main still requires the exact strict contexts **CI required** and
**Architecture required**. The old analyzed head's architecture aggregate
passed and its CI aggregate was cancelled. Its macOS dependency failed before
test execution while downloading the hyper sparse-index entry; that failure
does not establish the cause of every cancellation.

The finite published-head snapshot at **09:08:43–09:08:45 UTC on 2026-11-17**
contains 221 unique checks across three non-atomic pages: 189 succeeded, eleven
failed, five were running, fifteen were skipped and one was neutral.
**Architecture required** succeeded. The exact **CI required** context was not
observed, so it has no passing result in this snapshot. The snapshot is not a
terminal CI result.

Against the complete recorded **08:11 reference snapshot**, the candidate
contains **1,904 of 7,230 ordinary current-snapshot heads**, with 5,326 remaining.
This is not a frozen-original-head count or a new live inventory. The recorded
235 protected names and 244 current/historical/marker pins have no intersection
with the candidate ancestry. No HIA branch, main reference or ordinary branch
was changed by this evidence freeze. A new complete reference/protection check
is required before publication or cleanup.

## Lossless evidence

The bundle retains **396 original files as 370 unique byte objects**. It includes
the original source reviews, fourteen-test receipts, canonical commit metadata,
full PR-base policy output, all CodeQL results, required-rule responses and the
original failed preparation logs.

- `originals-manifest.json.gz` maps every original file, length, SHA-256 and role
  to its content object.
- `carrier-index.json` records all forty independently compressed tar-stream
  pieces, their offsets, lengths and hashes.
- `freeze-result.json` records the exact restoration and unchanged-input checks.
- `proof-part-*.tar-stream.gz` preserve the complete tar stream. Decompress each
  piece in index order and concatenate the resulting bytes before reading the
  tar archive.

Every original object was restored from the reconstructed archive and checked
against its recorded length and SHA-256. Fourteen existing gzip originals were
also independently round-tripped. The largest new carrier is 480,090 bytes,
below the unchanged repository limit. An original preparation PTY stored outside
the task directory was copied by its one exact approved path and hash; its
custody mapping and the initial scope-check failure are retained. No unrelated
external files, tool installations, Git indexes or caches are included.
