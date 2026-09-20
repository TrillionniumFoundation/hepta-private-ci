use pretty_assertions::assert_eq;

use super::AgentId;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

#[test]
fn canonical_id_is_stable_across_display_parse_and_serde() -> Result<(), Box<dyn std::error::Error>>
{
    let parsed = AgentId::parse(AGENT_ID)?;
    let json = serde_json::to_string(&parsed)?;
    let decoded: AgentId = serde_json::from_str(&json)?;

    assert_eq!(
        (parsed.clone(), parsed.to_string(), json, decoded),
        (
            AGENT_ID.parse::<AgentId>()?,
            AGENT_ID.to_string(),
            format!("\"{AGENT_ID}\""),
            parsed,
        )
    );
    Ok(())
}

#[test]
fn noncanonical_or_directory_unsafe_ids_are_rejected() {
    for value in [
        "018F4F72-5F8F-7CC1-8F55-DF9FB3AA2C12",
        "018f4f725f8f7cc18f55df9fb3aa2c12",
        "018f4f72-5f8f-0cc1-8f55-df9fb3aa2c12",
        "018f4f72-5f8f-7cc1-7f55-df9fb3aa2c12",
        "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c1/",
        "../018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12",
    ] {
        assert!(AgentId::parse(value).is_err(), "accepted {value:?}");
    }
}

#[test]
fn deserialize_revalidates_untrusted_wire_value() {
    let error = serde_json::from_str::<AgentId>("\"018F4F72-5F8F-7CC1-8F55-DF9FB3AA2C12\"")
        .expect_err("uppercase agent id must be rejected");

    assert_eq!(
        error.to_string(),
        "agent id must be a canonical lowercase UUID"
    );
}
