# Static V2 authority build and actual execution boundary

Frozen Hepta `3a50d14f8b7d3e9d4ef28bb82d7d0ea1313679d9` completed the original
Rust1.96 default-feature release/static build and original symbol archive/strip
in54m09s (wrapper3286.664s). Complete tracked source snapshots match. Packaged
host8119192B SHA138e9dd69c3ecd279b2cc4bc55663f763bfe4b0738c3f77e53ceac45586411ea
and peer7734376B SHA200888a05459782b68a4fb65717443d07d2797b6f06d41961a77ceb0f22c9a27
passed the original8MiB file/16MiB LOAD, permission and alignment inspector.
No feature, release-profile or shape limit was relaxed. This does not qualify
the full CLI's much larger ELF or a native recovered writer.

Linux reference01 failed after reading V2 proof1;02 failed protected authority
initialization. Metadata-only diagnostic03 also failed initialization. Its
actual final protected clock file fsync0.672732s plus directory fsync0.360229s
exceeded the original1s window. The safe summary retains syscall durations and
trace identity, without read/write buffers, environment or private key bytes.

Reference04 used a new isolated root-only persistent system-SSD directory,
distinct from build/data, without migrating or resetting earlier authority.
It passed2.723s with actual UID60001, no capabilities/no-new-privileges,
proof1 -> Objective2 -> FinalUse3 and feed148ms. Both complete ELFs were
prefetched before fresh clock/lease initialization; this is a warm-page result.
The fixture bind is not automatically restored after reboot and is not an
installed production service. Checkpoint had no ACK; server exit alone does
not prove a handler result or a writable/recovered owner.

Actual native execution used the previously qualified d5a21 ordinary kernel
f22e596de885a901cda99d5115edd915a12b017f31c383327ea5179c6f6d8c8d,
512MiB/SMP1/KVM, modern virtio ext2, original120s guest and original500ms
client limit. It failed the V2 read assertion (client101); raw QEMU33 is not a
qualification pass. Complete serial and failed result are retained. The later
protected-clock-window change requires another frozen build and actual gate;
the old V1 success cannot qualify this V2 failure.

[The manifest](publication.json) retains original build/readelf/source snapshots,
all four reference attempts, safe storage/trace summaries, the failed native
run and exact launcher/helper sources. It excludes executable/symbol archives,
private trace and the private ext2 image containing qualification keys.
