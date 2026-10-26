# Native original-owner qualification runners

These run only a new isolated QEMU and private generated ext2 image. They accept
no existing disk, host block device, network, production policy or private key.
The output directory may contain newly created qualification keys: retain it
privately; publish selected source/ELF/lock fingerprints and sanitized results,
never the disk image. A VM crash is not physical power-loss qualification.

`run-native-owner-qualification.py --help` describes the required exact Desktop
and Hepta commit/tree pins, original owner ELF/SHA256, new output and kernel
target paths. Build the Hepta feature `qualification-native-owner` with locked
normal dependencies as a static musl ET_EXEC. The Desktop revision must contain
the G2 loader and original HOS2 ABI. The runner builds and verifies that exact
product profile, then runs complete original ownership and two byte-identity
rejection cases. `--reuse-kernel-build` admits only its fully verified matching
product build. A successful fresh build retains a read-only receipt binding its
source snapshot, owner, exact build/target paths and final kernel hash. Reuse
requires that existing receipt; changing targets or overwriting the kernel is
rejected before QEMU. Builds predating this receipt require a fresh build. This
local artifact receipt is evidence provenance, not a Root authority credential.

`run-native-owner-history.py` takes the same arguments. It keeps the same disk
inode, kernel and ELF across two VMs: exact acknowledged Current and stopped
owner, deliberate SIGKILL and reap, then original read-only WAL recovery of the
old operation. Unknown cannot reopen a writer, renew authority, replay or retire.
Root resource observation and Agentd delivery-history observation remain distinct.
The old payload's actual expected revision binds its previous/resulting history
and Root observation. The second boot binds independent Root and Agentd resource
observations without assuming a constant initial revision. Integer, boot, scope
and overflow checks remain strict.

Both enforce bounded artifacts/logs, a fixed 3072 MiB experimental guest budget,
no networking, finite 900-second maximum per boot, and source/artifact rechecks.
The guest uses kernel `loglevel=warn`: the actual SQLite workload otherwise
exhausts the unchanged 4 MiB serial bound with per-syscall and virtio INFO logs.
Warnings/errors and direct image/role/owner qualification prints remain visible.
The complete raw serial is retained without filtering; excess output still fails.
Keep every failed attempt; `passed` is only set after actual evidence validates.
Neither enables production or claims general cross-boot writer handoff.

## Reproduce the original owner build

Install Rust 1.95.0 with the `x86_64-unknown-linux-musl` target, `musl-gcc`,
and the normal locked workspace build dependencies. From this repository root,
choose dedicated absolute build and temporary directories, then run:

```sh
export NATIVE_OWNER_TARGET=/absolute/path/to/dedicated-target
export NATIVE_OWNER_TMP=/absolute/path/to/build-temporary-directory
mkdir -p "$NATIVE_OWNER_TARGET" "$NATIVE_OWNER_TMP"
cd codex-rs
env RUSTUP_TOOLCHAIN=1.95.0-x86_64-unknown-linux-gnu \
  CARGO_BUILD_JOBS=2 CARGO_INCREMENTAL=0 \
  CARGO_PROFILE_RELEASE_DEBUG=0 CARGO_PROFILE_RELEASE_STRIP=symbols \
  CARGO_TARGET_DIR="$NATIVE_OWNER_TARGET" TMPDIR="$NATIVE_OWNER_TMP" \
  CARGO_TARGET_X86_64_UNKNOWN_LINUX_MUSL_LINKER=musl-gcc \
  CC_x86_64_unknown_linux_musl=musl-gcc \
  CARGO_TARGET_X86_64_UNKNOWN_LINUX_MUSL_RUSTFLAGS='-C target-feature=+crt-static -C relocation-model=static -C link-arg=-no-pie' \
  cargo build --locked --offline --release --target x86_64-unknown-linux-musl \
    -p codex-hepta-agentd --features qualification-native-owner \
    --bin hepta-native-owner-qualification
```

Populate the locked dependency cache before using `--offline`. The existing
release profile remains unchanged; do not substitute a stub owner or remove
dependencies to fit the loader. Retain the clean commit/tree, complete build
command and log, and source measurements before and after compilation. Copy
`$NATIVE_OWNER_TARGET/x86_64-unknown-linux-musl/release/hepta-native-owner-qualification`
to a separate retained artifact, measure its SHA256 and inspect it with
`readelf -h -l`: require static `ET_EXEC`, no `INTERP` or `DYNAMIC`, and the
runner's bounded segment/TLS limits. A successful compiler exit alone is not a
native execution result. Supply canonical absolute paths to the runner; its
build receipt also checks the actual compiler arguments and target paths.

`test-native-history-oracle.py` and `test-native-complete-oracle.py` test only the
actual serial parsers with explicitly synthetic examples. They are not native
evidence. Actual result summaries must bind
the runner hashes, original raw serial, complete source/lock/ELF measurements,
kernel manifest and exclusive-disk lifecycle. See
`codex-rs/hepta-agentd/NATIVE_OWNER_QUALIFICATION.md` for the owner-side contract.
