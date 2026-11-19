# c2d control source union: original audit evidence

This package preserves the original source proposals, exact input maps, commands, receipts, logs and JUnit files for the first c2d source layer. Its 50 source paths add the types, control-plane and cell-roles interfaces and retain the existing production refusal boundaries.

The final Linux run passed the original formatter, explicit checks for all 43 Rust files, the original three-package Clippy recipe and all 351 tests, with zero skips. All 13,678 input files remained unchanged during every final gate. The source baseline is tree 287374b63ee68a43d4aab7597eea5c90ea67195c. A separate receipt shows that the 50 preimages still match commit 60658ec54cf7f857197733fecf455ba44fecd3d4; this does not extend the native run to that later commit.

The earlier failures remain intact: missing Git/tool prerequisites, the seven failing rejection assertions against the original verifier, and the original Clippy run that changed nine files and therefore stopped input verification before tests. The same eight verifier regressions passed in the final complete package run. The unrelated in-memory role and checkpoint helpers do not acquire signed external evidence or production authority from these results.

Each carrier file is a complete gzip stream. The manifest records compressed and decoded hashes and maps every original path to its original byte content. Run python3 restore.py OUTPUT_DIRECTORY to validate all carriers, reconstruct the archive and restore every original file. The output directory must not already exist. Repeated original content is stored once and restored to each recorded path without changing any byte.

This evidence does not claim that the remaining c2d paths, its complete commit history, Windows execution, or the whole repository have passed or been merged.
