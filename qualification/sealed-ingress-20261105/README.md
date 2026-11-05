# Sealed qualification ingress: source and native evidence

The original source handoff below records the four-stage migration before
native formatting and the additional trust-identity regression. Current source
identities, actual native results and limitations are recorded in
[native-validation.md](native-validation.md), [native-source-manifest.json](native-source-manifest.json)
and [validation.json](validation.json). The [convergence target](convergence-target.md)
sets the A/B/C product acceptance boundaries without granting runtime authority.

## Current native result

Exact source `eed6541df0add428add8e2d9ab2cbd54a961abeb` passed the original
unfiltered three-package command: **805/805 tests passed, one slow, 66 skipped**.
All seven critical ingress regressions passed. Four isolated mutation controls
first produced their required behavioral failures and restored the positive
source; Q3's earlier compilation failure remains a separate failed attempt.

The final scoped fix returned zero and produced only one mechanical last-use
clone removal in a plasticity test fixture. Current source
`0766fc4d5feabea9569d48e7eca4e0a3431bd0f5` records that change separately.
No test was rerun after fix, and the E result is not assigned to the later
source. Original CI, production receipt recovery, the real task/effect/restart
chain and independently measured adaptive benefit remain separate requirements.

## Original handoff: candidate and validation state

This is a source migration for the three identified generic signed-evaluation
consumers. It requires the canonical sealed product receipt, revalidates its
exact signed evidence at current use, and retains its qualification/publication
identities in downstream commitments. It does not claim production activation,
native qualification, full receipt recovery, or measured adaptive benefit.

- Original source baseline: `1d87082c0d5afd2b474a2c453ea98005fd540dea`.
- Stacked-PR baseline: `a20a8191ec37375876a99b7c18bae053f9bc185d`.
- All nine existing touched source blobs were independently fetched at exact
  `a20a819` and match the original source baseline. Five source paths are new.
- The contract correction is based on exact `a20a819` contract blob
  `a273b84b031b0884ca995f2f89cbae6b5366429b` and applies after all four code stages.
- Four ordered code patches and their combined patch produce identical bytes
  for all 14 changed source files. Ordered code plus contract and the final
  combined patch produce identical bytes for all 15 changed files.
- All patches passed local `git apply --check`. The original contract's CI
  closure evidence section is byte-for-byte unchanged.
- Root reviewed stage 1; product independently reviewed stages 2–4 and the
  combined source, including exact no-update branch/signing-byte preservation.
- At this original handoff, Rust formatting, compilation, Clippy and native
  tests had **not run**. Later observations are recorded separately above.
  Static review and patch application are not native evidence.

Root created and read back the four source commits below on the intended
`a20a819` base. The compare is four commits ahead, zero behind, and all 14
final source blobs match the frozen manifest. The resulting source head is
`2ac5e02011e480dc39cd84bed655518db2d37a69`, tree
`9c4e0b985d0693d27d24bca5cc3da4491969da80`. These identities establish the
reviewed source bytes; they do not establish native test results or full-tree
caller coverage.

| Source stage | Verified Git commit |
|---|---|
| 1 | `75670fa10204f941e6d34a83282a06453c678308` |
| 2 | `2925932f22d81aeff8b29f1be41febc6ab73f711` |
| 3 | `37ad8694e19879d4e68f7f66519bd1f44e720719` |
| 4 | `2ac5e02011e480dc39cd84bed655518db2d37a69` |

The 14-file source patch is `sealed-ingress-combined.patch`, SHA-256
`18310badac441b743572144b57808cddf0da6863b24b076eb848bb4d11e85c59`.
The 15-file source-plus-contract patch is `stacked-candidate.patch`, SHA-256
`39512552b61fd8935d9c89eef8c91ff3eef147bbaacfe8d0a074a74723254586`.
`combined-manifest.json` and `stacked-candidate-manifest.json` contain each
base blob, final blob and SHA-256, including the final eval `lib.rs` that
combines stages 1 and 4. Only the declared candidate files are represented in these manifests.

## Exact tracked-Rust caller inventory

An isolated checkout at `1d87082c0d5afd2b474a2c453ea98005fd540dea`
verified all 5,309 tracked Rust files (80,594,298 bytes) against their Git blobs.
The broad lexical search ran with a clean checkout before and after, using
`git grep` because `rg` was unavailable. Its complete result is
`caller-inventory-base.txt`: 65 matching lines in 17 source paths.

A separate review compared every baseline match with the exact documentation-only
`a20a819` successor and the verified 14-file source delta at `2ac5e020`.
The derived final inventory is 81 lines in 20 paths, recorded in
`caller-inventory-final-derived.txt` and `caller-inventory-review.json`.
No omitted tracked-Rust consumer or newly required struct construction was
found. Both renamed v1 signing payload references disappear; remaining generic
V2 references stay within the eval crate. This is a source inventory and delta
review, not an executed compiler or a physical product acceptance result.

## Ordered implementation stages

| Order | Patch | Purpose | SHA-256 |
|---|---|---|---|
| 1 | `stage-1-sealed-revalidation.patch` | Shared sealed-receipt/current-evidence check | `3602605a0c3655d1a0da8f09c942d91efaef78d0352886f42f47af3b569388bc` |
| 2 | `stage-2-agentd-sealed-ingress.patch` | Mandatory Agentd receipt and signed use/consumption commitments | `f949ef57ded947e29f2c8bc9bc704fae761ba908b7231decbab9a5f8b0c9ecde` |
| 3 | `stage-3-plasticity-sealed-ingress.patch` | Mandatory candidate receipts and durable proposal commitments | `433bb1b5276fdbcaa2b9203c9df635647b15be48d50dccd7f0cfb6fd9b5e49e5` |
| 4 | `stage-4-self-evolution-sealed-ingress.patch` | Longitudinal ingress, selector commitment and V2 export withdrawal | `2271f0a11ebe1b151580556eafe6c590c0933e9d0a881eecc3a650f98bb8eb07` |
| 5 | `contract/production-contract-sealed-ingress.patch` | Actual source state and remaining host/recovery obligations | `e9d780e91ba1f93e799dd23a43f94243c5194f68996c7b2236b64f9772740d19` |

Stage 4's eval `lib.rs` base is stage 1's blob
`3158743fd82bb4b05156c952f10467308800eac5`; the final blob is
`3fb8fe09947c342710f9cc982bd14f2015abb58c`. Apply stages in order, or apply the
combined patch once. Preserve the four code stages as separate review commits.
Any native formatting or compile correction creates a new candidate identity
and requires refreshed manifests and review of the actual changed bytes.

## Exact evidence binding

`revalidate_product_qualification_v1` validates the receipt's private seal,
compares its complete generator/evaluator principals and public context with
the supplied raw bundle, and normalizes snapshot IDs exactly as the product
runner does. It selects Qualification or SystemLongitudinal explicitly and
reruns the existing signed admission under the current host-owned verifier
and clock. The result must equal the **complete** `SignedEvaluationDecisionV1`
inside the sealed receipt.

The decision evidence digest commits the raw bundle, including frozen plan,
holdout use, metrics, estimates/support, lineage and claim-scope evidence. The
existing authentication digest commits the host trust digest and the exact
generator/evaluator signing bytes and signatures. The evaluator's signed
payload includes the metric roles; V3 also binds the observer/time evidence
and minimum future-window policy. Thus a valid new signature over different
metrics, roles, timing, or attestation metadata cannot substitute for the
published qualification merely by producing the same eligibility label.
The current clock is used again for admission; it is not replaced by the
original receipt's historical verification time.

Agentd and parameter plasticity use Qualification mode. Agentd retains its
existing millisecond clock semantics and never passes that clock into the V3
microsecond interface. Self-evolution uses SystemLongitudinal, the original
raw time evidence and current minimum-window policy, then retains the existing
authoritative dataset/ledger checks, minimum record count, G/E/O checks and
independent selector separation. No external principal assertion becomes
authentication, and all evaluation decisions remain `DENY_ALL`.

## Downstream commitment and compatibility

| Consumer | Mandatory source change | Commitment and compatibility |
|---|---|---|
| Agentd | `AgentdSignedEvaluationV1.qualification`; sealed revalidation before candidate use | `intelligence_evaluation_binding_payload_v2` and `hepta.agentd.evaluation-use.v2` bind qualification evidence and publication; `hepta.agentd.evaluation-consumption.v2` retains both in preparation |
| Parameter plasticity | `CandidateEvaluationAdmissionV1.qualification` for every update candidate | `hepta.intelligence.plasticity-evaluations.v2` includes both identities; existing governed admission, durable proposal and composition digests carry the commitment |
| Self-evolution | Mandatory receipt argument to `prepare_self_evolution_selection_v1` | Receipt stores both identities; `selection_signing_payload_v2`, `self-evolution-selection.v2` and `self-evolution-selection-receipt.v2` bind them; rollback remains bound through the selection digest |

The Agentd v1 use-signing API and selector v1 signing API are renamed; callers
must migrate and re-sign. The generic signed V2 re-export becomes `pub(crate)`
only after all three known consumers are migrated; V3 is also crate-internal.
Trusted in-process compatibility remains behind its existing explicit feature.
The candidate adds no zero digest default, old-signature fallback or replay
upgrade. It does not alter the already repaired ProductQualificationReceipt
seal domains on the first-wave baseline.

`NoAdmissibleUpdate` keeps its existing independent evaluator attestation,
empty candidate evaluations, original signing functions and v1 evaluation
commitment bytes. The returned qualifications list is empty. It neither
requires nor manufactures a candidate qualification.

The proposal-registry codec remains readable. Readability does not confer new
qualification on an old proposal: a different qualification/publication
commitment changes the proposal identity and cannot replay as the old one.
The existing append implementation checks an identical proposal before a stale
predecessor, so the publication-substitution regression exercises commitment
integrity rather than merely triggering predecessor rejection.

Generator freeze and evaluator bundle signatures precede publication and are
not modified to include a later publication digest. The existing Agentd use
and selector signatures bind that later identity; plasticity retains it in the
existing owner-controlled durable proposal. No new signing authority is
invented. Revalidation and a new use signature never consume a final holdout
again or authorize bypassing the authoritative one-use owner.

## Native acceptance protocol

Follow repository AGENTS and the existing toolchain. From `codex-rs`, run:

```sh
just fmt --base 432421d0d9ca9d82c5e3401fe3425af29131505a
just fmt --base 4e31abc907f09740d402d1ddef7a1d2fe0a366a6 --check
# Run each isolated mutation control and restore the positive source.
just test --locked -p codex-hepta-intelligence-eval -p codex-hepta-agentd -p codex-hepta-intelligence
just fix --locked -p codex-hepta-intelligence-eval -p codex-hepta-agentd -p codex-hepta-intelligence
```

Use the explicit source identity and order in the native validation plan.
Scoped fix is last; preserve and review any resulting diff and distinguish its
new source identity from the tested source. Do not rerun tests merely after fix
or formatting. A concrete new defect or a required gate needs its own record.

The formatter needs the explicit comparison base: a clean published checkout
has no uncommitted source changes, so bare `just fmt` would skip this candidate.
Use the repository `just test` interface, not a substitute direct test command.
The complete three-package run compiles the identified construction sites and
shared signed-integration fixtures; the exact-tree inventory may require
additional consumer builds. Also search the exact assembled checkout for old
cross-crate V2 and v1 payload callers; GitHub code search indexes the default
branch and is not exact candidate-tree proof.
Any prescribed broader CI checks remain unchanged. Exact-head and
ordered-parent synthetic-merge Lane E artifacts, coverage, repeated fenced
holdout stress and signed cross-crate E2E evidence are still required before
`source_qualified_exact_head` may be claimed.

### Meaningful regression coverage in the new source

| Test | Required behavior |
|---|---|
| `product_runner_binds_estimator_receipts_and_persists_signed_decision` | Exact runner receipt revalidates; legal current-trust re-signing with the same inner decision, valid re-signed different metrics, new evaluator attestation metadata, roles, expired evidence and modified publication are rejected without another publish/release |
| `independently_resigned_metrics_cannot_replace_the_qualified_estimator_evidence` | Agentd rejects a valid new bundle/use signature paired with the old qualification |
| `current_use_attestation_binds_the_exact_sealed_publication` | Agentd rejects an old use signature for a different legitimate publication; a correct new signature succeeds |
| `signed_generic_metrics_cannot_replace_the_product_qualification_before_append` | Plasticity rejects substituted validly signed metrics before registry or anchor changes |
| `durable_proposal_identity_commits_the_exact_qualification_publication` | Two legitimate publications of the same decision produce different proposal commitments; the second cannot replay as the first |
| `sealed_longitudinal_qualification_reaches_public_preparation_and_independent_selector` | Actual runner SystemLongitudinal receipt reaches public prepare, separate selector admission and rollback |
| `valid_v3_resignatures_cannot_replace_published_metrics_or_time_policy` | Changed metrics, or legal re-signed minimum-window 5→6 with the same inner decision, cannot replace the published receipt |
| `public_preparation_retains_observed_time_and_authoritative_dataset_checks` | Observer time, minimum record count and actual ledger source membership still reject invalid input |
| `selector_signature_commits_the_exact_qualification_publication` | Actual selector admission rejects another publication under the old signature and accepts its correct signature |

Existing G/E and O/E controller-collision tests remain. Their updated fixtures
qualify first under independent trust, then change current host trust so the
consumer exercises the actual separation boundary. The expiry regression is
an expiry test, not a claim that every revocation path was exercised.

### Behavioral mutation controls

Four independent patches in `negative-controls/` each remove one production
binding from the final positive stack while preserving identical tests.
They are mutations of the migrated implementation, not a literal old-baseline
build. Apply each to a fresh isolated positive candidate and run its relevant
named regression. A compilation failure is not a useful negative result;
require the test to compile and fail because the forbidden substitution is
accepted. Restore the positive candidate between controls.

| Control | Sole removed binding | Most direct regression |
|---|---|---|
| `negative-complete-decision-binding.patch` | Full signed-decision equality in the shared helper | Product-runner binding test and self-evolution valid V3 re-signature test |
| `negative-agentd-publication-signature.patch` | Qualification identities in the Agentd use-signing bytes | `current_use_attestation_binds_the_exact_sealed_publication` |
| `negative-plasticity-publication-commitment.patch` | Qualification identities in the per-candidate durable commitment | `durable_proposal_identity_commits_the_exact_qualification_publication` |
| `negative-selector-publication-signature.patch` | Qualification identities in selector signing bytes | `selector_signature_commits_the_exact_qualification_publication` |

The original negative patches passed local application checks at the source
handoff. Native formatting changed the shared-helper guard layout; its control
was regenerated with identical mutation semantics and unchanged tests. Current
patch hashes and execution observations are in `negative-controls/manifest.json`
and `native-validation.md`. Compiler or setup failures never count as a
behavioral negative result.

## Remaining production obligations

1. A named production final-holdout data provider and qualification evidence
   sink are not connected to these consumers. The concrete file CAS backend
   provides storage/fencing semantics, not authenticated observations or a
   production publication authority.
2. A complete persisted ProductQualificationReceipt codec and qualified
   readback/handoff are missing. The plasticity registry preserves digest
   commitments; returned full qualifications exist in memory. The sink trait
   receives temporal execution identity plus SignedDecision, not a full sealed
   receipt recovery format.
3. The default canonical Agentd host still lacks a durable seven-owner/App
   Server handoff and authenticated Decision/Outcome composition through the
   existing LedgerWriter. Optional legacy PendingIntelligenceLedgerAppendV1
   is only an in-memory qualification carrier. This migration does not close
   the A-line task/result/restart chain.
4. New fixture CAS and publication implementations are explicitly test-only.
   Self-evolution uses synthetic signed windows and an in-memory ledger-core
   snapshot; these test structural admission and membership, not durable
   production writer provenance or real future-calendar efficacy.
5. Independent selection, current-owner effect authorization, external
   acceptance, canary and release evidence remain separate. A proposal,
   shadow Decision or selection token is not a physical effect. No stronger
   baseline result or measured adaptive improvement is asserted by this patch.

The exact-source native observations and independently reviewed mutation
results are recorded in `native-validation.md` and `validation.json`. The
historical source handoff, frozen plans and failed attempts retain their
original states. The production obligations above remain open after package
validation; this is not a declaration of complete product readiness.
