# Same-processor typed-channel versus UDS probe

This bounded probe compares the existing typed in-process request/event facade with an added same-process UDS WebSocket bridge, above one real AppServer MessageProcessor. It does not switch the Agentd production transport.

## Registered measurement shape

- 32 warm-up pairs; 256 measured pairs; alternate which transport runs first.
- Two equivalent ephemeral threads, `thread/settings/update` requests and matching `thread/settings/updated` events.
- One outstanding request; explicit bridge queue capacity 8.
- Last serialized request / event-params sizes: 318 / 558 bytes.
- No model turn, provider request or token consumption.
- Linux x86_64 debug test build, under the same durable job CPU quota 200% and memory ceiling 8 GiB.
- Other isolated build/test jobs were active on this host. Pairing reduces temporal drift but does not remove host interference.
- Setup is reported separately: 2.086 s.

## Observed result

| Measurement | p50 | p95 |
|---|---:|---:|
| Typed request + event | 2.620 ms | 3.093 ms |
| UDS bridge request + event | 3.918 ms | 4.664 ms |
| Paired UDS minus typed | 1.288 ms | 1.961 ms |

These are descriptive quantiles from one run, not confidence intervals or independent host replications. The raw nanosecond values are retained in `measurement.json`.

## Decision boundary

Keep the backend interface independent of transport and retain the existing production UDS path until owner bindings are carried through direct startup. The upstream direct startup currently uses absent Hepta extension bindings. A faster local transport without those bindings is not an equivalent execution backend.

This test does not measure model latency, whole-agent task success, token usage, process-tree RSS, overload, cancellation under load or large streaming payloads. The upstream facade has an unbounded internal consumer event queue; one outstanding request bounds this probe's backlog only. No production memory or backpressure guarantee follows.

## Reproduction and provenance

Run from `codex-rs`:
```
just test -p codex-app-server-client --lib same_owner_typed_and_uds_transport_probe -- --ignored --nocapture
```

Actual test job: `1a16c8d19a4-1b6abb-45c8`.
Test source parent: `96917c8eac7b109e2a0d94eb6b54b29fbeec7d39`.
The source hashes in `provenance.json` identify the exact unformatted input tested, before the required fix/format pass. The experiment adds no production configuration or service change.
