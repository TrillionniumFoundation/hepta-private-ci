# learning.plasticity integration contract

`TECHNICAL.md` lists `learning.eval`, `learning.artifacts` and `kernel.evidence` as direct module dependencies. That is an architectural/port dependency statement, not a claim that `codex-hepta-plasticity` must link every owner crate directly.

The native crate deliberately keeps external trust acquisition behind typed host verifier interfaces. This avoids turning a digest lookup or an unevaluated cross-owner record into an authentication claim and avoids creating ownership cycles between proposal construction, artifact storage and evidence authority.

## learning.artifacts

Concrete owner source: `codex-rs/hepta-learning-artifacts`.

The selected host SHOULD obtain the selected artifact through the artifact owner using `load_pinned_candidate` or an equivalently registered current-view path. `LoadedPinnedCandidate` proves exact payload/manifest agreement against the supplied registry receipt, while `RevalidatingCandidate::with_current` supports a monotonic current-view recheck. The artifact crate itself explicitly leaves trusted file opening and receipt freshness to the host.

For plasticity composition, the host converts an authenticated/current artifact observation into an `EvidenceClaimV1` with kind `SelectedArtifact`, exact selected artifact digest and window scope. `EvidenceVerifier` then enforces the registered producer/trust-root/freshness/revocation policy before proposal construction.

The plasticity crate MUST NOT directly mutate the artifact registry or interpret artifact eligibility as selection/activation authority.

## learning.eval

Concrete owner source: `codex-rs/hepta-intelligence-eval`.

The evaluation owner produces evaluation facts; plasticity binds the resulting `evaluation_digest`. The composed plasticity path additionally requires an `EvaluatorClaimV1` and an `IndependentEvaluatorVerifier` grant. This separation is intentional: deterministic evaluation arithmetic does not by itself authenticate the principal that performed/approved the independent evaluation.

The host MUST bind the evaluator attestation to proposer identity, evaluator identity, selected artifact, window and evaluation digest, and MUST enforce freshness/revocation before returning success.

## kernel.evidence

Concrete owner source: `codex-rs/hepta-evidence`; canonical contracts include `IndependentDecisionReceiptV1` and qualification-evidence domain reads.

At the current source boundary, no plasticity-local API is allowed to mint or self-accept an independent decision. The host/evidence boundary owns decoding/authenticating registered evidence records and exposes the result to plasticity only through `EvidenceVerifier` / `IndependentEvaluatorVerifier`.

This is not a substitute for a future concrete evidence adapter. When a stable Rust representation and authenticated consumer API for the canonical evidence contracts is admitted, an adapter MAY be added, but it must still preserve the same verifier boundary and must not let plasticity become the evidence authority.

## Why Cargo.toml remains narrow

`codex-hepta-plasticity` currently links `codex-hepta-types` because its deterministic proposal core and durable format do not need to own artifact/evaluation/evidence stores. The named product-composition source is `codex-hepta-intelligence::run_plasticity_proposal_cycle_v1`, which supplies the host boundary and can compose the owner services without moving their durable facts into the plasticity crate.

Therefore:

- module dependency != mandatory direct Rust crate dependency;
- a non-zero cross-module digest != authenticated evidence;
- direct linking alone would not close provenance, freshness, revocation or independent-principal requirements;
- the production claim remains false until a target host binds concrete registered verifier implementations and demonstrates execution evidence.

## Required integration tests before activation

A target-host qualification MUST demonstrate at least:

1. artifact pin/current-view mismatch blocks generation;
2. withdrawn/revoked artifact or dataset evidence blocks generation;
3. evaluation digest scope mismatch blocks generation;
4. self/same-principal or revoked evaluator blocks generation;
5. stale evidence/evaluator attestations block generation;
6. valid owner observations produce the same deterministic proposal as replayed identical observations;
7. failure of any owner dependency cannot fall back to caller-asserted digests;
8. durable append acknowledgement cannot be interpreted as acceptance, selection or activation.
