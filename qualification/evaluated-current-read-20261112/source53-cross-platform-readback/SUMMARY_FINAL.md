# Exact source53 cross-platform readback

Source53b3227a8dff5af9e39ecef6356cfce702d80b1c, tree10cb49cee9c3ca8ed280a680fb262c7e7ce549a1. Original synthetic checkout7302b0d4d0cd9335c9c505db7995689e8dc9f9c8 has that same tree.

All nine assigned jobs are terminal. Nine complete raw logs contain 6954814 bytes in 34 contiguous parts, independently read back from Git. This is not the whole native suite or overall qualification.

| Job | Outcome | Evidence boundary |
| --- | --- | --- |
| Fence/blob policy | success | v0.13 audit healthy; protection_available=false, observation-only |
| Windows native-path wrappers | success | 48 wrapper tests, not full Rust methods |
| Windows release | success | 1047 build targets /5500 actions |
| Windows Clippy | success | 6915 actions, no method claim |
| Windows shard1 | failure | exec_process2 pass/1 fail/21 ignored; legacy refusal |
| Windows shard2 | failure | Windows sandbox14 unique failed methods, CLI1, app-server2 |
| Windows shard3 | failure | one TUI method,3 original attempts; ordinary vs verbatim Windows path |
| Windows shard4 | failure | filesystem17 and core3 unique failed methods |
| Mac Intel | failure | matrix restart1, supervisord1, app-server2; neuron target PASSED252.6s |

Bazel target totals include cache hits. Original flaky retries are not independent samples. Mac ARM jobs were cancelled before method evidence; Windows native-main was skipped. Successful Mac neuron target did not emit complete method stdout, so no independently observed209-method claim. Source84 timeout remains archived.

Windows legacy refusal is an unconditional original production guard, not an actual ACL measurement. Separate audit preserves positive capability OPEN; no Elevated/Disabled fallback or global ACL change.

INITIAL/PROGRESS artifacts remain historical. Current metadata snapshot20:35:59UTC. No CI/actor/native/Bazel dispatch, source change or reference update was performed.
