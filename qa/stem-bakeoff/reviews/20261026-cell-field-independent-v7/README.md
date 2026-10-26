# Independent V7 and V7b development review

Both complete development grids remain preserved. These are post-run verification tools and receipts; none is retroactively included in either 103-file executed source closure.

## Main receipts

- [Original V7 audit](v7/receipts/audit.json): all 864 outputs, 26,238 exact Adam updates, 3,275 retained controller snapshots, and source-loss/selection arithmetic reproduced with zero discrepancy.
- [Original terminal preimage recovery](v7/receipts/controller-recovery.json): all 93 missing stopped terminal preimages recovered only when their canonical bytes matched the original trace SHA256. Original plan/repair records, paid timings and stop ledgers remain unchanged. Twenty-eight intended plans were regenerated only at their last committed origins; the new costs are separately charged.
- [Independent recovery verification](v7/receipts/controller-recovery-peer-audit.json): all 93 original commitments, paid ledgers and complete optimizer checkpoints verified without optimizer/control calls.
- [Corrected V7b audit](v7b/receipts/audit.json): all 864 outputs, 26,662 exact Adam updates, 3,400 retained controller snapshots, and all 864 actual terminal preimages directly available. Source-loss/selection arithmetic again reproduced with zero discrepancy.
- [Complete paired comparison](v7b/receipts/comparison.json): every original slot has its corrective counterpart. Data, initial states, panels, configurations, order and selection rules are unchanged. Only the two declared implementation sources differ.
- [Two completed-to-stopped cases](v7b/receipts/stopped-regressions.json): exact IDs, first action differences, frozen KKT checks and bounded nonlinear repair failures. This diagnosis only reads records; it executes no optimizer and changes no thresholds.

## Observed disposition

| Measure | Original V7 | Corrected V7b |
|---|---:|---:|
| Registered/observed primary outputs | 864/864 | 864/864 |
| Completed 32-step policies | 739 | 766 |
| Actual execution-error records | 29 | 0 |
| Eligible configurations | 0/12 | 0/12 |
| Plausible configurations | 0/12 | 0/12 |
| Selected configuration | none | none |
| Scientific acceptance | false | false |

Of the original 29 execution-error cases, 28 completed in V7b and one stopped with a tangent-infeasibility result. Two previously completed policies now stop under the unchanged numerical-certificate/repair rules; both remain in the census. Ratios involving unequal completed work cannot establish scientific eligibility or a causal speedup.

All 72 config00 action byte sequences, complete optimizer-state/receipt traces, and source-loss endpoints are identical between runs. The V7b controller contract nevertheless has separate protocol and source identities. Each native input manifest retains 96 registered cutpoints: 70 active, 22 completed, one stopped for rejection, and three missing. These input manifests alone do not claim native execution; actual native qualification is a separate published stage.

## Layout and reproduction

Each version has its own `tools/` directory, preserving the exact audited post-run source bytes. Run each tool from its corresponding directory, using the pinned research Python environment and a workspace containing the recorded source checkouts, historical warmups, datasets, features and full sealed run artifacts. The audit CLI accepts `--workspace`, `--grid`, `--output`, and `--native-output`; the source checkouts are named `hepta-repo` and `hepta-repo-v7b` respectively.

The complete source-metric census is `case-census.json.gz`; decompress it beside `audit.json` to recover the exact `case-census.json` bytes committed by that audit. `all864-comparisons.json.gz` retains every paired row, including stopped/error cases and byte-level comparisons. The publication manifest records compressed and uncompressed hashes.

Planning identity files contain current-training and reused empirical planning-panel identities. No future/old selection labels are included. The V7b export reuses exactly the original planning array bytes and checks all non-timing frozen provenance before binding them to the new protocol. Arrays and complete run traces remain in recorded inputs/archives; this compact review does not replace them.

The 71 stopped-origin mechanism study, 29-case action-interpolation reproducer, and actual native qualification are separately published stages. The publication manifest here explicitly lists only this independent-audit bundle; separately owned `mechanism-v7/` files are not rewritten by this bundle.
