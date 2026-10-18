# Matrix SDK 0.18 SQLite upgrade fixture

These six data files were produced by the real Matrix SDK 0.18.0 and its SQLite
store APIs, using a synthetic account and a fixed test passphrase. They provide
old-format input to `tests/sdk_store_upgrade.rs`. The test copies the fixture
before opening it; the checked-in files remain the original old SDK data.

## Original provenance

The original generator linked the Rust libraries built from commit
`0c142a8dbc7066c0b0609c462a7218b5d31834e1` with
`cargo build --frozen -p codex-hepta-matrix-sdk --lib`, Rust 1.95.0
(`59807616e1fa2540724bfbac14d7976d7e4a3860`, x86_64 Linux). The old SQLite
vendor already contained its existing rusqlite 0.39 manifest adjustment.
No schema or encrypted record was fabricated with SQL.

The original generator's final source SHA256 was
`c64d58644be36aae226a8fa0b91ed72753f7a54f6062aa15c2cce3b7fecfd296`.
The adjacent `generator.rs` is a reusable port: the original absolute output path
is now a command-line argument, the source commit is supplied by the runner, and
generation and verification are explicit subcommands. It retains the original
SDK operations and checks, but its source bytes and SHA256 are different.

The published commit `905eee88586735f61be174886bbb370e27fc312c` can reproduce
the same old dependency graph. It shares these exact inputs with the original
generation commit:

| Input | Identity |
| --- | --- |
| `codex-rs/hepta-matrix-sdk` Git tree | `4e44163267e68183b7bc52f0330f8938bfa4356d` |
| `codex-rs/third_party/matrix-sdk-sqlite-0.18.0` Git tree | `e574621565ebecc51e359f94c2a68883696b8948` |
| `codex-rs/Cargo.lock` SHA256 | `8354b4cbdf14389db7aa5508e2ed5b524fc2d4c4ea0ecb475955c933f8bea389` |

Account keys, Megolm keys and store-encryption randomness are newly generated on
each run. Reproduction creates equivalent test data with new expected values;
it does **not** recreate the hashes below. Do not replace this fixture while
running an upgrade test.

## Recorded files

| File | Bytes | SHA256 |
| --- | ---: | --- |
| `matrix-sdk-crypto.sqlite3` | 180224 | `b741a6a5bbe7df75d6b2812af16d42cf1145f5a15e36f8cdb002aa57268e4dc1` |
| `matrix-sdk-state.sqlite3` | 139264 | `c1dee7a9cf324cc15d4365948bcbf5ce0f564374f1e2dfda12d76ded1ad94046` |
| `matrix-sdk-event-cache.sqlite3` | 69632 | `9c6373b2db0314c333619676e0792c7e54d243c97e5765764a9e93620dc48f3d` |
| `matrix-sdk-media.sqlite3` | 36864 | `7319bebb57d279494f50bf03d0cb5a521280ea689fa3f5d3c328ee890326bcb7` |
| `session.json` | 140 | `2e1d794dc381ad22a96f5bc12fde8a792d3863716099da8ce3ef9cdfa679d177` |
| `expected.json` | 3607 | `66297b4911c1795deebf5248ff0a4486dea912dd8b244f178884bd8b9e63033b` |

The original SDK schema versions in `kv["version"]` are crypto **17**, state
**15**, event cache **14**, and media **2**. `PRAGMA user_version` is zero and is
not the SDK schema version. All committed data was checkpointed into the four
main files; no WAL or SHM file belongs to this fixture.

## Objects and verification boundary

`OlmMachine::with_store` created the account and own device through the actual
old `SqliteCryptoStore`. The generator explicitly saved `LocalTrust::Verified`,
imported one Megolm key produced using vodozemac 0.10.0, exported it, and encrypted
a fixed `m.room.message`. `SqliteStateStore::save_changes` saved a sync token and
a Joined `RoomInfo`. `session.json` is an actual old `MatrixSession` serialized
by serde; it was not assembled as a substitute JSON structure.

Generation and a separate old-SDK verification process both exited zero. The
second process used the same ordinary passphrase and checked both public identity
keys, the entire serialized device, the entire exported Megolm key list, the
sync token, room membership and session deserialization. It also decrypted the
stored encrypted event and compared its event type and content with the expected
plaintext. The test token, passphrase and exported secret are synthetic and are
recorded in `session.json` and `expected.json`; the generator makes no HTTP calls.

Both cache stores contain initialized schemas without cached event or media
rows. They support a schema-upgrade check, not a claim that populated old cache
contents were discarded correctly. Cross-signing keys, backup keys and peer Olm
sessions were not populated. The generator does not create a Hepta owner database;
the upgrade integration test prepares and compares its own owner state separately.
The supported direction is old SDK to new SDK. This fixture makes no rollback or
new-format-to-old-SDK compatibility claim.

## Reproduce on x86_64 Linux

Use Python 3, Git, rustup and the native build prerequisites for this repository.
Keep the old checkout and target directory separate from a current SDK build.
Run the following from a checkout containing this README:

```bash
fixture_repo=$(git rev-parse --show-toplevel)
fixture_tools="$fixture_repo/codex-rs/hepta-matrix-sdk/tests/fixtures/sdk-0.18"
fixture_work=$(mktemp -d)
fixture_old_commit=905eee88586735f61be174886bbb370e27fc312c

git -C "$fixture_repo" fetch origin "$fixture_old_commit"
git -C "$fixture_repo" worktree add --detach "$fixture_work/old" "$fixture_old_commit"
rustup toolchain install 1.95.0 --profile minimal
(
  cd "$fixture_work/old/codex-rs"
  RUSTUP_TOOLCHAIN=1.95.0 \
    CARGO_TARGET_DIR="$fixture_work/target" \
    CARGO_PROFILE_DEV_DEBUG=0 CARGO_INCREMENTAL=0 \
    cargo build --locked -p codex-hepta-matrix-sdk --lib
)
python3 "$fixture_tools/run_generator.py" \
  --repo "$fixture_work/old" \
  --target-dir "$fixture_work/target" \
  --output "$fixture_work/generated"
```

The runner checks the old tracked checkout, tree identities and lock hash. It
uses Cargo's recorded dependency fingerprints to choose the exact already-built
rlibs, then invokes `rustc` directly; it does not edit a manifest or invoke Cargo.
It runs generation followed by verification in a separate process and writes
the precise commands, exit codes and new file hashes next to the output.
The portable CLI adaptation is source-reviewed; the original generation and
reopen results above belong to the original program and recorded files.

New output uses `state/` and `cache/` subdirectories, matching the actual store
open paths. The four databases are flattened here only for `include_bytes!`
inputs; the integration test restores their proper locations in a temporary
directory. Keep `expected.json` and `session.json` with the data from the same
generation. The runner rejects output that already exists and reports any
nonempty WAL before the main files are used alone.
