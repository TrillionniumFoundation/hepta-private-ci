# Keyring synchronous provider candidate

Base: `4b1a326ec50c28e8803d390e81d2f03457cc7499` (i18n PR #4709).
This candidate remains **DRAFT / HOLD** until its real credential recovery,
native identity, generated Bazel lock, and original platform CI checks pass.
No advisory ignore, license allowance, existing acceptance assertion, or
application capability was removed or relaxed.

## Source and graph changes

The official keyring 3.6.3 archive is retained. Only the two manifests and the
two production Secret Service connection cfgs / incompatible-feature guard have
functional changes. Other Rust diffs result from the original `just fmt` import
and whitespace formatting. `vendor-files.json` records original and candidate
bytes; it does not claim that formatted files are byte-identical.

Both direct workspace consumers select the encrypted synchronous provider.
The Entry API, service/account/target lookup, macOS/Windows providers, and
official default-builder behavior are retained. The existing 3.6.3 persistent
builder creates an `SsCredential`; this change does not introduce a new
kernel-keyring caching implementation.

The minimal Cargo resolution removes 20 net packages, including the obsolete
zbus family. No retained package version or registry checksum is upgraded.
Some retained dependency lists lose unused feature edges or no longer need
version disambiguation; `lock-delta.json` records those changes exactly.
The same advisory database and unchanged policy must still be checked before
claiming any advisory closed.

Bazel receives the pinned D-Bus 1.16.2 client definition from the reviewed
historical source, rechecked against the official archive. Its 47 C sources match
the upstream client/shared/Unix lists. LP64 Linux x86_64/aarch64 guards, ordinary
argument checks/assertions, peer identity, FD passing, and kernel randomness
remain enabled. Native licenses are retained upstream; see `third_party/dbus`.

## Actual local results

- Original `just fmt` passed.
- Separate baseline and candidate binaries compiled the exact production
  `keyring-store/src/lib.rs` against the official old and patched new providers.
  No mock or provider override is used. The candidate was also rebuilt with
  the pinned 47-source D-Bus client; `ldd` confirms no dynamic host libdbus.
- The original C identity test compiled but **failed** at its pidfd identity
  assertion. This environment exposes an ancestor PID namespace in procfs:
  `fdinfo.Pid` differs from `getpid`, while the final `NSpid` component matches.
  The upstream resolver reads `Pid`. Later ordinary-FD, peer-identity, and
  high-FD assertions therefore did not execute. They are not counted passed.
- Real private Secret Service replay **could not start**: this environment
  rejects D-Bus local socket binding with `Operation not permitted`. Both the
  default session address and a private filesystem socket failed before any
  credential stage. No historical credential roundtrip is substituted.
- The original scoped `just test -p codex-secrets --locked --no-tests=fail
  --retries 0` passed: 15 tests, 0 skipped. Source hashes stayed unchanged
  through compilation and final formatting; actual log and JUnit are retained. The keyring library's zero-test
  configuration cannot establish credential behavior by itself.

## Reproduction and hosted checks

`build_pinned_client.py --output <new-directory>` verifies and unpacks the
official archive, compiles the same C inputs, builds a static client, and runs
the unchanged identity assertions. Any failed assertion exits nonzero.

`prepare_probes.py --official-crate <keyring-3.6.3.crate> --output <new-directory>`
checks the official checksum and prepares separate baseline/candidate builds.
It copies the exact production wrapper and records all candidate source hashes.
Build each manifest with Rust/Cargo 1.95 and set `PKG_CONFIG_PATH` to the pinned
client's `lib/pkgconfig` directory for the candidate.

`run_private_service.py` uses only fresh temporary XDG directories, a private
D-Bus address, synthetic credentials, and a real GNOME Secret Service. It checks
old writes, daemon restart/recovery, implicit runtime-directory bus discovery,
new updates readable by the old binary, deletion/NoEntry/account isolation,
encrypted sessions, and an explicit rejected-DH server with no plaintext retry.
Inputs must be unchanged before/after. The service fixture never accesses an
existing desktop session or changes the default credential builder.

The branch-scoped qualification workflow runs those same checks on a supported
Ubuntu host, preserves every failure, generates the real MODULE lock with
`just bazel-lock-update`, runs the original lock check, and builds/tests the
actual Bazel native and keyring targets. The generated lock must be adopted
and the original platform CI rerun; this supplemental job does not replace it.
