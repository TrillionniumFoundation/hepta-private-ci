use pretty_assertions::assert_eq;

use super::request::Surface;
use super::request::parse_request;
use super::test_support::PROMPT;
use super::test_support::app_request;
use super::test_support::mcp_request;
use crate::QualificationError;

#[test]
fn parses_the_frozen_app_server_pair() -> Result<(), QualificationError> {
    for ordinal in 1..=2 {
        let bytes = app_request(ordinal)?;
        let parsed = parse_request(Surface::AppServer, ordinal, &bytes, "/unused")?;
        assert_eq!(parsed.body_sha256.len(), 64);
        assert_eq!(parsed.provider_semantic_sha256.len(), 64);
        assert_eq!(parsed.sample_token_sha256.len(), 64);
    }
    Ok(())
}

#[test]
fn parses_the_frozen_mcp_pair() -> Result<(), QualificationError> {
    let cwd = "/private/tmp/hepta-shadow";
    for ordinal in 1..=2 {
        let bytes = mcp_request(ordinal, cwd)?;
        let parsed = parse_request(Surface::Mcp, ordinal, &bytes, cwd)?;
        assert_eq!(parsed.body_sha256.len(), 64);
    }
    Ok(())
}

#[test]
fn rejects_noncanonical_or_multiline_requests() -> Result<(), QualificationError> {
    let noncanonical = format!(
        "{{\"method\":\"turn/start\",\"id\":3,\"params\":{{\"threadId\":\"thread\",\"input\":[{{\"type\":\"text\",\"text\":{PROMPT:?},\"textElements\":[]}}]}}}}\n"
    );
    assert!(parse_request(Surface::AppServer, 1, noncanonical.as_bytes(), "/unused").is_err());

    let multiline = noncanonical.replace("\"id\":3", "\n\"id\":3");
    assert!(parse_request(Surface::AppServer, 1, multiline.as_bytes(), "/unused").is_err());
    Ok(())
}
