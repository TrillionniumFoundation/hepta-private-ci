# Native Linux ARM64 Synapse qualification

This is a separate Linux qualification of the existing
`real_synapse_dual_agentd_dual_matrixd_restart_and_isolation` integration test.
The macOS schema 8, its `required()` implementation and validators, the original
Mac shell runner, proxy, and business assertions remain unchanged. A Linux
receipt says `linux_exact` and `native-linux-arm64`. It does not qualify macOS,
Windows, dependency-policy acceptance, production activation, or an operator
approval.

## CI entry

The checkout must be the exact producer source commit, with this driver already
committed in that source. Download the candidate artifact from the same workflow
run and attempt. The producer supplies both expected hashes below. The entry
restores the candidate through the original port restore, dependency-policy,
graph, vendor, source, and lock checks; a host Rust installation is unnecessary.

```sh
env -u CARGO_PROFILE_DEV_DEBUG -u CARGO_PROFILE_TEST_DEBUG \
  python3 -I codex-rs/hepta-matrixd/tests/fixtures/run-hermetic-synapse-linux.py ci \
  --restored-root "$GITHUB_WORKSPACE" \
  --producer "$RUNNER_TEMP/ndu-port-candidate" \
  --producer-result-sha256 "$EXPECTED_RESULT_SHA256" \
  --source-commit "$EXPECTED_SOURCE" \
  --output "$RUNNER_TEMP/ndu-native-synapse" \
  --docker-socket /var/run/docker.sock
```

The output must be a new physical directory outside the checkout. The entry
creates `ndu-native-synapse-worktrees/preparation` and
`ndu-native-synapse-worktrees/qualification` beside the output directory. Each is
an independent worktree of a private qualification-only commit. Both commit trees
must equal an independent replay of the producer's complete candidate patch,
including Git file modes. The original restored checkout keeps its HEAD and
staged candidate. Neither qualification commit is a production commit.

The driver is loaded from exact HEAD bytes without Python bytecode caches or a
workspace entry on `sys.path`. The port helper is separately checked against its
HEAD Git blob before execution. Invalid paths, changed helpers, staged bytecode,
stdlib shadows, an extra candidate path, or an altered file mode cannot supply
execution authority.

## Preparation and tool authority

`preparation/` is explicitly online. It materializes these original immutable
ARM64 images; architecture emulation is rejected:

| Input | Immutable identity |
| --- | --- |
| Synapse | `matrixdotorg/synapse@sha256:467a587a5052dadd5d0bf1f8d89f043cc652d5201bca510307340f8dddb6b312` |
| Synapse ImageID | `sha256:d1292ef4b8d934a5b2acc9471eeabc53f718dd748cf10773454f401f678db784` |
| Rust 1.96.0 Bookworm ARM64 base | `docker.io/library/rust@sha256:05f85ef6eb0f2600ac62e9d779642b5b362d5be2ed67b80e162fae6e28b66524` |
| Rust base ImageID | `sha256:e1c74d1ab074f9e6696ae7b759e9c522b1517b32c5a30cc567b3f11f8c3e1be0` |

Native packages come from the fixed Debian snapshot `20261026T000000Z`.
Repository signatures remain required; the historical release validity-date
exception is recorded explicitly. The complete installed package versions,
downloaded package hashes, signed index hashes, Dockerfile and capture program
are retained. The derived local ImageID and its complete compressed image archive
are bound into `BUILDER_SEAL.json`. The archive is fully decompressed and hashed
again before its redundant uncompressed copy is removed. No upstream RepoDigest
is invented for this derived image.

The external bundle uses exactly just 1.51.0, nextest 0.9.103, and DotSlash 0.5.9
official ARM64 assets, with sizes and SHA-256 digests pinned in `prep_tools.py`.
The prep checks actual ELF architecture and executed versions. It resolves and
hashes the real compiler and native tools, requires Rust release 1.96.0 and commit
`ac68faa20c58cbccd01ee7208bf3b6e93a7d7f96`, and observes the complete Rust sysroot
and actual ELF library dependencies during the subsequent offline build.

`libcap-dev` and system `bubblewrap` are explicit snapshot packages. Their actual
pkg-config/version output and bubblewrap's required `--as-pid-1` and `--perms`
capabilities are checked. The image pins system bubblewrap bytes and libraries;
it does not fabricate a bundled bubblewrap digest or claim a sandbox operation
was exercised by a help/version probe. `linux-sandbox/build.rs` does not emit a
separate runtime resource. The independent `codex-bwrap` crate's build script
requires libcap for its own C executable.

The exact host Docker client is also executed inside the derived proxy image
without a socket or network, and its version must equal the sealed host client.
The Cargo seed is fetched with the candidate's exact lock and complete graph,
then all registry archives/indexes/git sources and file modes are inventoried.
No build or test runs in this online fetch phase. Missing tools, snapshot packages,
assets, or dependencies fail closed; there is no ambient-tool fallback.

## Offline build and execution

Build and business containers run as the non-root host UID with a read-only image,
no added effective capabilities, no-new-privileges, and no Docker socket/client
mount. Their network has only loopback. Actual mounts, process status, kernel,
daemon architecture, memory and free disk are recorded. The trusted external
controller and proxy sidecar possess broad Docker authority; their socket is
privileged fixture infrastructure, not a stronger product sandbox claim. Only
the proxy shares the business container's network namespace. It does not share
the product PID or mount namespace.

Two cold targets run sequentially. The first builds the real integration binary;
the second independently builds agentd and matrixd. Compiler JSON, each actual
executable, full test inventory and Cargo/nextest reuse metadata are preserved,
fsynced and reopened before deleting each regenerable target. This arrangement
does not claim two targets existed simultaneously. It reduces the peak storage
requirement of the standard ARM runner; actual resource feasibility still must be
established by the job.

The business execution uses the repository's actual `just test` entry, the
preserved metadata, an explicit target-directory remap, a fresh external nextest
store, an explicit profile, retries 0, and the exact original business case. The
complete binary inventory is retained; only the original business case may match.
The selected relocated path and its bytes must equal the frozen actual binary.
Metadata and executable identities are checked before and after execution.

The original fixed Synapse server runs on an internal network with no published
port, registration/federation disabled, and fresh synthetic credentials. The
unchanged original proxy supplies its loopback transport. The original business
test exercises both real agentd/matrixd pairs, encryption, restart, acknowledgement
loss, deduplication, isolation, pending approval and persistent state. Its
completion nonce, process history, release-copy observations and explicit shutdown
remain required. Provider outputs in this original integration test use its mock
SSE providers; this is not a live model-provider evaluation.

## Teardown and artifacts

`RESOURCE_OWNER.json` is written before the first owned resource is created.
Ordinary failures and catchable termination enter bounded cleanup. Discovery by
the unique random label covers a create operation that completed before its
Python return. Every object is checked for that ownership before removal. Keep
an `always()` step, conditional on `BOOTSTRAP_AUTHORITY.json` existing:

```sh
python3 -I codex-rs/hepta-matrixd/tests/fixtures/run-hermetic-synapse-linux.py cleanup-ci \
  --restored-root "$GITHUB_WORKSPACE" \
  --source-commit "$EXPECTED_SOURCE" \
  --output "$RUNNER_TEMP/ndu-native-synapse" \
  --docker-socket /var/run/docker.sock
```

Recovery writes `teardown-recovery-*/RESULT.json`, preserves the original failure,
and can only report `teardown_only_not_qualified`. A lost host/daemon, uncatchable
kill, or cancelled workflow that cannot run its always step cannot be reported as
successful teardown. This limitation is not converted into a qualification pass.

Upload the whole output tree, including hidden files and failed attempts. Key
identities are `BOOTSTRAP_AUTHORITY.json`, `restore/RESTORED_SOURCE.json`,
`preparation/{PREPARATION_RESULT,BUILDER_SEAL}.json`, the image archive, full seed,
`qualification/source/SOURCE_SEAL.json`, `qualification/build/BUILD_RESULT.json`,
actual frozen binaries, compiler JSON, command logs, runtime INPUTS/JUnit/completion,
`qualification/TEARDOWN.json`, and `CI_RESULT.json`.

Only `CI_RESULT.status == "qualified_native_linux_arm64_only"`, supported by the
exact source, actual build, actual single-test pass and complete owned-resource
teardown, closes this Linux business-qualification gate. Local Python checks or a
reuse-only binary probe do not produce that status.
