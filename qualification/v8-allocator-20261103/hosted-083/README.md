# V8 native qualification on exact 083 source

Both original platform jobs in run 41710309685 succeeded on
083116160fe81198ae0c441aad22224c0c8d2940. Each original artifact independently
binds 132 before/after Git inputs, full logs/XML and the original commands.
Each platform passed the fresh-process 16-thread case, then all 115 original
consumer cases with zero failed, ignored, measured or filtered cases, both
sandbox assertions and three Clippy binaries. Linux checks the committed
lock first. The original native wrappers and 30-minute budgets are retained.

To restore and repeat the read-only inspection, run `python3 verify.py
--platform windows --repo /path/to/repo` and repeat with `--platform linux`.
Python reads original artifact bytes and immutable Git blobs; no archived
source or native executable is run. Original failed attempts remain in the
parent qualification directory. This checkpoint does not advance the tested
product branch. Full CI, V8 source-build deadlines and qualification with the
combined dependency graph remain separate. Draft / HOLD_NO_GO / DENY_ALL.
