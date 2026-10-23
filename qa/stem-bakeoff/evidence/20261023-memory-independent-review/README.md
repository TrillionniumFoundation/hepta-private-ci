# Independent implementation and evidence review

The completed routing event is internally consistent with its frozen development
protocol. A separate reviewer reconstructed raw outputs, utilities, routing,
scores, costs and identities: **19,379 comparisons, no experimental mismatch**.
Scientific Phase 3, future-task advantage and equal total budget remain open.

## Readable reviews

- [Boundary review](boundary-review.md) inspects the typed service, source and
  parameter lifecycle, domain controls and one-host network mechanism.
- [Final routing review](routing-final-review.md) covers all three completed
  seeds, all nine scoring policies and the corrected publication revision 2.
- [Final compact summary](routing-final-summary.json) retains machine-readable
  identities, results, denormalized cost totals and audit artifact locations.
- [Earlier cutoff review](routing-early-cutoff-review.md) remains byte-identical
  to the partial observation made before all three seeds completed. It must not
  be presented as the final all-seed review.

The final audit checked 912 source-utility observations, 2,904 decoder rows,
3,816 saved linear-router predictions and 720 nearest-source routes. It checked
107 repository Python files, five diagnosis modules, 201 historical JSON files,
48 checkpoint files and six publisher base files against the frozen pins.
All 284 run-002 files in the published archive matched the original outputs.

## Retained audit bundle

`hepta-memory-independent-review-20261023.tar.gz` contains the exact original
review files, detailed audit JSON, the executed standard-library audit script,
its final log, and both earlier audit-harness error records. Its internal
`MANIFEST.json` records every other member's bytes and SHA-256. Every member was
compared with its original bytes while packaging. Verify `SHA256SUMS` before
extraction. The scripts and receipts retain their original absolute paths;
they document the inspected environment rather than fabricate a portable rerun.

The two harness errors compared unlike hash contracts and initially looked for
base identity in the wrong record. They were corrected only in the audit code.
Their logs remain available; they are not experimental failures or model runs.
The final audit used standard-library arithmetic, without Torch or NumPy, and
performed no model inference, fitting or gradients. Its roughly 6.06 seconds
and 85.5 MB peak RSS are separate audit costs, not new experiment work.

The experiment and reviewer share the same local host and principal. This is
independent evidence reconstruction, not independent-host execution attestation.
The exact result and reproduction bundle are published in [PR #3576](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3576).
