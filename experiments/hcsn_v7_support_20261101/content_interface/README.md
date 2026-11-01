# v7 common-content and value-control contracts

Status: **contract fixture implementation; trained adapters and scientific confirmation are unavailable**.

This package isolates two concrete interface problems exposed by the preceding
v6 report: loss of content through a compressed recurrent path, and comparison
of a future strong-head correctness forecast against a different core's maximum
class probability. It does not reproduce that report, load its weights, train a
new core, or establish recognition, mechanism, latency, or economic gains.

## Implemented content boundary

`PrefixObservation` copies supplied feature sequences into immutable tuples of
Python floats. The conversion to binary64 values is explicit. It records object
and event identities, modality, source-prefix end, source availability, completion,
raw content features, aligned features, alignment identity, and aligned source
interval. All times in this support interface use a common episode/source-clock
origin; an eventual native adapter must perform that mapping explicitly.

`VisibleContent.accept` returns a new snapshot. It rejects future completions,
mixed objects, repeated event identities, nonadvancing acceptance time, and any
update other than the next one-second prefix for that modality. Raw and aligned
payloads only become visible after acceptance. Previously returned snapshots stay
unchanged. Identifiers are bounded to 128 UTF-8 bytes and accepted-event metadata
is bounded by the declared budget, six events by default.

**Duplicate cache events raise `ContractError`.** A future scheduler may handle
transport retransmissions idempotently by reusing the already accepted receipt;
it must not call content acceptance or core propagation again. No such scheduler
is implemented here, and this package does not claim an idempotent transport.

The optional pair transform is unavailable when either modality is absent. With
both present, pairing requires identical `alignment_id`, identical
`aligned_window`, and the same aligned feature dimension. Merely having two
nonempty modalities is insufficient. A caller must supply separately computed,
causally valid aligned features for a common interval; this module cannot invent
the missing temporal correspondence or fit its projection.

The common cache's declared capacity is separate from the core:

- `CacheBudget.max_payload_bytes` bounds the retained raw-plus-aligned nominal
  float64 payload: eight times the number of feature scalars in the latest
  accepted audio and video observations.
- `CoreSnapshot` separately holds 32 scalar values, nominally 256 float64 bytes.
  This is **not total model or total content capacity**.
- `storage_accounting()` reports that nominal payload and the runtime
  `sys.getsizeof` total over the snapshot's unique dataclass, tuple and value
  objects. Shared references within that snapshot are counted once.
- This object-graph count is not RSS, PSS, allocator fragmentation, or full-system
  memory. Encoder/readout assets and temporary pairing workspace remain outside
  it and must be measured in actual execution. The cache budget, alignment,
  copy/serialization rules and common head must be identical across A/B/C/D.

## Implemented value interface

The common STOP head receives only `VisibleContent`; a core identity or core
state is not an argument. Its class distribution determines the output class.
Its **separate calibrated correctness prediction** determines STOP value.
`max(class_probabilities)` is never substituted for correctness in the selector.

Each continuation backend predicts the correctness of the same common STOP head
after a legal action. Both current and future values must declare
`correctness_of_common_stop_head.v1` and the same `head_id`. This target is a
semantic contract, not proof that a supplied function is trained or calibrated.
The eventual loader must bind exact fitted asset hashes to the adapters and
validate their predictions on development trajectories.

For a legal next prefix action, the common score is

```text
Q(action) = predicted common-head correctness after action
            - observation_fee
            - latency_weight * expected additional elapsed time
            - deadline_penalty * predicted deadline-miss probability

Q(STOP)   = calibrated current common-head correctness
            - deadline_penalty * 1(current time > deadline)
```

Already incurred costs are common to all alternatives and cancel in this
single-step comparison. Actual incurred costs still need separate execution
accounting. Service-duration and risk forecasts are caller-supplied development
models; no realized future test service time or outcome is supplied by this API.

STOP wins a tie or any nonpositive improvement. It is legal before any observation
and at low confidence. Once the deadline has passed, no continuation reader is
called. Equal positive scores use the same deterministic action-identity tie rule.

A core backend requires a 32-scalar `CoreSnapshot` bound to the exact visible
content fingerprint; a stale state is rejected. A declared direct-history
reference must receive no core state. Each decision records backend kind,
reader identity, optional core identity, content fingerprint and all scored
alternatives. `core_state_supplied_to_reader` records that the reader was called
with state. It **does not prove that a fitted reader uses that state**, or that it
improves quality. State-intervention and fixed-action experiments remain necessary.

## Scope that remains unimplemented

This package implements **STOP and one legal next-prefix READ**. It has no WAIT,
RESET, multi-step lookahead, risk model fit, strong-head fit, action-value training,
core propagator, forced-first-audio scheduler, recovery service, v6 adapter, or
fresh-cohort evaluator. `Purpose.SCIENTIFIC_CONFIRMATION` always raises
`MissingFittedAdapters`; it is not a switch that a metadata flag can enable.

The explicit fixture purpose returns `scientific_execution=False`. Future
integration must implement and freeze actual fitted adapters and the complete
execution path before scientific confirmation can be enabled. Shared identities
alone do not prove semantic nonleakage inside an encoder's feature vector;
feature construction and cohort isolation still require independent auditing.

## Executed checks

Seventeen targeted tests passed in one complete subprocess. They cover immutable
copies, causal acceptance, bounded payload/metadata, object identity, repeated
events, aligned intervals, stale state, common-head value semantics, initial STOP,
deadline handling, and refusal of scientific confirmation without fitted adapters.

The critical non-null fixture changes only a core-supplied forecast while keeping
the common STOP head fixed: it changes the selected action from STOP to READ.
This proves the interface permits core information to affect control. The equal-
forecast fixture gives the core and direct-history reference exactly the same
action and scores. Neither fixture is evidence that an analytic core learns a
useful signal on real data.

The recorded subprocess used 0.072130 user CPU seconds and 0.011205 system CPU
seconds, with 0.196628 seconds wall time and a single-process high-water RSS of
13,893,632 bytes. These are test-execution costs, not candidate economics.
`CONTRACT_TESTS.json` binds exact source and log hashes and keeps both trained
model calls and real AV confirmations at zero. See `CONTRACT_TESTS.log` for all
test outcomes.

From this directory the checks can be reproduced with:

```bash
python3 -m unittest -v test_content_interface
```

No network access, dependency installation, other research-line source import,
Git mutation or old v6 result modification was used in this package.
