# Original b054 Windows scoped-fix result

Original run43038376307/job130583219316 used harnessc97586834214c8a0a610f860cc7ae261ce8cccde against sourceb0547d2f874c0aeb54dabd3491caa2bee49fcb0b/tree3f89ddeff13d0af85f4abe2690699107357f1038. The original job failed.

All three just fix commands exited0. Neuron and core retained clean source. The Windows sandbox command rewrote exactly elevated_impl.rs and tests/helper_manifest.rs, so the strict unchanged-source check failed; collection retained its original partial_or_failed result. The third timeout_observed is null after the source validation error, while the first two explicitly record false. These are original lint/compile commands, with zero native test or model commands; no assertion, budget or refusal gate was relaxed.

The archive includes the original73486-byte artifact ZIP, all144 ZIP members, the complete80304-byte original job log, original jobs API and artifact metadata, every phase/source/tool/lock receipt, both exact original source files and actual postimages, and independent static peer review. The supplied fix-run-raw.json is the jobs endpoint response; no separate run-level API object is claimed. DOWNLOAD_INPUT.json and its signed download URL are excluded.

Run python3 records/verify_scoped_fix_original.py after extraction. The verifier checks every packaged byte, ZIP CRC and all144 members, the runner143-entry manifest, original raw payload equality, exact source/tool/lock identities, phase commands/exits/dirty states, and actual two-file patch replay. It starts no native/model/host execution. OFFLINE_AUDIT.json is its original deterministic result. The offline parser preparation error about false versus null timeout fields is preserved separately; it did not change original evidence.

The Clippy edits are static equivalence candidates: two same-method cancellation closure substitutions and one nested-if to short-circuit let-chain. Native delete-boundary and LEAK qualification remain separate. Formatting or future validation must bind a new exact source.
