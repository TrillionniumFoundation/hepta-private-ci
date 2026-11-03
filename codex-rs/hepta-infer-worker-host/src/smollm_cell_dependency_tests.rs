//! Cross-language codec controls only; the actual material factory still requires
//! its fixed public family and real payload pins before this boundary is reached.

use super::*;
use pretty_assertions::assert_eq;

fn fixture() -> (Vec<u8>, Digest32, Vec<u8>, Vec<Member>) {
    let value: serde_json::Value = serde_json::from_str(include_str!(
        "../fixtures/smollm-cell-tcd1-synthetic-v1.json"
    ))
    .unwrap();
    let decode = |key: &str| super::super::wire::unhex(value[key].as_str().unwrap()).unwrap();
    (
        decode("wire_hex"),
        value["closure_id"].as_str().unwrap().parse().unwrap(),
        decode("release_hex"),
        serde_json::from_value(value["members"].clone()).unwrap(),
    )
}

#[test]
fn exact_existing_eleven_file_profile_matches_independent_python_tcd1() {
    let (wire, id, release, members) = fixture();
    assert_eq!(
        verify(
            DependencyPlan::PinnedTcd1 { wire, id },
            /*generation*/ 3,
            Digest32::from_array([6; 32]),
            &release,
            &members
        ),
        Ok(())
    );
}

#[test]
fn every_changed_wire_byte_cannot_be_reauthorized_by_changing_its_self_hash() {
    let (wire, _, release, members) = fixture();
    for offset in 0..wire.len() {
        let mut changed = wire.clone();
        changed[offset] ^= 1;
        let id = Digest32::of_parts(&[b"trnm.cell-dependency-closure.v1\0", &changed]);
        assert!(
            verify(
                DependencyPlan::PinnedTcd1 { wire: changed, id },
                /*generation*/ 3,
                Digest32::from_array([6; 32]),
                &release,
                &members
            )
            .is_err(),
            "byte {offset}"
        );
    }
}

#[test]
fn exact_plan_refuses_wrong_current_generation_profile_missing_member_and_readme_alias() {
    let (wire, id, release, mut members) = fixture();
    for (generation, profile) in [(4, [6; 32]), (3, [7; 32])] {
        assert!(
            verify(
                DependencyPlan::PinnedTcd1 {
                    wire: wire.clone(),
                    id
                },
                generation,
                Digest32::from_array(profile),
                &release,
                &members
            )
            .is_err()
        );
    }
    assert!(
        verify(
            DependencyPlan::PinnedTcd1 {
                wire: wire.clone(),
                id
            },
            /*generation*/ 3,
            Digest32::from_array([6; 32]),
            &release,
            &members[..10]
        )
        .is_err()
    );
    members[3].name = "base/readme.md".to_owned();
    assert!(
        verify(
            DependencyPlan::PinnedTcd1 { wire, id },
            /*generation*/ 3,
            Digest32::from_array([6; 32]),
            &release,
            &members
        )
        .is_err()
    );
}

#[test]
fn closure_suffix_truncation_wrong_domain_and_oversize_are_rejected() {
    let (wire, id, release, members) = fixture();
    let mut suffix = wire.clone();
    suffix.push(0);
    for changed in [wire[..wire.len() - 1].to_vec(), suffix, vec![0; 1_048_577]] {
        assert!(
            verify(
                DependencyPlan::PinnedTcd1 { wire: changed, id },
                /*generation*/ 3,
                Digest32::from_array([6; 32]),
                &release,
                &members
            )
            .is_err()
        );
    }
    let wrong = Digest32::of_bytes(&wire);
    assert!(
        verify(
            DependencyPlan::PinnedTcd1 { wire, id: wrong },
            /*generation*/ 3,
            Digest32::from_array([6; 32]),
            &release,
            &members
        )
        .is_err()
    );
}
