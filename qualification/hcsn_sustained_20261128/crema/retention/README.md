# Cold evidence retention qualification

The earlier sustained-run collector verified every checkpoint but added only the best checkpoint to the publication list. It therefore dropped first-quality-gate weights even when a terminal summary referenced them. The producer also saved raw scores only for the best checkpoint. The baseline reproduces the omitted files; this repair does not recreate old unsaved predictions.

## Changes

- Retain every original history checkpoint, including each first-quality-gate selection.
- Save each actually evaluated selection's original numeric output and bind it to its checkpoint digest; keep the existing best-score alias byte-identical.
- Keep first-written scores and indices immutable. A resumed exact write is idempotent; conflicting bytes are refused without replacing the original.
- Check every selected record against verified history before deduplicating filenames. A good gate record cannot hide an invalid best record with the same filename.
- Require the current cold-evidence profile at the ordinary publisher boundary. The expectation comes from the externally pinned collector source, independently of the artifact's own marker. Missing marker, missing whole index, or both missing cause refusal.
- Revalidate the complete local inventory after host-to-relay transport.

The explicit `legacy_inventory()` recovery API returns `UNKNOWN` and `complete=false`; neither publication entrypoint calls it. It retains surviving originals and leaves absent historical gate scores absent. A manifest marker and hashes alone do not attest host honesty or scientific validity.

## Recorded execution

The first observation at `f2d08345463dbd7b8294ea4ed72146f3de9ca834` passed 5 test methods before the whole-index/schema-downgrade and selection-alias cases were discovered. Its original source, logs, hashes and format receipts are preserved in `first-observation.tar.gz`. That first result is not the final completeness qualification.

The new publication semantics were frozen at `d0e1f5baa4fb88f0c45bb5f72b24486890d258de`. The second execution passed all 5 test methods, with no failures, errors or skips, in 0.332447 seconds. The real tar roundtrip retained 101 members with zero digest mismatches. Restored arrays matched their originals. The archive payload itself is included in `strict-profile.tar.gz`, alongside source snapshots, all rejection records and environment details.

The eight recorded refusals cover missing and changed scores, missing gate-index entries, missing whole index, simultaneous marker/index removal, wrong checkpoint binding, changed gate digest, and a shadowed best digest. A separate legacy control retained 65 files and stayed `UNKNOWN`; its missing gate scores were never written. Exact resume and conflicting-write protection also passed.

`just fmt` completed with exit 0. Ruff formatted only affected function ranges and the new test file; all four Python files had identical ASTs before and after formatting. No tests were rerun after that final formatting pass. The first pass's original missing sparse-fixture failure and its recovery remain in the first archive.

## Reproduce and interpret

From a checkout containing the tested source, with NumPy installed:

```sh
python -m unittest discover -s qualification/hcsn_sustained_20261128/crema -p test_archive_retention.py -v
```

`RESULTS.json` names both source commits and archive hashes; `PROTOCOL.json` preserves the original controls and `SCHEMA_SCOPE.json` records the later semantic change that required another execution. The archives retain exact test-time source bytes rather than implying the formatted tree was executed.

These are synthetic engineering fixtures using real filesystem, NPZ and tar operations. No model training, Torch forward, held-out scientific scoring, remote deployment, or active-job restart was performed. The study-loop integration was reviewed structurally. A previously running producer loaded from older source does not acquire this patch retroactively and must not be certified complete by deleting the new marker. This qualification establishes the tested retention behavior, not restored historical results, circuit superiority, model generalization, or a training-time advantage.
