# Synchronizing the cancelled resident Admit test

The test aborts an Admit queued behind a blocked Tokio worker. It requires zero bytes at the peer, an empty client channel and a subsequent readback rejected with `Unavailable`. The production exchange takes the lane permit before inspecting the channel. The blocking closure holds that permit throughout its scope. Closing its already-taken channel can wake the peer while the closure still holds the permit.

In the original observation the same assert ran once in each of ten fresh processes. The diagnostic recorded the error returned by that readback. Five processes returned `QueueFull` and failed. The other five returned `Unavailable` and passed. The ten subprocesses together took 0.354657 s. [Original observation](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45134423798/job/137557170681)

The adjusted test first observes the original cancellation, zero frame bytes and empty channel. It then takes and drops the lane permit with a two-second timeout before checking the original exact `Unavailable` assertion. The solo test client has no other pending caller. The old cancellation, I/O, timing and rejection assertions all remain, and a lane that never releases now fails explicitly. The production transport is the same Git blob `40b744877e6e3a0e02dea0fdc9fffb8859eefdf7` on all four source trees.

| Program tree | Identical test change |
|---|---|
| [e3277e96](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/e3277e9677688be5c4c235a7a127f0b51e373399) | [3002afb8](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/3002afb8e319abd7909e57ac816b0fedc8f0233c) |
| [43e5da1b](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/43e5da1bb81369e4e999adfa8558f5ccb5460eb6) | [e1969bcf](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/e1969bcf8dbb9e9e42cd718401a9df6d13f79d98) |

The runner built each original musl libtest against its own tree using Bazel. On the same Ubuntu 24.04 VM, the driver alternated which build ran first for each of ten pairs. Each invocation checked its real and effective UID immediately before exec, used the original qualification paths, ran one exact case, and recorded the raw stdout and stderr. [Workflow and pinned build setup](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/d188155e0e4231c89b03336b9f663ced5274c1ff/.github/workflows/agentd-cancelled-readback-sync-pair.yml) · [Raw Actions run](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45135852345/job/137561814315)

The per-process wall timings include sudo, UID verification, ELF start and shutdown. The whole-loop monotonic clock also covers invoking the two arms and writing intermediate evidence. The two Rust binaries were initially built outside that interval. The original libtest reports elapsed time to hundredths of a second. This targeted run exercises the listed case and makes no production latency claim.

## Observed results

| Source and synchronized fixture | Exact case passed | Subprocess walls, total | Median | Range | Libtest self-reported total |
|---|---:|---:|---:|---:|---:|
| e327 + 3002 | 10/10 | 0.674195 s | 0.048272 s | 0.047478–0.239211 s | 0.22 s |
| 43e5 + e196 | 10/10 | 0.470346 s | 0.046983 s | 0.045905–0.050867 s | 0.10 s |

The complete twenty-process loop took 1.154459 s. Both real and effective UID were zero in every invocation. The verification report includes both distinct ELF SHA-256 values. The raw 23,344-byte Actions archive is artifact 14800556569.

From this directory, reproduce the two independent reads with Python 3:

```sh
python3 verify_observation.py observation.zip
python3 verify_sync.py sync-pair.zip --sha256 4ecf851bd8d88d5bd7b6622eeccf7af143cecc3c6da9adc28de379a04399cedf
```
