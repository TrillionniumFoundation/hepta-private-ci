# kernel.authority clock and evidence hardening — 2026-09-29

Status: source changes and executable evidence checks; **not production acceptance**.

## Development entry and immutable identity

Read `TECHNICAL.md`, then generated `CURRENT_IMPLEMENTATION.md`, then generated
`PORT_MATRIX.md`, followed by the relevant trust, linearization, recovery, or
capacity contract. `qualification/kernel-authority/status_manifest.json` remains
the only source-state manifest. Its `sourceAnchor` names a real ancestor commit
and tree; the eight projections are produced by `generate_status.py`. Updating
an implementation requires a source commit followed by rebinding and regeneration.
The generator rejects changes to mapped files after the anchor. A source anchor
is never a native passing SHA. There is no newly verified native passing SHA in
this remediation record; current execution status belongs to the exact-candidate
CI receipts, not a copied historical assertion.

## Shared clock ownership and irreversible invalidation

`authority_runtime_clock.rs` retains `Arc` ownership of the selected clock and
live custody provider. Sampling serializes custody validation, time acquisition,
post-acquisition custody validation, interval checks and last-observed-time update
under one private sample mutex. The scope is a clock sample, not an authorization
cache or a replacement lease/FinalUse owner. Key custody is re-read after the
potentially slow clock call. Observed invalidity, generation drift, a backwards
time sample, interval underflow/overflow or uncertainty outside the selected
profile permanently fences that wrapper. Temporary provider unavailability emits
no time and does not invent a new trust generation. Mutex poisoning fails closed.
The last sample is only an in-process regression fence; the existing independent
frontier and durable clock floor remain the restart/rollback boundary.

The Agentd private `FeedClock` clears a previous window before replacement
sampling. Observed expiry, out-of-window time or a clock error clears the active
window. A later return to an old wall-clock value cannot resurrect it. Only the
existing signed-feed verification and committed-head publication path can reopen
admission. No public raw-window setter or second feed authority was added.

Existing parent revocation, final-use checks, durable consumption/revocation,
unknown-effect reconciliation and owner-held post-entry receipts are unchanged.
No nonce refund, unknown-operation replay, static-clock fallback or history reset
was introduced.

## Executable port evidence projection

`qualification/kernel-authority/port_acceptance.py` consumes the existing
`runtime_qualification.py` product-pilot receipt and reopens each raw log. It binds
the exact candidate, registered product, command, working directory, log path,
length and SHA-256; then it independently parses the exact executed test set.
Missing/duplicate/zero-test/ignored cases, changed logs, symlinked or escaping
paths, contradictory aggregate flags and production-grant flags are rejected.
The collector is read-only and writes outside the qualified source checkout.

```sh
python3 -B qualification/kernel-authority/port_acceptance.py \
  --identity /evidence/identity.json \
  --pilot-dir /evidence/product-pilot \
  --output /evidence/port-acceptance.json
```

Omitting `--pilot-dir` explicitly reports `nativeEvidence=not-supplied`.
`sourceWired`, `nativePilotVerified`, `nativeIntegrationVerified` and
`productionAccepted` remain separate. Existing Browser/Fleet pilots may establish
only their enrolled pilot scope after byte verification. They do not establish
all seven per-port cuts: queued revocation, parent retirement, epoch change,
pre-effect cancellation, post-effect cancellation, two-product-process recovery
and replay. Those obligations remain explicitly unproved, and full native
integration and production acceptance remain false. This report does not add or
rename a target port or interpret another module's independent protocol as a
kernel.authority integration.

The read-only `kernel-authority-evidence-gate.yml` runs the entire Python evidence
regression suite, verifies generated state and emits an exact-source matrix with
unproved obligations. Its green result would establish parser/source integrity,
not native execution. Native and two-process qualification remain owned by the
existing production-closure and product-process-recovery workflows.

## Production bootstrap boundary

The existing `ProductionAuthorityTrustBundle` production constructors retain the
real provider contract; their runtime clock is hardened here. Normal Agentd's
existing `AgentdFinalUseTrustStore` composition is still a local trust profile.
It must not be relabelled production merely because it owns a signed feed and a
separate directory. Selecting and wiring real deployment clock, frontier and
KMS/HSM providers into normal Agentd/Fleet startup remains necessary. No fixture
provider, new credential, attestation or deployment receipt is fabricated here.
The ordinary startup path must retain its authenticated recovery head and must
not fall back to an unqualified open on failed recovery.

## Performance and validation boundary

The additional custody recheck and serialized sampling have a cost. Measure
contention and provider latency on the selected target before optimizing them.
Do not cache an authorization result, move final-use persistence outside its
owner's atomic boundary, or delete revocation history. The existing 55-row target
matrix, fault cuts and history-sensitive diagnostics remain the performance
acceptance path. This change reports no speedup, percentile or SLO.

New Rust regressions exercise custody rotation during time acquisition, permanent
rollback/invalid-interval fences, shared provider ownership, and feed failure or
invalidation. They are source tests until native execution receipts exist.
Python tests exercise byte-level receipt integrity and source-only nonpromotion.
A target-runbook assertion now normalizes prose whitespace instead of failing
because a sentence was line-wrapped; it retains the prohibition on executing the
untrusted candidate on the privileged target runner.

No production-ready, full-port-complete, successful native compilation, successful
two-process restart, or target-host soak claim is made by this document.
