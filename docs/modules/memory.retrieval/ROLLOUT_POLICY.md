# Protected retrieval rollout policy

Status: source contract and ordinary-process bootstrap wiring. This document does not approve a rollout, prove host isolation, establish an independent operator, or promote `productionImplementation`, `productExecutionProved`, `independentAcceptance`, `activation`, or `release`.

## Ownership

Retrieval delivery is fixed by host composition. Request payloads, model output, tools, memories and agents cannot select `compatibility`, `hnmf-shadow`, `hnmf-canary` or `hnmf-required`, cannot change a canary cohort, and cannot enlarge a shadow budget.

The ordinary Agentd loader accepts two descriptor schemas:

- `hepta.agentd.retrieval-bootstrap.v1` preserves the historical fixed approximately five-percent owner cohort and the existing product structural ceilings. It rejects every v2 rollout field.
- `hepta.agentd.retrieval-bootstrap.v2` requires one complete rollout and shadow-budget policy. Partial policies are invalid; there is no field-by-field fallback to v1.

The descriptor is protected host configuration and is pinned by the exact SHA-256 of its original bytes. A policy change therefore requires new descriptor bytes, a new approved pin and a new process launch. It is not a request-time control surface.

## Descriptor v2 fields

In addition to all v1 fields, v2 requires:

| Field | Meaning | Bound |
| --- | --- | --- |
| `canary_threshold_ppm` | Deterministic owner-cohort fraction | `0..=1000000` |
| `canary_cohort_salt_hex` | Nonzero 32-byte policy-generation salt | 64 lowercase hex characters |
| `shadow_maximum_channel_candidates` | Maximum declared candidates for any channel during non-delivery evaluation | `1..=512` |
| `shadow_maximum_nodes` | Maximum HNMF nodes during non-delivery evaluation | `1..=4096` |
| `shadow_maximum_synapses` | Maximum HNMF synapses during non-delivery evaluation | `1..=32768` |
| `shadow_maximum_settling_steps` | Maximum HNMF settling steps during non-delivery evaluation | `1..=4` |

A zero canary threshold keeps every owner on compatibility delivery while permitting bounded shadow evaluation. One million ppm selects every owner. Intermediate cohorts use a deterministic 64-bit sample derived from the policy salt and exact owner identity. The cutoff is computed in 128-bit arithmetic rather than modulo reduction. The v1 cohort algorithm is retained exactly; upgrading to v2 is an explicit cohort-policy transition.

## Binding and final use

Agentd captures the provider's delivery policy once during process composition. Every routed retrieval lifecycle binding covers:

- delivery mode;
- canary policy version;
- canary threshold;
- canary salt;
- all four shadow structural ceilings;
- the signed publication/frontier lifecycle identity.

Changing any of those values changes the routed binding and invalidates in-flight reads at publication and final-use revalidation. An invalid policy cannot silently become compatibility delivery: canary and required paths fail closed; shadow remains non-exposure and skips failed optional work.

## Shadow and non-delivering canary behavior

`hnmf-shadow` and canary owners outside the delivery cohort use the owner-ranked compatibility result. HNMF is optional evidence only. Before HNMF execution, Agentd validates the context's declared per-channel candidate bound, node count, synapse count and settling-step count against the captured shadow policy. Exceeding any ceiling skips HNMF work and cannot poison compatibility delivery or be recorded as exposure.

These are structural admission ceilings, not CPU, wall-time, allocation or RSS isolation. Separate execution pools, deadlines, cancellation and measured resource enforcement remain required before claiming isolated shadow operation.

## Promotion and rollback

A v2 policy may be promoted only after the exact descriptor, source head, source tree, ordered parents, provider publication and target-host evidence have independent approval. Recommended progression is `0 ppm` shadow, a small approved cohort, staged increases and finally required mode. Each step must use a new salt or an explicitly approved cohort-continuity decision.

Rollback is a host operation: launch compatibility mode or a lower-threshold approved descriptor. Do not edit a live descriptor in place, reuse a digest for different bytes, or treat a failed HNMF request as authority to change the arm. Revocation of the signed context/frontier remains independent from cohort rollback.

## Remaining evidence gates

The source contract does not close these gates:

- native exact-head and ordered-parent synthetic-merge qualification;
- protected launcher/filesystem qualification;
- independently deployed durable frontier recovery;
- CPU/RSS/allocation isolation for shadow execution;
- real encoder/vector-index composition and calibrated OOD/score/coverage policy;
- nine-stage Agentd measurements under concurrency and contention;
- independent reviewer and release-authority approval.
