//! DATA codec and immutable-byte compatibility controls only. Synthetic hashes
//! and profile text here are not signed receipts, Root acceptance or authority.

use pretty_assertions::assert_eq;

use super::*;

// Retain the exact old field order and seven-element representation so the
// comparison is against the prior wire encoding, not two copies of the new type.
#[derive(Serialize)]
struct LegacyAcceptanceData {
    schema: u8,
    purpose: String,
    initial: String,
    target: String,
    deployment: String,
    original_profile: String,
    frozen_scope: String,
    terminal_head: String,
    checkpoint: String,
    root_verified_at_seconds: u64,
    original_task: String,
    journals: [String; 7],
    signatures: [String; 7],
    independent_b: String,
    publication: String,
}

fn legacy_data() -> LegacyAcceptanceData {
    let digest = |label: &str| Digest32::of_bytes(label.as_bytes()).to_string();
    LegacyAcceptanceData {
        schema: 1,
        purpose: PURPOSE.into(),
        initial: digest("initial"),
        target: digest("target"),
        deployment: digest("deployment"),
        original_profile: "{\"fixture\":\"DATA encoding only\"}".into(),
        frozen_scope: digest("frozen-scope"),
        terminal_head: digest("terminal-head"),
        checkpoint: digest("checkpoint"),
        root_verified_at_seconds: 20,
        original_task: digest("original-task"),
        journals: std::array::from_fn(|index| digest(&format!("journal-{index}"))),
        signatures: std::array::from_fn(|index| digest(&format!("signature-{index}"))),
        independent_b: digest("independent-b"),
        publication: digest("publication"),
    }
}

#[test]
fn original_seven_signature_record_has_identical_wire_bytes_and_digest() -> anyhow::Result<()> {
    let original = legacy_data();
    let bytes = serde_json::to_vec(&original)?;
    let decoded: RootCompletedLearningAcceptanceDataV1 = serde_json::from_slice(&bytes)?;
    assert!(matches!(
        &decoded.signatures,
        CompletedSignatureDigests::Seven(_)
    ));
    assert_eq!(
        decoded.signatures.as_slice(),
        original.signatures.as_slice()
    );
    assert_eq!(decoded.journals, original.journals);
    assert_eq!(serde_json::to_vec(&decoded)?, bytes);
    assert_eq!(
        decoded.data_digest()?,
        Digest32::of_parts(&[b"hepta.root.completed-learning.acceptance.v1\0", &bytes])
    );
    Ok(())
}

#[test]
fn six_signature_record_is_distinct_and_roundtrips_without_padding() -> anyhow::Result<()> {
    let original_bytes = serde_json::to_vec(&legacy_data())?;
    let original: RootCompletedLearningAcceptanceDataV1 = serde_json::from_slice(&original_bytes)?;
    let mut six = original.clone();
    six.signatures = CompletedSignatureDigests::Six(std::array::from_fn(|index| {
        Digest32::of_bytes(format!("six-signature-{index}").as_bytes()).to_string()
    }));
    let bytes = serde_json::to_vec(&six)?;
    let value: serde_json::Value = serde_json::from_slice(&bytes)?;
    let signatures = value["signatures"]
        .as_array()
        .ok_or_else(|| anyhow::anyhow!("signature array missing"))?;
    assert_eq!(signatures.len(), 6);
    assert!(signatures.iter().all(serde_json::Value::is_string));
    assert_eq!(six.journals, original.journals);
    assert_eq!(
        serde_json::from_slice::<RootCompletedLearningAcceptanceDataV1>(&bytes)?,
        six
    );
    assert_ne!(six, original);
    assert_ne!(six.data_digest()?, original.data_digest()?);
    assert_eq!(serde_json::to_vec(&original)?, original_bytes);
    Ok(())
}

#[test]
fn signature_digest_data_rejects_other_lengths_or_element_types() -> anyhow::Result<()> {
    let original = serde_json::to_value(&legacy_data())?;
    let digest = Digest32::of_bytes(b"bounded-signature-data").to_string();
    for length in [0, 1, 5, 8, 128] {
        let mut changed = original.clone();
        changed["signatures"] = serde_json::to_value(vec![digest.clone(); length])?;
        assert!(serde_json::from_value::<RootCompletedLearningAcceptanceDataV1>(changed).is_err());
    }
    for length in [6, 7] {
        let mut changed = original.clone();
        changed["signatures"] = serde_json::to_value(vec![digest.clone(); length])?;
        let decoded: RootCompletedLearningAcceptanceDataV1 =
            serde_json::from_value(changed.clone())?;
        assert_eq!(decoded.signatures.as_slice().len(), length);
        for replacement in [
            serde_json::Value::Null,
            serde_json::json!(1),
            serde_json::json!({}),
        ] {
            let mut malformed = changed.clone();
            malformed["signatures"][0] = replacement;
            assert!(
                serde_json::from_value::<RootCompletedLearningAcceptanceDataV1>(malformed).is_err()
            );
        }
    }
    let mut extra = original;
    extra["signature_padding"] = serde_json::Value::Null;
    assert!(serde_json::from_value::<RootCompletedLearningAcceptanceDataV1>(extra).is_err());
    Ok(())
}
