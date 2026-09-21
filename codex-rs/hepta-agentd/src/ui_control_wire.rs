use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fmt;
use std::str::FromStr;

use codex_hepta_types::Digest32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Deserializer;
use serde::de::Error as _;
use serde::de::MapAccess;
use serde::de::SeqAccess;
use serde::de::Visitor;
use serde_json::Value;
use sha2::Digest as _;
use sha2::Sha256;

const MAX_REQUEST_BYTES: usize = 64 * 1024;
const MAX_SAFE_INTEGER: u64 = 9_007_199_254_740_991;
const REQUEST_SEMANTICS_SCHEMA: &str = "hepta.ui-control.request-semantics.v1";
const TRANSPORT_REQUEST_SCHEMA: &str = "hepta.ui-control.transport-request.v1";
const RUNTIME_RESOURCE: &str = "runtime.agentd";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum UiControlEffectKind {
    Restart,
    Stop,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct VerifiedUiControlRequest {
    pub operation_id: StableId,
    pub semantic_digest: Digest32,
    pub action_id: StableId,
    pub resource_id: StableId,
    pub expected_revision: Revision,
    pub displayed_revision: Revision,
    pub effect: UiControlEffectKind,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) enum UiControlWireError {
    Invalid(&'static str),
    UnsupportedAction(String),
    DigestMismatch,
}

impl fmt::Display for UiControlWireError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Invalid(message) => write!(f, "invalid ui.control request: {message}"),
            Self::UnsupportedAction(action) => {
                write!(f, "unsupported ui.control product action: {action}")
            }
            Self::DigestMismatch => f.write_str("ui.control semantic digest mismatch"),
        }
    }
}

impl std::error::Error for UiControlWireError {}

pub(crate) fn verify_ui_control_request(
    method: &str,
    request_json: &[u8],
) -> Result<VerifiedUiControlRequest, UiControlWireError> {
    if request_json.is_empty() || request_json.len() > MAX_REQUEST_BYTES {
        return Err(UiControlWireError::Invalid("request byte bound"));
    }
    let request = parse_strict_json(request_json)?;
    let request = object(&request, "request object")?;
    let payload_key = match method {
        "operation/request" => "intent",
        "runtime/stop" => "scope",
        _ => return Err(UiControlWireError::Invalid("method")),
    };
    require_exact_keys(
        request,
        &[
            "schema",
            "sessionId",
            "connectionGeneration",
            "runtimeGeneration",
            "runtimeDigest",
            "displayedRevision",
            "operationId",
            "semanticDigest",
            payload_key,
        ],
    )?;
    if string(request, "schema")? != TRANSPORT_REQUEST_SCHEMA {
        return Err(UiControlWireError::Invalid("transport schema"));
    }

    let operation_id = stable_id(string(request, "operationId")?, "operation id")?;
    let semantic_digest = digest(string(request, "semanticDigest")?, "semantic digest")?;
    let displayed_revision = revision(integer(request, "displayedRevision")?, "displayed revision")?;
    let connection_generation = integer(request, "connectionGeneration")?;
    let runtime_generation = integer(request, "runtimeGeneration")?;
    let session_id = stable_id(string(request, "sessionId")?, "session id")?;
    let runtime_digest = digest(string(request, "runtimeDigest")?, "runtime digest")?;
    let payload = request
        .get(payload_key)
        .ok_or(UiControlWireError::Invalid("payload"))?
        .clone();

    let (action_id, resource_id, expected_revision, effect) = if method == "operation/request" {
        verify_operation_payload(&payload, &operation_id)?
    } else {
        verify_stop_scope(&payload, displayed_revision)?
    };

    let displayed_view = Value::Object(
        [
            ("sessionId".to_string(), Value::String(session_id.as_str().to_string())),
            (
                "connectionGeneration".to_string(),
                Value::Number(connection_generation.into()),
            ),
            (
                "generation".to_string(),
                Value::Number(runtime_generation.into()),
            ),
            (
                "revision".to_string(),
                Value::Number(displayed_revision.get().into()),
            ),
            (
                "digest".to_string(),
                Value::String(runtime_digest.to_string()),
            ),
        ]
        .into_iter()
        .collect(),
    );
    let semantics = Value::Object(
        [
            (
                "schema".to_string(),
                Value::String(REQUEST_SEMANTICS_SCHEMA.to_string()),
            ),
            ("method".to_string(), Value::String(method.to_string())),
            (
                "operationId".to_string(),
                Value::String(operation_id.as_str().to_string()),
            ),
            ("displayedView".to_string(), displayed_view),
            ("payload".to_string(), payload),
        ]
        .into_iter()
        .collect(),
    );
    let canonical = canonical_json(&semantics)?;
    let observed = Digest32::new(Sha256::digest(&canonical).into());
    if observed != semantic_digest {
        return Err(UiControlWireError::DigestMismatch);
    }

    Ok(VerifiedUiControlRequest {
        operation_id,
        semantic_digest,
        action_id,
        resource_id,
        expected_revision,
        displayed_revision,
        effect,
    })
}

fn verify_operation_payload(
    payload: &Value,
    operation_id: &StableId,
) -> Result<(StableId, StableId, Revision, UiControlEffectKind), UiControlWireError> {
    let intent = object(payload, "operation intent")?;
    require_exact_keys(
        intent,
        &[
            "kind",
            "operationId",
            "subjectId",
            "action",
            "expectedRevision",
            "authorityGranted",
            "directStoreWrite",
        ],
    )?;
    if string(intent, "kind")? != "UiOperationProposalV1"
        || string(intent, "operationId")? != operation_id.as_str()
        || string(intent, "subjectId")? != RUNTIME_RESOURCE
        || boolean(intent, "authorityGranted")?
        || boolean(intent, "directStoreWrite")?
    {
        return Err(UiControlWireError::Invalid("operation intent binding"));
    }
    let action = string(intent, "action")?;
    let effect = match action {
        "request_retry" => UiControlEffectKind::Restart,
        "request_quarantine" | "request_reconcile" | "request_rollback" => {
            return Err(UiControlWireError::UnsupportedAction(action.to_string()));
        }
        _ => return Err(UiControlWireError::Invalid("operation action")),
    };
    Ok((
        stable_id(action, "action id")?,
        stable_id(RUNTIME_RESOURCE, "resource id")?,
        revision(integer(intent, "expectedRevision")?, "expected revision")?,
        effect,
    ))
}

fn verify_stop_scope(
    payload: &Value,
    displayed_revision: Revision,
) -> Result<(StableId, StableId, Revision, UiControlEffectKind), UiControlWireError> {
    let scope = object(payload, "stop scope")?;
    require_exact_keys(scope, &["scopeKind", "targetId"])?;
    if string(scope, "scopeKind")? != "runtime"
        || string(scope, "targetId")? != RUNTIME_RESOURCE
    {
        return Err(UiControlWireError::Invalid("stop scope binding"));
    }
    Ok((
        stable_id("runtime_stop", "action id")?,
        stable_id(RUNTIME_RESOURCE, "resource id")?,
        displayed_revision,
        UiControlEffectKind::Stop,
    ))
}

fn parse_strict_json(input: &[u8]) -> Result<Value, UiControlWireError> {
    let mut deserializer = serde_json::Deserializer::from_slice(input);
    let StrictValue(value) = StrictValue::deserialize(&mut deserializer)
        .map_err(|_| UiControlWireError::Invalid("unambiguous JSON"))?;
    deserializer
        .end()
        .map_err(|_| UiControlWireError::Invalid("trailing JSON data"))?;
    validate_canonical_value(&value, 0, &mut 0)?;
    Ok(value)
}

struct StrictValue(Value);

impl<'de> Deserialize<'de> for StrictValue {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        deserializer.deserialize_any(StrictValueVisitor)
    }
}

struct StrictValueVisitor;

impl<'de> Visitor<'de> for StrictValueVisitor {
    type Value = StrictValue;

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("JSON without duplicate object keys")
    }

    fn visit_bool<E>(self, value: bool) -> Result<Self::Value, E> {
        Ok(StrictValue(Value::Bool(value)))
    }

    fn visit_i64<E>(self, value: i64) -> Result<Self::Value, E>
    where
        E: serde::de::Error,
    {
        if value.unsigned_abs() > MAX_SAFE_INTEGER {
            return Err(E::custom("integer exceeds JavaScript safe range"));
        }
        Ok(StrictValue(Value::Number(value.into())))
    }

    fn visit_u64<E>(self, value: u64) -> Result<Self::Value, E>
    where
        E: serde::de::Error,
    {
        if value > MAX_SAFE_INTEGER {
            return Err(E::custom("integer exceeds JavaScript safe range"));
        }
        Ok(StrictValue(Value::Number(value.into())))
    }

    fn visit_f64<E>(self, _value: f64) -> Result<Self::Value, E>
    where
        E: serde::de::Error,
    {
        Err(E::custom("floating-point JSON is not canonical ui.control input"))
    }

    fn visit_str<E>(self, value: &str) -> Result<Self::Value, E>
    where
        E: serde::de::Error,
    {
        Ok(StrictValue(Value::String(value.to_string())))
    }

    fn visit_string<E>(self, value: String) -> Result<Self::Value, E> {
        Ok(StrictValue(Value::String(value)))
    }

    fn visit_none<E>(self) -> Result<Self::Value, E> {
        Ok(StrictValue(Value::Null))
    }

    fn visit_unit<E>(self) -> Result<Self::Value, E> {
        Ok(StrictValue(Value::Null))
    }

    fn visit_seq<A>(self, mut access: A) -> Result<Self::Value, A::Error>
    where
        A: SeqAccess<'de>,
    {
        let mut values = Vec::new();
        while let Some(StrictValue(value)) = access.next_element::<StrictValue>()? {
            values.push(value);
        }
        Ok(StrictValue(Value::Array(values)))
    }

    fn visit_map<A>(self, mut access: A) -> Result<Self::Value, A::Error>
    where
        A: MapAccess<'de>,
    {
        let mut seen = BTreeSet::new();
        let mut values = serde_json::Map::new();
        while let Some(key) = access.next_key::<String>()? {
            if !seen.insert(key.clone()) {
                return Err(A::Error::custom("duplicate JSON object key"));
            }
            let StrictValue(value) = access.next_value::<StrictValue>()?;
            values.insert(key, value);
        }
        Ok(StrictValue(Value::Object(values)))
    }
}

fn validate_canonical_value(
    value: &Value,
    depth: usize,
    nodes: &mut usize,
) -> Result<(), UiControlWireError> {
    *nodes = nodes
        .checked_add(1)
        .ok_or(UiControlWireError::Invalid("canonical node count"))?;
    if depth > 32 || *nodes > 4_096 {
        return Err(UiControlWireError::Invalid("canonical structure bound"));
    }
    match value {
        Value::Null | Value::Bool(_) | Value::String(_) => Ok(()),
        Value::Number(number) => {
            if number
                .as_u64()
                .is_some_and(|value| value <= MAX_SAFE_INTEGER)
                || number
                    .as_i64()
                    .is_some_and(|value| value.unsigned_abs() <= MAX_SAFE_INTEGER)
            {
                Ok(())
            } else {
                Err(UiControlWireError::Invalid("canonical number"))
            }
        }
        Value::Array(items) => {
            for item in items {
                validate_canonical_value(item, depth + 1, nodes)?;
            }
            Ok(())
        }
        Value::Object(map) => {
            for value in map.values() {
                validate_canonical_value(value, depth + 1, nodes)?;
            }
            Ok(())
        }
    }
}

fn canonical_json(value: &Value) -> Result<Vec<u8>, UiControlWireError> {
    let mut output = Vec::new();
    append_canonical_json(value, &mut output)?;
    if output.len() > MAX_REQUEST_BYTES {
        return Err(UiControlWireError::Invalid("canonical request byte bound"));
    }
    Ok(output)
}

fn append_canonical_json(
    value: &Value,
    output: &mut Vec<u8>,
) -> Result<(), UiControlWireError> {
    match value {
        Value::Null => output.extend_from_slice(b"null"),
        Value::Bool(false) => output.extend_from_slice(b"false"),
        Value::Bool(true) => output.extend_from_slice(b"true"),
        Value::Number(number) => output.extend_from_slice(number.to_string().as_bytes()),
        Value::String(value) => output.extend_from_slice(
            serde_json::to_string(value)
                .map_err(|_| UiControlWireError::Invalid("JSON string"))?
                .as_bytes(),
        ),
        Value::Array(items) => {
            output.push(b'[');
            for (index, item) in items.iter().enumerate() {
                if index != 0 {
                    output.push(b',');
                }
                append_canonical_json(item, output)?;
            }
            output.push(b']');
        }
        Value::Object(map) => {
            output.push(b'{');
            let sorted = map.iter().collect::<BTreeMap<_, _>>();
            for (index, (key, value)) in sorted.into_iter().enumerate() {
                if index != 0 {
                    output.push(b',');
                }
                output.extend_from_slice(
                    serde_json::to_string(key)
                        .map_err(|_| UiControlWireError::Invalid("JSON object key"))?
                        .as_bytes(),
                );
                output.push(b':');
                append_canonical_json(value, output)?;
            }
            output.push(b'}');
        }
    }
    Ok(())
}

fn object<'a>(
    value: &'a Value,
    _name: &'static str,
) -> Result<&'a serde_json::Map<String, Value>, UiControlWireError> {
    value
        .as_object()
        .ok_or(UiControlWireError::Invalid("object"))
}

fn require_exact_keys(
    map: &serde_json::Map<String, Value>,
    expected: &[&str],
) -> Result<(), UiControlWireError> {
    if map.len() != expected.len()
        || expected.iter().any(|key| !map.contains_key(*key))
    {
        return Err(UiControlWireError::Invalid("missing or unknown field"));
    }
    Ok(())
}

fn string<'a>(
    map: &'a serde_json::Map<String, Value>,
    key: &'static str,
) -> Result<&'a str, UiControlWireError> {
    map.get(key)
        .and_then(Value::as_str)
        .ok_or(UiControlWireError::Invalid(key))
}

fn boolean(
    map: &serde_json::Map<String, Value>,
    key: &'static str,
) -> Result<bool, UiControlWireError> {
    map.get(key)
        .and_then(Value::as_bool)
        .ok_or(UiControlWireError::Invalid(key))
}

fn integer(
    map: &serde_json::Map<String, Value>,
    key: &'static str,
) -> Result<u64, UiControlWireError> {
    let value = map
        .get(key)
        .and_then(Value::as_u64)
        .ok_or(UiControlWireError::Invalid(key))?;
    if value == 0 || value > MAX_SAFE_INTEGER {
        return Err(UiControlWireError::Invalid(key));
    }
    Ok(value)
}

fn stable_id(value: &str, label: &'static str) -> Result<StableId, UiControlWireError> {
    StableId::new(value).map_err(|_| UiControlWireError::Invalid(label))
}

fn digest(value: &str, label: &'static str) -> Result<Digest32, UiControlWireError> {
    let digest = Digest32::from_str(value).map_err(|_| UiControlWireError::Invalid(label))?;
    if digest.is_zero() {
        return Err(UiControlWireError::Invalid(label));
    }
    Ok(digest)
}

fn revision(value: u64, label: &'static str) -> Result<Revision, UiControlWireError> {
    Revision::new(value).map_err(|_| UiControlWireError::Invalid(label))
}

#[cfg(test)]
mod tests {
    use super::*;

    const D1: &str = "1111111111111111111111111111111111111111111111111111111111111111";
    const GOLDEN: &str = "fbdaf3b3aa6869642a07aafbdb0cdba25a3765f32da2f56a7062fdbed8b6ef58";

    fn operation_json(action: &str, digest: &str) -> String {
        format!(
            r#"{{"connectionGeneration":2,"displayedRevision":4,"intent":{{"action":"{action}","authorityGranted":false,"directStoreWrite":false,"expectedRevision":7,"kind":"UiOperationProposalV1","operationId":"operation.1","subjectId":"runtime.agentd"}},"operationId":"operation.1","runtimeDigest":"{D1}","runtimeGeneration":3,"schema":"hepta.ui-control.transport-request.v1","semanticDigest":"{digest}","sessionId":"session.1"}}"#
        )
    }

    #[test]
    fn rust_recomputes_the_browser_recursive_lexicographic_digest() {
        let verified = verify_ui_control_request(
            "operation/request",
            operation_json("request_retry", GOLDEN).as_bytes(),
        )
        .expect("golden browser request");
        assert_eq!(verified.semantic_digest.to_string(), GOLDEN);
        assert_eq!(verified.effect, UiControlEffectKind::Restart);
        assert_eq!(verified.expected_revision.get(), 7);
    }

    #[test]
    fn semantic_digest_substitution_and_duplicate_keys_fail_closed() {
        assert!(matches!(
            verify_ui_control_request(
                "operation/request",
                operation_json("request_retry", &"2".repeat(64)).as_bytes(),
            ),
            Err(UiControlWireError::DigestMismatch)
        ));
        let duplicate = operation_json("request_retry", GOLDEN)
            .replace(r#""sessionId":"session.1""#, r#""sessionId":"evil","sessionId":"session.1""#);
        assert!(verify_ui_control_request("operation/request", duplicate.as_bytes()).is_err());
    }

    #[test]
    fn unsupported_frontend_actions_never_alias_to_a_product_effect() {
        for action in [
            "request_quarantine",
            "request_reconcile",
            "request_rollback",
        ] {
            let request = operation_json(action, GOLDEN);
            assert!(matches!(
                verify_ui_control_request("operation/request", request.as_bytes()),
                Err(UiControlWireError::UnsupportedAction(ref observed)) if observed == action
            ));
        }
    }
}
