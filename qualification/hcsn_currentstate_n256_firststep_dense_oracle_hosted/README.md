# N256 warm-1 dense oracle hosted execution

Status: **SOURCE_FROZEN / ONE_ATTEMPT / HOLD_PENDING_EXECUTION / all_closed=false**.

This dependent stage freezes one GitHub-hosted attempt for the exact independent
dense oracle already frozen in #6614.  The launcher must capture and satisfy
the #6636 same-job policy before it opens authentic N256 input or imports the
numerical oracle.  A child receives a 4 GiB address-space limit before `exec`,
one-thread numerical settings, and a 600-second deadline.  The workflow itself
has concurrency one, does not cancel an in-progress job, and has a 20-minute
deadline.

The bounded target is only warm 0→0.001: one dynamic step, two SciPy dense
matrix exponentials of orders 258 and 259, and one canonical 69,728-coordinate
full-state packet.  The unique execution key is
`hcsn-n256-firststep-dense-oracle-hosted-20261118-c06d-001`.

At source freeze there are zero N256 input reads, serializer calls, dynamic
steps, matrix exponentials, Torch calls, or optimizer steps.  A preflight
rejection is an authoritative RED with zero numerical execution.  A successful
artifact would close only this independent warm-1 oracle output and its actual
cost; it would not provide candidate/oracle equality, later cycles, arbitrary
histories, N512, full-network training, finite-domain qualification, task
benefit, or production adoption.

All earlier RED/OOM/cancelled/UNKNOWN records, C2 full replay 0/6, HPCA
NoUpdate/external custody, equal-budget benefit, asynchronous complete cost,
and `all_closed=false` remain unchanged.
