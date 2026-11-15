# Reviewed small legacy source integrations

Each incoming tip is merged normally after a fresh preview against the current
local head. Small/clean deltas are reviewed as code; historical PASS records do
not establish results for the combined source. Remote and protected HIA refs
are not changed by this local work.

## Independent v1 scorer

Incoming `0f8091d6f27b1f81eac08f1a1f3383a952a4ab80` adds the standalone model-free
audit, tests, explanation and a historical receipt. Review covered the complete
scorer, bounded reference-subset matching, exact frozen episode/method roster,
PNG bytes, score and cost reconciliation. No model/network job is introduced.

A concrete cache bug was reproduced: after accepting a 20x20 PNG, the auditor
accepted the same digest against a later 21x20 reference. The cache had stored a
reference-specific validity flag. It now stores only the pinned PNG's intrinsic
digest, format and dimensions, and rechecks each reference. Decoding uses the
same bytes that were hashed. Positive-to-negative and negative-to-positive cache
regressions both pass. The complete focused suite passes 13 tests without skips.

The original source-pinned historical receipt remains unchanged; its private
evidence archive was not supplied or rerun. The new checks do not revise the
frozen scientific result or authorize promotion. Exact hashes/test logs are in
`legacy-small/independent-v1-audit.json` and its companion log.
