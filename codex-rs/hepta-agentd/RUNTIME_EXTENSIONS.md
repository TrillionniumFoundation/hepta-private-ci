# Optional runtime services and executable identity

`RuntimeTasks` is the public task host used by Agentd, not a second executor.
A composition owner supplies an admitted implementation through
`spawn_optional_service(name, factory, quarantine, retire)`. The factory receives
a child cancellation token. `retire_optional` stops admission, waits for the
service to drain and invokes its route-removal callback. Timeout is not a
successful retirement; failed owner callbacks still fence the host. The task
host never retries an unknown effect or issues a replacement generation.

A service owner must still use its canonical persistent store and its existing
handoff protocol. Stopping a future does not transfer writer ownership.
`AutomationStore::handoff_timer`, for example, advances the durable writer epoch
and leaves the successor draining until explicit resume. Every schedule-creation
path, including `create_task_from_operation`, checks that epoch inside the same
SQLite write transaction as the effect. Historical dedupe receipt replay remains
read-only after retirement. Uncommitted work cannot acquire a receipt from a
rejected old writer.

## Built-in executable observations

Agentd binds built-in implementation identity to the executable bytes plus the
module ID and manifest digest. `candidate_artifact_digest` identifies the
observed executable, not the manifest. The observation is bounded and cached once
per process; the runtime never substitutes a manifest or environment string if
reading the executable fails.

On Linux `/proc/self/exe` names the loaded image, including after unlink or path
replacement. Other targets explicitly report `ExecutablePath`, a weaker
observation that must not be treated as a kernel-attested loaded image. Neither
kind authenticates build provenance, independent review, selection or release.
Bootstrap's input/output port vectors still need concrete, versioned owner-port
bindings before they can be advertised as a general hot-replacement ABI. An
executable hash alone is not protocol compatibility.

## Running-service regression

From the repository root:

```sh
cargo test --locked --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-agentd --test optional_module_restart forty_first_service -- --nocapture
cargo test --locked --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-automation --test operation_timer_fence
cargo test --locked --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-agentd runtime_executable
```

The first test starts a forty-first optional service using the same public host,
executes real SQLite schedule mutations, injects a post-commit task panic and an
abrupt OS-process exit before acknowledgement, and reopens the owner in later
processes. Four same-schema replacements advance the actual writer epoch; stale
handles fail and exact requests retain the original dedupe receipt. Retirement
survives another process restart and rejects new schedule effects. Required
sibling services exchange real messages before and after optional lifecycle
changes.

The forty required services in this fixture are bounded echo services, **not
forty Codex sessions**. This test does not establish production App Server
integration, arbitrary cross-schema migration, multi-host handoff, a target-host
capacity limit, physical-effect completion, independent credential custody or
future-window learning efficacy. Those boundaries retain their own qualification.
No command definition or test source is a test-pass receipt.
