# Actual build-script qualification after the first native probe

The first Windows probe at `051be3cda3aad7a145830884a45999f2e549278f`
failed before compiling C: its isolated dependency disabled the default
`libsqlite3-sys` features, leaving `pkg_config` and `vcpkg` unavailable to
the real upstream build script. That observation remains a failed build with
zero native cases executed.

The corrected probe source is
`41af7ab4d29018d46d2052b4790dd0347e02f356`. Its seven SQLite features and
five pinned build dependencies match the production selection. A separate,
single-job Linux check used this actual locked probe graph and selected the
actual vendored `libsqlite3-sys` library. It did not modify or compile the
Windows-only probe entry point, replace the build script, or use fake bindings.

Command: `cargo check --manifest-path <native-probe/Cargo.toml> -p libsqlite3-sys --lib --locked --offline`.

Observed on 2026-11-24 with Rust 1.96: exit 0 in 9.299 seconds. Cargo actually
compiled `find-msvc-tools`, `shlex`, `cc`, `pkg-config`, `vcpkg`, and the vendored
library. The build generated a 3,175,194-byte Linux SQLite archive. The attached
receipt pins the command, log, archive and ten source/manifest/lock inputs;
all ten input hashes were unchanged after execution.

This closes the observed missing-build-dependency error for the corrected
graph on the Linux host. It does **not** compile the Windows-specific owner
VFS branches, link a Windows binary, execute any of the eight native cases,
or qualify the SQLx consumers. Those remain separate Windows CI requirements.
