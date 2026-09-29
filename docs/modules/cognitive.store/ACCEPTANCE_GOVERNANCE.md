# Independent acceptance and release-evidence governance

## Purpose and boundary

`acceptance_governance.py` verifies an externally authored and independently signed review set for one exact `cognitive.store` candidate. It does not merge source, authorize runtime effects, activate a host, publish a generation, erase data or perform a release.

The contract preserves the existing owner and product path. Reviewers evaluate evidence produced by the canonical SQLite owner, `AgentdProductionWriterHost`, the exact source-head/base-merge qualification lanes, selected-host ceremony, retention readiness and per-storage-owner lifecycle reconciliation. The verifier never creates a replacement execution path or signs a review on a reviewer's behalf.

## Signed acceptance plan

The coordinator signs `hepta.cognitive.acceptance-plan.v3`. The plan binds:

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

## Bound evidence bundle

Digest strings alone are not accepted. The verifier also consumes a bounded descriptor-pinned JSON evidence bundle containing exactly the five report objects named above. For every object it recomputes the canonical digest and compares it to the signed plan before validating the report's schema and outcome.

The source-head and base-merge manifests must be v2 terminal-success manifests with no identity errors, complete passing command records, retained evidence and no escalated host, acceptance or release claims. The source-head must test the exact plan commit/tree. The base-merge must bind the frozen base/source parent pair and the same source commit.

The selected-host report must contain the complete ordered ceremony, a strictly newer rollback generation, a fresh rollback authority grant and completed post-rollback recovery profiles, while keeping target-host qualification, SLO acceptance, activation and release authorization false. The retention report must contain all completed segment-owner and rebuild receipts, a consistent segment count, and no publication, pruning or erasure claims. The lifecycle report must cover all nine storage classes with completed owner observations while keeping effect, physical-erasure and host-qualification claims false.

The bundle is reread after signature and review verification. A same-path replacement or changed report set cannot produce an acceptance result from earlier bytes.

## Review receipts

Each reviewer signs `hepta.cognitive.acceptance-receipt.v3`. The receipt repeats the exact source and all five evidence digests, binds the role-specific criteria and records one of `approved`, `rejected`, `pending` or `indeterminate`. Missing or non-approved decisions keep the report incomplete. An approval cannot follow a supplied earlier review that is pending, rejected or indeterminate; in particular, release approval cannot sit on top of non-approved operator acceptance. Missing earlier receipts keep the set incomplete rather than manufacturing a prerequisite. Changed source, evidence, reviewer, criteria, trust or validity fails closed. V1 and V2 artifacts are not silently reinterpreted under this content-validated evidence contract.

A complete v3 report is named `external_approval_set_verified` and sets `all_bound_evidence_reports_validated=true`. It may report that the supplied external signatures form a complete independent approval set, but it always keeps:

```text
authorized_effects = false
activation_performed = false
release_performed = false
```

Actual activation and release remain separate controlled operations. Repository fixture keys and unit tests do not satisfy the current deployment's acceptance gate.

## Usage

```sh
python3 tools/cognitive-store-host-bootstrap/acceptance_governance.py \
  --plan /trusted/acceptance-plan.json \
  --receipts /trusted/acceptance-receipts.json \
  --evidence-bundle /trusted/acceptance-evidence.json \
  --trusted-owners /trusted/current-reviewer-trust.json \
  --expected-plan-sha256 "$REQUESTED_PLAN_DIGEST" \
  --expected-trust-sha256 "$CURRENT_TRUST_DIGEST"
```

The evidence bundle has exactly these keys, each holding the corresponding JSON report rather than a pathname or bare digest:

```text
source_head_manifest_sha256
base_merge_manifest_sha256
host_qualification_report_sha256
retention_readiness_report_sha256
lifecycle_reconciliation_report_sha256
```

All files use the bounded descriptor-pinned signed-file reader shared with lifecycle reconciliation. Exit code 0 means the complete external approval set and all bound report contents were authenticated. Exit code 2 means the review set is incomplete. Neither code performs deployment effects.

Review receipt times are monotone in the required semantic, durability, security, operator and release order. The final report repeats every evidence digest from the signed plan.
