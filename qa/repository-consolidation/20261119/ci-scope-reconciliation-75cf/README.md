# Reconcile concurrent CI repairs

A fresh branch lease check observed remote 60e508e while the locally reviewed CI repair was still unreferenced. The remote was preserved as a real merge parent. Both changes contain the same exact-head concurrency identity. The remote selects main.rs, whose wrapper has the same 55 bytes and Git blob as codex.rs; Bazel uses Cargo-derived binary roots. The stronger local regression now checks that exact selected root.

The normal two-parent merge had two workflow conflicts. The resolved source tree equals an independently constructed overlay, and all 19 original test inputs match the 68/68 passing receipt with zero skips. The two prior repair audit directories and the remote round08 record remain unchanged. Native Cargo/Bazel qualification and all required GitHub checks remain to be observed on the final merge head. No main merge or branch deletion is implied.
