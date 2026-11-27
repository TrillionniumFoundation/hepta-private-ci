# v6 execution and fresh branch protection evidence

This archive retains the two completed local v6 runs and the branch protection snapshot captured on 2026-11-17 at 00:37 UTC. It contains 540 retained file paths backed by 311 distinct byte sequences. The 41 payload files are independent gzip streams, each smaller than 500,000 bytes. Original bytes and file permission modes are recorded in the compressed index.

## Execution scope

The source was commit 2ba689204e95d8032415205af8ecba67cf333ea8, tree bbbe2a18e09f3a72ddc8b33c63f75c2d616e9815. All 13,751 selected source and configuration inputs remained unchanged. The first run executed 12 original Bash steps and retained explicit receipts for the five setup or build steps completed earlier or represented by local initialization. It produced 17 successful command receipts, 102 passing Python tests, a finite Oracle result covering 128 cases and 803 stopping paths, and 56 complete smoke rows with eight native receipts. The smoke command used 163.250 seconds of its original 900 second budget.

The first native execution used cargo-nextest 0.9.137. The separate exact tool check used the official pinned cargo-nextest 0.9.103 distribution, verified against the release API digest and the official checksum file. Its six original nextest steps produced 12 successful command receipts and 552 passing test executions. The executed test identities and outcomes match the first run. Original ignored or filtered cases remain explicit in the individual step summaries: six, four and two respectively. No scientific smoke or Oracle command was repeated for this tool check. The original 249 evidence files and all 135 copied input artifacts remained byte identical.

The local kernel retained kernel.apparmor_restrict_unprivileged_userns=1; the hosted workflow setup writes zero. This archive does not claim equivalence with a hosted GitHub runner. It does not qualify later source overlays or re-sign historical calibration or research efficacy. Original launcher failures and their narrow corrections remain included.

## Branch protection scope

The snapshot has 7,335 branch heads and 104 protected new HIA heads. It records 17 new protected names, the independently advancing HIA union head, and the known integration publication. Main remained 732e934ba496d90fbe042b8d41d479ef901643e5. The complete ref snapshot, all 18 immutable commit responses and the protection proof are retained. Candidate 652dd6d7e0d4257170ea0017f2aba5a8b64173bc covers 1,835 of the 7,230 original eligible heads, leaving 5,395. Its current, prior and original protected heads and both protected markers have no ancestry intersection. The single parent bridge to 65b50f809e0cf159a867af992228ff4fab34f560 adds no incoming branch ancestry. Twenty legacy names containing HIA remain distinguished from the protected new family.

## Restore and verify

Run python restore.py /absolute/path/to/a/new-directory from this archive. The destination must not exist. The restorer requires POSIX file modes and O_NOFOLLOW. It checks the pinned index checksum, every gzip chunk, the complete payload, each SHA256 and Git blob identity, and every restored permission mode. It creates files only, does not execute archived source, and does not download external data. The retained restoration-receipt.json records an actual complete restoration and independent comparison with the source files.

The raw index SHA256 is f6875fd1dcf01837ad0a860abab69cbce9e17aea8e36b51cbdc3e43451d91845. Its gzip SHA256 is adf6da648c5c39a2b4f9d4f79ac2667c4f961f62e11e8529782e8fd77ae96cca. The decompressed unique-content payload is 19381042 bytes with SHA256 5a4a4a528354bcd1919e9b868d98012560fc70865d09e2ee5eea85e9407d75f2.

## Explicit exclusions

There are 12 excluded file paths. These are only the four original MNIST compressed downloads in each run, the captured rollout executable in each run, and the downloaded official nextest archive and extracted executable. Their exact paths, modes, lengths, SHA256 values and recovery sources remain in the index. MNIST entries also retain the registered MD5 values. A rebuilt rollout is not assumed byte identical; its original build command, complete input identity and qualified binary hash are retained. The official nextest release response and download verification receipts are included.

All generated model weights, rows, observer files, native receipts and consumer outputs inside the completed run directories are included. The validation checkout, native target directory, Python environment and package caches are outside this archive.

## Formatter correction

The explicit repository-locked Ruff 0.15.13 check initially required formatting of the archive restore helper. Version two changes only its layout: the complete Python AST is unchanged. Both Ruff format --check and Ruff check --diff pass. All 540 retained files were restored again with their exact original bytes and modes. The original helper, failed format check, first restoration receipt and the correction proof are retained in formatter-proof.json.gz. The original 45-entry publication manifest and its source files remain unchanged. This additional helper check does not claim execution of the complete repository formatter.
