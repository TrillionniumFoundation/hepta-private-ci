# Authentic N256 warm t=0 capsule (HOLD)

Identity: `hcsn-n256-authentic-t0-capsule-20261115-c06d-001`.

This lane performs one canonical serialization of the authentic frozen N256 initial state and eight initial exponential-flux packets, followed by an independent fresh-process stdlib decoder and byte-derived oracle. It compares all 2,656 FP64 coordinates exactly: 2,600 current-state coordinates and 56 packet coordinates. The cold auditor does not import the writer or the canonical serializer.

The execution budget is one serializer call, zero dynamics, zero matrix exponentials, zero model/provider calls, zero Torch, and zero optimizer calls. The capsule is capped at 8 MiB. Historical RED and UNKNOWN records remain unchanged.

This does **not** qualify the full 18,225,028-coordinate / 279-frame roster, N256 dynamics, arbitrary histories, checkpoint recovery, N512, full prior, migration, full network training, task benefit, production adoption, or `all_closed`. The old unexecuted sparse intent remains separate; it expects `content`, while the authentic frozen phase input contains `signed_content`.
