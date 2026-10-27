//! Real selection/CURRENT byte checks; no model or product qualification.
use super::*;

#[test]
fn public_initial_admission_rejects_profile_crossing_and_changed_factors() {
    let original = material();
    for public in [false, true] {
        for changed in [false, true] {
            let mut bytes = original.clone();
            if changed {
                *bytes.last_mut().unwrap() = 1;
            }
            let mut declared = manifest(&bytes);
            if public {
                declared.compatibility_digest =
                    Digest32::of_bytes(SMOLLM_PUBLIC_INITIAL_PROFILE_V2);
            }
            let fixture = Fixture::new(&bytes, declared);
            for v2 in [false, true] {
                let (current, snapshot) = fixture.current();
                let selected = fixture
                    .selector
                    .verify(&fixture.signed(&current), &current, /*now*/ 30)
                    .unwrap();
                let result = if v2 {
                    selected
                        .load_public_initial_smollm_material_v2(
                            File::open(snapshot).unwrap(),
                            File::open(fixture.root.join("payload")).unwrap(),
                            current,
                            /*now*/ 30,
                        )
                        .map(|mut value| {
                            let (current, _) = fixture.current();
                            value
                                .with_current(current, /*now*/ 30, Digest32::of_bytes)
                                .unwrap()
                        })
                } else {
                    selected
                        .load_initial_smollm_material(
                            File::open(snapshot).unwrap(),
                            File::open(fixture.root.join("payload")).unwrap(),
                            current,
                            /*now*/ 30,
                        )
                        .map(|mut value| {
                            let (current, _) = fixture.current();
                            value
                                .with_current(current, /*now*/ 30, Digest32::of_bytes)
                                .unwrap()
                        })
                };
                assert_eq!(result.is_ok(), public == v2 && !changed);
                if let Ok(actual) = result {
                    assert_eq!(actual, Digest32::of_bytes(&original));
                }
            }
        }
    }
}

#[test]
fn public_initial_expired_current_is_sticky_and_cannot_be_revived() {
    let bytes = material();
    let mut declared = manifest(&bytes);
    declared.compatibility_digest = Digest32::of_bytes(SMOLLM_PUBLIC_INITIAL_PROFILE_V2);
    let fixture = Fixture::new(&bytes, declared);
    let (current, snapshot) = fixture.current();
    let selected = fixture
        .selector
        .verify(&fixture.signed(&current), &current, /*now*/ 30)
        .unwrap();
    let mut value = selected
        .load_public_initial_smollm_material_v2(
            File::open(snapshot).unwrap(),
            File::open(fixture.root.join("payload")).unwrap(),
            current,
            /*now*/ 30,
        )
        .unwrap();
    let (current, _) = fixture.current();
    assert!(value.with_current(current, /*now*/ 81, |_| ()).is_err());
    let (current, _) = fixture.current();
    assert!(value.with_current(current, /*now*/ 30, |_| ()).is_err());
}
