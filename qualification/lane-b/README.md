# Lane B runtime implementation closure

This directory is the repository-controlled truth and traceability surface for `LANE-B-RUNTIME`.

## Authority and source identity

The immutable lineage anchor is recorded in `LANE_B_CANDIDATE_MANIFEST.json`. The exact candidate is always the clean Git `HEAD` checked by CI. No document embeds a self-referential final head hash, and no branch name, moving tag or PR body is accepted as source identity.

Repository-controlled closure may establish module coverage, operation disposition, native source anchors, generated maps, executable boundary tests and explicit residual gates. It cannot self-issue a deployed product caller, remote effect, real model/device execution, hardware evidence, independent acceptance, signing, selection, promotion or release.

## Authoritative files

- `LANE_B_CANDIDATE_MANIFEST.json` — lineage anchor, bounded path envelope and claim ceiling.
- `LANE_B_IMPLEMENTATION_TRUTH.json` — exact eleven-module set and all 39 operation dispositions.
- `LANE_B_TEST_TRACEABILITY.json` — operation-to-test and suite mapping.
- `LANE_B_NATIVE_CLOSURE.md` — human-readable projection of the machine truth.
- `docs/readiness/LANE_B_RUNTIME_COMPOSITION.md` — process topology, identity, startup, request, cancellation, fault, recovery and rollback semantics.
- `docs/modules/<lane-b-module>/IMPLEMENTATION_MAP.json` — generated module projection; never edit independently.

## Validation

Run from the repository root:

```bash
python3 scripts/hepta-lane-b-truth.py self-test
python3 -m unittest scripts/test_hepta_lane_b_truth.py
python3 scripts/hepta-lane-b-truth.py verify
python3 scripts/hepta-lane-b-docs.py verify
```

The workflow `.github/workflows/hepta-lane-b-truth.yml` runs governance checks at the exact source head and at a deterministic synthetic merge. It also runs the Lane B JavaScript runtime tests, the five owner-boundary Rust binary tests, and focused Supervisor, Agentd and Codex-adapter package tests.

## State vocabulary

- `implemented`: repository-controlled target semantics are mapped to a current native symbol and executable test surface.
- `implemented_partial`: a real native operation exists, but product integration or part of the target semantics remains outside repository proof.
- `delegated_partial`: the module intentionally delegates to another registered owner; it does not duplicate that owner.
- `boundary_only`: a checked validation or observation boundary exists without the target effect.

`allDesignOperationsDispositioned=true` means all operations have an explicit state and evidence. It does not mean target deployment or external evidence is complete.

## Change discipline

Change the machine truth first, regenerate or update its human projection and generated module maps in the same candidate, and run both validators. A mapped owner entrypoint must stay inside its registered implementation roots. A delegated callee must name a registered module and real source symbol. Every operation must retain test identifiers and every residual item must be classified as repository work or external evidence.

Unknown gaps are added rather than suppressed. A green repository result is never promoted into a remote, physical, future-time or independent decision.
