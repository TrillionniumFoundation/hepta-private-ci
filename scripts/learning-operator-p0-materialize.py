#!/usr/bin/env python3
"""One-shot, self-deleting source patch for PR #1008 P0 remediation."""

from pathlib import Path

root = Path(".")

path = root / "scripts/hepta-lane-e-closure.py"
text = path.read_text(encoding="utf-8")
count = text.count("\x08")
if count != 6:
    raise SystemExit(f"expected six corrupted regex boundaries, found {count}")
text = text.replace("\x08", r"\b")
path.write_text(text, encoding="utf-8")

path = root / "codex-rs/hepta-intelligence-eval/Cargo.toml"
text = path.read_text(encoding="utf-8")
needle = "trusted-inprocess-eval = []\n"
replacement = """trusted-inprocess-eval = []
# Enables only cryptographically verified runtime-consumer fixtures. This
# feature is absent from default and production builds and grants no authority.
qualification-test-support = []
"""
if text.count(needle) != 1:
    raise SystemExit("unexpected intelligence-eval feature block")
path.write_text(text.replace(needle, replacement, 1), encoding="utf-8")

path = root / "codex-rs/hepta-intelligence-eval/src/self_evolution_selection.rs"
text = path.read_text(encoding="utf-8")
needle = "fn validate_policy(\n"
helper = r'''/// Qualification-only bridge for exercising an actual runtime consumer.
///
/// Unlike a bare test constructor, this verifies signatures for generator,
/// evaluator, observer and selector against one host-owned trust snapshot,
/// checks pairwise controller separation, validates the selection receipt, and
/// then delegates to the same opaque admission used by production. It is not
/// compiled unless `qualification-test-support` is explicitly enabled.
#[cfg(feature = "qualification-test-support")]
#[allow(clippy::too_many_arguments)]
pub fn admit_self_evolution_selection_for_qualification_v1(
    receipt: SelfEvolutionSelectionReceiptV1,
    generator_evidence: &SignedLearningEvidenceV1,
    generator_payload: &[u8],
    evaluator_evidence: &SignedLearningEvidenceV1,
    evaluator_payload: &[u8],
    observer_evidence: &SignedLearningEvidenceV1,
    observer_payload: &[u8],
    selector_evidence: &SignedLearningEvidenceV1,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<VerifiedSelfEvolutionSelectionV1, SelfEvolutionSelectionError> {
    if verifier.trust_digest() != receipt.evaluation_trust_digest {
        return Err(SelfEvolutionSelectionError::BindingMismatch);
    }
    let generator = verifier.verify(
        LearningEvidenceRoleV1::Generator,
        generator_evidence,
        generator_payload,
        now,
    )?;
    let evaluator = verifier.verify(
        LearningEvidenceRoleV1::Evaluator,
        evaluator_evidence,
        evaluator_payload,
        now,
    )?;
    let observer = verifier.verify(
        LearningEvidenceRoleV1::Observer,
        observer_evidence,
        observer_payload,
        now,
    )?;
    verify_verified_role_separation(&generator, &evaluator, now)?;
    verify_verified_role_separation(&generator, &observer, now)?;
    verify_verified_role_separation(&evaluator, &observer, now)?;
    let prepared = PreparedSelfEvolutionSelectionV1 {
        receipt,
        generator,
        evaluator,
        observer,
    };
    admit_self_evolution_selection_v1(prepared, selector_evidence, verifier, now)
}

'''
if text.count(needle) != 1:
    raise SystemExit("unexpected selection validation anchor")
path.write_text(text.replace(needle, helper + needle, 1), encoding="utf-8")

path = root / "codex-rs/hepta-intelligence-eval/src/lib.rs"
text = path.read_text(encoding="utf-8")
needle = "pub use self_evolution_selection::admit_self_evolution_selection_v1;\n"
replacement = """pub use self_evolution_selection::admit_self_evolution_selection_v1;
#[cfg(feature = "qualification-test-support")]
pub use self_evolution_selection::admit_self_evolution_selection_for_qualification_v1;
"""
if text.count(needle) != 1:
    raise SystemExit("unexpected selection export anchor")
path.write_text(text.replace(needle, replacement, 1), encoding="utf-8")

path = root / "codex-rs/hepta-agentd/Cargo.toml"
text = path.read_text(encoding="utf-8")
needle = "[dev-dependencies]\n"
replacement = """[dev-dependencies]
codex-hepta-intelligence-eval = { path = "../hepta-intelligence-eval", features = ["qualification-test-support"] }
"""
if text.count(needle) != 1:
    raise SystemExit("unexpected agentd dev-dependency anchor")
path.write_text(text.replace(needle, replacement, 1), encoding="utf-8")

path = root / "codex-rs/hepta-agentd/src/cognitive_ranker_tests.rs"
text = path.read_text(encoding="utf-8")
anchor = '''fn item(name: &str) -> CognitiveContextItem {
    CognitiveContextItem {
        memory_id: name.to_string(),
        revision: 1,
        content: format!("lemon {name}"),
        content_sha256: hash(name).to_string(),
    }
}

'''
helper = r'''fn signed_runtime_evidence(
    verifier: &codex_hepta_learning_ledger::LearningEvidenceVerifierV1,
    key: &ed25519_dalek::SigningKey,
    principal_id: &str,
    role: codex_hepta_learning_ledger::LearningEvidenceRoleV1,
    payload: &[u8],
) -> codex_hepta_learning_ledger::SignedLearningEvidenceV1 {
    use ed25519_dalek::Signer;
    let mut evidence = codex_hepta_learning_ledger::SignedLearningEvidenceV1 {
        evidence_id: id(&format!("{principal_id}-runtime-evidence")),
        principal_id: id(principal_id),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: hash("runtime-selection-scope"),
        objective_digest: verifier.objective_digest(),
        authority_epoch: verifier.authority_epoch(),
        issued_at: 20,
        expires_at: 90,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    evidence
}

fn runtime_selection(
    manifest: &ArtifactManifest,
) -> codex_hepta_intelligence_eval::VerifiedSelfEvolutionSelectionV1 {
    use codex_hepta_intelligence_eval::SelfEvolutionSelectionReceiptV1;
    use codex_hepta_intelligence_eval::admit_self_evolution_selection_for_qualification_v1;
    use codex_hepta_intelligence_eval::selection_signing_payload_v1;
    use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
    use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
    use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
    use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
    use codex_hepta_learning_ledger::TrustedLearningSignerV1;
    use ed25519_dalek::SigningKey;

    let scope = hash("runtime-selection-scope");
    let roles = [
        ("runtime-generator", "runtime-generator-controller", LearningEvidenceRoleV1::Generator, 11_u8),
        ("runtime-evaluator", "runtime-evaluator-controller", LearningEvidenceRoleV1::Evaluator, 22_u8),
        ("runtime-observer", "runtime-observer-controller", LearningEvidenceRoleV1::Observer, 33_u8),
        ("runtime-selector", "runtime-selector-controller", LearningEvidenceRoleV1::Selector, 44_u8),
    ];
    let keys = roles.map(|(_, _, _, seed)| SigningKey::from_bytes(&[seed; 32]));
    let signers = roles
        .iter()
        .zip(keys.iter())
        .map(|((name, controller, role, _), key)| TrustedLearningSignerV1 {
            principal: AuthenticatedPrincipalV1 {
                principal_id: id(name),
                credential_chain_digest: hash(&format!("{name}-credential")),
                signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                scope_digest: scope,
                authority_epoch: 7,
                authenticated_at: 10,
                expires_at: 100,
            },
            controller_id: id(controller),
            verifying_key: key.verifying_key().to_bytes(),
            roles: vec![*role],
            revoked_at: None,
        })
        .collect();
    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: scope,
        objective_digest: manifest.objective_digest,
        authority_epoch: 7,
        signers,
    })
    .expect("runtime selection trust");
    let predecessor_generation = Generation::new(
        manifest
            .generation
            .get()
            .checked_sub(1)
            .expect("candidate has predecessor"),
    )
    .expect("predecessor generation");
    let receipt = SelfEvolutionSelectionReceiptV1 {
        selection_id: id("runtime-selection"),
        objective_digest: manifest.objective_digest,
        predecessor_id: id("runtime-baseline"),
        predecessor_generation,
        predecessor_artifact_digest: hash("runtime-baseline-payload"),
        candidate_id: manifest.artifact_id.clone(),
        candidate_generation: manifest.generation,
        candidate_artifact_digest: manifest.content_digest,
        no_change_baseline_id: id("runtime-baseline"),
        no_change_baseline_digest: hash("runtime-baseline-payload"),
        dataset_digest: manifest.support_digest,
        ledger_head_digest: hash("runtime-ledger-head"),
        evaluation_evidence_digest: hash("runtime-evaluation-evidence"),
        evaluation_authentication_digest: hash("runtime-evaluation-authentication"),
        evaluation_trust_digest: verifier.trust_digest(),
        frozen_plan_digest: hash("runtime-frozen-plan"),
        minimum_dataset_records: 2,
        minimum_future_window_micros: 1,
        authority: AuthorityPosture::DENY_ALL,
    };
    let generator_payload = b"runtime-generator-payload";
    let evaluator_payload = b"runtime-evaluator-payload";
    let observer_payload = b"runtime-observer-payload";
    let generator = signed_runtime_evidence(
        &verifier,
        &keys[0],
        "runtime-generator",
        LearningEvidenceRoleV1::Generator,
        generator_payload,
    );
    let evaluator = signed_runtime_evidence(
        &verifier,
        &keys[1],
        "runtime-evaluator",
        LearningEvidenceRoleV1::Evaluator,
        evaluator_payload,
    );
    let observer = signed_runtime_evidence(
        &verifier,
        &keys[2],
        "runtime-observer",
        LearningEvidenceRoleV1::Observer,
        observer_payload,
    );
    let selector_payload = selection_signing_payload_v1(&receipt).expect("selection payload");
    let selector = signed_runtime_evidence(
        &verifier,
        &keys[3],
        "runtime-selector",
        LearningEvidenceRoleV1::Selector,
        &selector_payload,
    );
    admit_self_evolution_selection_for_qualification_v1(
        receipt,
        &generator,
        generator_payload,
        &evaluator,
        evaluator_payload,
        &observer,
        observer_payload,
        &selector,
        &verifier,
        50,
    )
    .expect("independently signed runtime selection")
}

'''
if text.count(anchor) != 1:
    raise SystemExit("unexpected cognitive fixture anchor")
text = text.replace(anchor, anchor + helper, 1)
old = "generation: Generation::new(1).unwrap(),"
if text.count(old) != 1:
    raise SystemExit(f"unexpected ranker model generation count: {text.count(old)}")
text = text.replace(old, "generation: Generation::new(2).unwrap(),", 1)
needle = "    let mut registry = ArtifactRegistry::new();\n"
if text.count(needle) != 1:
    raise SystemExit("unexpected registry anchor")
text = text.replace(needle, "    let selection = runtime_selection(&manifest);\n    let mut registry = ArtifactRegistry::new();\n", 1)
old = '''        PinnedCognitiveRanker::load(
            owner(),
            1,
'''
new = '''        PinnedCognitiveRanker::load_evaluated(
            owner(),
            2,
'''
if text.count(old) != 1:
    raise SystemExit("unexpected ranker load anchor")
text = text.replace(old, new, 1)
old = '''            model_pin,
            view.clone(),
        )
'''
new = '''            model_pin,
            view.clone(),
            &selection,
        )
'''
if text.count(old) != 1:
    raise SystemExit("unexpected ranker load tail")
text = text.replace(old, new, 1)
old_name = "fn current_loaded_model_changes_read_order_and_abstains_on_unseen_or_corrected_records() {"
new_name = "fn signed_runtime_consumer_e2e_loads_independently_selected_candidate_and_abstains() {"
if text.count(old_name) != 1:
    raise SystemExit("unexpected primary runtime test name")
text = text.replace(old_name, new_name, 1)
text = text.replace(
    '.rank(&owner(), 2, "lemon", &mut ranked)',
    '.rank(&owner(), 3, "lemon", &mut ranked)',
    1,
)
text = text.replace(".rank(&owner(), 1,", ".rank(&owner(), 2,")
text = text.replace(".rank(&foreign, 1,", ".rank(&foreign, 2,")
text = text.replace('&owner(), 1, "lemon",', '&owner(), 2, "lemon",')
path.write_text(text, encoding="utf-8")

path = root / ".github/workflows/hepta-lane-e-gap-closure.yml"
text = path.read_text(encoding="utf-8")
old = """      - name: Evaluated-shadow signed runtime admission E2E
        shell: bash
        run: |
          set -euo pipefail
          mkdir -p .hepta-evidence/learning-eval
          just test --locked             -p codex-hepta-intelligence             evaluated_shadow             --test-threads=1             2>&1 | tee .hepta-evidence/learning-eval/runtime-e2e.log
"""
new = """      - name: Signed runtime consumer load_evaluated E2E
        shell: bash
        run: |
          set -euo pipefail
          mkdir -p .hepta-evidence/learning-eval
          cargo test --manifest-path codex-rs/Cargo.toml --locked \\
            -p codex-hepta-agentd \\
            signed_runtime_consumer_e2e \\
            -- --test-threads=1 \\
            2>&1 | tee .hepta-evidence/learning-eval/runtime-e2e.log
"""
if text.count(old) != 1:
    raise SystemExit("unexpected runtime E2E workflow block")
path.write_text(text.replace(old, new, 1), encoding="utf-8")

path = root / "scripts/hepta-learning-eval-evidence.py"
text = path.read_text(encoding="utf-8")
needle = '    "codex-rs/hepta-intelligence/src/evaluated_shadow.rs",\n'
replacement = """    "codex-rs/hepta-intelligence/src/evaluated_shadow.rs",
    "codex-rs/hepta-agentd/src/cognitive_ranker.rs",
    "codex-rs/hepta-agentd/src/cognitive_ranker_tests.rs",
"""
if text.count(needle) != 1:
    raise SystemExit("unexpected evidence input anchor")
path.write_text(text.replace(needle, replacement, 1), encoding="utf-8")
