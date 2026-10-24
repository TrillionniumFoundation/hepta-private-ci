//! Original issuer/Registry component fixtures, not installed Root authority.
use super::*;
use pretty_assertions::assert_eq;

fn objective_only(f: &Fixture) -> IssuerState {
    let before = f.issuer.store.load(STATE_OWNER).unwrap();
    let mut initial = before.clone();
    initial.policies = vec![DeploymentGrantPolicy {
        subject_id: f.writer.registered_agent_id.to_string(),
        destination_id: "objective.profile:organ.notes.literal.v1".into(),
        scope_sha256: [9; 32],
        lifetime_ms: 1_000,
    }];
    f.issuer
        .store
        .compare_and_set(STATE_OWNER, &before, &initial)
        .unwrap();
    initial
}

#[test]
fn deployment_notes_first_actual_target_preserves_all_original_issuer_state() {
    let f = Fixture::new();
    let before = objective_only(&f);
    let key = f.issuer.trust_key().unwrap();
    f.issuer
        .install_first_notes_policy(&f.writer, &f.target, 1_000)
        .unwrap();
    let after = f.issuer.store.load(STATE_OWNER).unwrap();
    let mut expected = before.clone();
    expected.policies.push(DeploymentGrantPolicy {
        subject_id: f.binding.subject_id.clone(),
        destination_id: f.binding.destination_id.clone(),
        scope_sha256: f.binding.scope_sha256,
        lifetime_ms: 1_000,
    });
    assert_eq!(
        serde_json::to_value(&after).unwrap(),
        serde_json::to_value(&expected).unwrap()
    );
    assert_eq!(f.issuer.trust_key().unwrap(), key);
    f.issuer
        .install_first_notes_policy(&f.writer, &f.target, 1_000)
        .unwrap();
    assert_eq!(
        serde_json::to_value(f.issuer.store.load(STATE_OWNER).unwrap()).unwrap(),
        serde_json::to_value(after).unwrap()
    );
    let grant = f.admission().issue(&f.issuer, &f.binding).unwrap().unwrap();
    assert_eq!(grant.grant.binding, f.binding);
    assert_eq!(f.sequence(), before.sequence + 1);
}

#[test]
fn deployment_notes_first_policy_cannot_replace_or_bypass_expired_writer() {
    let f = Fixture::new();
    let original = f.issuer.store.load(STATE_OWNER).unwrap();
    let other = NotesTargetIdentity {
        task_id: f.target.task_id + 1,
        ..f.target.clone()
    };
    assert!(
        f.issuer
            .install_first_notes_policy(&f.writer, &other, 1_000)
            .is_err()
    );
    assert!(
        f.issuer
            .install_first_notes_policy(&f.writer, &f.target, 0)
            .is_err()
    );
    assert_eq!(
        serde_json::to_value(f.issuer.store.load(STATE_OWNER).unwrap()).unwrap(),
        serde_json::to_value(original).unwrap()
    );
    let before = objective_only(&f);
    f.clock.0.store(20_000, Ordering::SeqCst);
    assert!(
        f.issuer
            .install_first_notes_policy(&f.writer, &f.target, 1_000)
            .is_err()
    );
    assert_eq!(
        serde_json::to_value(f.issuer.store.load(STATE_OWNER).unwrap()).unwrap(),
        serde_json::to_value(before).unwrap()
    );
}

#[test]
fn deployment_notes_first_policy_refuses_ambiguous_or_full_routes() {
    let f = Fixture::new();
    let before = f.issuer.store.load(STATE_OWNER).unwrap();
    let mut ambiguous = before.clone();
    ambiguous.policies.push(before.policies[0].clone());
    f.issuer
        .store
        .compare_and_set(STATE_OWNER, &before, &ambiguous)
        .unwrap();
    assert!(
        f.issuer
            .install_first_notes_policy(&f.writer, &f.target, 1_000)
            .is_err()
    );
    assert_eq!(
        serde_json::to_value(f.issuer.store.load(STATE_OWNER).unwrap()).unwrap(),
        serde_json::to_value(&ambiguous).unwrap()
    );
    let mut full = ambiguous.clone();
    full.policies = (0..16)
        .map(|i| DeploymentGrantPolicy {
            subject_id: f.writer.registered_agent_id.to_string(),
            destination_id: format!("objective.profile:{i}"),
            scope_sha256: [9; 32],
            lifetime_ms: 1_000,
        })
        .collect();
    f.issuer
        .store
        .compare_and_set(STATE_OWNER, &ambiguous, &full)
        .unwrap();
    assert!(
        f.issuer
            .install_first_notes_policy(&f.writer, &f.target, 1_000)
            .is_err()
    );
    assert_eq!(
        serde_json::to_value(f.issuer.store.load(STATE_OWNER).unwrap()).unwrap(),
        serde_json::to_value(full).unwrap()
    );
}

struct UnavailableClock;
impl AuthorityClock for UnavailableClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Err(AuthorityTrustError::Unavailable)
    }
}

#[test]
fn deployment_notes_first_policy_post_cas_unknown_retains_exact_policy_and_key() {
    let mut f = Fixture::new();
    let before = objective_only(&f);
    let key = f.issuer.trust_key().unwrap();
    f.issuer.clock = Arc::new(UnavailableClock);
    assert!(
        f.issuer
            .install_first_notes_policy(&f.writer, &f.target, 1_000)
            .is_err()
    );
    let retained = f.issuer.store.load(STATE_OWNER).unwrap();
    assert_eq!(retained.policies.len(), before.policies.len() + 1);
    assert_eq!(retained.sequence, before.sequence);
    assert_eq!(f.issuer.trust_key().unwrap(), key);
    f.issuer.clock = f.clock.clone();
    f.issuer
        .install_first_notes_policy(&f.writer, &f.target, 1_000)
        .unwrap();
    assert_eq!(
        serde_json::to_value(f.issuer.store.load(STATE_OWNER).unwrap()).unwrap(),
        serde_json::to_value(retained).unwrap()
    );
}
