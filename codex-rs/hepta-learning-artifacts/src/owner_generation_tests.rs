use super::tests::*;
use super::*;

use ed25519_dalek::Signer;
use pretty_assertions::assert_eq;

use crate::admit_manifest_at_withdrawal_head_v3;
use crate::test_support::FixtureValue;

#[test]
fn terminal_maximum_generation_head_remains_readable_but_cannot_extend() {
    let directory = TestDir::new();
    let key = signer();
    let scope = withdrawal_scope();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope.clone());
    let owner = LearningArtifactOwnerHost::open(
        &directory.0,
        trust(&key, scope.digest()),
        lease(&key, scope.digest()),
        /*now*/ 20,
    )
    .fixture("owner");
    let (registry, mut transaction) =
        deterministic_publication(&owner, &withdrawals, /*now*/ 20);
    owner
        .ensure_payload_durable(&mut transaction, &registry, b"payload", /*now*/ 20)
        .fixture("payload durable");
    owner
        .ensure_registry_durable(
            &mut transaction,
            &registry,
            &withdrawals,
            digest("binding"),
            /*now*/ 20,
        )
        .fixture("registry durable");
    let mut signed = signed_head(&key, scope.digest(), registry.snapshot().head_digest);
    signed.witness.generation = Generation::new(u64::MAX).fixture("maximum generation");
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    owner
        .ensure_witness_durable(&mut transaction, &signed, &withdrawals, /*now*/ 20)
        .fixture("maximum CURRENT durable");
    owner
        .acknowledge(&mut transaction, &withdrawals, /*now*/ 20)
        .fixture("acknowledge");
    assert_eq!(
        owner
            .discover_current_head(20)
            .fixture("maximum CURRENT")
            .fixture("head")
            .signed,
        signed
    );
    drop(owner);
    let owner = LearningArtifactOwnerHost::open_with_required_current_head(
        &directory.0,
        trust(&key, scope.digest()),
        lease(&key, scope.digest()),
        signed.clone(),
        /*now*/ 21,
    )
    .fixture("anchored maximum generation restart");
    assert_eq!(
        owner
            .current_registry_view(21)
            .fixture("view")
            .receipt()
            .head_digest,
        signed.witness.head_digest
    );
    let mut child = manifest();
    child.artifact_id = id("child");
    child.generation = Generation::new(2).fixture("child generation");
    child.predecessor_ids = vec![id("candidate")];
    let admission = admit_manifest_at_withdrawal_head_v3(
        &withdrawals,
        withdrawals.head_digest(),
        child,
        /*now*/ 21,
    )
    .fixture("child admission");
    let before = [
        "transactions",
        "payloads",
        "registries",
        "witnesses",
        "heads",
        "admissions",
    ]
    .map(|name| {
        fs::read_dir(directory.0.join(name))
            .fixture("effects")
            .count()
    });
    assert!(matches!(
        owner.begin_publication(
            id("child-operation"),
            admission,
            &withdrawals,
            &registry,
            signed.witness.head_digest,
            21
        ),
        Err(ArtifactOwnerHostError::CurrentHeadContext)
    ));
    assert_eq!(
        [
            "transactions",
            "payloads",
            "registries",
            "witnesses",
            "heads",
            "admissions"
        ]
        .map(|name| fs::read_dir(directory.0.join(name))
            .fixture("effects")
            .count()),
        before
    );
    assert_eq!(
        owner
            .discover_current_head(21)
            .fixture("retained CURRENT")
            .fixture("head")
            .signed,
        signed
    );
}
