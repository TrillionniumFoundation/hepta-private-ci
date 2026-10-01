use super::tests::*;
use super::*;

use pretty_assertions::assert_eq;

use crate::admit_manifest_at_withdrawal_head_v3;
use crate::test_support::FixtureValue;

fn effect_inventory(root: &Path) -> [usize; 6] {
    [
        "transactions",
        "payloads",
        "registries",
        "witnesses",
        "heads",
        "admissions",
    ]
    .map(|name| fs::read_dir(root.join(name)).fixture("effects").count())
}

#[test]
fn new_publication_rejects_insufficient_completion_capacity_before_admission_or_prepared() {
    for (domain, quota, remaining) in [
        ("transactions", MAX_HEAD_RECORDS * 6, 5),
        ("payloads", MAX_HEAD_RECORDS * 2, 1),
        ("registries", MAX_HEAD_RECORDS * 4, 1),
        ("witnesses", MAX_HEAD_RECORDS * 4, 1),
        ("heads", MAX_HEAD_RECORDS * 2, 1),
    ] {
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
        let admission = admit_manifest_at_withdrawal_head_v3(
            &withdrawals,
            withdrawals.head_digest(),
            manifest(),
            /*now*/ 20,
        )
        .fixture("legal admission");
        for index in 0..quota - remaining {
            fs::write(
                directory
                    .0
                    .join(domain)
                    .join(format!("interrupted-{index}.pending")),
                b"",
            )
            .fixture("real interrupted publication records");
        }
        let before = effect_inventory(&directory.0);
        assert!(
            owner
                .begin_publication(
                    id("new-operation"),
                    admission,
                    &withdrawals,
                    &ArtifactRegistry::new(),
                    Digest32::ZERO,
                    /*now*/ 20,
                )
                .is_err()
        );
        assert_eq!(effect_inventory(&directory.0), before);
        assert_eq!(
            owner
                .recover_publication(&id("new-operation"))
                .fixture("no Prepared"),
            None
        );
        assert_eq!(
            owner
                .recovery_required_operations()
                .fixture("no dead-end recovery fence"),
            Vec::new(),
        );
    }
}
