# Independent acceptance and release-evidence governance

## Purpose and boundary

`acceptance_governance.py` verifies an externally authored and independently signed review set for one exact `cognitive.store` candidate. It does not merge source, authorize runtime effects, activate a host, publish a generation, erase data or perform a release.

The contract preserves the existing owner and product path. Reviewers evaluate evidence produced by the canonical SQLite owner, `AgentdProductionWriterHost`, the exact source-head/base-merge qualification lanes, selected-host ceremony, retention readiness and per-storage-owner lifecycle reconciliation. The verifier never creates a replacement execution path or signs a review on a reviewer's behalf.

## Signed acceptance plan

The coordinator signs `hepta.cognitive.acceptance-plan.v1`. The plan binds:

- canonical Agent identity;
- exact source commit and tree;
- terminal source-head qualification manifest digest;
- terminal deterministic base-merge qualification manifest digest;
- selected-host qualification report digest;
- retention-readiness report digest;
- lifecycle-reconciliation report digest;
- a distinct independently trusted reviewer and criteria digest for every required role;
- a bounded validity interval.

The required roles are semantic review, durability review, security review, operator acceptance and release approval. The coordinator cannot fill a review role, and one signer cannot collapse multiple independent roles.

## Review receipts

Each reviewer signs `hepta.cognitive.acceptance-receipt.v1`. The receipt repeats the exact source and all five evidence digests, binds the role-specific criteria and records one of `approved`, `rejected`, `pending` or `indeterminate`. Missing or non-approved decisions keep the report incomplete. Changed source, evidence, reviewer, criteria, trust or validity fails closed.

A complete report is named `external_approval_set_verified`. It may report that the supplied external signatures form a complete independent approval set, but it always keeps:

```text
authorized_effects = false
activation_performed = false
release_performed = false
```

Actual activation and release remain separate controlled operations. Repository fixture keys and unit tests do not satisfy the current deployment's acceptance gate.

## Usage

```sh
python3 tools/cognitive-store-host-bootstrap/acceptance_governance.py   --plan /trusted/acceptance-plan.json   --receipts /trusted/acceptance-receipts.json   --trusted-owners /trusted/current-reviewer-trust.json   --expected-plan-sha256 "$REQUESTED_PLAN_DIGEST"   --expected-trust-sha256 "$CURRENT_TRUST_DIGEST"
```

All files use the bounded descriptor-pinned signed-file reader shared with lifecycle reconciliation. Exit code 0 means the complete external approval set was authenticated. Exit code 2 means the set is incomplete. Neither code performs deployment effects.

Review receipt times are monotone in the required semantic, durability, security, operator and release order. The final report repeats every evidence digest from the signed plan.
