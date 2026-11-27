# Admit a dedicated paired-process child executable

The two Unix product scenarios previously installed their entire current
libtest executable as both agentd and matrixd. The release catalog copies and
hashes the admitted executable and revalidates it on subsequent resolution.
The retained Intel phase records localize substantial time to fixture setup
and release operations. They do not provide CPU measurements or prove that
hashing alone accounts for all of that interval.

This change moves the existing child-only functions into a private module
behind the explicit `hepta-paired-process-fixture` Cargo binary. The old ignored
`paired_child_process` libtest entry becomes that binary's Unix entrypoint;
its role selection and error handling are preserved. The agent/matrix socket,
request, lifecycle and response function bodies are unchanged. On non-Unix
targets the binary rejects execution, while the two product scenarios retain
their existing Unix-only compilation condition.

The parent resolves the executable through the existing `cargo_bin` helper,
canonicalizes it, and supplies that executable to the original release-bundle
installation. Both roles use empty arguments because libtest selection flags
are no longer needed. The installed program itself contains the child code;
there is no shell wrapper or external executable hidden in manifest arguments.
All original install, allow, resolve and complete-byte hash checks remain.

The two actual scenarios, their serialization lock, release ID, agent IDs,
generation/PID/adoption assertions, sockets, cleanup, configuration and every
existing wait or timeout remain. No TTL, retry, payload verification or
production supervisor behavior changes. Removing the ignored child harness
entry does not remove either product scenario.

`Cargo.toml` declares the new binary without changing dependencies. The
unchanged Bazel crate macro consumes generated `DEP_DATA` binary metadata,
creates the matching binary target, and puts it in integration-test data and
`CARGO_BIN_EXE_*`. Its source glob includes the private module. The metadata
and lock checks are recorded separately; generated files are never handwritten.
The existing release-only build sweep also compiles this new Rust target.
The existing Bazel macro additionally creates its usual binary unit-test
wrapper; this fixture module contains no unit tests. The paired product target
still contains the same two non-ignored product scenarios.

Preparation obtained successful offline Cargo metadata and an actual Bazel
loading query for the fixture and both native/cross test targets. Full
`just bazel-lock-update` was terminated twice with exit 137, including once with
a smaller metadata JVM heap; its cause is not established. Both original lock
files remain byte-identical. The successful narrow query is not a successful
full lock update. That required gate remains pending, with all original output
retained and no handwritten generated metadata.

One best-effort fixed-size stderr record per test process reports the original
libtest and fixture file lengths. Metadata or diagnostic-output errors do not
replace the test result. Its byte bound does not bound filesystem or stderr
latency. No ratio is asserted: the linker and normal qualification run must
establish actual binary sizes and any elapsed-time improvement.

Source formatting and metadata checks do not establish native success. No
fixture binary has been compiled or executed during this preparation. The next
normal native qualification must run the same two product scenarios and retain
their stage/size observations; the original cancelled and failed runs remain
part of the record.
