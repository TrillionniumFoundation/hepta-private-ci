
# learning.artifacts stage-measurement protocol

Status: executable source contract; not a target-host SLO receipt.

The owner measures the complete durability path before any cache or index change is
accepted. Fixed, bounded histograms expose p50/p95/p99 upper bounds and maxima for:

- payload validation and hashing;
- canonical request-identity persistence;
- pending-checkpoint recovery scans;
- payload write plus file/directory synchronization;
- registry encode/write plus synchronization;
- signed CURRENT/witness publication;
- checkpoint preparation and acknowledgement;
- startup recovery;
- authenticated current-view issuance;
- pinned candidate load;
- withdrawal-frontier persistence; and
- durable drain persistence.

`ArtifactOwnerOperationalMetricsV1` uses a closed stage enumeration and fixed
logarithmic buckets. It never uses operation IDs, digests, tenant strings or error
bodies as metric labels. The embedding host may report an independently observed
`ArtifactOwnerResourceUsageV1` containing pinned bytes, pending-erasure bytes,
resident bytes, logical payload bytes and actual durable bytes written. The owner
does not infer those gauges from cache eviction. Write amplification is emitted
only when the host supplied both logical and durable byte totals.

For each selected host/filesystem profile, retain the exact commit/tree, binary,
mount options, kernel, storage/cache policy, payload size, registry depth, sample
count and raw samples. Measure at minimum: empty/genesis, median history, 4,096
records, small payload, representative payload and the 64 MiB ceiling. Separate
warm and cold runs. Include restart scans, lock contention, withdrawal install,
drain and read-side pinned acquisition.

An optimization is acceptable only when correctness gates are unchanged and it
reduces a measured component of end-to-end p50/p95/p99, memory, or write
amplification. It may not remove directory synchronization, weaken identity
binding, bypass current-view revalidation, collapse unknown outcomes into failure,
or raise durable representation limits without a versioned migration.
