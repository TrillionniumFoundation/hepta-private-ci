# Complete owner qualification records

This archive preserves 150 original records and reconstruction inputs for the reviewed Core, Goal, and Queue source subset. It includes the four test attempts, five canonical lock attempts, final fix and format commands, source manifests, original logs, and complete durable task status and output streams. Failed attempts remain present.

Run `python verify_archive.py` from this directory to check all parts and all original members. Each `.tar.gz` file is a separate gzip stream of at most 384,000 raw bytes. Decompress the parts in manifest order and concatenate those raw slices to recover the original TAR stream. Do not concatenate the gzip bytes and treat individual compressed fragments as text.

The successful test scope is 130 total tests: three new Goal regressions, 24 original Goal tests, 38 original Queue tests, and 65 original Core tests. Another 2,420 Core tests were filtered out. This is Linux source qualification for the owner subset; it does not qualify the whole ca77 frontier or Windows behavior.

The parent source commit is `9035ea6762dce841e6bd6a86e4d66446d58af6d8`. This evidence addition does not change its twelve source and dependency paths and does not repeat any test or build.
