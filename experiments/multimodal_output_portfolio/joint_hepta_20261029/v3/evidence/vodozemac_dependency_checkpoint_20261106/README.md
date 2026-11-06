# Vodozemac dependency recipe checkpoint

This package retains a failed GitHub Actions proposal and a separate local Linux experiment. The original Cargo update generated three extra dependency rebindings, and the unchanged full graph guard rejected it. The original ZIP, job log and API metadata remain intact.

The local experiment used the official Cargo 1.96 binary in an isolated complete checkout and cache. It reproduced the failed GitHub lock byte for byte, then used precise same-version updates for the already present itertools 0.14.0 and getrandom 0.3.4 packages. The original graph guard passed after both complete cycles, and the final locks matched byte for byte. Only the vodozemac patch version and the three previously reviewed zeroize edges differ from the baseline. No manifest was changed.

Unit 21 contains the three-file source proposal for this recipe. Its GitHub qualification is pending at this checkpoint. The local experiment did not execute Bazel generation or cargo-deny and does not replace the original workflow or complete product CI.

Run `python restore.py /absolute/path/to/new-empty-directory` to recover the evidence. The reader checks its fixed index, every independent gzip member, the complete compressed archive and each regular file before writing anything. It refuses an existing destination and restores inert 0644 files. It never executes archived source. Each compressed blob is at most 450000 bytes.

The INDEX records original SHA-256, Git blob identities and modes. The original failed ZIP has SHA-256 `7c667068738abf1f10022496f7814b9e0edca34f2a26c43e97adf39e5b5c700f`; its extracted payload inventory was independently verified before packaging. Exact official Cargo and crate source identities explain the resolver mechanism without accepting any additional graph allowance.
