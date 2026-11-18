# Git-utils Chrono retirement on the joint candidate

The execution source is `975a29ae7e01aa070e60e1d70256452ae2837cae`, tree `02e42082bed744d2b5c35daa122c489513b00434`, on exact predecessor `7e28e13e82045f936cb66f9fea4a27ad4368f896`. Subsequent evidence commits preserve this execution identity.

## Actual result

The complete original package ran through the repository entry point:

`just test --locked --offline -p codex-git-utils --retries 0 --test-threads 2 --no-tests fail --success-output final --failure-output final`

**38 distinct cases passed**, with no skips, failures, errors or retries. All seven original baseline cases ran, including configured-hook isolation, unborn-repository recovery, reset history, status scanning, diff handling and executable-bit handling. The original child wait and persistent terminal owner both exited 0. Command wall time was 77.67503870799999 seconds including compilation; this is not a performance qualification.

[Original JUnit](retained/original-junit.xml), [case index](retained/CASES.json), [native result](retained/NATIVE_RESULT.json), and [complete readout](retained/READOUT.json) retain the evidence.

- JUnit UUID: `3022c3aa-45d5-4fcb-b3c0-ecc6d3e626d0`.
- JUnit SHA-256: `d3a7e3370cfec2350a97a9f944b7c1cb69f3ab045868c46399dc6b073ea85108`.
- Native result SHA-256: `5b0be1147d457cc843fc60b2ddd1fdcee1a0a6c292c3d5b873b0fc525c10d659`.
- Original terminal: `dpty-46f05ccc157ffb1c431fbb60d15bcba5369127d7ac8bfcf8ba99ae706fde9840`.
- Terminal exit SHA-256: `abf83ee28b9377bf050532f70f5d9b1677002227474a0f22fb42913692465f8f`.

## Change and source binding

The internal baseline commit signature obtains its whole Unix seconds from `time::OffsetDateTime::now_utc().unix_timestamp()`. Its name, email, zero UTC offset, tree, commit construction, index handling and configured-hook isolation remain the same. This replaces the package's direct Chrono dependency with the existing workspace time crate. The original package tests were not edited.

All **11890 materialized tracked files** were checked against their actual Git blobs. Source inventory SHA-256 was identical before and after native execution:

`3d968f658a5f7bac56a737d0e0ec08876ef9001c4997d6f9d4680814e6739aee`

[The source freeze](retained/SOURCE_FREEZE.json) and complete inventory in the originals archive bind the exact source. [ORIGIN.json](ORIGIN.json) records the scope; [NATIVE_PROTOCOL.json](NATIVE_PROTOCOL.json) was published before execution.

The actual target-platform offline Cargo metadata, Bazel lock update/check, scoped `just fix`, repository formatter, and diff check all passed before the freeze. The independent target is an APFS clone of this task's completed predecessor target; every regular clone file was checked for distinct inodes and a single link. It is not shared for writes.

- Cargo lock SHA-256: `1bcd8351057718fb842f9407544a5ac644ad079ea15c684c6059cc4243481c21`.
- Bazel lock SHA-256: `d240b972292c4101a01eceb1281dd15cdc43c77979711281bcaa5d0c680580c1`.
- Actual Bazel regeneration and check both exited 0; regeneration retained identical lock bytes.

## Remaining dependency graph

The unchanged #6624 scanners were run against this new lock. Direct workspace roots decreased **26 → 25**, indirect-only roots increased **95 → 96**, and **121 of 194 source-less candidate roots still reach Chrono**. The total direct local/registry/vendored edges is 33.

The remaining git-utils witness is `git-utils → protocol → Chrono`. [The graph result](retained/CHRONO_GRAPH.json) retains the actual `--require-zero` exit 2. This does not close Cargo-deny, complete Chrono retirement, all-platform metadata, or Windows qualification. No advisory ignore was added.

## Complete originals

[GIT_UTILS_ORIGINALS.tar.xz](retained/GIT_UTILS_ORIGINALS.tar.xz) retains **115 original artifacts and receipts**, including actual metadata and both locks, source inventory, unmodified scanner output, complete native output/JUnit, and the preparation/freeze/native terminal request, start, exit and complete output. Compiled targets and the terminal runtime implementation remain on the original host.

- Archive size: 2095028 bytes.
- Archive SHA-256: `2ba5a3035e20eeb8b9b90249e0928fa78120fe00e8d105e5a6fa685b4cc43a98`.
- [INDEX.json](retained/INDEX.json) SHA-256: `993a38f681572d1b315a2d38d85ceb5e9dce4923f548b77028e6b1a8afa72444`.

Every archived member was reread against the index. The size exception binds only this exact archive SHA and path. The global 512000-byte limit remains unchanged.
