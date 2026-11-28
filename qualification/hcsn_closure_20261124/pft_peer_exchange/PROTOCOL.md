# Persistent peer exchange: prospective engineering controls

Scope: connect the independently checked PFT statistics ledger to real TCP
processes. This does not introduce a learning objective or reopen any E1–E6,
HCSN final-test, adoption, or topology-superiority budget. Register this protocol
and freeze the implementation bytes before its first test execution.

## Fixed behavior

Each peer owns its own SQLite ledger and solves its own candidate. Peers push
missing immutable contributions over a directed cycle. No process computes a
shared authoritative solution, and the test coordinator sends only addresses,
termination signals and read-only observations after startup.

The representation contract survives socket-address changes and process restart.
Every RPC binds the contract, operation and exact canonical request bytes.
An offer is acknowledged only after the existing ledger transaction returns.
An interrupted response means unknown delivery. The same packet can be retried;
the retained batch identity resolves it without counting its rows again.
Conflicting batch bytes, a foreign contract and stale expected heads must fail.

This is an explicitly loopback-only research transport with no identity or
confidentiality claim. It cannot bind a public address. A frame is at most 8 MiB,
an exchange at most 1,024 batches, and each frame read has one absolute
two-second deadline shared by its header and body. Connection/write operations
also have two-second timeouts. The protocol provides engineering data consistency, not authenticated
work, truthful statistics, user permission, payment or production authority.

## Fixed controls and endpoints

1. NumPy seed 48117, four non-IID synthetic batches with 3, 7, 11 and 13 rows,
   five features and two outputs, ridge lambda 0.2. Four spawned OS processes
   each start with only one batch. On a directed cycle they must converge to
   the same four-batch head and byte-identical weight digest within 20 seconds.
   Compare every weight with independent augmented least squares at
   rtol=atol=1e-7. One owner must never be required to aggregate the network.
2. Terminate one real receiver with exit 71 immediately after its first new
   transaction commits and before its TCP response. The sender observes unknown
   delivery. Restart the receiver on its original database, possibly a new port;
   repeat exactly the original packet and original expected head. It must return
   idempotent, retain revision one and match the independent solution. This is
   a new transport control, not a rerun of a scientific cold-adoption experiment.
3. Through actual sockets reject foreign contracts, conflicting batch bytes,
   stale heads and malformed/noncanonical/oversized/incomplete frames. Compare before/after
   heads. Rejected requests cannot become accepted contributions.
4. Bind every response to its request digest. A response for a different request
   must be rejected, including a superficially successful response.

Retain the first outcome of every control and actual child PID/exit evidence.
Maximum whole test-run wall time: 60 seconds. No retry of a failed whole run
without a source correction and a separately retained subsequent attempt.
Source syntax and formatting checks are not evidence that these endpoints pass.
No final-test files, teacher API calls, new training trajectories or live-user
materials are accessed. New outputs remain research candidates.
