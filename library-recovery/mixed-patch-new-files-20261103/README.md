# Exact new files from original mixed patches

This inactive directory anchors 30 exact new-file source/build objects and 3 original license/notice objects. All 33 were already present in the target repository and freshly verified before tree reuse; no source payload was reuploaded. The 30 comprise 24 source/build files plus six JSON patch manifests read by concrete archived build scripts. Original paths, modes, zero-base hunks, Git index prefixes, parent fingerprints and line positions remain in the manifest.

A bounded parser accepts only a complete single new regular-file hunk, checks all added-line counts, validates the Git index prefix, preserves exact CR/LF bytes and requires an explicit no-newline marker when needed. The initial independent review found three malformed-input acceptance cases; their actual failures and the subsequent 14-case passing regression are retained. Re-parsing all five frozen original patches left all 212 reconstructed object identities and locations unchanged.

The complete original patches remain unsynchronized: binary blocks, existing-file modifications needing exact bases, and other non-source material are not covered by this projection. These 30 objects are outside the frozen 6116-candidate union and add zero to the formal 5887 verified count. Notices add no source count. No preserved code was executed, no patch applied, and no historical CI, scientific or production claim requalified.

The newly authored verify_sources.py checks bytes, optionally against SHA-named original patch files using --original-patches DIRECTORY. Original patch reads are bounded to 32 MiB total plus a one-byte overflow probe before refusal; no RSS bound is claimed. Optimized Python is refused. DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO remain; original deletion count is zero.

## Byte-preserving container

The 30 source/build objects are now stored as inert members of `source-custody.tar.gz`. `ARCHIVE_MANIFEST.json` binds every original path, mode, Git blob identity, SHA256 and byte count to the unchanged `SOURCE_MANIFEST.json`. The container also preserves all eight original control and notice files, including the original version of this README and verifier. All 38 member bytes match the source tree at commit aa37c2723e4856f5c251cc52721286ff8c48851c. The three notices remain directly visible at their original paths.

Run `python3 -B library-recovery/mixed-patch-new-files-20261103/verify_sources.py` from the repository root. The maintained verifier reads checked container bytes without extracting or executing them. Its existing optional `--original-patches DIRECTORY` mode still checks exact parent fingerprints, hunk locations, reconstructed bytes and extraction metadata using the unchanged bounded parser. The original parser qualification record remains a historical record; new parser regression tests exercise synthetic inputs only.

This storage change avoids treating historical fragments as active formatter inputs. It adds no Cargo manifest, formatter exception, source execution or new qualification. Original commits and all preserved source bytes remain available.
