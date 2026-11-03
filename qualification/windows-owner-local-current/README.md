# Windows owner-local transport on the dependency union

Status: **DRAFT / HOLD_NO_GO** until the exact committed successor completes the
original native and Bazel gates. This is one scoped stage of the remaining
Windows work; private state directory adapters, retained SQLite recovery,
Agentd integration and the full Windows CI remain separate open work.

Base: `0b9da54535a7795b2433947a479e6d9e71525e0a` from the real dependency union.
This preserves the actual Rust 1.96.0, Matrix 0.19.1, YAML, AWS, keyring, ZIP,
Fleet and adopted union Bazel lock changes.

## Source changes and provenance

The authenticated owner-local implementation is taken from the exact existing
PR #4712 source `c6f98ff2b5d6ae9056cdfe100a4494b8dbee9899`. Its opaque pending
stream exposes application I/O only after authentication. Windows uses the
actual named-pipe handle's protected DACL and owner SID, first-instance claim,
local clients only, a fixed handshake, identification-level client token check,
and mandatory synchronous restoration of the impersonating thread. The same
OS user remains the security boundary; this does not identify an executable
or grant authority to application requests. Existing generation, identity,
fence, frame, connection-capacity and deadline checks remain in place.

The same exact upstream tree also contains a necessary, small AF_UNIX
prerequisite: inspect the Windows rendezvous reparse entry with
`symlink_metadata`, plus the original close/unlink/rebind regression. Unix
behavior is unchanged. No general AF_UNIX peer identity support is invented
for Windows; its existing unsupported-identity test remains.

Only these relevant files and their actual Cargo edges are ported. No broad
common integration branch is imported. `upstream-source.json` records original
blob identities and candidate hashes. The independent review describes the
security scope and its limitations. The source size reflects reuse of this
existing implementation with its complete native negative tests; dropping
those tests merely to split the review would remove necessary qualification.

The Automation fixture now canonicalizes the directory it has just created
before persisting and reopening the historical database. All four original
checksum, migration and second-reopen cases remain intact. The production
canonical-path check is unchanged. The already integrated Fleet fixture change
is tested on Windows here without changing its production path check.

Actual Cargo resolution changes exactly one of 1,517 package records:
`codex-uds` gains existing `sha2 0.10.9` and `windows-sys 0.61.2` dependency
edges. No dependency version, checksum, advisory policy or capability is removed.

The actual repeated all-features `cargo deny` check against frozen database
`6c5fedf8ff03c485ed674d8f941e0180f3f72d70` exits zero with the original policy:
advisory, bans, license and source errors are all zero. The original 2/115/1/1
warnings remain. Scoped original `just fix -p codex-uds --locked --no-deps`
also exits zero and leaves all imported source bytes unchanged. These do not
substitute for native Windows execution.

## Evidence and current limits

The three retained upstream artifact ZIPs are exact GitHub artifact bytes,
verified against their API SHA-256 digest, size and ZIP CRC. They contain the
upstream source identity and original test logs: Windows 14 UDS + 31 Matrixd,
Linux and macOS 10 + 31, with no reported skips. Those results belong only to
the upstream Rust 1.95 source. They are not current-union acceptance.

The first local Rust 1.96 run compiled the narrow port and actually ran the
original UDS library suite before adding the pre-existing AF_UNIX prerequisite.
Its nine-case report was six reported passes and three failures with local
permission errors. Existing socket tests can return early on such errors, so
this is retained as a failed environment execution, not six verified identity
successes. The complete output and JUnit are retained in `local/`. No skip,
permission bypass or assertion change was added.

## Reproduce the current source

On each supported hosted runner, the qualification wrapper runs the actual
Rust 1.96 toolchain and locked production metadata, then every original
library test in `codex-uds`, `codex-hepta-matrixd`, `codex-hepta-fleet` and
`codex-hepta-automation`, using the original `just test` entry point. It keeps
the per-test watchdogs, disables retries, requires fresh complete JUnit, binds
the required original regression cases, retains successful test output, and
rejects existing runtime early-return messages. Linux builds and executes the
same pinned D-Bus client/identity prerequisite as the already qualified
Matrix owner workflow. Setup failures and its receipt are preserved.

```sh
python qualification/windows-owner-local-current/run_qualification.py native --output /absolute/new/output
```

The Bazel mode first runs the original committed-lock check, then the original
generation and check commands. It always retains the actual generated bytes.
A stale initial lock or any changed generated bytes keeps the run failed until
those exact bytes are committed and the checks are repeated. Only then does it
run the four original `*-unit-tests` targets. No lock facts are hand-written.

```sh
python qualification/windows-owner-local-current/run_qualification.py bazel --output /absolute/new/output
```

Before/after input snapshots, original command output, JUnit, exact generated
lock, toolchain identity and all failures are artifact outputs. Passing these
scoped gates does not imply the complete Windows suite, Matrix service
restoration, retained private-state recovery or production readiness.
