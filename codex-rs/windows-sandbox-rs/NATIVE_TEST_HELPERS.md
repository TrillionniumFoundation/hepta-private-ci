# Native sandbox test binaries and source identity

The original elevated functional case launches the actual setup and command
runner targets. A Cargo library-only test does not build those binaries, and its
test executable resides in `dev-small/deps`, outside the installed product's
bin/resources layout. Building only the library or placing an unrelated command
on PATH cannot qualify the real child process behavior.

`windows_real_test_helpers.py` builds both declared Cargo targets with the same
locked source, pinned native compiler and dedicated target directory as the
original test scope. It records executable/tool hashes and source before/after,
then exports the two exact `CARGO_BIN_EXE_*` test inputs. A separate always-run
after check verifies those same original files and source following the tests.
Build success grants no functional qualification. Original case output, environment
forwarding, actual exit code, scopes, deadlines and zero retries remain required.

Only `cfg(test)` calls with the actual current test executable use the existing
`codex-utils-cargo-bin` Cargo/Bazel resolver for these two fixed target names.
Synthetic path/layout regression probes retain the original resolver, and all
non-test installed-product lookup behavior is unchanged. Bazel uses the macro's
`unit_test_extra_binaries` contract to expose real runfiles and executable env
inputs; runtime data alone does not establish their paths.

This change does not relax legacy workspace or readonly refusal. Existing
ambient-ACL/parent-delete failures remain visible until real isolation and the
original assertions have been executed successfully. It does not change signer
authority, SSHSIG verification, the original 91-case driver or its scope file.

## Runner process lifetime

The transport retains the exact process handle and PID returned by
`CreateProcessWithLogonW`, through the entire startup handshake and both real
consumers: the unified-exec blocking reader and synchronous capture. The private
`RunnerProcess` owns the handle; it exposes no raw handle or process-writing port.
An IPC exit frame is published only after the real process is signaled and its
native exit code matches that frame. No new sleep, test timeout or retry is used.

EOF, protocol/error frames, startup failure and a dropped unconsumed transport
terminate and reap this owned runner. Ordinary error paths report cleanup errors;
Drop is a fallback for unwinding. Killing the owned runner also closes its existing
job handles; this does not add permission or loosen legacy isolation. The original
command timeout and cancellation IPC remain responsible for live commands.
During the native-exit interval, both real callers preserve cancellation. Their
existing cancel/kill path also sets a private atomic request; the blocking waiter
checks it at the capture writer's existing 50 ms responsiveness and terminates
and reaps its own retained process. This object exposes neither a raw handle nor
an arbitrary-process operation. The synchronous capture cancellation thread is
joined only after real exit, including failure/cancellation. A natural-exit race
with TerminateProcess is accepted only after the same retained handle is signaled.

The original native run378 reported the elevated case as **LEAK**, even though its
functional assertions succeeded. Retaining and reaping the process addresses a
real early-exit lifecycle gap, but local cross compilation does not establish that
this fixes that native result. The exact original case must be rerun against the
new clean source before reporting functional PASS.
