# N256 joint full-coordinate comparator source intent

Status: **HOLD / source intent only / `all_closed=false`**.

This package freezes a stdlib-only comparator and future joint-runner manifest
contract. It binds the authentic N256 input bundle, published roster identity,
candidate, independent-oracle, canonical-serializer, and resource-observation
source hashes. It cannot start or admit N256 numerical work.

The future comparator requires exactly 14 ordered capsules (warm 8, coarse 3,
cold 3) and 18,225,028 coordinate records. Candidate, oracle, and an independent
reference stream must have identical frame and coordinate identities. Candidate
and oracle absolute errors are gated separately; signed cancellation is
forbidden. Warm, coarse, and cold saved-state round trips must each be byte
exact.

The existing frozen candidate and oracle interfaces do not yet emit the shared
reference stream needed for those separate gates. That gap remains OPEN. Every
runtime, host, ancestor-cgroup, allocation, calendar, lane, and joint admission
field is null, so the contract rejects before opening any stream. No numerical
idempotency key is created or reserved here.

Historical #6295 RED, #6302 RED/UNKNOWN, and #6303 joint-admission RED remain
unchanged. This package grants no N256, continuum, checkpoint, training,
production, or global qualification.
