use super::super::wire::ChatCommand;
use super::*;
struct FixtureAuth;
impl ChatCookieAuthenticator for FixtureAuth {
    fn authenticate(&self, cookie: &str) -> std::result::Result<String, String> {
        match cookie {
            "valid-a" => Ok("alice".into()),
            "valid-b" => Ok("bob".into()),
            _ => Err("expired".into()),
        }
    }
}
fn boundary() -> HttpBoundary<FixtureAuth> {
    HttpBoundary {
        authenticator: FixtureAuth,
        principal: "alice".into(),
        origin: "https://chat.example".into(),
        csrf: "a".repeat(32),
        session: "session-a".into(),
        generation: 4,
    }
}
fn request() -> Vec<u8> {
    serde_json::to_vec(&ChatRequest {
        session_id: "session-a".into(),
        connection_generation: 4,
        command: ChatCommand::List {
            cursor: None,
            limit: 5,
        },
    })
    .unwrap()
}
#[test]
fn verifier_runs_for_every_request_and_principals_cannot_cross() {
    let boundary = boundary();
    assert!(
        boundary
            .authorize(
                "POST",
                "application/json",
                "valid-a",
                &boundary.origin,
                &boundary.csrf,
                &request()
            )
            .is_ok()
    );
    for cookie in ["", "expired", "valid-b"] {
        assert!(
            boundary
                .authorize(
                    "POST",
                    "application/json",
                    cookie,
                    &boundary.origin,
                    &boundary.csrf,
                    &request()
                )
                .is_err()
        );
    }
}
#[test]
fn rejects_cross_origin_csrf_method_media_type_and_size() {
    let boundary = boundary();
    for (method, media, origin, csrf) in [
        (
            "GET",
            "application/json",
            boundary.origin.as_str(),
            boundary.csrf.as_str(),
        ),
        (
            "POST",
            "text/plain",
            boundary.origin.as_str(),
            boundary.csrf.as_str(),
        ),
        (
            "POST",
            "application/json",
            "https://attacker.example",
            boundary.csrf.as_str(),
        ),
        (
            "POST",
            "application/json",
            boundary.origin.as_str(),
            "wrong",
        ),
    ] {
        assert!(
            boundary
                .authorize(method, media, "valid-a", origin, csrf, &request())
                .is_err()
        );
    }
    assert!(
        boundary
            .authorize(
                "POST",
                "application/json",
                "valid-a",
                &boundary.origin,
                &boundary.csrf,
                &vec![b' '; 65_537]
            )
            .is_err()
    );
}
#[test]
fn rejects_session_generation_and_json_authority_smuggling() {
    let boundary = boundary();
    for (key, value) in [
        ("sessionId", serde_json::json!("other")),
        ("connectionGeneration", serde_json::json!(5)),
        ("agentId", serde_json::json!("other")),
    ] {
        let mut payload: serde_json::Value = serde_json::from_slice(&request()).unwrap();
        payload[key] = value;
        assert!(
            boundary
                .authorize(
                    "POST",
                    "application/json",
                    "valid-a",
                    &boundary.origin,
                    &boundary.csrf,
                    &serde_json::to_vec(&payload).unwrap()
                )
                .is_err()
        );
    }
}
