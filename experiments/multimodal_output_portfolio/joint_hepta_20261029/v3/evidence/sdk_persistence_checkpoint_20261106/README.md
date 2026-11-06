# SDK persistence evidence checkpoint

This package preserves 75 files and 1,357,955 original bytes in 1 independently wrapped binary gzip parts. Every part is at most 450,000 bytes.

Run `python -B restore.py /absolute/path/to/a-new-directory` with Python 3.12 or later. The destination must not exist. The reader verifies its fixed index, bounded gzip segments, complete archive hashes, canonical paths, exact membership and every file before writing inert 0644 regular files. No restored source executes.

Fixed INDEX SHA-256: `02e2640d255b6402334472dc4ab2127b47c19622b77be340b52d3425747e9390`. The reader logic is the published native checkpoint reader; only its index seal differs. Its original bytes and provenance are retained.

After restoration, read `round3_native/SDK_CHECKPOINT_HISTORY.md`. It distinguishes the frozen durable-publication candidate, corrected Unix relative-parent probe, unbound lock proposal, later safe test diagnostics and the actual Windows persist-stage failure. The original proposal still requires a new source amendment for the later SDK preimage.

No generated SDK lock, owning SDK compilation, Windows persistence fix, crash durability, full repository pass or new scientific efficacy is claimed. Archive verification is evidence custody only. Internal review is not external audit.
