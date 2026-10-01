use super::tests::*;
use super::*;

use ed25519_dalek::Signer;
use pretty_assertions::assert_eq;

use crate::test_support::FixtureValue;

#[test]
fn last_legal_current_head_fits_while_an_extra_final_head_rejects_before_effects() {
    let directory = TestDir::new();
    let key = signer();
    let scope = withdrawal_scope();
    let owner = LearningArtifactOwnerHost::open(
        &directory.0,
        trust(&key, scope.digest()),
        lease(&key, scope.digest()),
        /*now*/ 20,
    )
    .fixture("owner");
    let mut predecessor = Digest32::ZERO;
    for index in 1..MAX_HEAD_RECORDS {
        let mut signed = signed_head(&key, scope.digest(), digest(&format!("head-{index}")));
        signed.witness.generation = Generation::new(index as u64).fixture("head generation");
        signed.witness.predecessor_head_digest = predecessor;
        signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
        fs::write(
            owner.signed_head_record_path(&signed),
            encode_signed_head(&signed),
        )
        .fixture("complete authenticated historical head");
        predecessor = signed.witness.head_digest;
    }
    let mut last = signed_head(&key, scope.digest(), digest("last-legal-head"));
    last.witness.generation = Generation::new(MAX_HEAD_RECORDS as u64).fixture("last generation");
    last.witness.predecessor_head_digest = predecessor;
    last.signature = key.sign(&last.signing_bytes()).to_bytes();
    owner
        .persist_signed_head_record(&last)
        .fixture("last legal CURRENT record fits");
    let before = fs::read_dir(directory.0.join("heads"))
        .fixture("head entries")
        .count();
    assert_eq!(before, MAX_HEAD_RECORDS);
    let mut extra = last.clone();
    extra.witness.generation = last.witness.generation.next().fixture("next generation");
    extra.witness.predecessor_head_digest = last.witness.head_digest;
    extra.witness.head_digest = digest("extra-head");
    extra.signature = key.sign(&extra.signing_bytes()).to_bytes();
    assert!(owner.persist_signed_head_record(&extra).is_err());
    assert_eq!(
        fs::read_dir(directory.0.join("heads"))
            .fixture("unchanged entries")
            .count(),
        before
    );
    assert_eq!(
        owner
            .discover_current_head(/*now*/ 20)
            .fixture("maximum valid inventory is readable")
            .fixture("CURRENT")
            .signed,
        last,
    );
}
