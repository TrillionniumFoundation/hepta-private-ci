# Governed self-iteration execution specification

**Overlay:** `HEPTA-V8-PRECODING-READINESS` v8.2.0-readiness
**Bound modules:** `learning.plasticity`, `control.engineering`, `learning.eval`, `learning.artifacts`, `intelligence.control`, `kernel.evidence`

## 1. Scope and authority boundary

Self-iteration means generating bounded candidates and evidence, not autonomously replacing production code, parameters or topology. The generator may reach `sandbox_tested`; independent identities are required for evaluation, review, acceptance, selection, merge, promotion and release. No candidate can mint a credential or receipt that advances itself.

Candidate classes are parameter, prompt factor, policy, workflow, skill, code and topology. External effects are excluded from the first code-candidate slice.

## 2. Typed mutation grammar

`MutationGrammarManifestV1` defines exact operations per class:

```text
parameter: bounded_delta, replace_with_predecessor_compatible_artifact
prompt: add_factor, revise_realization, retire_factor
workflow: add_step, revise_bounded_step, retire_step
skill: add, revise_precondition, revise_effect_model, retire
code: add_file, edit_ast_node, delete_owned_file, dependency_update
 topology: add, split, merge, rewire, retire
```

Every operation has allowed paths, maximum files/bytes, semantic preconditions, mandatory tests and rollback. Arbitrary binary patches, policy weakening, evaluator mutation and unknown topology operations are rejected. The no-change candidate is always present.

## 3. Protected surfaces and sandbox isolation

Default protected surfaces include authority, evidence independence, deletion policy, branch protection, release credentials, hidden tests and the verifier judging the same candidate. A separate governance envelope and independent review are required even to propose changes there.

Sandboxes use an isolated worktree or image, no production credentials, no uncontrolled network, read-only source inputs and bounded CPU, memory, disk, process, file-descriptor and wall-clock limits. Symlink, case-folding, Unicode and mount-escape checks precede execution. `SandboxExecutionReceiptV1` records zero credential exposure, path escape and authority delta.

## 4. Candidate lineage and state machine

`CandidateLineageV1` binds content-derived ID, exact base, predecessors, generator, dataset, mutation, tests, evaluations, rollback and state. Equivalent semantic candidates deduplicate independently of enumeration order.

```text
drafted -> statically_validated -> sandbox_tested -> independently_evaluated
        -> review_requested -> accepted_candidate -> selected -> promoted -> released
        -> rejected | quarantined | superseded | revoked
```

The generating identity cannot advance beyond `sandbox_tested`. Base drift returns the candidate to drafted with a new identity and complete reevaluation. Current-run replacement is forbidden.

## 5. Independent evaluation and selection

Evaluation compares every candidate with no-change and the selected predecessor using frozen metrics, hidden tests, mutation testing, security checks, resources, retention and rollback. Generator and evaluator identities, credential chains and signing keys must be distinct. Selection and merge are separate from acceptance.

A candidate that improves a visible score while reducing test sensitivity, widening permissions, hiding failures or changing its evaluator is rejected. Human or separately governed operator decisions remain required for production transitions.

## 6. Canary abort and rollback

Before canary, every candidate has an exact predecessor and rehearsed rollback. Canary envelopes bind population, duration or event count, resource ceilings, safety floors and abort triggers. Default abort triggers include any authority delta, safety breach, deletion resurrection, error-rate increase above profile, p99 latency breach, resource ceiling breach, OOD false acceptance, unresolved indeterminate effect or retention regression.

Abort stops new work, fences the candidate, reconciles outstanding operations, selects the predecessor and verifies reload. Compensation is a separately authorized effect and is never assumed to reverse external actions.

## 7. Security, privacy and reward-hacking controls

Untrusted issues, pages, emails, repository text and tool output are evidence, not mutation instructions. Candidate generation excludes credentials, unrestricted private content, revoked rows and evaluator hidden data. Generated tests undergo mutation testing and independent counterexamples.

Feedback becomes an immutable future dataset; it does not alter the running generator. Diversity and acceptance metrics cannot reward path escape, permission expansion or test weakening.

## 8. Resource envelope

Pilot limits are `<=32` candidates, `<=100` changed files, `<=1 MiB` textual diff, `<=8` parallel sandboxes, `<=2` retries for infrastructure-only failures and zero retry for semantic rejection. Duplicate ratio `>=50%`, base drift, isolation failure or inability to construct rollback stops the search.

Queues are bounded and backpressure rejects new envelopes. Candidate logs and artifacts have retention and deletion policies.

## 9. Golden fixtures and tests

The canonical mutation fixture contains valid edit, path escape, mandatory-test deletion and no-change; only valid and no-change are feasible. Additional fixtures cover symlink escape, case collision, binary insertion, protected-root edit, evaluator identity collision, altered hidden-test digest, nondeterministic candidate ID, resource breach, base drift, rollback failure and a topology proposal that attempts self-activation.

Property tests enforce valid state transitions, content-derived identity, no-change presence, immutable receipts, exact source/merge execution, distinct decision roles, bounded resources and inability to alter the evaluator.

## 10. Implementation sequence

Implement envelope and grammar types, no-change candidate, isolated worktree sandbox, path/authority/resource validators, mandatory tests, semantic deduplication, lineage store, independent evaluator adapter, pull-request proposal, rollback rehearsal, then parameter/prompt, code and topology candidates in that order.

## 11. Coding-entry checklist

Coding may start when grammar, sandbox and lineage protocols compile, protected paths are frozen, source and lane receipts are current, no-change and rollback fixtures pass, generator/evaluator roles are registered, and the package explicitly denies self-review, self-selection, self-merge, self-promotion and self-release.

## Appendix A. Closed gap and protocol mapping

This appendix is a closed-world traceability projection. Each identifier is normative in `READINESS.json`, `PROTOCOLS.json` or `GAPS.json`; this Markdown file does not redefine the registry record.

Protocols:

- `MutationGrammarManifestV1`
- `SandboxExecutionReceiptV1`
- `CandidateLineageV1`
- `EvaluatorIndependenceReceiptV1`

Closed documentation gaps:

- `RDY-GAP-SI-001`
- `RDY-GAP-SI-002`
- `RDY-GAP-SI-003`
- `RDY-GAP-SI-004`
- `RDY-GAP-SI-005`
- `RDY-GAP-SI-006`

Bound work packages:

- `ART-1-LEARNING-ARTIFACT-REGISTRY`
- `ART-2-NEXT-SNAPSHOT-RELOAD-ROLLBACK`
- `C1-PROMPTED-MEMORY-RETRIEVAL-RANK`
- `DOC-0-CANONICAL-DOCUMENT-CONSOLIDATION`
- `DOC-1-V8-SEMANTIC-UPGRADE`
- `DOC-2-DEFAULT-BRANCH-SELECTION`
- `DOC-3A-SOURCE-BINDING-RECONCILIATION`
- `DOC-3B-MODULE-TECHNICAL-DOCUMENTS`
- `DOC-3C-MODULE-DOC-CLOSED-WORLD`
- `DOC-3D-ADAPTIVE-ALGORITHM-DOC-CLOSED-WORLD`
- `DOC-3E-PRECODING-READINESS-CLOSED-WORLD`
- `DOC-REGISTRY-CLOSED-WORLD`
- `ECP-1-ENGINEERING-CONTROL-PLANE`
- `HBO-1-OPERATOR-SENSOR-CORE`
- `INT-2-AGENTD-CODEX-COMPOSITION`
- `INTELLIGENCE-A0-Q0.63`
- `LONG-1-TEMPORAL-HOLDOUT`
- `LONG-2-RETENTION-FORGETTING`
- `LONG-3-UNLEARNING-NON-RESURRECTION`
- `LRN-2-CAUSAL-EVALUATION`
- `P0.9-EXTERNAL-GATES`
- `PLS-1-PARAMETER-PLASTICITY`
- `PLS-2-TOPOLOGY-PROPOSAL`
- `PLS-3-BOUNDED-STRUCTURAL-CANARY`
- `SELF-1-CODE-CANDIDATE-PIPELINE`
