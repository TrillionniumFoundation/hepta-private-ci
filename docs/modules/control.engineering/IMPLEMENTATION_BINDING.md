# `control.engineering` latest implementation binding

This document binds the canonical Lane G module specification to the current repository-owned implementation. It does not grant independent acceptance, merge, activation, promotion, release, deployment, peer-enrollment, credential, or runtime authority.

## Authoritative source package

- `tools/hepta-engineering-control/control_engineering_v2/`
- public composition boundary: `control_engineering_v2.__init__`
- hardening implementation: `control_engineering_v2/hardening.py`
- component registry: `COMPONENTS.json`
- operation traceability: `TRACEABILITY.json`
- blocker closure registry: `HARDENING.json`
- maturity dimensions: `MATURITY.json`
- failure taxonomy: `HARDENING_FAILURE_CODES.json`
- external gates: `EXTERNAL_GATES.json`

## Repository-owned closure

The implementation provides persistent work envelopes, fenced path leases, deterministic assignment generations, bounded candidate generation, a clean disconnected-clone test boundary, exact evidence verification, separately signed candidate/evidence binding, review-request composition, authenticated dormant assimilation composition, audit projection, schema versioning, replay checks, and negative-path qualification.

Assignment generations bind the exact envelope revision, source identity and active-lease frontier. Owner mutations begin with `BEGIN IMMEDIATE`. Candidate qualification rejects zero checks and detects source HEAD, tree, worktree and ref mutation. Exact-source and synthetic-merge receipts must be fresh, signed and bound to the exact candidate before a review or eligible decision can be recorded.

## Qualification identity

`.github/workflows/hepta-lane-g-engineering.yml` tests the exact source head on Linux, macOS and Windows. Pull requests additionally construct an ordered base/head synthetic merge and rerun the complete Lane G, documentation and repository-integrity gates. The workflow emits content-addressed qualification receipts with `authorityGranted=false`.

## External boundary

The source stops at a review request and a dormant assimilation candidate. Production-grade hostile-workload isolation, organizationally independent evaluator credentials, owner-issued production consent, reviewer acceptance, merge, activation, release and deployment remain external gates and may not be self-asserted by this module or its author.
