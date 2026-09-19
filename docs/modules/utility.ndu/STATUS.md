# utility.ndu status and claim boundary

This page is the short interpretation guide for the status fields used by the `utility.ndu` documentation set. It grants no effect, activation, acceptance, promotion, signing or release authority.

## Independent status axes

The canonical work-package lifecycle in `TECHNICAL.md`, bounded source maturity in `IMPLEMENTATION_MAP.json`, Lane-D maturity, product composition, exact-head qualification, independent acceptance and release are separate axes. A `planned` delivery package does not mean that no source exists; a `candidate_implemented` source operation does not mean production composition or activation.

The repository-wide `sourceBase` remains a canonical baseline identity. This closure candidate was created from `main@331b81d385a88837e252bd80fda8b8ac35ea4191`. Exact post-base source identity is established by the qualification receipt for the candidate commit/tree, not by relabeling `sourceBase`.

## Current bounded capability

The accurate capability description is:

> deterministic NDU / preference-utility source candidate with a crash-bounded durable projection-store candidate and stochastic numerical compatibility building blocks.

Current source includes:

- policy-bound feasibility, aggregation, Pareto/scalarization and uncertainty handling;
- bounded preference solving where 64-step exhaustion is unavailable rather than a successful terminal state;
- subject-bound local solver receipts with structural validation before protocol publication;
- explicit subject/parent hierarchy staging, allowing siblings and unrelated hierarchies to advance without a global class lock;
- semantic projection-journal recovery with objective/subject-scoped revocation;
- `NduProjectionStoreV1` single-writer, temp-write + file-sync + atomic-rename + parent-directory-sync durability on the Unix qualification profile, poison-on-indeterminate, versioned/checksummed V1 store images, deterministic migration from the predecessor raw-journal image, revocation-reserved retention policy and monotonic backup restore;
- centered conditional covariance/backward-regression numerical support;
- admitted original/whitened Z-coordinate conversion and signed Q24 nearest/ties-to-even conversion receipts with `DENY_ALL` authority.

## Caller truth

Request-local read-only/planning composition is established in the repository through:

- `codex-rs/hepta-control-plane/src/planner_context.rs`;
- `codex-rs/hepta-control-plane/src/planner_ndu.rs`;
- `codex-rs/hepta-intelligence/src/vertical.rs`.

These are real product callsites. They are not an authenticated production NDU owner/caller, do not activate the durable writer, and do not issue effect authority. The authenticated production owner/caller therefore remains not established.

## Production closure remains open

The following gates remain separate and fail closed until evidence exists:

- authenticated production owner/caller composition;
- selected production projection-store host and enrollment;
- target-filesystem durability/recovery qualification, retention policy and restore drills;
- exact-head and synthetic-merge qualification receipts for the selected candidate;
- production stochastic coefficient/profile provenance and consumer admission;
- conditional identification and supported real future-outcome evidence;
- independent well-posedness and convergence decisions owned outside `utility.ndu`;
- immutable training/evaluation lineage sufficient for the selected stochastic profile;
- operator acceptance, activation, canary, promotion and release.

## Stochastic/FBSDE claim boundary

Whitening/Q24 conversion and covariance regression close numerical convention ambiguity only. They do not establish coefficient provenance, conditional identification, well-posedness, longitudinal efficacy, an independent `NduConvergenceCertificateV1`, or a production stochastic consumer.

The next stochastic closure order is therefore:

1. authenticate and bind `NduCoefficientManifestV1` provenance to exact dataset/artifact/profile identities;
2. establish conditional-identification evidence with pre-boundary features and immutable folds;
3. consume independently issued `NduWellPosednessCertificateV1`;
4. bind immutable training/evaluation lineage and future-window outcomes;
5. require the independent convergence/acceptance certificate;
6. only then compose a production stochastic consumer.

## Qualification truth

`.github/workflows/hepta-ndu-recursion.yml` covers pull-request source heads, deterministic synthetic merges, relevant `main` pushes and manual dispatch. It also runs the Control product-caller regression package. The workflow definition is not itself a pass receipt; `exactHeadSourceQualification` stays pending until the exact candidate/head has a successful run.
