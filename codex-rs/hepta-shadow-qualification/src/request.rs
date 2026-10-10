use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;

use crate::QualificationError;
use crate::digest::framed_digest;
use crate::digest::sha256;

const SAMPLE_TOKEN_DOMAIN: &[u8] = b"hepta-live-product-shadow-sample-token:v2";
const PROVIDER_SEMANTIC_DOMAIN: &[u8] = b"hepta-live-product-shadow-provider-request-semantic:v2";
const ORACLE_SAMPLE_ID_SHA256: &str =
    "426468e3c420e5557f2edbbb0adfc845b611c00416112c1ed95d99219fa9c5ef";
pub(crate) const FIXED_PROMPT: &str =
    "Run the controlled qualification command exactly once and report completion.";
pub(crate) const FIXED_MODEL: &str = "hepta-shadow-qualification";
pub(crate) const FIXED_PROVIDER: &str = "hepta-shadow-loopback-v1";
const FIXED_MCP_BASE_INSTRUCTIONS: &str = "Execute only the exact requested controlled qualification command. Do not invoke any other tool or network service.";
const FIXED_MCP_DEVELOPER_INSTRUCTIONS: &str =
    "This is a controlled short trial, not a duration soak and not promotion authority.";

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Surface {
    AppServer,
    Mcp,
}

impl Surface {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::AppServer => "app_server",
            Self::Mcp => "mcp",
        }
    }

    pub(crate) fn method(self) -> &'static str {
        match self {
            Self::AppServer => "turn/start",
            Self::Mcp => "tools/call",
        }
    }
}

#[derive(Debug, Eq, PartialEq)]
pub(crate) struct ParsedRequest {
    pub(crate) body_sha256: String,
    pub(crate) provider_semantic_sha256: String,
    pub(crate) sample_token_sha256: String,
}

pub(crate) fn app_server_sample_request(
    ordinal: u8,
    thread_id: &str,
) -> Result<Vec<u8>, QualificationError> {
    if !(1..=2).contains(&ordinal) || !valid_dynamic_id(thread_id) {
        return Err(invalid("invalid app-server sample identity"));
    }
    json_line(&serde_json::json!({
        "id": ordinal + 2,
        "method": "turn/start",
        "params": {
            "input": [{"text": FIXED_PROMPT, "textElements": [], "type": "text"}],
            "threadId": thread_id,
        },
    }))
}

pub(crate) fn mcp_sample_request(
    ordinal: u8,
    expected_work_directory: &str,
    thread_id: Option<&str>,
) -> Result<Vec<u8>, QualificationError> {
    let value = match (ordinal, thread_id) {
        (1, None) => serde_json::json!({
            "id": 2,
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "arguments": {
                    "approval-policy": "never",
                    "base-instructions": FIXED_MCP_BASE_INSTRUCTIONS,
                    "cwd": expected_work_directory,
                    "developer-instructions": FIXED_MCP_DEVELOPER_INSTRUCTIONS,
                    "model": FIXED_MODEL,
                    "prompt": FIXED_PROMPT,
                    "sandbox": "workspace-write",
                },
                "name": "codex",
            },
        }),
        (2, Some(thread_id)) if valid_dynamic_id(thread_id) => serde_json::json!({
            "id": 3,
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "arguments": {"prompt": FIXED_PROMPT, "threadId": thread_id},
                "name": "codex-reply",
            },
        }),
        _ => return Err(invalid("invalid MCP sample identity")),
    };
    json_line(&value)
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct AppServerRequest {
    id: u64,
    method: String,
    params: AppServerParams,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct AppServerParams {
    #[serde(rename = "threadId")]
    thread_id: String,
    input: Vec<AppServerInput>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct AppServerInput {
    #[serde(rename = "textElements")]
    text_elements: Vec<Value>,
    text: String,
    #[serde(rename = "type")]
    kind: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct McpRequest {
    id: u64,
    jsonrpc: String,
    method: String,
    params: McpParams,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct McpParams {
    name: String,
    arguments: McpArguments,
}

#[derive(Deserialize)]
#[serde(untagged)]
enum McpArguments {
    First(McpFirstArguments),
    Reply(McpReplyArguments),
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct McpFirstArguments {
    #[serde(rename = "approval-policy")]
    approval_policy: String,
    #[serde(rename = "base-instructions")]
    base_instructions: String,
    cwd: String,
    #[serde(rename = "developer-instructions")]
    developer_instructions: String,
    model: String,
    prompt: String,
    sandbox: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct McpReplyArguments {
    prompt: String,
    #[serde(rename = "threadId")]
    thread_id: String,
}

pub(crate) fn parse_request(
    surface: Surface,
    ordinal: u8,
    bytes: &[u8],
    expected_work_directory: &str,
) -> Result<ParsedRequest, QualificationError> {
    if !(1..=2).contains(&ordinal)
        || bytes.len() < 2
        || bytes.last() != Some(&b'\n')
        || bytes[..bytes.len() - 1]
            .iter()
            .any(|byte| matches!(byte, b'\n' | b'\r'))
    {
        return Err(invalid(
            "driver request must be ordinal one or two and exactly one compact JSON line plus LF",
        ));
    }
    let body = &bytes[..bytes.len() - 1];
    let value: Value = serde_json::from_slice(body)
        .map_err(|error| invalid(format!("invalid driver request JSON: {error}")))?;
    if canonical_json(&value)? != body {
        return Err(invalid("driver request must use compact canonical JSON"));
    }
    match surface {
        Surface::AppServer => validate_app_server(body, ordinal)?,
        Surface::Mcp => validate_mcp(body, ordinal, expected_work_directory)?,
    }
    Ok(ParsedRequest {
        body_sha256: sha256(body),
        provider_semantic_sha256: provider_semantic(surface, ordinal)?,
        sample_token_sha256: sample_token(surface, ordinal),
    })
}

pub(crate) fn canonical_json<T: Serialize>(value: &T) -> Result<Vec<u8>, QualificationError> {
    let mut value = serde_json::to_value(value)
        .map_err(|error| QualificationError::Serialization(error.to_string()))?;
    sort_value(&mut value);
    serde_json::to_vec(&value).map_err(|error| QualificationError::Serialization(error.to_string()))
}

pub(crate) fn json_line<T: Serialize>(value: &T) -> Result<Vec<u8>, QualificationError> {
    let mut bytes = canonical_json(value)?;
    bytes.push(b'\n');
    Ok(bytes)
}

fn validate_app_server(body: &[u8], ordinal: u8) -> Result<(), QualificationError> {
    let request: AppServerRequest = serde_json::from_slice(body)
        .map_err(|error| invalid(format!("invalid app-server driver request: {error}")))?;
    let input = request.params.input.as_slice();
    if request.id != u64::from(ordinal) + 2
        || request.method != Surface::AppServer.method()
        || !valid_dynamic_id(&request.params.thread_id)
        || input.len() != 1
        || input[0].kind != "text"
        || input[0].text != FIXED_PROMPT
        || !input[0].text_elements.is_empty()
    {
        return Err(invalid(
            "app-server driver request differs from the frozen ordered workload",
        ));
    }
    Ok(())
}

fn validate_mcp(
    body: &[u8],
    ordinal: u8,
    expected_work_directory: &str,
) -> Result<(), QualificationError> {
    let request: McpRequest = serde_json::from_slice(body)
        .map_err(|error| invalid(format!("invalid MCP driver request: {error}")))?;
    let common_matches = request.id == u64::from(ordinal) + 1
        && request.jsonrpc == "2.0"
        && request.method == Surface::Mcp.method();
    let shape_matches = match (
        ordinal,
        request.params.name.as_str(),
        request.params.arguments,
    ) {
        (1, "codex", McpArguments::First(arguments)) => {
            arguments.prompt == FIXED_PROMPT
                && arguments.model == FIXED_MODEL
                && arguments.cwd == expected_work_directory
                && arguments.approval_policy == "never"
                && arguments.sandbox == "workspace-write"
                && arguments.base_instructions == FIXED_MCP_BASE_INSTRUCTIONS
                && arguments.developer_instructions == FIXED_MCP_DEVELOPER_INSTRUCTIONS
        }
        (2, "codex-reply", McpArguments::Reply(arguments)) => {
            arguments.prompt == FIXED_PROMPT && valid_dynamic_id(&arguments.thread_id)
        }
        _ => false,
    };
    if !common_matches || !shape_matches {
        return Err(invalid(
            "MCP driver request differs from the frozen ordered workload",
        ));
    }
    Ok(())
}

fn sample_token(surface: Surface, ordinal: u8) -> String {
    let ordinal = ordinal.to_string();
    framed_digest(
        SAMPLE_TOKEN_DOMAIN,
        [
            surface.as_str().as_bytes(),
            ordinal.as_bytes(),
            ORACLE_SAMPLE_ID_SHA256.as_bytes(),
        ],
    )
}

fn provider_semantic(surface: Surface, ordinal: u8) -> Result<String, QualificationError> {
    let semantic = serde_json::json!({
        "driver_owned_transport": "jsonrpc_stdin",
        "method": surface.method(),
        "model": FIXED_MODEL,
        "oracle_sample_id_sha256": ORACLE_SAMPLE_ID_SHA256,
        "ordinal": ordinal,
        "product_http_pre_send_claimed": false,
        "prompt": FIXED_PROMPT,
        "provider": FIXED_PROVIDER,
        "surface": surface.as_str(),
    });
    Ok(framed_digest(
        PROVIDER_SEMANTIC_DOMAIN,
        [canonical_json(&semantic)?.as_slice()],
    ))
}

pub(crate) fn valid_dynamic_id(value: &str) -> bool {
    (1..=256).contains(&value.len())
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.' | b':'))
}

fn sort_value(value: &mut Value) {
    match value {
        Value::Array(items) => items.iter_mut().for_each(sort_value),
        Value::Object(map) => {
            let mut entries = std::mem::take(map).into_iter().collect::<Vec<_>>();
            entries.sort_by(|(left, _), (right, _)| left.cmp(right));
            for (_, item) in &mut entries {
                sort_value(item);
            }
            map.extend(entries);
        }
        _ => {}
    }
}

fn invalid(message: impl Into<String>) -> QualificationError {
    QualificationError::Invalid(message.into())
}
