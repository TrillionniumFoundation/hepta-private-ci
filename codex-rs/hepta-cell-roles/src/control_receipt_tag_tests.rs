use super::*;
use pretty_assertions::assert_eq;
use std::error::Error;
use std::io;

fn digest(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}

fn terminal_owner() -> Result<InMemoryControlRoleOwnerV1, Box<dyn Error>> {
    let dispatch_id = StableId::new("dispatch.receipt-tag")?;
    let cell_id = StableId::new("cell.receipt-tag")?;
    let generation = Generation::new(3)?;
    let route_fence_digest = digest("receipt-tag-fence");
    let mut owner = InMemoryControlRoleOwnerV1::default();
    owner.activate_generation(cell_id.clone(), generation, route_fence_digest)?;
    owner.prepare(ControlDispatchIntentV1 {
        dispatch_id: dispatch_id.clone(),
        cell_id,
        generation,
        scope_digest: digest("receipt-tag-scope"),
        operation: ControlOperationKindV1::Router,
        request_digest: digest("receipt-tag-request"),
        route_fence_digest,
        idempotency_key_digest: digest("receipt-tag-idempotency"),
        payload_digest: digest("receipt-tag-payload"),
        precondition_digest: digest("receipt-tag-precondition"),
        effect_class_digest: digest("receipt-tag-effect"),
        deadline_ms: 10,
        expiry_ms: 20,
        authority: AuthorityPosture::DENY_ALL,
    })?;
    owner.forward(&dispatch_id)?;
    owner.record_terminal(&dispatch_id, digest("receipt-tag-terminal"))?;
    Ok(owner)
}

fn reconciled_owner() -> Result<InMemoryControlRoleOwnerV1, Box<dyn Error>> {
    let mut owner = terminal_owner()?;
    owner.reconcile_restart(&StableId::new("dispatch.receipt-tag")?)?;
    Ok(owner)
}

fn directory(label: &str) -> Result<PathBuf, Box<dyn Error>> {
    let nonce = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)?
        .as_nanos();
    let directory = std::env::temp_dir().join(format!(
        "hepta-control-receipt-tag-{label}-{}-{nonce}",
        std::process::id()
    ));
    fs::create_dir(&directory)?;
    Ok(directory)
}

fn encoded_tag_offset(
    owner: &InMemoryControlRoleOwnerV1,
    snapshot: &[u8],
) -> Result<usize, Box<dyn Error>> {
    assert_eq!(owner.records.len(), 1);
    let record = owner
        .records
        .values()
        .next()
        .ok_or_else(|| io::Error::other("missing test receipt"))?;
    let mut receipt = Vec::new();
    encode_receipt(&mut receipt, &record.receipt);
    let positions: Vec<_> = snapshot
        .windows(receipt.len())
        .enumerate()
        .filter_map(|(offset, bytes)| (bytes == receipt).then_some(offset))
        .collect();
    assert_eq!(positions.len(), 1);
    let present = record.receipt.restart_reconciliation_digest.is_some();
    let tag_offset = positions[0] + receipt.len() - if present { 33 } else { 1 };
    assert_eq!(snapshot[tag_offset], u8::from(present));
    Ok(tag_offset)
}

fn replace_tag_and_checksum(snapshot: &[u8], tag_offset: usize, tag: u8) -> Vec<u8> {
    let mut bytes = snapshot.to_vec();
    bytes[tag_offset] = tag;
    let payload_length = bytes.len() - 32;
    let checksum = digest_bytes(
        b"hepta.cell-role.control-owner.snapshot.v1",
        &[&bytes[..payload_length]],
    );
    bytes[payload_length..].copy_from_slice(checksum.as_array());
    bytes
}

#[test]
fn canonical_absent_and_present_receipts_decode_and_reopen() -> Result<(), Box<dyn Error>> {
    let directory = directory("canonical")?;
    for (label, owner) in [
        ("absent", terminal_owner()?),
        ("present", reconciled_owner()?),
    ] {
        let bytes = encode_durable_control(&owner)?;
        encoded_tag_offset(&owner, &bytes)?;
        let decoded = decode_durable_control(&bytes)?;
        assert_eq!(decoded, owner);
        assert_eq!(encode_durable_control(&decoded)?, bytes);
        let path = directory.join(label);
        fs::write(&path, &bytes)?;
        let reopened = DurableControlRoleOwnerV1::open(&path)?;
        assert_eq!(reopened.inner(), &owner);
        assert_eq!(fs::read(&path)?, bytes);
        drop(reopened);
    }
    fs::remove_dir_all(directory)?;
    Ok(())
}

#[test]
fn every_noncanonical_reconciliation_tag_rejects_a_valid_checksum() -> Result<(), Box<dyn Error>> {
    let owner = reconciled_owner()?;
    let original = encode_durable_control(&owner)?;
    assert_eq!(decode_durable_control(&original)?, owner);
    let tag_offset = encoded_tag_offset(&owner, &original)?;
    for tag in 2..=u8::MAX {
        let malformed = replace_tag_and_checksum(&original, tag_offset, tag);
        assert_eq!(
            decode_durable_control(&malformed),
            Err(ControlOwnerErrorV1::InvalidDurableSnapshot),
            "noncanonical reconciliation tag {tag}"
        );
    }
    Ok(())
}

#[test]
fn every_noncanonical_reconciliation_tag_is_rejected_on_reopen() -> Result<(), Box<dyn Error>> {
    let directory = directory("invalid-reopen")?;
    let path = directory.join("snapshot");
    let owner = reconciled_owner()?;
    let original = encode_durable_control(&owner)?;
    let tag_offset = encoded_tag_offset(&owner, &original)?;
    fs::write(&path, &original)?;
    let positive = DurableControlRoleOwnerV1::open(&path)?;
    assert_eq!(positive.inner(), &owner);
    drop(positive);
    for tag in 2..=u8::MAX {
        let malformed = replace_tag_and_checksum(&original, tag_offset, tag);
        fs::write(&path, &malformed)?;
        assert_eq!(
            DurableControlRoleOwnerV1::open(&path),
            Err(ControlOwnerErrorV1::InvalidDurableSnapshot),
            "noncanonical reconciliation tag {tag}"
        );
        assert_eq!(fs::read(&path)?, malformed);
    }
    fs::remove_dir_all(directory)?;
    Ok(())
}
