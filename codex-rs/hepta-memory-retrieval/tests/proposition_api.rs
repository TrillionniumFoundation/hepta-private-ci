use codex_hepta_memory_retrieval::ContradictionEvidenceV2;
use codex_hepta_memory_retrieval::PropositionPolarityV2;
use codex_hepta_memory_retrieval::RecallErrorV1;
use codex_hepta_types::Digest32;

#[test]
fn canonical_value_constructor_derives_the_only_proposition_digest() {
    let generation = Digest32::of_bytes(b"generation-7");
    let evidence = ContradictionEvidenceV2::from_canonical_value(
        b"subject\x1fpredicate\x1fobject\x1fscope",
        generation,
        PropositionPolarityV2::Affirmed,
    )
    .expect("canonical proposition evidence");

    assert_eq!(
        evidence.proposition_digest(),
        Digest32::of_bytes(b"subject\x1fpredicate\x1fobject\x1fscope")
    );
    assert_eq!(evidence.generation_vector_digest(), generation);
    assert_eq!(evidence.polarity(), PropositionPolarityV2::Affirmed);
    evidence.validate(generation).expect("bound generation");
}

#[test]
fn empty_canonical_value_cannot_be_represented_as_evidence() {
    let error = ContradictionEvidenceV2::from_canonical_value(
        b"",
        Digest32::of_bytes(b"generation-7"),
        PropositionPolarityV2::Denied,
    )
    .expect_err("empty canonical value must fail");

    assert_eq!(
        error,
        RecallErrorV1::EmptyDigest("canonical_proposition_value")
    );
}
