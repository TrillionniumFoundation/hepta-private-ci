# Bounded product federation execution

`cognitive_runtime::retrieve_federated_product_original` limits concurrent
owner discovery and concurrent complete V2 peer attempts to four. Both queues
retain their original input order. Discovery still considers the original
bounded owner layout set; stable sorting, capability deduplication, the sixteen
source limit and explicit truncation/failure coverage are unchanged.

Each queued peer checks the original request-wide deadline when its slot
starts. It receives the same `global_deadline_ms` and original `started_at` as
every other peer. Queueing never starts a fresh two-second budget. The original
`execute_once` cancellation race still bounds preflight, transport and the
post-I/O authority check, and expired queued peers record deadline failures.

All discovery and both authority observations still open through the original
SQLite VFS and perform the existing integrity, owner, schema and full current
capability checks. This module adds no cached authority, retained alternate
descriptor, path-only identity check, new database owner or recovery ledger.

## Failure evidence and acceptance

The actual pre-change 17-owner regression in
`hepta-native-full-owner-check-04/original-peer-two-second-regression.log`
(SHA256 `9c7970d72611f71d53f1bd6c84095a1ef97a29622d5a794980feafd1f778a37d`)
reported sixteen deadline failures, zero completed peers and one truncated
peer. Its bounded phase trace retained 592 events with none omitted and an
elapsed time of 2,064,205 microseconds. Initial discovery ended at 472,490
microseconds; concurrent preflight checks then took 587,359–990,758
microseconds and all attempts reached the original common deadline.

Separate diagnostic runs after that failed request closed their original
read-only SQLx pools and measured all seventeen discoveries at widths 1, 2,
4 and 17: 616,906, 195,988, 172,908 and 816,800 microseconds respectively.
Those measurements informed the concurrency bound. Their filesystem cache
was not claimed cold, and they do not replace the failed product result.

Acceptance requires the unchanged
`product_v2_reports_peer_truncation_before_aggregation` test to complete all
sixteen requested peers inside the original product deadline, plus the
original cognitive-runtime/federation regression tests. Use `just test`; do
not extend the deadline, omit failed runs or count these host tests as native
Asterinas execution. The fullcheck-04 failure remains part of the record.
