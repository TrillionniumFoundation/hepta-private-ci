# Complete private registration and retained owner qualification

This qualification operates on the exact composed-source commit after its original generation job reports `committed-lock-qualified`. The caller retains the first committed lock check, actual Cargo/Bazel generation, and unchanged-source requirement. The reusable workflow does not activate native jobs on the isolated reader-controls branch.

## Original test groups

| Group | Complete Cargo libraries | Native hosts | Existing job limit |
| --- | --- | --- | --- |
| path-fleet | codex-utils-path, codex-hepta-fleet | Windows 2025, Ubuntu 24.04, macOS 15 | 30 minutes |
| agentd | codex-hepta-agentd | Windows 2025, Ubuntu 24.04, macOS 15 | 80 minutes |
| retained-memory | codex-utils-path, codex-state, codex-hepta-memory | Windows 2025, Ubuntu 24.04, macOS 15 | 30 minutes |

The Path library is intentionally present in both original owner groups; its repeat executions must not be presented as additional distinct tests. The retained-memory group preserves the original Path/State/Memory scope and seven named ignored controls. Its current schema 16/17 cases are determined from the newly compiled inventory. No historical case count or old schema-15 result is substituted.

The native reader retains the exact inventory, JUnit, failure-detail and duplicate-key functions from the independently qualified Memory source `296e88630b132f05b623f4391c1bbbdeaf79449c`. It runs each original `just test --locked -p PACKAGE --lib --no-tests=fail --retries 0 --success-output=final` with default features and the original local profile and 8 MiB stack. Agentd's default product feature remains production-cognitive-write; all-features and qualification-only features are not substituted. All executable inventory names must occur exactly once in fresh JUnit, with no failure, skip or retry. The original scoped `just fix --locked ... --no-deps` and source stability checks remain required.

Windows additionally requires the exact four new creation cases and all five original Agentd failure identities. These are membership requirements inside the full compiled inventory, not filters. The existing Memory recovery controls remain required. On Linux, Agentd first builds and executes the existing pinned D-Bus client, binds its archive/identity/pc bytes before and after use, and supplies the same PKG_CONFIG_PATH used by the maintained YAML consumers.

## Original Bazel coverage

Linux runs two original three-target groups: Path/Fleet/Agentd and Path/State/Memory. Every original target, complete --list inventory, ignored inventory, report file, XML wrapper, original result summary, and scoped Clippy target is required. State retains four shards and the existing FNV partition rule. Sharding is disabled only for listing, as required by Bazel run. The test command retains original sharding and time budgets.

The reader is Linux-only. The Windows Agentd wrapper emits multiple legitimate batches in a single test.log; this reader is not claimed to validate that different format. Windows coverage here comes from actual original Cargo libraries. The complete original Windows Bazel job remains a separate gate.

## Evidence and boundaries

Every tracked input is bound to its Git mode and blob, including symlink target bytes. Logs, compiled inventories, binary hashes, fresh JUnit and all failures are retained. The original 24 reader controls are preserved, and four added controls exercise exact Windows-case coverage and group preservation. These controls are reader tests, not product executions.

The isolated diagnostic branch executes only the 28 reader controls, optimized-Python rejection checks and exact-release actionlint 1.7.12 validation of the two workflow files. A passing reader job cannot enable product work there. Native and Bazel jobs run only through the composed generation caller on its fixed integration branch after the unchanged committed-lock gate.

DRAFT/HOLD remains in force. Successful component evidence does not close unrelated original full CI failures or authorize product activation.
