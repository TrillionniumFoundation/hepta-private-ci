# N256 streaming full-state static intent

Status: **HOLD_NO_NUMERICAL_EXECUTION / all_closed=false**.

This independent stage starts from #6295 exact evidence head
`3a1f51acf100405fac7435731ceaef8d4a5ed497`. It addresses only the storage
representation exposed by #6295's retained resource RED. It does not reclassify
that RED and does not execute the N256 model.

The plan preserves the exact 18,225,028-coordinate denominator. Candidate state
is retained as canonical state vectors, packet alpha/output vectors, and a
global canonical CSR operator table. A separately implemented oracle must emit
the same implicit coordinate order in fixed 65,536-coordinate frames. Candidate
zeros are reconstructed from CSR; they are not omitted from comparison.

The static gate checks exact roster and #6295 evidence hashes, packet order,
capsule denominators, chunk bounds, structured-container bytes, oracle stream
bytes, and the retained N128 storage caps. Passing this static gate only closes
a representation arithmetic sub-blocker. Actual N256 candidate/oracle code,
expm workspace/RSS, serializer/cold-loader execution, durable host and ancestor
cgroup allocation, concurrency/calendar, and warm/cold byte equality remain
open.

No claim transfers to dynamic resource safety, full-state numerical
qualification, historical N256 recovery, third/later cycles, continuum or rare
tails, Torch, optimizer, training, fullnetwork, task benefit, asynchronous
execution, energy, or production adoption. Historical negative results and
UNKNOWN states remain unchanged.
