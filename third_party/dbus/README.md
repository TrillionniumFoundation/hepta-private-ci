# Hermetic D-Bus client library

`libdbus-sys` uses the pinned D-Bus 1.16.2 client library from
<https://dbus.freedesktop.org/releases/dbus/dbus-1.16.2.tar.xz>.
`MODULE.bazel` verifies SHA-256
`0ba2a1a4b16afe7bceb2c07e9ce99a8c2c3508e5dec290dbb643384bd6beb7e2`.

The 47 C sources match the upstream `dbus/meson.build` client, shared and
Unix source lists. Bazel's registered C toolchain compiles them and passes
the resulting `CcInfo` through the `libdbus-sys` annotation. Its pkg-config
build script is unnecessary because the native dependency is explicit.
No host library directories or pkg-config results are accepted, and the
crate's older bundled D-Bus 1.14.4 is not compiled.

The configuration supports Linux x86_64 and aarch64 with LP64 glibc or musl.
Other operating systems are incompatible with this target, and the ABI
header rejects unsupported CPU/word-size combinations. Windows and macOS
use their existing native keyring backends.

The client keeps argument checks, assertions, Unix descriptor passing,
peer credentials, monotonic waits and kernel randomness. It does not build
a daemon, privileged helper or X11 launcher. Optional integration with
systemd and X11 autolaunch is disabled; an explicit session bus address or
the standard user-runtime bus socket must be available for Secret Service.
Paths in `config.h` are runtime D-Bus defaults, not build-machine search
paths. `/etc/machine-id` fallback remains in upstream `dbus-sysdeps-unix.c`.
The Linux syscall numbers for `pidfd_open` and `close_range` are supplied
when absent from older toolchain headers; they are identical on the two
supported architectures. `close_range.patch` gives upstream's internal
syscall wrapper a private name so it also compiles with newer libc headers
that already declare `close_range`. Kernel failures retain upstream's
fallback behavior. See the Linux v6.18
[x86_64 syscall table](https://github.com/torvalds/linux/blob/v6.18/arch/x86/entry/syscalls/syscall_64.tbl),
[generic syscall table](https://github.com/torvalds/linux/blob/v6.18/include/uapi/asm-generic/unistd.h)
and [close-range flags](https://github.com/torvalds/linux/blob/v6.18/include/uapi/linux/close_range.h).

Upstream `COPYING` offers AFL-2.1 or GPL-2.0-or-later and notes additional
permissive file-level terms. The complete original source and all its
copyright notices are retained in the fetched archive. `@dbus//:COPYING`
and `@dbus//:LICENSES/*.txt` expose the upstream license files, including
the additional TCL terms on `dbus-hash.c`. This is a native dependency and
its terms are separate from the Rust wrapper's license.

When upgrading, verify the archive hash, compare all three upstream source
lists and configuration macros, and build both the library and the actual
consumer's test executable. A library-only Rust build does not prove the
final native symbol link or a live Secret Service session.

```sh
bazel build //codex-rs/keyring-store:keyring-store
bazel test //third_party/dbus:native_identity_test
bazel test //codex-rs/keyring-store:keyring-store-unit-tests
```

The Rust test executable is a final-link check; in this configuration it
discovers zero Rust tests, so its successful exit is not behavior coverage.
A live isolated Secret Service test and each supported platform's required
CI remain separate gates.
The native identity test links the actual configured library and checks its
version, wire round-trip, live PID-file-descriptor resolution, rejection of
an ordinary descriptor by the PID resolver, and Unix socket
peer UID/PID. It requires a Linux kernel with `pidfd_open` and readable
`/proc/self/fdinfo`, and also checks high descriptor close-on-exec and
closure after reducing a child process's descriptor limit. Missing runtime
capabilities fail the test.
