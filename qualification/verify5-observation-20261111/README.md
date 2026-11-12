# VERIFY-5 retained observation experiment

User-facing date: 2026-11-11 America/New_York. Actual execution timestamps are
retained in UTC. Baseline: VERIFY-4 `88deb8a490565fd9b55851ba4581c9516fd1029f`.

**Outcome: informative partial readback in this fixture; no terminal policy
benefit or independent real-task qualification. HOLD / NoUpdate / NONE.**

## Executed results

The final local package suite ran **242 tests with zero failures**. The existing
SQLite smoke again confirmed **72/72** planned rows, and existing dispatch smoke
ran **9 scenarios / 17 subprocesses**. Their historical model inference counter
remained zero. The new experiment separately executed **one frequency-table
fit and 60 actual frequency predictions**, with **zero neural-model inferences**.

All **132/132** new controlled SQLite trajectories completed with known terminal
labels: 60 information probes plus 72 four-arm trajectories. Ten template groups
share one fixture generator; they are not ten statistically independent sources.
New independently adjudicated real business tasks remain **zero**.

| Diagnostic | Initial ACK constant prior | Paid partial-readback frequency model |
| --- | --- | --- |
| Train empirical probability resolution | 0 | 0.0972222222 |
| Confirmation Brier | 0.2225 | 0.1391836735 |
| Confirmation fixed-bin ECE | 0.0166666667 | 0.0904761905 |
| Shift Brier | 0.3725 | 0.4387755102 |
| Shift fixed-bin ECE | 0.4833333333 | 0.5476190476 |

Brier improved while ECE did not; prediction resolution and calibration must
be assessed separately. The shift changes a declared fixture mixture, not an
independently sampled deployment. Recalibration necessity is unknown when the
identity/completeness gate passes; no statistical drift decision is fabricated.

Each actual arm has 18 confirmation cases and fresh mandatory host acceptance:

| Arm | Optional property checks | Paid extra observations/predictions | Accepted | Accepted known value errors |
| --- | --- | --- | --- | --- |
| no_optional_check | 0 | 0 | 6 | 0 |
| fixed_readback | 18 | 0 | 6 | 0 |
| risk_triggered | 15 | 18 partial reads + 18 frequency predictions | 6 | 0 |
| oracle_information | 12 | 18 oracle reads | 6 | 0 |

All arms rejected zero cases whose terminal values were known clean. This is
not a causal false-rejection guarantee for owner/authorization obligations.
Skipping optional checks misses twelve errors at that optional stage, but the
mandatory terminal check prevents accepting them. Optional checks do not repair
state here, so fewer checks cannot be promoted to terminal improvement.
Full costs include separately retained training/probe acquisition. Single-run
timing is not a speedup claim; energy, pricing and complete physical loss remain
unknown. No model or policy is adopted.

## Evidence and exact source boundaries

- `ENGINEERING.zip` (reassembled from `ENGINEERING.zip.part-000` and
  `ENGINEERING.zip.part-001` using `ARCHIVE_PARTS.json`): executed Python source
  bytes, all four command logs, raw
  observation/cost/label records and actual SQLite databases; SHA-256
  `941750dfede43cbf37706191d7c870ba0a9a4c67967eb6a150589ed2366faffb`.
- `RESULT.json`, `DIAGNOSTICS.json`, `MODEL.json`, `PLAN.json`: unchanged readable
  copies from the final actual run; `EXECUTED.json` retains commands and identity.
- `SOURCE_BINDING.json` and `FORMAT.json`: exact executed/published file hashes;
  six changed Python files have identical ASTs across final formatting. The
  repository `just fmt` excludes these experiment paths, so scoped Ruff also ran.
  Local tests were not rerun after that final formatting operation.
- `CHECKER_REPAIR.zip` / `REPLY_INTEGRITY.md`: before/after callback integrity
  counterexamples, including pending recovery without checker replay.
- `PRELIMINARY.zip`: the earlier 241-test checkpoint and preliminary experiment,
  preserved rather than relabeled as the final 242-test source.
- `RETROSPECTIVE.zip`: exact original decoded GitHub responses and their source
  manifest for six run attempts / sixteen jobs: 11 success, 2 failure, 3 cancelled.
  It has zero pre-terminal snapshots, zero observed initial ACKs, and sixteen
  UNKNOWN business labels. It is not added to the experiment denominator.

The GitHub source adapter reads are from the same provider trust domain. API
head SHA and executed checkout identity remain distinct. Its 18 calls retained
162,854 UTF-8 payload bytes; their elapsed sum is not parallel wall time.
`MANIFEST.json` binds all retained top-level files. The live workflow now also
runs this observation experiment and uploads failures with the original receipts.

## Lossless archive packaging repair

The original CI blob-policy job rejected the 683,590-byte `ENGINEERING.zip`.
It is now stored as two ordered parts of 360,000 and 323,590 bytes, each within
the unchanged 512,000-byte policy. The original archive, source bytes and data
are unchanged after concatenation. `MANIFEST.json` remains the original run's
manifest; `ARCHIVE_PARTS.json` separately binds the replacement representation.
This packaging change adds no task executions, fits or predictions.

Reassemble from this directory into a new destination:

```python
import hashlib, json
from pathlib import Path
root = Path("qualification/verify5-observation-20261111")
manifest = json.loads((root / "ARCHIVE_PARTS.json").read_text())
chunks = [(root / part["name"]).read_bytes() for part in manifest["parts"]]
for part, chunk in zip(manifest["parts"], chunks):
    assert len(chunk) == part["bytes"]
    assert hashlib.sha256(chunk).hexdigest() == part["sha256"]
archive = b"".join(chunks)
assert len(archive) == manifest["original_bytes"]
assert hashlib.sha256(archive).hexdigest() == manifest["original_sha256"]
with Path("/tmp/verify5-engineering-restored.zip").open("xb") as stream:
    stream.write(archive)
```
