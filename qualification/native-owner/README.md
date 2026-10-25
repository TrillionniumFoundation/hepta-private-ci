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

`test-native-history-oracle.py` and `test-native-complete-oracle.py` test only the
actual serial parsers with explicitly synthetic examples. They are not native
evidence. Actual result summaries must bind
the runner hashes, original raw serial, complete source/lock/ELF measurements,
kernel manifest and exclusive-disk lifecycle. See
`codex-rs/hepta-agentd/NATIVE_OWNER_QUALIFICATION.md` for the owner-side contract.
