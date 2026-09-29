# Selected-host qualification evidence

## Purpose and boundary

`host_qualification.py` verifies externally produced, independently signed evidence for the selected production host. It does not perform recovery, issue authority, execute a canary, inject a filesystem fault, accept an SLO, activate a deployment or approve release.

The verifier preserves the existing architecture: `hepta-memory::CognitiveStore` remains the only physical owner and `AgentdProductionWriterHost` remains the semantic-write façade. The host ceremony observes that path; it does not introduce another database, writer or test-only product entry.

A complete report is deliberately named `owner_attested_complete`. The report keeps `target_host_qualified`, `slo_accepted`, `activation_authorized` and `release_authorized` false. Those decisions require independent review outside this repository.

## Signed plan

The coordinator signs `hepta.cognitive.host-qualification-plan.v1`. The plan binds:

- canonical Agent identity;
- exact deployed source commit and tree;
- writer generation and authority-grant digest;
- exact-current-cut recovery witness and independent custody digest;
- host and filesystem identities;
- the selected SLO profile;
- one independent executor and evidence-profile digest for every required step;
- a bounded validity interval.

The required steps are:

1. exact-cut signed bootstrap;
2. post-pointer-rename directory-`fsync` failure, producing an explicit indeterminate result while retaining the possibly active candidate;
3. committed canary that advances the semantic cut;
4. abrupt crash and restart at the exact successor cut;
5. stale-witness rejection followed by governed current-cut reconciliation;
6. live revocation that preserves committed history and denies a later write;
7. rollback through a fresh writer generation without semantic-cut regression;
8. 256-record optimized recovery measurement;
9. 16,384-record optimized recovery measurement.

The host independently pins the expected plan digest and current trust digest. Neither value may be copied from the input under verification.

## Owner receipts

Each planned executor signs `hepta.cognitive.host-qualification-receipt.v1`. A receipt binds the exact plan, source objects, writer generation, host/filesystem identities, before/after cuts, disposition, observation time and evidence/metrics digests.

Completed canary and witness-gap steps must advance their cut. Every other completed step must preserve the semantic cut. In particular, the expected `Indeterminate` result of the injected publication fault is a successful qualification observation only when the candidate was retained; it is not rewritten as an ordinary successful recovery.

Missing, pending, indeterminate or failed owner receipts keep the report incomplete. A coordinator cannot sign an executor receipt, duplicate steps are rejected, and current trust is reread after verification before a report is returned.

## Usage

```sh
python3 tools/cognitive-store-host-bootstrap/host_qualification.py \
  --plan /trusted/host-qualification-plan.json \
  --receipts /trusted/host-qualification-receipts.json \
  --trusted-owners /trusted/current-owner-trust.json \
  --expected-plan-sha256 "$REQUESTED_PLAN_DIGEST" \
  --expected-trust-sha256 "$CURRENT_TRUST_DIGEST"
```

All files use the bounded, no-follow signed-file reader shared with lifecycle reconciliation. Exit code 0 means all required owner receipts were authenticated. Exit code 2 means the evidence set is incomplete. Neither code is an activation or release decision.
