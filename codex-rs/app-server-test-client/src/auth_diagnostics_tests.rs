use super::jsonrpc_message_for_logging;
use super::login_completion_status;
use anyhow::Result;
use anyhow::bail;
use codex_app_server_protocol::AccountLoginCompletedNotification;
use codex_app_server_protocol::LoginAccountResponse;
use codex_app_server_protocol::RequestId;
use pretty_assertions::assert_eq;
use serde_json::json;

#[test]
fn login_request_diagnostics_redact_credentials_without_changing_wire_values() -> Result<()> {
    let variants = [
        json!({"type": "apiKey", "apiKey": "sentinel-api-key"}),
        json!({"type": "amazonBedrock", "apiKey": "sentinel-bedrock-key", "region": "us-east-1"}),
        json!({"type": "chatgptAuthTokens", "accessToken": "sentinel-access-token", "chatgptAccountId": "account-id"}),
        json!({"type": "amazonBedrockAccessKeys", "accessKeyId": "sentinel-key-id", "secretAccessKey": "sentinel-secret-key", "sessionToken": "sentinel-session-token", "region": "us-east-1"}),
    ];
    for params in variants {
        let request =
            json!({"id": "login-request", "method": "account/login/start", "params": params});
        let original = request.clone();
        let logged =
            jsonrpc_message_for_logging(&request, /*pending_login_response_id*/ None)?;
        assert!(!logged.to_string().contains("sentinel-"));
        assert_eq!(request, original);
        assert_eq!(logged["method"], request["method"]);
        assert_eq!(logged["params"]["type"], request["params"]["type"]);
        assert_eq!(logged["params"]["region"], request["params"]["region"]);
        assert_eq!(
            logged["params"]["chatgptAccountId"],
            request["params"]["chatgptAccountId"]
        );
    }
    Ok(())
}

#[test]
fn login_instructions_retain_exact_values_after_diagnostic_redaction() -> Result<()> {
    let responses = [
        json!({"id": "login-request", "result": {"type": "chatgpt", "loginId": "login-id", "authUrl": "https://example.test/authorize?state=sentinel-browser-state"}}),
        json!({"id": "login-request", "result": {"type": "chatgptDeviceCode", "loginId": "login-id", "verificationUrl": "https://example.test/device", "userCode": "sentinel-device-code"}}),
    ];
    for response in responses {
        let original = response.clone();
        let logged =
            jsonrpc_message_for_logging(&response, /*pending_login_response_id*/ None)?;
        assert!(!logged.to_string().contains("sentinel-"));
        assert_eq!(response, original);
        assert_eq!(logged["result"]["loginId"], "login-id");
        let typed: LoginAccountResponse = serde_json::from_value(response["result"].clone())?;
        match typed {
            LoginAccountResponse::Chatgpt { login_id, auth_url } => {
                assert_eq!(login_id, "login-id");
                assert_eq!(
                    auth_url,
                    "https://example.test/authorize?state=sentinel-browser-state"
                );
            }
            LoginAccountResponse::ChatgptDeviceCode {
                login_id,
                verification_url,
                user_code,
            } => {
                assert_eq!(login_id, "login-id");
                assert_eq!(verification_url, "https://example.test/device");
                assert_eq!(user_code, "sentinel-device-code");
            }
            LoginAccountResponse::ApiKey {}
            | LoginAccountResponse::ChatgptAuthTokens {}
            | LoginAccountResponse::AmazonBedrock {} => bail!("unexpected login response"),
        }
    }
    Ok(())
}

#[test]
fn completion_diagnostics_keep_status_without_unbounded_error_text() -> Result<()> {
    let notification = json!({
        "method": "account/login/completed",
        "params": {
            "loginId": "login-id",
            "success": false,
            "error": "token endpoint returned sentinel-token",
            "onboardingEntrypoint": null
        }
    });
    let original = notification.clone();
    let logged =
        jsonrpc_message_for_logging(&notification, /*pending_login_response_id*/ None)?;
    assert_eq!(logged["params"]["error"], "<redacted>");
    assert_eq!(logged["params"]["success"], false);
    assert_eq!(notification, original);
    let completion: AccountLoginCompletedNotification =
        serde_json::from_value(notification["params"].clone())?;
    let status = login_completion_status(&completion);
    assert!(status.contains("success=false"));
    assert!(status.contains("error_present=true"));
    assert!(!status.contains("sentinel-token"));
    assert_eq!(
        completion.error.as_deref(),
        Some("token endpoint returned sentinel-token")
    );

    let success: AccountLoginCompletedNotification = serde_json::from_value(json!({
        "loginId": null, "success": true, "error": null, "onboardingEntrypoint": null
    }))?;
    let success_status = login_completion_status(&success);
    assert!(success_status.contains("success=true"));
    assert!(success_status.contains("error_present=false"));
    let success_message = json!({"method": "account/login/completed", "params": success});
    assert_eq!(
        jsonrpc_message_for_logging(&success_message, /*pending_login_response_id*/ None)?,
        success_message
    );
    Ok(())
}

#[test]
fn login_rpc_error_redaction_matches_only_the_pending_request_id() -> Result<()> {
    let request_id = RequestId::String("login-request".to_string());
    let error = json!({
        "id": "login-request",
        "error": {
            "code": -32602,
            "message": "upstream echoed sentinel-token",
            "data": {"rawBody": "sentinel-token"}
        }
    });
    let original = error.clone();
    let logged = jsonrpc_message_for_logging(&error, Some(&request_id))?;
    assert_eq!(logged["error"]["code"], -32602);
    assert_eq!(logged["error"]["message"], "<redacted>");
    assert_eq!(logged["error"]["data"], "<redacted>");
    assert!(!logged.to_string().contains("sentinel-token"));
    assert_eq!(error, original);
    assert_eq!(
        jsonrpc_message_for_logging(&error, /*pending_login_response_id*/ None)?,
        original
    );
    let other_id = RequestId::String("another-request".to_string());
    assert_eq!(
        jsonrpc_message_for_logging(&error, Some(&other_id))?,
        original
    );
    Ok(())
}

#[test]
fn unrelated_diagnostics_and_account_metadata_remain_available() -> Result<()> {
    let messages = [
        json!({"method": "account/updated", "params": {"authMode": "chatgpt", "planType": "plus"}}),
        json!({"id": 4, "result": {"rateLimits": {"primary": {"usedPercent": 25}, "credits": {"balance": "10"}}}}),
        json!({"id": 5, "result": {}}),
        json!({"method": "other/request", "params": {"apiKey": "non-auth-fixture"}}),
        json!({"id": 6, "error": {"code": -32600, "message": "unrelated failure", "data": null}}),
    ];
    for message in messages {
        assert_eq!(
            jsonrpc_message_for_logging(&message, /*pending_login_response_id*/ None)?,
            message
        );
    }
    Ok(())
}
