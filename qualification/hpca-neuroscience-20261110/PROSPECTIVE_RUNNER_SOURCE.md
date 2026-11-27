# Frozen development runner source

This source stage builds on the separately published96-task protocol. It has
no model results yet. Ten local preflight tests pass without importing Torch;
they check split/exposure exclusion, base-only calibration selection, fixed tie
order, invalid-output denominators and rejection of a mismatched publication
manifest before any model import.

The launcher must read the exact published GitHub commit and compare every
execution file's blob bytes to the locally verified source. It then writes
`PUBLICATION.json` containing that commit and the SHA256 of all seven source
and input files named by the runner. The runner rejects a mismatch, pins these
bytes before/after execution and binds the publication manifest hash into
PREEXECUTION. This is a materialized-file source binding; a complete local Git
tree or external scientist/Owner authentication is not claimed.

Invoke only after publication and source-byte readback:

```sh
python prospective_devel.py --model ORIGINAL_PINNED_MODEL \
  --adapter-root ORIGINAL_EIGHT_ADAPTERS --out NEW_EXCLUSIVE_OUTPUT \
  --publication-manifest PUBLICATION.json
```

PREEXECUTION binds one journal run ID and the resolved configuration before
the first model generation. The final result binds journal, PREEXECUTION,
generation configuration and wrapper-selection file hashes. Each condition's
same64-question timing is separated from model loading and the base's extra48
calibration/development calls. Process/setup/failed-attempt costs remain distinct.

Independent future B, source custody, production selection and adoption remain
unqualified. All weights stay unchanged and every decision remains HOLD_NO_GO.
