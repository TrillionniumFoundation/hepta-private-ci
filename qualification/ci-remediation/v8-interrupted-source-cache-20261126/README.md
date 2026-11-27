# Retaining interrupted V8 source-build caches

## Actual failure and inspected contracts

At source `97ab00451799667faebac2c455a1e3176ebc90cb`, the two Windows V8
source jobs reached their original 30-minute job limit while Ninja was still
compiling. The retained logs end at 1787/4431 ARM64 and 1449/2421 x64 actions.
These are progress counters, not completed build or test results. The exact
and prefix cache lookups missed; the later read-only cache inventory contained
no matching entries. A cache miss by itself is not a configuration defect.

The pinned `actions/cache` commit `668228422ae6a00e4ad889ee87cd7109ec5666a7`
saves its combined action only on `success()`. Its standalone save action can
archive an existing partial directory, but does not verify compilation. Cache
entries are immutable: saving partial progress under the original fixed key
would prevent later progress from replacing it.

The actual runner version was 2.338.2, source
`d1eb12d4b115c301201de27d667284e1a80f2ab5`. Its StepsRunner distinguishes a
step timeout from a canceled job: a step timeout records failure while the
job can continue to an eligible cleanup step. Overall job cancellation still
ends the available budget. Its process cleanup is best effort; a successful
cache action alone is not proof that a usable archive was finalized.

## Candidate behavior

The job limit stays 30 minutes. This proposal explicitly reduces the source
compile step to 20 minutes. After the original staging, smoke and artifact
steps have passed or been skipped due to the build failure, it allows at most
one minute to stop the owned sccache server and check for remaining compiler
processes, and at most three minutes for one cache-save step. The observed setup portions were about 3:35
and 4:37, but future setup or upload durations are not guaranteed. No new run,
retry, compiler parallelism, runner, or extra job is introduced.

The original build command, Rust 1.91.0, sandbox feature, targets, NUM_JOBS
policy, and 256 MiB sccache limit are unchanged. A failed or timed-out build
remains failed; no continue-on-error masks it. Staging, Cargo smoke linking,
artifact upload and the final source check keep their original conditions.
The cache steps do not run after a job cancellation. If compiler processes
remain or sccache cannot be stopped successfully, saving is skipped. The one
process enumeration fails closed on errors; it filters the resulting process
names without printing other processes.

Restore and save use the same pinned action source. A new namespace binds the
upstream commit, recursive submodule status, upstream lock and build script,
Rust compiler identity, hosted image OS/version, workflow and setup action.
Target, runner label and sandbox variant remain explicit. Each normal run and
attempt saves under a new immutable key; fallback is limited to that complete
compatibility prefix. The old prefix that omitted the source hash is not used.
No source checkout or input modification time is rewritten to manufacture a hit.

## Limits and required evidence

Only the existing sccache and GN output paths are retained. A cache is an
untrusted build optimization, not a qualified release pair. Ninja may rebuild
objects because fresh checkout or tool timestamps changed; the fixed sccache
capacity may evict entries. Progress is not asserted to be monotonic across
runs. A directory archive is not an atomic snapshot or a proof of every possible
writer's absence. The stopped-process check supplements the runner's cleanup.

Compression, upload or finalization can exceed the reserved time or fail.
The pinned save action can also exit successfully with only a warning. A later
qualification must retain the actual saved key and restore key, source/image
identity, compiler outcome and original stage/smoke results; a green save step
or cache hit alone is insufficient. The full source build and existing smoke
gate must pass on the resulting source before this lane is qualified.

This is a source proposal only. No new V8 build, cache save/restore, workflow
dispatch or public ref update was performed to prepare it. The original timed
out jobs and their raw logs remain failed evidence.
