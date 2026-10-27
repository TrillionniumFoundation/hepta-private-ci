# zstd-sys 2.1 Windows patch compatibility

Run `40503203294`, Linux Bazel job `122187796472`, failed while applying the
existing Windows patch to `zstd-sys 2.1.2+zstd.1.5.7`. The new upstream source
already guards the visibility flag with `hide_symbols() && !target_is_msvc()`;
the old patch's visibility hunk therefore has no matching old context.

`patches/zstd-sys_2_1_windows_msvc_include_dirs.patch` adds the ten MSVC include
lines to the new cc backend and calls its existing target-environment helper.
The original patch remains byte-for-byte unchanged for the inactive original
dependency graph. The new file is exported by `patches/BUILD.bazel`. Only the
generated candidate MODULE annotation should refer to the new patch.

## Actual checks

Both official crate archives were downloaded and reopened against the checksums
in their respective Cargo locks. The old patch applies to the old source and
rejects the new source; the new patch applies cleanly to the new source.

The source-bound diagnostic compiled 24 small host Rust executables containing
the exact old patched, new pristine, or new patched `build.rs`. A recording
`cc` substitute observes configuration calls without running a C compiler.
Across 192 executions, all eight combinations of `zdict_builder`, `legacy`, and
`seekable`, four target configurations, and both `ZSTD_SYS_NO_HIDE_SYMBOLS`
states were checked. Old and new patched include sequences match exactly.
Every new-upstream configuration call other than the intended MSVC includes
is unchanged. MSVC never receives `-fvisibility=hidden`; the new upstream
visibility opt-out remains effective for other targets.

The four target configurations are x86-64 MSVC, ARM64 MSVC, Windows GNU, and
Linux GNU. These are inputs to a host diagnostic, not actual cross-compilations.
No Windows C compilation, MSVC linker run, CMake execution, or repaired remote
Bazel qualification is claimed. Those gates retain their existing scope.

`HANDOFF.json` binds the original failed artifact, official source archives,
exact new patch, before/after source, and the configuration diagnostic receipt.
Full commands, 192 stdout/stderr records, trace executables, and source archives
remain under the task evidence directory named in that handoff. The former
failed remote output has not been replaced.
