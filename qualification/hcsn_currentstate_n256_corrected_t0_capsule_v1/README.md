# Corrected-lineage authentic N256 t=0 capsule (HOLD)

Identity: `hcsn-n256-corrected-t0-capsule-contract-20261117-c06d-001`.

This isolated successor to Draft #6608 performs one authentic warm `t=0`
serialization using the corrected `signed_content` candidate parser, the
independent stdlib oracle adapter, the published N256 original bytes, and the
canonical packet serializer.  A separate fresh process parses the resulting
capsule without importing the writer or serializer and compares all 2,656
FP64 coordinates exactly (2,600 current-state coordinates plus 56 packet
coordinates).

The first local development execution used key
`hcsn-n256-corrected-t0-capsule-20261117-c06d-001` before a Git source commit.
Its complete source, capsule, BUILD, and RECEIPT bytes are preserved under
`evidence/precommit_attempt001`; it is a protocol RED and is not qualification
evidence.  That key is consumed and must not be run again.

The separately frozen hosted execution key is
`hcsn-n256-corrected-t0-capsule-20261117-c06d-002`.  The frozen budget is one
oracle-adapter call, eight candidate phase-parser calls, one canonical decode,
two canonical encode invocations (the publish encode and the decode's exact
roundtrip encode), one atomic publication, and zero dynamics, matrix
exponentials, provider/model calls, Torch calls, optimizer steps, or training.

Attempt002 does not transfer either the older #6366 capsule or the invalid
precommit attempt001 capsule and does not qualify
`cold_load`, N256 dynamics, the 18,225,028-coordinate / 279-frame roster,
arbitrary histories, checkpoint recovery, N512, full prior, migration,
full-network training, task benefit, asynchronous full cost, production
adoption, or `all_closed`.  Historical RED, cancellation, and UNKNOWN records
remain authoritative.

Status: **HOLD**; `largegrid_qualification=false`, `all_closed=false`.
