# V8 sandbox allocator initialization qualification

This Draft addresses the original Windows failure on source
`1ef3216ffb86271d87e6aea049ce7ca7f2b76809`, run 41685992806, job
126096184676. The original PoC, code-mode runtime and code-mode host test
targets abort in `PartitionAddressSpace::InitConfigurablePool` because the
configurable pool is already initialized. The original PoC sandbox-feature
assertion also fails. The complete original job log is retained losslessly.

## Source analysis and change

The committed Rusty V8 150.4.0 crate archive was verified against its Cargo
checksum. Its `ArrayBuffer::Allocator::NewDefaultAllocator` constructs a
wrapper around the default isolate group's sandbox allocator. That wrapper
stores group-owned pointers; destroying the wrapper does not destroy the
backend. The PartitionAlloc-backed backend's `LazyInitialize` checks and
assigns its implementation without synchronization. Its constructor
initializes the configurable pool, whose original assertion rejects a
second initialization. The other sandbox backend has a mutex and is not
the basis of this analysis.

Concurrent first construction is therefore a source-supported explanation
for the observed Windows failure. The fix constructs and drops one default
allocator inside the existing process-wide `OnceLock`, after V8 is
initialized and before that completed state is published to isolate
threads. The PoC uses the same ordering inside its existing `Once`.
The existing JIT choice, sandbox policy, allocation backend and isolate
concurrency remain unchanged.

The two MSVC prebuilt libraries selected in `MODULE.bazel` already enable
the sandbox. The PoC's `sandbox` crate feature now reflects those existing
libraries on MSVC as well as the other platforms. The original assertion
continues to check the feature against the linked V8 library.

The added regression starts 16 concurrent first-use isolates and checks
that each complete result preserves its own array-buffer contents. The
hosted qualifier first runs that test alone in a fresh process, then runs
the complete original three consumer unit targets without exclusions.
All six pre-existing PoC tests and their assertions are unchanged.

## Actual local evidence

- The repository's original `just test --locked -p codex-v8-poc --features
  sandbox` passed all 7 tests with zero skipped tests.
- The original complete runtime and host package command executed 153
  tests: 152 passed, one failed, zero skipped. The remaining test cannot
  create a Unix socket in this local execution environment. An independent
  socket prerequisite probe also received `EPERM` before any product code
  ran. The complete failure is retained; this run is not reported as a
  complete pass.
- The scoped original `just fix` for the two changed crates passed. It did
  not introduce additional source changes. Original formatting and the
  unchanged workflow, spelling and blob-size checks are also recorded.
- The original default upstream V8 download returned 404. The local run
  instead used the repository's existing official artifact-fetch logic,
  verifying the exact OpenAI release archive and binding pair against the
  original checksum manifest and independent GitHub asset digests.
  No mirror layout or unverified binding substitution was used.

`local-evidence.zip` retains complete original command output, failed
prerequisite attempts, the actual package and artifact identities, the
upstream source-file hashes, and the independent review. The manifest
records every member and both original archive hashes. Nine actual test
binaries were hashed before this task's regenerable compiler cache was
removed after compilation finished; original sources and evidence remain.

## Required hosted validation

The qualifier uses the repository's original authenticated Bazel wrapper
and unchanged 30-minute budget on native Windows MSVC and Linux runners.
Windows retains the original MSVC host/target selection, SDK environment
and argument transport. It first runs the fresh-process parallel test,
then all original PoC/runtime/host unit tests, including the original
sandbox assertions, followed by the original Clippy selector and all
three test binaries. The original selector includes the runtime and host;
it intentionally excludes the PoC. The qualifier preserves that selector
contract and explicitly checks the PoC binary in addition. The Linux job
also checks the committed lock first.
All committed inputs are hashed before and after; complete output and test
XML are retained even on failure.

The first Windows qualifier at `84424d4a35153aa5ab5b1cc778e2e80be6d411e4`,
run 41702757767, job 126150033271, failed before Bazel or the tests started.
Python resolved unqualified `bash` to the system WSL launcher; its original
UTF-16LE output reports that no Linux distribution is installed. The
command exited 1 after 0.063 seconds. `launcher-844-negative.zip` preserves
the complete original artifact, and `launcher-844-negative.json` records
the artifact, output and immutable Git-input verification. The workflow
now passes its executing Git Bash as a native absolute path. It does not
install or use WSL. The original wrapper and native MSVC configuration
remain unchanged.

Actual Windows and Linux hosted test results are pending. Local success and
static review do not establish that the original Windows crash is closed.
The source remains Draft / HOLD_NO_GO / DENY_ALL. Full required CI,
unrelated Windows failures, performance and scientific obligations, and
source-history and Library-clearance gates remain independent.
