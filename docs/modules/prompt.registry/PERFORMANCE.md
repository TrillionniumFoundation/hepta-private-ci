# prompt.registry performance measurement contract

Measurements must identify source SHA, tested tree, toolchain, runner, command,
sample count and exit status. A queued job, an ignored test, a fixture ceiling
or a source archive is not a measured baseline. Numeric results belong in a
source-bound execution artifact/report, not in an assumed production SLA.

## Native operational profiles

From `codex-rs`:

```sh
cargo test --locked -p codex-hepta-prompt-registry operational_ \
  -- --ignored --nocapture --test-threads=1
cargo test --locked -p codex-hepta-agentd \
  operational_pipeline_compile_stage_final_use_profile \
  -- --ignored --nocapture --test-threads=1
```

| Profile | Actual measured operations | Samples and limitations |
| --- | --- | --- |
| `operational_scale_profile_1k_8k_16k` | Initial persist, fresh-owner reopen, durable factor registration, lifecycle update, snapshot/dereference, copy-compaction, owner-local GC and file sizes | 1,000 / 8,000 / 16,384 logical records; 31 snapshot and dereference samples per size; writes are one sample per size, not write-tail percentiles |
| `operational_fsync_profile` | Anchored temporary-file write, file fsync, directory fsync, synchronized cleanup | 31 samples each at 4 KiB / 64 KiB / 1 MiB; isolated filesystem diagnostic, not full request latency |
| `operational_pipeline_compile_stage_final_use_profile` | Authenticated fixture's real compile-and-stage, preparation current-use gate and owner-local validation timings | 31 one-realization runs; no actual provider network; setup/admission excluded from the marked intervals |

Each scale fixture is semantically validated. Bulk fixture construction is
reported separately, not counted as durable registration throughput. An actual
single durable registration is timed after reopen. The logical record count
includes factor and realization records rather than pretending that every
record is a full-sized payload. A 64 KiB maximum payload combined with a 32 MiB
selected-payload ceiling admits at most 512 such full-sized payloads, not 16k.

Scale JSON schema is `hepta.prompt-registry.operational-scale.v2`; fsync is
`hepta.prompt-registry.fsync-profile.v2`; pipeline is
`hepta.prompt-registry.pipeline-profile.v1`. The qualification collector checks
that required tests were compiled/executed, parses all expected scale/fsync
rows, and checks the pipeline profile emits 31 rows. It stores raw logs and
structured rows with their digests outside the checkout.

Nearest-rank p50/p95/p99 and maximum are reported only for sampled series.
With 31 samples p99 is the maximum, not a statistically strong tail estimate.
Pipeline emits individual timing rows for downstream aggregation; a compile
or render latency at 16k factors is not inferred from its one-realization test.
The actual native operation is compilation/delivery, not an invented registry
`render` endpoint. Restoring/reopening and fsync are measured separately.

## Memory and resource interpretation

On Linux, optional `/proc/self/status` VmHWM is the process-lifetime resident
high-water mark. It is not per-operation allocated memory or an independent
per-size peak: later sizes inherit earlier peaks in the same test process.
Non-Linux platforms report missing memory data, not zero. Independent per-size
process measurements and realistic workload mixes are required before making a
capacity or production latency promise.

Operational gauges expose current active bytes, selected bytes, reclaimable
inactive bytes, physical payload/metadata file bytes, lifecycle-event count,
revocation frontier, remaining logical/byte capacity and high-water usage.
Poisoned owners expose diagnostic predecessor gauges with `authoritative=false`
and `requires_reopen=true`, not a writable or deliverable state.

Current-use counters expose check/rejection counts, expiry, withdrawal,
identity conflicts, reopen-required observations, total time and maximum time.
They are process-generation counters without cardinality-growing labels.
They reset at restart and are not a persistent authority/epoch failure ledger.
`oldest_reclaimable_age_ms` remains null because there is no versioned durable
GC-enqueue timestamp. Store-open failures should be counted by the embedding
host that observes them; this patch does not invent an in-owner counter for
an owner that could not be constructed.

## Optimization decision

The implemented changes prioritize source consistency, immutable payload
sharing, current-use correctness, diagnostic separation and safe copy-compaction and two-slot owner-local GC.
They do not introduce a WAL, Merkle tree, mutable cache, parallel writer or
weakened fsync boundary. Full-image cloning/serialization/hashing and retained
lifecycle metadata still have size-dependent cost. Use measured scale growth,
write rate, recovery time and capacity pressure to select the next optimization.

Before a performance claim, repeat against the deployment's filesystem and
hardware, with realistic payload/retirement distributions, concurrent readers,
provider latency, restart and long-running metadata growth. Record sample
counts and noise; do not promote diagnostic runner numbers into an SLA.


## Additional measured collection and publication diagnostics

Each existing 1k/8k/16k scale row now includes an actual `inPlaceGc` receipt,
`afterGc` operational gauges and `ioBeforeGc` publication/sync counters. The
collector requires exactly one inactive payload to be removed and cleanup to
finish, rather than accepting a GC function name or a copied checkpoint as
physical reclamation evidence. The fixture still contains one payload at each
scale; it does not establish GC latency for 16k full-sized payloads. Writer and
GC numbers are single observations, not invented p95 or p99 estimates.

The four-lane aggregator checks exact source/base/run/attempt identities,
complete required checks, raw log SHA-256 digests and matching core/product
source trees. A pass is a source qualification result, not deployed-provider
activation or acceptance. Local Python harness tests validate evidence parsing
only; Rust and product tests still have to execute on the exact candidate.


`operational_writer_latency_profile` additionally performs 31 **changed** durable
registrations and 31 durable retirements at each final size 1k/8k/16k, reporting
nearest-rank p50/p95/p99 and max separately. The starting record count is final
size minus 31, not a constant size. Each factor is admitted between the measured
registration and retirement intervals by a test-only governed fixture path;
admission itself is outside those timings and no publisher-grant verification
latency is inferred. The I/O counters include all 93 actual publications. The
JSON schema is `hepta.prompt-registry.writer-profile.v1`. Full request-network
latency, authorization-service latency and deployment SLA remain separate.
