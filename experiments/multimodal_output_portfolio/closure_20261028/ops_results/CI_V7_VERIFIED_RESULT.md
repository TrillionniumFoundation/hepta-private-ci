# v7 dependency candidate: verified result

Observed source: `943768d41de711ef888d8c21c1466aa783885307`. [Candidate run 40656660435](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40656660435) completed with **7 successful jobs and 4 failed jobs**. The generated dependencies have **not** been applied to the live branch; this is not a green PR or promotion result.

## What actually passed

| Scope | Executed / passed | Ignored or selected out | Result |
| --- | ---: | --- | --- |
| `codex-keyring-store` | 1 / 1 | 0 declared ignored | [Pass](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40656660435/job/122709943432) |
| `codex-execpolicy` | 34 / 34 | 0 declared ignored | [Pass](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40656660435/job/122709943556) |
| `codex-aws-auth` | 5 / 5 | 0 declared ignored | [Pass](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40656660435/job/122709943537) |
| `codex-login` | 0 / 0 | No tests executed | [Compilation failed: E0061](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40656660435/job/122709943537) |
| `codex-secrets` | 9 / 9 | 0 declared ignored | [Pass](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40656660435/job/122709943537) |
| `codex-utils-yaml` | 9 / 9 | 0 declared ignored | [Pass](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40656660435/job/122709943381) |
| `codex-skills` | 49 / 49 | 0 declared ignored | [Pass](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40656660435/job/122709943381) |
| `codex-skills-extension` | 175 / 175 | 0 declared ignored | [Pass](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40656660435/job/122709943381) |
| `codex-core-plugins` | 426 / 426 | 0 declared ignored | [Pass](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40656660435/job/122709943381) |
| `codex-external-agent-migration` | 0 / 0 | No tests executed | [Compilation failed: E0061](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40656660435/job/122709943381) |
| `codex-hepta-matrix-protocol` | 12 / 12 | 0 declared ignored | [Pass](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40656660435/job/122711813403) |
| `codex-hepta-matrix-store` | 36 / 36 | 0 declared ignored | [Pass](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40656660435/job/122711813403) |
| `codex-hepta-matrix-sdk` | 36 / 36 | 2 declared ignored | [Pass](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40656660435/job/122711813403) |
| `codex-hepta-matrixd` | 0 / 0 | No tests executed | [Compilation failed: E0061](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40656660435/job/122711813403) |
| Full upstream AWS source | 244 / 244 | 1 original ignored; 0 passed after retry | Pass |
| Independent old Matrix fixture producer | 1 / 1 | 2 other tests selected out | Pass |
| New Matrix binary reopens old fixture | 1 / 1 | 2 other tests selected out | Pass |

The successful Rust commands executed **1,038 passing tests**: 792 workspace tests, 244 independent upstream AWS tests, and two explicitly selected fixture phases. This is a command execution count, not a unique-test census across all workflows. The normal Matrix SDK command retains its two declared ignored fixture-phase tests; the producer and consumer phases explicitly execute their respective test with zero retries. The generator also passed 32 port/fixture behavior tests, 18 Linux Synapse helper tests, and 12 post-qualification helper tests.

The Linux Bazel job built all **12 selected targets**, with `--lockfile_mode=error`, reporting 4,654 actions. This establishes the selected Linux libraries and first-party consumers, without claiming full platform qualification. The original full-scope pinned cargo-deny action passed; pre-scan restore and post-scan unchanged-state receipts are verified. Its raw job log could not be read because the connector returned `Transport closed`, so the policy conclusion relies on the actual action result and those receipts.

## Generated locks and policy binding

- Generator RESULT SHA-256: `cd88dc0a753dedc84a7f9e6cad1a903a569d34eb661f471d1fb430ad434d4252`.
- Frozen v7 recipe SHA-256: `8c655b7b3c539527e6506869a52d0e98a88ed37e334e9d34d13be83713bce03f`.
- Source patch SHA-256: `9f76d0986e0ec2897c0cc95d550b132d1cf8c51b90f3d925a72859758217ada9`.
- Complete candidate patch SHA-256: `23661494d6dc1440bff896c80497509ef6e2415c1419dc0d3e452e70c67fcb4e`.
- Cargo lock SHA-256: `c335e0649d5d516cadd52d68c1a15ed5c136814d11553ef5c791ea7e5058a478`.
- Bazel lock SHA-256: `fe4bbfb92aac1eba58fb25357bf3182088d29a09b1838144041c94b03f8218cf`.

The actual generator ran `just bazel-lock-update` and `just bazel-lock-check`, both successfully. All 35 candidate payload files and 31 command logs were read and verified against the producer receipt. Cargo metadata before and after Bazel lock generation is byte-identical. The original dependency policy files are unchanged. The recorded graph excludes `anymap2`, `basic-toml`, `libbz2-rs-sys`, `serde_yaml`, `unsafe-libyaml`, `zbus_names`, `zvariant`, and `zvariant_derive`. ZIP retains the recorded compression/encryption feature set; the bzip2 backend resolves through `bzip2-sys`.

## Independent old-store migration

The producer compiled old source `6215cb6a87f29623d4beaad24cdf7bcb6bb4fb2c` with old Matrix SDK, crypto and SQLite versions 0.18.0, source tree `56af6d047db233fe945ef22f65e031f460ac649a`, and the original lock. It captured seven fixture files after its test process exited; no DB/WAL/SHM sidecar survived that process. The new candidate executed the real reopen test against a separate exact fixture copy, and the producer fixture remained unchanged.

- Old producer RESULT SHA-256: `a849ddbee5a11a47a8519f381b146cd0537d0753710545496967d02dc2d2a47c`.
- New consumer RESULT SHA-256: `eaeb4e7b33c262b7d68528682fb4eca4249b31f56472644e039021d44fe535c9`.
- Old executable SHA-256 recorded by CI: `968afe36fb81f38def30957cc30a9af99448e5ec6dee7e51a7447374f61b50c9`.
- New executable SHA-256 recorded by CI: `315290b884a6c6ea717f3ea55e253884e59520978841246058157d8a48117ae4`.

The local audit read selected RESULT files and command logs through HTTP Range, with member CRC and SHA checks. It did not download those complete binary/database archives. The producer and consumer execution evidence passes; this does not resolve the separate Matrix daemon compilation failure.

## Failures that remain open

Three candidate jobs failed at the same core API compatibility error, at `core/src/session/handlers.rs:417`, `handlers.rs:581`, and `turn_suspension.rs:449`. Their old single-argument `deliver_event_raw` calls no longer match the changed helper. The prepared compatibility wrapper retains the existing completion-aware delivery path; its next remote run is still required. Failed commands are `codex-login`, `codex-external-agent-migration`, and `codex-hepta-matrixd`.

The arm64 Synapse job stopped at `start-native-tool-probe` with exit 1, before business qualification. Its root cause remains unknown. The actual stdout/stderr and START/END receipt paths are under `preparation/controller-commands/`; their ordinal must come from the actual directory inventory. The 580,225,486-byte artifact exceeds the connector 536,870,912-byte download limit. A separate bounded export of complete JSON, stdout, stderr and logs is prepared for the next run; the original artifact stays intact.

The separate blocking workflow is not complete at this report snapshot. It still has the old live-lock cargo-deny failure, the same core compile error in the NDU smoke, and a Windows shard 4 failure. That Windows job executed 74 test targets: 70 passed and four failed locally, while 34 failed to build and 34 were skipped. The actual failing targets are exec-server file-system tests, operator acceptance, prompt optimizer, and shadow qualification. These are recorded for separate fixes; unfinished platform jobs are not counted as passed.

## Artifact readback boundary

| Artifact | Bytes | Local readback | Full archive SHA-256 |
| --- | ---: | --- | --- |
| [candidate](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40656660435/artifacts/12801988362) | 1,935,773 | Complete; SHA and member CRC verified | `e9e951cebcaee04c18cbffc3cc446be75c5de19e6fb2ec1afa57b48017643a95` |
| [deny](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40656660435/artifacts/12801384455) | 8,289 | Complete; SHA and member CRC verified | `9bd887475de5accca3ff3b20004019b12085eb055e022deb52e21168377eb75e` |
| [keyring](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40656660435/artifacts/12802023324) | 8,458 | Complete; SHA and member CRC verified | `062913436cf62ab7331ac795e4a3923817959a962f3a691240976bd1d2080a1f` |
| [execpolicy](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40656660435/artifacts/12802023486) | 10,966 | Complete; SHA and member CRC verified | `9874a133021f3e2e9abd8f985e45255c49550d9096f94112ff32e978c56c4623` |
| [aws-upstream](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40656660435/artifacts/12802023503) | 12,119,654 | Complete; SHA and member CRC verified | `c33d240acaf34a70dd1a42a8c0df8fee05003890f55a144ae3513017fba7c1e7` |
| [aws-workspace](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40656660435/artifacts/12803020278) | 30,477 | Complete; SHA and member CRC verified | `47bbbab8ccce24ae5031f74b2f8aef080b1cb12e3cba6deed8cbbdd8dccdc04e` |
| [yaml](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40656660435/artifacts/12802262991) | 52,825 | Complete; SHA and member CRC verified | `46749617554f14f1f062a87b946428484cae36c9edc6389ab345767014dc30a0` |
| [bazel](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40656660435/artifacts/12802985869) | 17,122 | Complete; SHA and member CRC verified | `fd07dd37aaee52be5dfe66e35d95d164aaf7ab3c0afd94bb341cfc1bf8fac07e` |
| [matrix-old](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40656660435/artifacts/12802019177) | 131,699,047 | Selected Range members only (10,431 bytes received) | `db5a5e9ddf229287a03ec9863c87386966df0bd6d345500f99f27808790f9ae4` |
| [matrix-consumer](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40656660435/artifacts/12802892641) | 99,782,933 | Selected Range members only (46,013 bytes received) | `02fd24cec114b3afefcdf400f923f85f755abb4d3b1064293da33c2438b9d3fe` |
| [synapse](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40656660435/artifacts/12801794126) | 580,225,486 | Not downloaded; connector size limit | `ad2f2d2c58f75df270d40fa57f885ff51fb4e6b7daa59115e4b6750f4adf2754` |

For Range-only and unavailable artifacts, the table hash is the server-reported archive digest, not an independently verified full-archive hash. The JSON includes RESULT identities, all 35 candidate payload identities and per-command test-log hashes.

## Applying the candidate

A temporary private Git index loaded the exact source HEAD and checked both patches. Source patch: 33 paths, exit 0. Complete candidate patch: 35 paths, exit 0. No changed or untracked working-tree file intersects those 35 paths. No live index, worktree file, lock or ref was changed. The payload is in `files/<repository-relative-path>` in the candidate artifact, including the 194-byte binary ZIP fixture. Apply the reviewed source changes and both generated locks together, preserving exact bytes.

The frozen v7 candidate driver unconditionally applies a patch and requires an exact changed-path set. Once those files are committed as live dependencies, rerunning that driver directly on the integrated HEAD will reject already-applied hunks. Integration therefore needs a new exact-tree verification path that binds the integrated HEAD, generated-file hashes and original policy; it must retain full cargo-deny, lock checks and qualification execution. The historical recipe and run remain immutable.

[Frozen recipe source](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/943768d41de711ef888d8c21c1466aa783885307/experiments/multimodal_output_portfolio/closure_v2_20261027/ci/port-remediation/RECIPE.v7.json) · [Candidate driver](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/943768d41de711ef888d8c21c1466aa783885307/scripts/ndu_port_candidate.py) · [Restore and identity checks](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/943768d41de711ef888d8c21c1466aa783885307/scripts/ndu_port_candidate_common.py) · [Blocking run](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40656660657)
