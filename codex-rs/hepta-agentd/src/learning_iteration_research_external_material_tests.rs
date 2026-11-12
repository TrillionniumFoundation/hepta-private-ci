//! Primitive boundaries only. Synthetic parser fixtures confer no training,
//! improvement, adoption, or production qualification. The actual native run
//! separately checks the new real candidate and durable owner through cold use.

use super::*;
use std::fs;
use std::os::unix::fs::symlink;


// The material reader intentionally refuses symlinked ancestors. macOS TMPDIR
// may be spelled through /var -> /private/var. Resolve only the trusted test
// fixture parent before creating it; do not relax production NOFOLLOW.
fn physical_tempdir() -> tempfile::TempDir {
    let parent = std::env::temp_dir()
        .canonicalize()
        .expect("physical temporary test parent");
    tempfile::Builder::new()
        .prefix("hepta-material-")
        .tempdir_in(parent)
        .expect("physical temporary test fixture")
}

#[test]
fn research_material_fixture_root_is_physical_and_readable() {
    let temp = physical_tempdir();
    assert_eq!(
        temp.path(),
        temp.path().canonicalize().expect("canonical fixture path")
    );
    assert!(directory(temp.path()).is_ok());
}

fn tensor_file(header: &Value, payload: &[u8]) -> anyhow::Result<Vec<u8>> {
    let header = canonical(header)?;
    let mut bytes = (header.len() as u64).to_le_bytes().to_vec();
    bytes.extend_from_slice(&header);
    bytes.extend_from_slice(payload);
    Ok(bytes)
}

#[test]
fn research_material_rejects_duplicate_json_keys_at_any_depth() {
    assert_eq!(
        parse(br#"{"b":[true,1,"x"],"a":null}"#).unwrap(),
        json!({"a":null,"b":[true,1,"x"]})
    );
    for raw in [
        br#"{"x":1,"x":2}"#.as_slice(),
        br#"{"a":[{"x":1,"x":1}]}"#,
        br#"{"a":NaN}"#,
        br#"{}{}"#,
    ] {
        assert!(parse(raw).is_err());
    }
}

#[test]
fn research_material_canonicalization_sorts_every_object_level() {
    let value = parse(br#"{"z":{"b":2,"a":1},"a":[{"y":2,"x":1}]}"#).unwrap();
    assert_eq!(
        canonical(&value).unwrap(),
        br#"{"a":[{"x":1,"y":2}],"z":{"a":1,"b":2}}"#
    );
}

#[test]
fn research_material_tensors_reject_overlap_holes_trailing_and_nonfinite() -> anyhow::Result<()> {
    let header = json!({"a":{"dtype":"F32","shape":[1],"data_offsets":[0,4]},
        "b":{"dtype":"I64","shape":[1],"data_offsets":[4,12]}});
    let mut payload = 1f32.to_le_bytes().to_vec();
    payload.extend_from_slice(&7i64.to_le_bytes());
    let raw = tensor_file(&header, &payload)?;
    assert_eq!(tensors(&raw).unwrap()["a"].raw, 1f32.to_le_bytes());
    let mut overlap = header.clone();
    overlap["b"]["data_offsets"] = json!([0, 8]);
    assert!(tensors(&tensor_file(&overlap, &payload)?).is_err());
    let mut hole = header.clone();
    hole["b"]["data_offsets"] = json!([5, 13]);
    let mut extended = payload.clone();
    extended.push(0);
    assert!(tensors(&tensor_file(&hole, &extended)?).is_err());
    assert!(tensors(&tensor_file(&header, &extended)?).is_err());
    payload[..4].copy_from_slice(&f32::INFINITY.to_le_bytes());
    assert!(tensors(&tensor_file(&header, &payload)?).is_err());
    Ok(())
}

#[test]
fn research_material_reads_reject_leaf_ancestor_and_hardlink_aliases() {
    let temp = physical_tempdir();
    let actual = temp.path().join("actual");
    fs::create_dir(&actual).unwrap();
    fs::write(actual.join("file"), b"retained").unwrap();
    let mut inputs = Inputs::default();
    assert_eq!(inputs.read(&actual.join("file"), 8).unwrap(), b"retained");
    symlink(actual.join("file"), temp.path().join("leaf")).unwrap();
    symlink(&actual, temp.path().join("ancestor")).unwrap();
    assert!(inputs.read(&temp.path().join("leaf"), 8).is_err());
    assert!(inputs.read(&temp.path().join("ancestor/file"), 8).is_err());
    fs::hard_link(actual.join("file"), actual.join("alias")).unwrap();
    assert!(inputs.read(&actual.join("file"), 8).is_err());
    assert!(directory(&actual.join("../actual")).is_err());
}

#[test]
fn research_material_size_reference_and_mutation_checks_use_actual_bytes() {
    let temp = physical_tempdir();
    let path = temp.path().join("input");
    fs::write(&path, b"before").unwrap();
    let reference =
        json!({"path":path,"sha256":Digest32::of_bytes(b"before").to_string(),"bytes":6});
    let mut inputs = Inputs::default();
    assert_eq!(inputs.pinned(&reference, 6).unwrap(), b"before");
    assert!(inputs.pinned(&reference, 5).is_err());
    let mut wrong_size = reference.clone();
    wrong_size["bytes"] = 5.into();
    assert!(inputs.pinned(&wrong_size, 6).is_err());
    fs::write(&path, b"after!").unwrap();
    assert!(inputs.pinned(&reference, 6).is_err());
}

#[test]
fn research_owner_publication_is_create_only_and_detects_directory_replacement() {
    let temp = physical_tempdir();
    let path = temp.path().join("owner");
    let owner = Directory::create(path.clone()).unwrap();
    owner.publish("receipt.json", b"original").unwrap();
    assert!(owner.publish("receipt.json", b"replacement").is_err());
    assert_eq!(owner.read("receipt.json").unwrap(), b"original");
    fs::rename(&path, temp.path().join("retired")).unwrap();
    fs::create_dir(&path).unwrap();
    assert!(owner.require_linked().is_err());
    assert_eq!(owner.read("receipt.json").unwrap(), b"original");
}

#[test]
fn research_owner_concurrent_handles_cas_has_exactly_one_retained_winner() {
    let temp = physical_tempdir();
    let path = temp.path().join("owner");
    let first = Directory::create(path.clone()).unwrap();
    let second = Directory::create(path).unwrap();
    let barrier = std::sync::Arc::new(std::sync::Barrier::new(2));
    let other = std::sync::Arc::clone(&barrier);
    let a = std::thread::spawn(move || {
        barrier.wait();
        first.publish("reservation.json", b"first").is_ok()
    });
    let b = std::thread::spawn(move || {
        other.wait();
        second.publish("reservation.json", b"second").is_ok()
    });
    let won_a = a.join().unwrap();
    let won_b = b.join().unwrap();
    assert_ne!(won_a, won_b);
    let reopened = Directory::create(temp.path().join("owner")).unwrap();
    assert_eq!(
        reopened.read("reservation.json").unwrap(),
        if won_a {
            b"first".as_slice()
        } else {
            b"second"
        }
    );
    assert!(reopened.optional("receipt.json").unwrap().is_none());
}

#[test]
fn research_owner_partial_entries_are_observable_and_never_replaced() {
    let temp = physical_tempdir();
    let owner = Directory::create(temp.path().join("owner")).unwrap();
    owner.publish("reservation.json", b"reserved").unwrap();
    fs::write(temp.path().join("owner/receipt.json"), b"{").unwrap();
    let raw = owner.read("receipt.json").unwrap();
    assert!(parse(&raw).is_err());
    assert!(owner.publish("receipt.json", b"{}").is_err());
    assert_eq!(owner.read("receipt.json").unwrap(), raw);
}

#[test]
fn research_owner_initial_freeze_rejects_existing_training_or_evaluation() {
    let temp = physical_tempdir();
    assert!(require_unstarted(temp.path()).is_ok());
    for name in [
        "training-start.json",
        "native-training-admission.json",
        "train-result.json",
        "evaluate-result.json",
    ] {
        let path = temp.path().join(name);
        fs::write(&path, b"{}").unwrap();
        assert!(require_unstarted(temp.path()).is_err());
        fs::remove_file(path).unwrap();
    }
}
