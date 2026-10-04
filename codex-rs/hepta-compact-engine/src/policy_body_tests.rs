use super::*;
use pretty_assertions::assert_eq;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}
fn policy() -> CompactionPolicyV2 {
    CompactionPolicyV2 {
        policy_id: id("policy"),
        algorithm_digest: Digest32::from_array([1; 32]),
        compatibility_digest: Digest32::from_array([2; 32]),
        maximum_retained_records: 7,
        protected_record_ids: vec![id("b"), id("a")],
    }
}
fn header_end() -> usize {
    DOMAIN.len() + 8 + 6 + 64 + 16
}

#[test]
fn canonical_body_preserves_existing_semantic_digest_and_sorts_the_set() {
    let original = policy();
    let body = encode_compaction_policy_body_v2(&original).unwrap();
    assert_eq!(Digest32::of_bytes(&body), original.digest());
    let mut canonical = original.clone();
    canonical.protected_record_ids.sort();
    let decoded = decode_compaction_policy_body_v2(&body).unwrap();
    assert_eq!(decoded, canonical);
    assert_eq!(encode_compaction_policy_body_v2(&decoded).unwrap(), body);
    assert_eq!(decoded.digest(), original.digest());
}

#[test]
fn independent_wire_vector_matches_existing_digest_preimage() {
    let expected = [
        b"hepta.compaction-policy.v2".as_slice(),
        &6_u64.to_be_bytes(),
        b"policy",
        &[1; 32],
        &[2; 32],
        &7_u64.to_be_bytes(),
        &2_u64.to_be_bytes(),
        &1_u64.to_be_bytes(),
        b"a",
        &1_u64.to_be_bytes(),
        b"b",
    ]
    .concat();
    assert_eq!(
        encode_compaction_policy_body_v2(&policy()).unwrap(),
        expected
    );
    assert_eq!(Digest32::of_bytes(&expected), policy().digest());
}

#[test]
fn every_truncation_unknown_domain_and_trailing_data_are_rejected() {
    let body = encode_compaction_policy_body_v2(&policy()).unwrap();
    for length in 0..body.len() {
        assert!(decode_compaction_policy_body_v2(&body[..length]).is_err());
    }
    for offset in 0..DOMAIN.len() {
        let mut changed = body.clone();
        changed[offset] ^= 1;
        assert!(matches!(
            decode_compaction_policy_body_v2(&changed),
            Err(PolicyBodyErrorV2::Malformed("domain"))
        ));
    }
    let mut extended = body;
    extended.push(0);
    assert!(matches!(
        decode_compaction_policy_body_v2(&extended),
        Err(PolicyBodyErrorV2::Malformed("trailing bytes"))
    ));
}

#[test]
fn length_count_and_total_size_limits_precede_allocation() {
    let body = encode_compaction_policy_body_v2(&policy()).unwrap();
    for length in [0_u64, 129, u64::MAX] {
        for offset in [DOMAIN.len(), header_end()] {
            let mut changed = body.clone();
            changed[offset..offset + 8].copy_from_slice(&length.to_be_bytes());
            assert!(decode_compaction_policy_body_v2(&changed).is_err());
        }
    }
    let count_offset = header_end() - 8;
    for count in [4097_u64, u64::MAX] {
        let mut changed = body.clone();
        changed[count_offset..count_offset + 8].copy_from_slice(&count.to_be_bytes());
        assert!(matches!(
            decode_compaction_policy_body_v2(&changed),
            Err(PolicyBodyErrorV2::Size)
        ));
    }
    let mut impossible = body;
    impossible[count_offset..count_offset + 8].copy_from_slice(&4096_u64.to_be_bytes());
    assert!(matches!(
        decode_compaction_policy_body_v2(&impossible),
        Err(PolicyBodyErrorV2::Malformed("truncated IDs"))
    ));
    assert!(matches!(
        decode_compaction_policy_body_v2(&vec![0; MAX_COMPACTION_POLICY_BODY_BYTES_V2 + 1]),
        Err(PolicyBodyErrorV2::Size)
    ));
}

#[test]
fn malformed_identifiers_duplicate_and_unsorted_wire_ids_reject() {
    let body = encode_compaction_policy_body_v2(&policy()).unwrap();
    for byte in [b'/', b' ', 0, 0xff] {
        let mut changed = body.clone();
        changed[DOMAIN.len() + 8] = byte;
        assert!(decode_compaction_policy_body_v2(&changed).is_err());
    }
    let start = header_end();
    let mut duplicate = body.clone();
    duplicate[start + 17] = b'a';
    assert!(matches!(
        decode_compaction_policy_body_v2(&duplicate),
        Err(PolicyBodyErrorV2::Malformed("noncanonical ID order"))
    ));
    let mut swapped = body;
    swapped[start + 8] = b'b';
    swapped[start + 17] = b'a';
    assert!(matches!(
        decode_compaction_policy_body_v2(&swapped),
        Err(PolicyBodyErrorV2::Malformed("noncanonical ID order"))
    ));
}

#[test]
fn invalid_retention_and_zero_digests_preserve_policy_validation() {
    let body = encode_compaction_policy_body_v2(&policy()).unwrap();
    let retention = header_end() - 16;
    let mut overflow = body.clone();
    overflow[retention..retention + 8].copy_from_slice(&u64::MAX.to_be_bytes());
    assert!(matches!(
        decode_compaction_policy_body_v2(&overflow),
        Err(PolicyBodyErrorV2::Malformed("retention overflow"))
    ));
    let mut zero = body.clone();
    zero[retention..retention + 8].fill(0);
    assert!(matches!(
        decode_compaction_policy_body_v2(&zero),
        Err(PolicyBodyErrorV2::InvalidPolicy(_))
    ));
    for offset in [DOMAIN.len() + 14, DOMAIN.len() + 46] {
        let mut zero = body.clone();
        zero[offset..offset + 32].fill(0);
        assert!(matches!(
            decode_compaction_policy_body_v2(&zero),
            Err(PolicyBodyErrorV2::InvalidPolicy(_))
        ));
    }
    let mut invalid = policy();
    invalid.maximum_retained_records = 0;
    assert!(matches!(
        encode_compaction_policy_body_v2(&invalid),
        Err(PolicyBodyErrorV2::InvalidPolicy(_))
    ));
}

#[test]
fn maximum_protected_id_set_roundtrips_and_next_entry_rejects() {
    let mut original = policy();
    original.protected_record_ids = (0..MAX_PROTECTED_COMPACTION_REFS)
        .rev()
        .map(|index| id(&format!("id-{index:04}-{}", "x".repeat(120))))
        .collect();
    let body = encode_compaction_policy_body_v2(&original).unwrap();
    assert!(body.len() < MAX_COMPACTION_POLICY_BODY_BYTES_V2);
    let decoded = decode_compaction_policy_body_v2(&body).unwrap();
    assert_eq!(
        decoded.protected_record_ids.len(),
        MAX_PROTECTED_COMPACTION_REFS
    );
    assert_eq!(Digest32::of_bytes(&body), original.digest());
    assert_eq!(decoded.digest(), original.digest());
    original.protected_record_ids.push(id("one-too-many"));
    assert!(matches!(
        encode_compaction_policy_body_v2(&original),
        Err(PolicyBodyErrorV2::InvalidPolicy(_))
    ));
}

#[test]
fn empty_protected_set_and_maximum_retention_keep_exact_digest() {
    let mut original = policy();
    original.protected_record_ids.clear();
    original.maximum_retained_records = 65_536;
    let body = encode_compaction_policy_body_v2(&original).unwrap();
    assert_eq!(decode_compaction_policy_body_v2(&body).unwrap(), original);
    assert_eq!(Digest32::of_bytes(&body), original.digest());
}
