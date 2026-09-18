# inference.worker production readiness and runbook

This document answers one operational question: **what must be true before `inference.worker` may be described as production-ready or activated?**

It does not replace `TECHNICAL.md`, `IMPLEMENTATION_MAP.json`, the Lane B execution dossier, or independently retained CI/qualification receipts. It turns their current open gates into one fail-closed checklist.

## 1. Current claim boundary

At the time this document was added, the canonical implementation map keeps all of the following false:

- `productionImplementation`
- `productExecutionComplete`
- `deploymentQualificationComplete`
- `independentAcceptanceComplete`
- `productExecutionProved`
- `independentAcceptance`
- `activation`
- `release`

Do not flip any of those claims from documentation alone.

## 2. Grant trust boundary

`model_worker::ResourceGrant` is currently an **in-process trusted capability representation**, not a self-authenticating network credential.

The worker validates the grant's local structure and current semantics (identity shape, semantic digest shape, generation, epoch, expiry, revocation flag and bounded capacities). It does **not** independently prove who minted the object, fetch authority state, validate a detached signature, or perform an online epoch/revocation lookup.

Therefore:

1. raw untrusted IPC/network payloads MUST NOT be deserialized or translated directly into `ResourceGrant` and treated as authority;
2. the component crossing an IPC/network/process trust boundary MUST authenticate the peer and validate the authoritative lease/grant before constructing the in-process value;
3. if `ResourceGrant` becomes a wire contract, the same change MUST add explicit issuer identity, signed or MAC-bound semantics (or an equivalently strong authenticated transport-bound capability), replay/freshness rules, and a worker-side verifier;
4. tests that construct `ResourceGrant` directly are fixtures and do not prove production authority authenticity.

A future implementation may move verification into this crate, but until that happens the trusted-constructor boundary is part of the security contract.

## 3. Isolation guarantees and non-guarantees

The current worker proves these isolation properties:

- exact Agent identity and generation fencing for the hosted App Server profile;
- fresh ephemeral hosted thread execution per newly admitted request;
- read-only App Server sandbox selection for the hosted profile;
- bounded prompt, context, output, token, model-count and local in-flight request limits;
- no model/tool approval authority is granted by the worker;
- uncertain post-dispatch execution is not automatically replayed.

The module does **not by itself** prove all host-security isolation properties for local-model execution. In particular, production local inference must not claim OS/device isolation until the selected launcher/runtime supplies and qualification proves the applicable controls, including:

- process/user or namespace isolation;
- cgroup or equivalent CPU/RAM limits;
- GPU/device ACL or device-lease enforcement;
- accelerator-memory admission and release;
- seccomp/system-call or equivalent sandbox policy where required;
- filesystem/model-artifact read boundaries;
- authenticated control transport when the worker is a separate process.

The deployment owner must record which layer enforces each property. "Isolated inference worker" must never be interpreted as proof of a complete host sandbox without that evidence.

## 4. Local-model production gate

Production local inference remains blocked until a non-test `ModelDriver` proves the complete path:

`verified manifest -> immutable weights/tokenizer/runtime -> device lease -> memory reservation -> load -> infer -> usage observation -> unload/release`.

Required evidence:

- exact weights, tokenizer, preprocessing, quantization, runtime and device digests;
- observed memory reservation versus peak use;
- no inference before all manifest/grant bindings pass;
- unload releases every acquired resource;
- cancellation and driver failure do not leak handles, memory, locks or device reservations;
- model/runtime substitution fails closed.

The injected unit-test driver is not acceptable evidence for this gate.

## 5. Provider reconciliation gate

For the hosted App Server path, transport loss after `turn/start` is intentionally indeterminate and must not be replayed.

Production recovery is complete only when a trusted provider execution identity can be reconciled after worker loss. The selected design must provide:

- stable provider execution identity bound to the durable request;
- replay-safe/idempotent dispatch semantics or a provider receipt that makes replay unnecessary;
- authenticated query/reconcile of terminal state after restart;
- reconciliation of late/missing token usage without inventing zero usage;
- bounded retention for provider execution identities and receipts;
- tests for crash before dispatch, during dispatch, after provider acceptance, after terminal provider state, and before durable settlement.

Until this gate closes, `indeterminate` is the correct safe outcome.

## 6. Product composition gate

A release candidate must name and prove the actual production caller and writer path:

`product caller -> authority/admission -> inference.control -> inference.worker -> selected provider/runtime -> durable terminal observation`.

Shadow, fixture, qualification-only and test callers do not satisfy this gate.

## 7. Hardware/runtime qualification matrix

The exact selected model/runtime/device combination must execute the following on the target host class.

| Case | Required observation |
|---|---|
| cold load / warm reload | exact artifact/runtime/device identity and bounded load latency |
| CPU and/or GPU inference | exact selected device, output terminality and usage |
| concurrent requests at grant ceiling | bounded admission; no oversubscription |
| request above grant ceiling | rejection before resource acquisition |
| model exceeds memory grant | deterministic rejection/release |
| real OOM | no fabricated success; resources recover or worker is fenced |
| cancellation during inference | terminal/cancel semantics and no resource leak |
| cancellation during unload | bounded drain and deterministic final ownership |
| driver crash | no duplicate execution; recovered resources/fencing |
| device reset/loss | failed or indeterminate outcome; no stale-success commit |
| repeated load/run/unload | stable descriptor/RAM/VRAM baseline within declared tolerance |
| App Server kill/restart | no blind provider replay; durable state remains coherent |
| worker kill at every durable boundary | restart result matches the durable journal and provider reconciliation contract |

Measurements and tolerances belong to the selected deployment profile; they must be retained as exact-candidate evidence, not copied into this document as synthetic pass claims.

### Machine-verifiable target-host evidence

The hardware matrix is paired with a fail-closed machine contract in
`scripts/hepta-inference-worker-readiness.py`. `--emit-hardware-template`
creates a deliberately non-passing `hepta.inference-worker-hardware-qualification.v1`
template; `--verify-hardware-evidence` accepts only an exact candidate-bound
record with all required model/device identities, isolation controls, target-host
scenarios and independent-observer fields complete.

The contract requires the candidate commit/tree/worker subtree, the digest of
the exact-candidate readiness receipt, host attestation identity, model/weights/
tokenizer/preprocessor/quantization/runtime/device digests, six named isolation
controls and all thirteen scenarios in the matrix above. Missing, duplicate,
`pending`, skipped or candidate-mismatched evidence fails verification.

Repository/unit CI validates the contract and its negative cases only. It must
not convert fixtures, mocks or a structurally valid JSON object into a claim
that real hardware ran. Physical attestation, raw measurements and observer
authenticity remain evidence-system responsibilities outside this module.

Generate a fail-closed template on the target candidate:

```sh
python3 scripts/hepta-inference-worker-readiness.py \
  --expected-sha "$(git rev-parse HEAD)" \
  --emit-hardware-template /secure/qualification/inference-worker-hardware.json
```

After the designated target-host owner fills it from real execution, validate:

```sh
python3 scripts/hepta-inference-worker-readiness.py \
  --expected-sha "$(git rev-parse HEAD)" \
  --verify-hardware-evidence /secure/qualification/inference-worker-hardware.json
```

## 8. Exact-candidate evidence binding

For every release candidate, retain a machine-readable receipt that includes:

- candidate commit, repository tree and exact worker subtree;
- the current implementation-map blob plus its historical `sourceBase`;
- the worker paths changed since that historical map source base;
- hash of `TECHNICAL.md`, this runbook, the implementation map and Lane B workflow;
- the exact evidence class and named checks executed for that candidate;
- current claim-boundary flags;
- repository-controlled gaps and external evidence gates.

The repository script `scripts/hepta-inference-worker-readiness.py` emits
schema `hepta.inference-worker-candidate-receipt.v2`. `sourceBase` remains
historical map provenance; `candidate.workerTree` is the current executable
source anchor. A non-empty source delta is therefore visible in the receipt
instead of being silently hidden by an older documentation snapshot.

The Lane B source-head and deterministic merge-candidate jobs emit a
`source-head-tested` or `merge-candidate-tested` receipt only after the
`codex-hepta-infer-core --lib` and `codex-hepta-infer-worker-host --lib`
suites succeed at that exact checkout. The documentation workflow may emit
the weaker `identity` class. No class is hardware, provider-reconciliation,
deployment or independent-acceptance evidence.

Target-host hardware evidence is separate and must validate against the same
candidate identity using the machine contract in Section 7. Do not merge
source/test identity and physical qualification into one self-issued claim.

## 9. Rollback and stop conditions

Stop activation or roll back on any of the following:

- authority issuer/epoch/generation ambiguity;
- model/runtime/device identity drift;
- unresolved provider execution identity after a path that claims terminal success;
- resource accounting exceeding the grant;
- repeated OOM/device-reset without deterministic fencing;
- inability to unload/release acquired resources;
- evidence bound to a different candidate revision;
- product caller or durable writer path differs from the qualified composition.

Rollback drains new admission first. Do not mix old and new model/runtime identities inside one worker generation.

## 10. Activation checklist

Activation requires all of the following to be independently true:

- real local driver gate closed if local inference is enabled;
- provider reconciliation gate closed for any provider path that can outlive the worker;
- named product caller and durable writer composed;
- target host isolation controls documented and proven;
- hardware/runtime qualification matrix passed on the selected host/model/runtime;
- exact source-head and merge-candidate receipts retained;
- security-authority deputy review completed;
- independent acceptance recorded outside the module's self-generated evidence.

Until then, keep production/activation/release claim flags false.
