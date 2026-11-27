use super::*;
use crate::HcsnStreamingCodecV1;
use crate::cell_test_support::checked;
use crate::hcsn_streaming_test_support::fixture;
use crate::restore_hcsn_research_state_v2;
use pretty_assertions::assert_eq;
use serde_json::Value;

fn original_records() -> Vec<Item> {
    let (context, clock, bytes) = fixture();
    let restored = checked(restore_hcsn_research_state_v2(
        &context,
        &clock,
        &bytes,
        &HcsnStreamingCodecV1,
    ));
    let journal: Journal = checked(serde_json::from_slice(&restored.state.snapshot.cost_ledger));
    journal.records
}

#[test]
fn original_cost_records_reject_duplicate_tags_and_cross_variant_fields() {
    let records = original_records();
    assert!(!records.is_empty());
    for item in records {
        assert_eq!(
            Digest32::of_bytes(item.canonical.as_bytes()).to_string(),
            item.hash
        );
        let original: Value = checked(serde_json::from_str(&item.canonical));
        let kind = checked(original["kind"].as_str().ok_or("kind"));
        let decoded = checked(Record::decode(&item.canonical));
        assert!(matches!(
            (kind, decoded),
            ("reserve", Record::Reserve(_)) | ("settle", Record::Settle(_))
        ));

        let prefix = checked(item.canonical.strip_suffix('}').ok_or("record object"));
        let duplicate_tag = format!("{prefix},\"kind\":\"{kind}\"}}");
        assert!(Record::decode(&duplicate_tag).is_err());
        let duplicate_budget = format!("{prefix},\"budget\":{}}}", original["budget"]);
        assert!(Record::decode(&duplicate_budget).is_err());

        // Even null-valued fields from the other variant must be rejected.
        let extra = if kind == "reserve" {
            "status"
        } else {
            "charge"
        };
        let cross_variant = format!("{prefix},\"{extra}\":null}}");
        assert!(Record::decode(&cross_variant).is_err());
        let unknown = format!("{prefix},\"unknown\":null}}");
        assert!(Record::decode(&unknown).is_err());
    }
}

#[test]
fn original_cost_records_reject_non_numeric_and_private_number_objects() {
    for item in original_records() {
        let original: Value = checked(serde_json::from_str(&item.canonical));
        for invalid in [
            Value::Null,
            Value::Bool(true),
            Value::String("1.0".to_owned()),
            serde_json::json!({"$serde_json::private::Number": "1.0"}),
        ] {
            let mut value = original.clone();
            value["budget"]["wall_seconds"] = invalid.clone();
            assert!(Record::decode(&checked(serde_json::to_string(&value))).is_err());
            if original["kind"] == "settle" {
                let mut value = original.clone();
                value["cumulative_wall_seconds"] = invalid;
                assert!(Record::decode(&checked(serde_json::to_string(&value))).is_err());
            }
        }
        let mut value = original;
        value["operation"] = serde_json::json!(1.0);
        assert!(Record::decode(&checked(serde_json::to_string(&value))).is_err());
    }
}
