# Secret Service zbus 6 migration

Production source comes from the official upstream proposal
https://github.com/open-source-cooperative/secret-service-rs/pull/122 at exact
commit `7a91b597904c1847f18a06b72a19ee8153e0a578`. The upstream proposal is still
unmerged. Its source uses version `6.0.0`, zbus 6's maintained names/wire types,
and the upstream `zruntime::block_on` blocking facade. The PR description predates
the retained blocking facade; the pinned code is the source of truth.

The reference registry package is `secret-service 5.2.0`, archive SHA-256
`5107b24b91445dd2aa449a258a1807b63240942157292354dc5bfdbeb8bc6db8`, matching
the original project Cargo.lock. Every original test name is retained. The two
plain/encrypted session tests deleted by upstream are restored with their exact
original AES-key assertions, calling the corresponding zbus 6 async entry point
through the same blocking executor. All 12 upstream-added tests are included.
The eight existing `#[ignore]` and two existing `no_env(GITHUB_ACTIONS)` marks
are preserved and reported separately; they are not counted as executed passes.

Upstream CI/mutation workflows are not imported. The project executes the full
vendor suites on a fresh private session bus with a real unlocked Gnome Keyring,
isolated XDG directories, serial test execution, and preserved raw results.
Original Secrets/Keyring/Login and all platform gates remain in force. The
root Bazel alias points to `@crates//:secret-service-6.0.0`, the native rules_rs
library generated from this excluded local path patch. Its resolved dependencies,
version and `crypto-rust` feature are checked in cloud before the real build.
No DBus tests are added to platforms on which a session Secret Service is
unavailable; the registry crate had no project-owned Bazel unit-test target either.

Source, examples, README, notes, changelog and both MIT/Apache licenses are
preserved. The isolated harness generates its lock in cloud and verifies its
normal dependency resolutions against the actual production graph. No local
Rust build or native test execution is claimed. This candidate still needs
exact-head original security/platform qualification after generated locks and
formatting postimages are committed.
