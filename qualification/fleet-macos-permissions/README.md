# Fleet immutable publication on the actual platforms

The original macOS ARM run at `c7629f5366434bc146ef961b873d2babe79e93aa`
failed one workspace canonical-path fixture and four release tests with EACCES.
The diagnostic source `da7223bcd8a9d4e0a207c4d07a6a379694db1773` kept those
production files byte-identical and ran the actual operations on macOS 15.8.2,
ARM64, as ordinary uid 501 with both official Rust 1.95 and 1.96.

## Observed cause and retained negative evidence

Both compilers produced the same result. Copying a readonly program, chmod,
flushing the retained writing handle, and syncing readonly files/directories
all succeeded. A same-parent rename of the directory after mode 0555 failed
with errno 13. The full traced original publication sequence stopped at that
same rename. The temp path also actually differed from its canonical path:
`/var/folders/...` resolved through `/private/var/folders/...`.

`hosted-da7223bc/macos-baseline.zip` retains the exact original artifact;
`VERIFIED.json` records its size/digest/CRC check and 81 inputs independently
reread from the exact Git source. The initial full-suite command did not run
tests because this wrapper duplicated `--no-fail-fast`, already supplied by
`scripts/run-nextest.py`. That failure is preserved. The corrected wrapper
leaves the original runner's option intact and does not supply it twice.

## Candidate change

Unix creates the staging directory atomically with mode 0700. On macOS the
publisher holds an open directory handle before rename, renames while the root
is still private and writable, then seals that same inode to 0555 and syncs it
through the retained handle. The original parent-directory sync still runs.
Other platforms keep the existing seal-before-rename order. Executables, bin,
manifest, byte hashes, and closed-world validation retain their original checks.

Catalog admission rejects the writable root during this interval. A new original
crate regression models interruption before sealing, reopens the registry, and
proves both resolution and first allowance creation fail without an allowance
marker. Sealing the unchanged data then permits the original exact release.
This is a state-based regression, not injected kernel-failure testing. A failure
after rename still returns an error and can leave a final directory requiring
administrator repair; automatic retry and complete crash recovery are not claimed.

The workspace-sweep fixture canonicalizes each directory it has just created,
matching the existing workspace API requirement. Production path validation is
unchanged.

## Exact current-source qualification

Ordinary unprivileged Linux and macOS runners compile the exact current production
copy, chmod, sync and publication functions into a small standard-library-only
probe under Rust 1.95 and 1.96. The old readonly-rename sequence remains an explicit
diagnostic counterexample. The actual candidate publication operation must succeed
and leave mode 0555 under both compilers.

The same job runs the original complete `codex-hepta-fleet` library suite through
`just test`, including all five originally failing cases and the new interruption
case. Fresh JUnit must contain at least 42 tests, all required names, and zero
failed or skipped cases. Inputs are hashed before and after execution. No original
assertion, access check or durability error is suppressed.

**DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO.** Current-source macOS and Linux
results and the original full CI remain required. The probe observations do not
establish full Fleet or paired-host acceptance.
