# Online fixed-feature statistics: registered engineering qualification

Registered on 2026-11-28 UTC before this protocol's executions.
Parent: hepta-private-ci PR #7071, commit 88414dda04443897def179754779aecdca6f0296.
Related scientific boundary: PR #7187 local-credit counterexample is unchanged.

## Question and scope
Can a peer accumulate compatible sufficient statistics across independent
processes and restarts without counting retries twice, accepting a conflicting
batch, mixing representation epochs, or partially committing a crashed write?
The new ledger is local to each peer; it supplies no central network reducer.
This is a new engineering protocol, not a rerun or replacement of E1-E6,
the final HCSN held-out tests, real A-to-B adoption, or learned-Circuit superiority.

## Fixed contract and transition
The contract binds schema/version, research model family, parent model bytes,
feature-program bytes, normalization bytes, target/loss objective, time semantics,
epoch, dimensions, float64 accumulation, and a strictly positive ridge penalty.
A contribution binds the exact contract, source bytes, a stable batch ID, a list
of stable source sample IDs, and unregularized Gram, rhs and full yTy matrices.
SHA256 is byte binding, not a signature or proof of truthful source statistics.
Counts and sample IDs agree exactly. Every matrix is finite and the augmented
[Gram,rhs;rhs.T,yTy] matrix must be symmetric positive semidefinite to the fixed
relative 1e-10 tolerance. Bounds: dimension <=1024, outputs <=32, rows <=100000.
An identical batch retry is idempotent. Reusing its ID with different bytes or
reusing one sample under another batch is rejected without mutation. A new batch
requires the current expected head and commits batch plus sample identities in
one SQLite transaction. No implicit migration between contracts/epochs.
The head hashes the contract and batch hashes in lexicographic batch-ID order.
Every solve uses that same float64 accumulation order and adds lambda once.
Candidate exports bind contract, head and little-endian float64 weight bytes.

## Registered checks
1. New synthetic fixture, NumPy seed 817, three non-IID shards with 3/7/11 rows,
   five features and two outputs. Compare against independently stacked data.
2. Eight spawned processes submit one identical batch: exactly one accepted,
   seven idempotent; changed bytes under that ID must fail.
3. Two distinct batches race against the same head: exactly one CAS succeeds;
   refreshing the head admits the other exactly once.
4. Reject stale contract/epoch, sample overlap, count mismatch, invalid digest,
   nonfinite/asymmetric/indefinite statistics, and invalid regularizer.
5. Child process exits after batch INSERT but before sample INSERT/COMMIT:
   recovered state is unchanged. Exit after a completed commit: retry is idempotent.
6. Independently restart and reverse admission order: head and float64 candidate
   bytes are equal. The independent pooled-data solve uses rtol=atol=1e-7.
7. Reuse all nine #7071 HCSN parents and their four pre-existing training shards,
   verifying each original shard SHA before use. No feature or model retraining.
   Run each parent's ledgers in forward/reverse order, reopen and compare with
   pooled data and original saved full solution at rtol=atol=1e-7.
   If source bytes are unavailable, retain this check as NOT_RUN; synthetic
   success never substitutes for the missing original-cache check.
8. Negative controls for duplicated contribution, mixed normalization and
   per-shard repeated regularization retain their measured objective differences.
   These diagnose protocol errors, not new capability/accuracy gains.

## Evidence and cost
Freeze implementation/test/runner SHA256 before execution. Retain first failures
and subsequent fixes as distinct attempts; never change the above endpoints from
observed results. Record source identities, process IDs/exits, database heads,
candidates, numerical differences, elapsed wall, and separate historical costs.
No final-test bytes, new agent trajectories, remote training, native E6 requests,
user adoption, production settlement, or scheduled jobs are consumed by this run.
Formatting follows repository instructions after validation; retain executed
pre-format source hashes and an AST-equivalence record if formatting changes bytes.
