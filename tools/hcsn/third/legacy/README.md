# Historical integrity capsule

The two archived modules are exact bytes from baseline commit
`1dd990bedee8a525093c1dd4008b2f00c2c5ff1c`. They are used exclusively to
reconstruct historical evidence snapshots in temporary directories. Active
financial computation uses the corrected modules in `analytic/`.

Run `python third/legacy/replay.py` from `tools/hcsn`. It verifies every baseline
Git blob, reconstructs the 575-file follow-up snapshot and the original
delivery-manifest subset separately, and runs each version's own integrity
checker in its corresponding source tree. The first-release checker predates
the `next/` schema and is therefore run only on the first-release subset.

The command never overwrites current source files or historical evidence.
Temporary snapshots are removed after completion. The output records
artifact integrity; the older failed scientific acceptance gates remain
failed. This capsule avoids changing historical SHA receipts when fixing
current numerical or admissibility bugs.
