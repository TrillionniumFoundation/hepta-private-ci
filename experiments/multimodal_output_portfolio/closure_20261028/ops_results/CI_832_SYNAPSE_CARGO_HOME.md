# Native ARM64 Cargo home failure and narrow fix

The actual failure in [candidate run 40661665504, job 122728804035](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40661665504/job/122728804035) occurred before the native tool probe completed. `rustup which cargo` exited with status 1 and wrote these exact 69 bytes:

```text
error: failed to determine cargo home: could not find cargo home dir
```

The child ran `/usr/local/cargo/bin/rustup` from `/`. Its recorded environment included `RUSTUP_HOME=/usr/local/rustup` but omitted `CARGO_HOME` and `HOME`. Both the pinned base image and the derived ARM64 builder record `CARGO_HOME=/usr/local/cargo` in `Config.Env`. The probe rebuilds a small explicit environment; `Commands.run` passes it directly to the process without inheriting the surrounding environment. The omission therefore discarded an image setting needed by Rustup.

The fix adds exactly `CARGO_HOME=/usr/local/cargo` to `probe_tools`. It retains the image's installed toolchain path and the existing environment allowlist. It does not inherit host variables, add `HOME`, mount credentials, change build/prefetch Cargo homes, or change container isolation. The observed launch remains UID/GID `1001:1001`, network `none`, read-only root filesystem, all capabilities dropped, and no new privileges.

The [official Cargo home documentation](https://doc.rust-lang.org/cargo/guide/cargo-home.html) documents the explicit `CARGO_HOME` setting and default home-directory fallback. The [Rustup environment documentation](https://rust-lang.github.io/rustup/environment-variables.html) separately documents `RUSTUP_HOME`.

## Evidence identities

The checked-out producer source was `832b2a382a155bc840df0d255b2c183a43b0d219`, with candidate tree `d454e457b2e5cb3c7f2b79480a7724aadf357fab`. The diagnostic workflow recorded event SHA `c94ee75afd9d1d16eb1452f78c6e9cd23fca0f13`; that merge/event identity is distinct from the source seal.

| Evidence | Bytes | SHA-256 |
| --- | ---: | --- |
| Manifest ZIP, artifact 12804089695 | 71,601 | `507a005318b83357e647f5e612ffb9d003ec6e547152fb1349a66e76adda8709` |
| Part ZIP, artifact 12804723667 | 1,249,426 | `72603dee172de1ed2a94513415575d544e305466e0a9becc285f5f1b301dcc70` |
| Reconstructed one-part tar | 1,249,280 | `f3d67a12239c345e405f70e193fba040b2fef4bc517a74a3f8c1b42aefb5df6c` |
| Original diagnostic inventory bytes | 71,455 | `14d4c07df22c04e27431002c38375577b310d1a9f23804a8aad4d5c9c9ea3502` |
| Actual Rustup stderr | 69 | `708fed68fb2ca6a521717b5e182165a34d37ee84990c43035d0d2efa855e4596` |
| Candidate ZIP, artifact 12805065260 | 1,935,599 | `eb427117ce2464ac58ff8af35dd1be44428b1204b82cb5768ef4c8832ea80b05` |

Each downloaded ZIP was verified against the API's full size/SHA and checked for member CRC errors. All 398 selected tar members were regular files and matched the complete published inventory by path, length, and SHA-256; their payload totaled 975,286 bytes. The exact original inventory is preserved in `CI_832_SYNAPSE_DIAGNOSTICS_INVENTORY.json`. The companion root-cause JSON preserves the actual failing command, stderr, container launch receipt, image identities, and test result.

This is complete verification of the selected diagnostic inventory. The original 580,275,852-byte artifact 12804139790 exceeded the connector's 512 MiB limit and was not transferred; its API-reported SHA `61228f5bb2d7900469d885fd8afbf48e3377331b23b50a1836d727d48dd3fa8d` is not an independently checked full-archive digest. No size override or limit bypass was used.

## Executed local validation and remaining gate

The five existing Linux preparation suites executed **21 tests, all passed**, including two added subprocess boundary tests. One invokes the actual probe path with a controlled real child, checks the image Cargo home reaches that child, and verifies hostile host home values and an unrelated marker are not inherited. It deliberately stops after the first lookup and cannot issue `TOOL_PROBE.json`. The other verifies the observed missing-home error bytes and nonzero status are preserved by the real command recorder.

These tests do not run Rustup, compile Rust, start ARM64 containers, or claim Synapse business qualification. The original 19 tests still execute, including cleanup, execution, source import, and restore rejection/positive paths. Tests ran before the final scoped Python formatting pass. Their full output is preserved in `CI_832_SYNAPSE_CARGO_HOME_TESTS.log` (SHA `4cdf81333322d0244310b71acd132d4974de08b03061f3de8e5b9db8535da21b`).

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  linux_synapse.test_boundaries linux_synapse.test_cleanup \
  linux_synapse.test_execution linux_synapse.test_restore \
  linux_synapse.test_source -v
```

Run from `codex-rs/hepta-matrixd/tests/fixtures`. The remaining acceptance gate is the original native ARM64 tool probe, sealed preparation, offline build, and real Synapse business test under unchanged isolation. A local environment regression pass does not close that native gate or authorize promotion. The historical v7 report, 13 frozen integrated-mode files, and 35 dependency payload files remain unchanged by this fix.
