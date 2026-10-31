## Why

The previous content study processed the complete prepared input before choosing observations, changed sequence length and physical horizon together, and metered several mechanism arms in one worker. Those contracts could not attribute actual sensing savings or complete per-arm execution costs.

This follow-up is stacked on #4519 and changes only `experiments/hcsn_causal_execution_v3`. Its inherited source baseline is `c5e159ec6c5ba174b36debacad166da635c57d48`.

## What changes

- Run the ordinary/analytic × lightweight/task-value 2×2 on three new fits and 768 new worlds. Separate current-observation forecasts from hypothetical READ continuations and meter every arm in its own process.
- Cross content length with physical horizon while retaining the same bindings. Add a separately frozen causal clock-cap intervention and a task-known keyed-memory reference.
- Fit ordinary AV interaction probes using training data and validation selection; preserve every candidate, selected checkpoint and prediction.
- Enforce READ before acquiring a payload or invoking the encoder. Recompute deltas from accepted history, check per-record/model identity, and restore actual episodes in new Python processes.
- Preserve raw evidence, independent auditors, process receipts, plots and portable verified archive restoration.

## Findings

| Acceptance question | Observed result |
| --- | --- |
| Extra analytic utility under the same controller | Matched D−B **+0.00984375**, descriptive 95% interval **[−0.00424544, +0.02557292]**; the primary increment remains inconclusive. |
| Complete per-arm CPU | B **136.850036 s**, D **85.700836 s** across 768 episodes each: D uses **37.3761% less**. No quality-noninferiority tolerance was preregistered. |
| Common content failure | Copy at L128/T3.2 is **99.7396%**, but L128/T12.8 is **6.7708%**; one fixed causal clock cap raises the latter to **96.6146%**. This is exploratory shared-content repair, with remaining seed-level failure. |
| AV representation and generalization | Ordinary models fit training at 100%; old-test emotion/binding are **5/12** and **13/24**. Cross-actor generalization remains inadequate. |
| Qualified observation savings | Both validation selections choose **READ-all**; eligible encoder/payload savings are **zero**. |
| Recovery | All **36** actual new-process resumes preserve actions, probabilities, acquired content and counters. |

The ordinary mechanism is a 23,712-parameter gated feedforward model, with a different structural prior from the analytic renewal law. This is not a strong-SSM or independent financial Put-channel result. AV uses the same two previously observed test actors. The clock intervention is post-diagnostic exploration.

## Validation and evidence

- **63/63 mechanism workers and 26/26 stream workers succeeded.**
- Independent mechanism audit reconstructs **27,648 predictions** and checks **1,536 forced replays** and **768 causal prefixes**.
- Independent stream audit checks **12,575 action records**, model/source/payload identities, selection, repeated measurements and all 36 recoveries.
- A complete AV process replay uses **3.010586 CPU seconds** and matches the arrays in **732 NPZ files**.
- Four multipart bundles contain **1,578 members** and **82 parts**; all were restored into independent directories and compared byte-for-byte.
- Remote tree readback verifies **146/146 scientific/report/evidence blobs** at `261ec28a6aa0dd6fa6d372107acbfa5ebcf958ef` against local Git blob hashes. Root/experiments tree comparison restricts the change to this one namespace.
- Whitespace checks pass. Canonical `just fmt` was attempted but changed-path discovery exited 2 because this selected-file local snapshot has no HEAD. The exact failure is retained; frozen candidate hashes are unchanged. No Rust source changes or native Rust test claims are included.

The stream source and protocol were published **before execution** at `58734d86b5dd8436f56a210632fca1acf8f3ea6c`. Other studies retain their local pre-execution source/seed freezes and all disclosed development/audit corrections.

## Cost boundary and review

CPU measurements cover the declared local processes, including imports, loading, output and waited recovery descendants. Outer and inner receipts are not double-counted. The shared host is not isolated; original-media decoding, live sensors/network and joule energy are not measured.

- [Complete Chinese report](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/261ec28a6aa0dd6fa6d372107acbfa5ebcf958ef/experiments/hcsn_causal_execution_v3/REPORT_ZH.md)
- [Mechanism evidence and all contrasts](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/261ec28a6aa0dd6fa6d372107acbfa5ebcf958ef/experiments/hcsn_causal_execution_v3/MECHANISM_RESULTS.md)
- [Content diagnosis and residual failures](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/261ec28a6aa0dd6fa6d372107acbfa5ebcf958ef/experiments/hcsn_causal_execution_v3/MEMORY_RESULTS_ZH.md)
- [AV representation and actor results](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/261ec28a6aa0dd6fa6d372107acbfa5ebcf958ef/experiments/hcsn_causal_execution_v3/AV_RESULTS.md)
- [Causal execution and costs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/261ec28a6aa0dd6fa6d372107acbfa5ebcf958ef/experiments/hcsn_causal_execution_v3/STREAM_RESULTS_ZH.md)
- [Restore and reproduce](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/261ec28a6aa0dd6fa6d372107acbfa5ebcf958ef/experiments/hcsn_causal_execution_v3/REPRODUCE.md)
- [Figure data and provenance](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/261ec28a6aa0dd6fa6d372107acbfa5ebcf958ef/experiments/hcsn_causal_execution_v3/figures/PLOT_SOURCE.json)

Draft for research review. The independent utility, broad AV generalization, same-quality economics and production qualification remain open.
