# Observe the OS pipe after a failed CodeMode startup

## Evidence and scope

The retained Intel macOS qualification at source `97ab00451799667faebac2c455a1e3176ebc90cb`
reported 34 endpoint-startup failures across the four network integration targets.
Their failure context observed a running child and a pending single Tokio stderr
read. Tokio can return pending before attempting an OS read, so that observation
does not establish whether the OS pipe contained bytes. ARM counterparts and
Intel stdio results do not explain the failing child startup phase. The endpoint
is published before explicit session construction; no evidence establishes that
these children entered V8 initialization.

This change affects the Unix integration fixture's failure observation. The
original endpoint read, 10-second startup timeout, endpoint validation, one
child-status query, child ownership and kill-on-drop behavior remain unchanged.
The non-Unix observation remains the existing single Tokio poll.

## One nonblocking OS read

After the original startup has failed, borrow the captured stderr descriptor and
duplicate it with `AsFd::try_clone_to_owned`. Query `F_GETFL` on that exact
duplicate and refuse to read unless `O_NONBLOCK` is already present. The helper
does not change status flags, convert Tokio stderr through `into_owned_fd`, wait
for readiness, create a task, retry an interrupted read, or extend the timeout.

An owned `File` performs one `Read::read` into a 4,096-byte buffer. EOF, available
bytes, would-block, and other I/O failures have distinct outputs. A successful
read may be short. At most 1,024 source bytes are displayed with lossy UTF-8 and
debug escaping; the returned observation stays below 8,192 bytes. Every ordinary
return closes only the duplicate. The child-status query and pipe read are
sequential observations, not a common instantaneous snapshot.

The fixture exclusively borrows its captured stderr and has no concurrent
status-flag-changing alias. Checking flags is not an atomic guarantee against
another user changing the shared open file description. Bounded syscall count
and nonblocking read semantics are not a hard wall-clock scheduling guarantee.

## Controls and dependency qualification

Three Unix kernel-descriptor controls exercise refusal of a blocking descriptor
without consuming its queued bytes, would-block versus peer-closed EOF, and a
single read with an unconsumed remainder and bounded escaped output. Their
assertions accept a legal short read. The controls use fresh owned socket pairs;
only the controls set their own nonblocking flags.

`libc` is a Unix-only development dependency at the existing locked version
`0.2.186`. A real full Cargo metadata resolution produced 1,399 package records
and the Unix development edge. Its generated `Cargo.lock` changes only the host
package's dependency list by adding `libc`; no package identity or checksum
changes. The original offline failure from missing cached `aws-config 1.13.3`
metadata is retained separately. Public dependency acquisition then completed
under the same 60-second, two-CPU, 2-GiB and 64-task resolver limits, with automatic
network retries disabled. Neither stage compiled or ran Rust tests.

After applying that actual generated lock, `just bazel-lock-update` and
`just bazel-lock-check` both passed. `MODULE.bazel.lock` remained byte-identical.
An actual Bazel loading query independently confirmed all five integration
targets receive one `libc` edge in each of six Unix platform branches, with no
such edge on Windows or the default branch and no other dependency changes.
The first loading query against the old lock had no `libc` edge; that failed
dependency qualification is retained, rather than inferred from Cargo's
`--no-deps` output.

These checks establish dependency resolution and generated build-graph wiring.
This candidate still requires Rust compilation and native controls at its own
source revision. It is a diagnostic, not a claimed fix for the Intel startup
failure, and does not alter production binaries, execution budgets or guards.
