use pretty_assertions::assert_eq;

use super::OAuthAuthorizationOrigins;
use super::OAuthAuthorizationOriginsError;

#[test]
fn canonical_authorization_origins_round_trip_without_normalization() {
    let values = vec![
        "http://localhost:43210".to_string(),
        "http://127.0.0.1:43211".to_string(),
        "https://[::1]:43212".to_string(),
        "https://authorization.example".to_string(),
    ];
    let origins = OAuthAuthorizationOrigins::new(values.clone()).unwrap();
    assert_eq!(origins.as_slice(), values);
    assert_eq!(
        serde_json::to_value(&origins).unwrap(),
        serde_json::json!(values)
    );
    assert_eq!(
        serde_json::from_value::<OAuthAuthorizationOrigins>(serde_json::json!(values)).unwrap(),
        origins
    );
    assert_eq!(
        serde_json::from_str::<OAuthAuthorizationOrigins>("[]").unwrap(),
        OAuthAuthorizationOrigins::default()
    );
}

#[test]
fn authorization_origins_reject_noncanonical_or_forbidden_destinations() {
    for origin in [
        "",
        "http://localhost:0",
        "http://localhost:43210/",
        "HTTP://localhost:43210",
        "http://LOCALHOST:43210",
        "http://localhost:80",
        "http://localhost:43210/metadata",
        "http://localhost:43210?scope=private",
        "http://localhost:43210#fragment",
        "http://user:secret@localhost:43210",
        " https://authorization.example",
        "https://authorization.example\n",
        "ftp://localhost:43210",
        "null",
        "http://169.254.169.254",
        "http://0.0.0.0",
        "http://[::]",
    ] {
        assert_eq!(
            OAuthAuthorizationOrigins::new(vec![origin.to_string()]),
            Err(OAuthAuthorizationOriginsError::InvalidOrigin { index: 0 }),
            "{origin:?}"
        );
    }
}

#[test]
fn authorization_origins_reject_duplicates_and_untyped_wire_values() {
    assert_eq!(
        OAuthAuthorizationOrigins::new(vec![
            "http://localhost:43210".to_string(),
            "http://localhost:43210".to_string(),
        ]),
        Err(OAuthAuthorizationOriginsError::DuplicateOrigin { index: 1 })
    );
    for raw in [
        r#"{"origins":["http://localhost:43210"]}"#,
        r#"["http://localhost:43210",null]"#,
        r#"["http://localhost:43210",7]"#,
        r#""http://localhost:43210""#,
    ] {
        assert!(
            serde_json::from_str::<OAuthAuthorizationOrigins>(raw).is_err(),
            "{raw}"
        );
    }
}

#[test]
fn authorization_origins_bound_entry_count_and_input_size() {
    let values = (43000..43016)
        .map(|port| format!("http://localhost:{port}"))
        .collect::<Vec<_>>();
    assert!(OAuthAuthorizationOrigins::new(values.clone()).is_ok());
    let mut excessive = values;
    excessive.push("http://localhost:43016".to_string());
    assert_eq!(
        OAuthAuthorizationOrigins::new(excessive),
        Err(OAuthAuthorizationOriginsError::TooManyOrigins)
    );
    assert_eq!(
        OAuthAuthorizationOrigins::new(vec!["x".repeat(16 * 1024 + 1)]),
        Err(OAuthAuthorizationOriginsError::OriginTooLong { index: 0 })
    );
}
