# Independent acceptance and release-evidence governance

## Purpose and boundary

`acceptance_governance.py` verifies an externally authored and independently signed review set for one exact `cognitive.store` candidate. It does not merge source, authorize runtime effects, activate a host, publish a generation, erase data or perform a release.

The contract preserves the existing owner and product path. Reviewers evaluate evidence produced by the canonical SQLite owner, `AgentdProductionWriterHost`, the exact source-head/base-merge qualification lanes, selected-host ceremony, retention readiness and per-storage-owner lifecycle reconciliation. The verifier never creates a replacement execution path or signs a review on a reviewer's behalf.

## Signed acceptance plan

The coordinator signs `hepta.cognitive.acceptance-plan.v5`. The plan binds:

- canonical Agent identity;
- exact source commit and tree;
- canonical committed qualification-plan digest;
- terminal source-head qualification manifest digest;
- terminal deterministic base-merge qualification manifest digest;
- selected-host qualification plan and report digests;
- retention-checkpoint plan and readiness-report digests;
- lifecycle plan and reconciliation-report digests;
- a distinct independently trusted reviewer and criteria digest for every required role;
- a bounded validity interval.

The required roles are semantic review, durability review, security review, operator acceptance and release approval. The coordinator cannot fill a review role, and one signer cannot collapse multiple independent roles.

## Coherent bound evidence bundle

Digest strings alone are not accepted. The verifier also consumes a bounded descriptor-pinned JSON evidence bundle containing exactly nine objects: the canonical qualification plan, two qualification manifests, the selected-host plan/report pair, the retention plan/report pair and the lifecycle plan/report pair. For every object it recomputes the canonical digest and compares it to the signed acceptance plan before validating its schema and outcome.

The source-head and base-merge manifests must be v2 terminal-success manifests with no identity errors, complete passing command records, retained evidence and no escalated host, acceptance or release claims. Their command records and retained artifacts must match the exact committed qualification-plan inventory: a one-command or one-artifact success-shaped manifest cannot stand in for the full plan. Exit codes, timeout/output-limit state, test thresholds, command identities and log identities are revalidated. The source-head must test the exact acceptance source commit/tree. The base-merge must bind the frozen base/source parent pair and the same source commit.

The selected-host report must bind the supplied selected-host plan, contain the complete ordered ceremony, use a strictly newer rollback generation and fresh rollback authority grant, and keep target-host qualification, SLO acceptance, activation and release authorization false. The selected-host plan must name the same Agent and source as the acceptance plan.

The retention report must bind the supplied checkpoint plan, contain all completed segment-owner and rebuild receipts, preserve the signed segment aggregate, and keep publication, pruning and erasure claims false. The checkpoint plan must name the same Agent and source, and its `current_cut_sha256` and `writer_generation` must equal the selected-host report's qualified cut and final writer generation.

The lifecycle report must bind the supplied lifecycle plan, cover all nine storage classes with completed owner observations, and keep effect, physical-erasure and host-qualification claims false. The lifecycle plan must name the same Agent and must use the same qualified cut and writer generation as the selected-host and retention evidence.

This cross-binding prevents five individually valid-looking reports for different Agents, cuts, generations or candidates from being combined into one approval set. Raw plan payloads are context evidence already named by the corresponding verifier reports; this verifier does not mint or replace their external signatures.

The complete bundle is reread after signature and review verification. A same-path replacement or changed report/plan set cannot produce an acceptance result from earlier bytes.

## Review receipts

Each reviewer signs `hepta.cognitive.acceptance-receipt.v5`. The receipt repeats the exact source and all nine evidence digests, binds the role-specific criteria and records one of `approved`, `rejected`, `pending` or `indeterminate`. Missing or non-approved decisions keep the report incomplete. An approval cannot follow a supplied earlier review that is pending, rejected or indeterminate; in particular, release approval cannot sit on top of non-approved operator acceptance. Missing earlier receipts keep the set incomplete rather than manufacturing a prerequisite. Changed source, evidence, reviewer, criteria, trust or validity fails closed. Each approved role must also bind a distinct review artifact digest; one review document cannot be replayed as several independent reviews or collide with a plan/report identity. V1–V4 artifacts are not silently reinterpreted under this coherent-context contract.

A complete v5 report is named `external_approval_set_verified` and sets both:

```text
all_bound_evidence_reports_validated = true
all_bound_evidence_context_coherent = true
```

It also repeats the selected-host `qualified_cut_sha256` and `qualified_writer_generation`. These are evidence identities, not write authority. The report always keeps:

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

The evidence bundle has exactly these keys, each holding the corresponding JSON object rather than a pathname or bare digest:

```text
qualification_plan_sha256
source_head_manifest_sha256
base_merge_manifest_sha256
host_qualification_plan_sha256
host_qualification_report_sha256
retention_checkpoint_plan_sha256
retention_readiness_report_sha256
lifecycle_plan_sha256
lifecycle_reconciliation_report_sha256
```

All files use the bounded descriptor-pinned signed-file reader shared with lifecycle reconciliation. Exit code 0 means the complete external approval set and all bound evidence contents and contexts were authenticated. Exit code 2 means the review set is incomplete. Neither code performs deployment effects.

Review receipt times are monotone in the required semantic, durability, security, operator and release order. The final report repeats every evidence digest from the signed plan.
