use std::collections::BTreeSet;
use std::time::Duration;

use serde_json::Value;

use crate::ChildOutcome;
use crate::FrozenProductBinary;
use crate::HttpAuditRecord;
use crate::LoopbackHandle;
use crate::ProductChild;
use crate::QualificationDriverRun;
use crate::QualificationError;
use crate::Surface;
use crate::SurfaceRuntimeLayout;
use crate::digest::sha256;
use crate::durable::read_private_bounded;
use crate::request::FIXED_MODEL;
use crate::request::FIXED_PROVIDER;
use crate::request::valid_dynamic_id;

const MAX_CONFIG_BYTES: usize = 64 * 1024;
const MCP_PROTOCOL_VERSION: &str = "2025-03-26";

pub(crate) struct SurfaceSessionOutcome {
    pub(crate) child: ChildOutcome,
    pub(crate) http: Vec<HttpAuditRecord>,
    pub(crate) thread_id: String,
    pub(crate) turn_ids: Vec<String>,
}

pub(crate) async fn run_app_server(
    product: &FrozenProductBinary,
    layout: &SurfaceRuntimeLayout,
    driver_run: &mut QualificationDriverRun,
    timeout: Duration,
) -> Result<SurfaceSessionOutcome, QualificationError> {
    require_surface(layout, Surface::AppServer)?;
    let loopback =
        LoopbackHandle::start(Surface::AppServer, driver_run.run_root(), timeout).await?;
    let config_sha256 = layout.write_config(loopback.address())?;
    let mut child = ProductChild::spawn(product, layout, driver_run.run_root(), timeout)?;
    let protocol = app_protocol(layout, driver_run, &mut child).await;
    let (thread_id, turn_ids) = match protocol {
        Ok(value) => value,
        Err(error) => return abort_with(child, error).await,
    };
    let child = child.shutdown().await?;
    let http = loopback.finish().await?;
    validate_http(&http, Surface::AppServer)?;
    verify_config(layout, &config_sha256)?;
    Ok(SurfaceSessionOutcome {
        child,
        http,
        thread_id,
        turn_ids,
    })
}

pub(crate) async fn run_mcp(
    product: &FrozenProductBinary,
    layout: &SurfaceRuntimeLayout,
    driver_run: &mut QualificationDriverRun,
    timeout: Duration,
) -> Result<SurfaceSessionOutcome, QualificationError> {
    require_surface(layout, Surface::Mcp)?;
    let loopback = LoopbackHandle::start(Surface::Mcp, driver_run.run_root(), timeout).await?;
    let config_sha256 = layout.write_config(loopback.address())?;
    let mut child = ProductChild::spawn(product, layout, driver_run.run_root(), timeout)?;
    let protocol = mcp_protocol(driver_run, &mut child).await;
    let thread_id = match protocol {
        Ok(value) => value,
        Err(error) => return abort_with(child, error).await,
    };
    let child = child.shutdown().await?;
    let http = loopback.finish().await?;
    validate_http(&http, Surface::Mcp)?;
    verify_config(layout, &config_sha256)?;
    Ok(SurfaceSessionOutcome {
        child,
        http,
        thread_id,
        turn_ids: Vec::new(),
    })
}

async fn app_protocol(
    layout: &SurfaceRuntimeLayout,
    driver_run: &mut QualificationDriverRun,
    child: &mut ProductChild,
) -> Result<(String, Vec<String>), QualificationError> {
    let stdin = child.take_stdin()?;
    let mut driver = driver_run.app_server(stdin)?;
    driver.initialize().await?;
    let initialize = result(
        child.read_response(/*expected_id*/ 1).await?,
        "app-server initialize",
    )?;
    if initialize.get("codexHome").and_then(Value::as_str)
        != Some(layout.home().to_string_lossy().as_ref())
    {
        return Err(invalid(
            "app-server initialize returned an unexpected product home",
        ));
    }
    driver.initialized().await?;
    driver.start_thread().await?;
    let thread = result(
        child.read_response(/*expected_id*/ 2).await?,
        "app-server thread/start",
    )?;
    let thread_id = dynamic_pointer(&thread, "/thread/id", "thread/start thread.id")?;
    if thread.get("model").and_then(Value::as_str) != Some(FIXED_MODEL)
        || thread.get("modelProvider").and_then(Value::as_str) != Some(FIXED_PROVIDER)
    {
        return Err(invalid(
            "thread/start selected an unexpected model or provider",
        ));
    }
    let mut turn_ids = Vec::with_capacity(2);
    for ordinal in 1_u8..=2 {
        driver.start_turn(&thread_id).await?;
        let response = result(
            child.read_response(u64::from(ordinal) + 2).await?,
            "app-server turn/start",
        )?;
        let turn_id = dynamic_pointer(&response, "/turn/id", "turn/start turn.id")?;
        let completed = child.read_notification("turn/completed").await?;
        validate_completed(&completed, &thread_id, &turn_id)?;
        turn_ids.push(turn_id);
    }
    if turn_ids.iter().collect::<BTreeSet<_>>().len() != 2 {
        return Err(invalid("app-server turns did not produce unique turn ids"));
    }
    drop(driver.finish()?);
    Ok((thread_id, turn_ids))
}

async fn mcp_protocol(
    driver_run: &mut QualificationDriverRun,
    child: &mut ProductChild,
) -> Result<String, QualificationError> {
    let stdin = child.take_stdin()?;
    let mut driver = driver_run.mcp(stdin)?;
    driver.initialize().await?;
    let initialize = result(
        child.read_response(/*expected_id*/ 1).await?,
        "MCP initialize",
    )?;
    if initialize.get("protocolVersion").and_then(Value::as_str) != Some(MCP_PROTOCOL_VERSION) {
        return Err(invalid("MCP negotiated an unexpected protocol version"));
    }
    driver.initialized().await?;
    driver.start_thread().await?;
    let first = result(
        child.read_response(/*expected_id*/ 2).await?,
        "first MCP tools/call",
    )?;
    ensure_mcp_success(&first)?;
    let thread_id = dynamic_pointer(
        &first,
        "/structuredContent/threadId",
        "MCP structuredContent.threadId",
    )?;
    driver.continue_thread(&thread_id).await?;
    let second = result(
        child.read_response(/*expected_id*/ 3).await?,
        "second MCP tools/call",
    )?;
    ensure_mcp_success(&second)?;
    if dynamic_pointer(
        &second,
        "/structuredContent/threadId",
        "MCP reply structuredContent.threadId",
    )? != thread_id
    {
        return Err(invalid("MCP reply changed thread identity"));
    }
    drop(driver.finish()?);
    Ok(thread_id)
}

pub(crate) fn result(message: Value, context: &str) -> Result<Value, QualificationError> {
    message
        .get("result")
        .cloned()
        .ok_or_else(|| invalid(format!("{context} response is missing result")))
}

pub(crate) fn dynamic_pointer(
    value: &Value,
    pointer: &str,
    context: &str,
) -> Result<String, QualificationError> {
    value
        .pointer(pointer)
        .and_then(Value::as_str)
        .filter(|value| valid_dynamic_id(value))
        .map(str::to_string)
        .ok_or_else(|| invalid(format!("{context} is missing or invalid")))
}

fn validate_completed(
    message: &Value,
    thread_id: &str,
    turn_id: &str,
) -> Result<(), QualificationError> {
    if message.pointer("/params/threadId").and_then(Value::as_str) != Some(thread_id)
        || message.pointer("/params/turn/id").and_then(Value::as_str) != Some(turn_id)
        || message
            .pointer("/params/turn/status")
            .and_then(Value::as_str)
            != Some("completed")
    {
        return Err(invalid("turn/completed identity or status differs"));
    }
    Ok(())
}

fn ensure_mcp_success(result: &Value) -> Result<(), QualificationError> {
    if result.get("isError").and_then(Value::as_bool) == Some(true)
        || result
            .get("content")
            .and_then(Value::as_array)
            .is_none_or(Vec::is_empty)
    {
        return Err(invalid("MCP tools/call did not return successful content"));
    }
    Ok(())
}

fn validate_http(records: &[HttpAuditRecord], surface: Surface) -> Result<(), QualificationError> {
    if records.len() != 4 {
        return Err(invalid(
            "loopback did not persist exactly four HTTP exchanges",
        ));
    }
    let mut call_ids = BTreeSet::new();
    for (index, record) in records.iter().enumerate() {
        let sequence = u8::try_from(index).map_err(|_| invalid("HTTP sequence overflow"))?;
        let sample = sequence / 2 + 1;
        let post = sequence % 2 + 1;
        if record.surface() != surface
            || record.sample_ordinal() != sample
            || record.post_ordinal() != post
            || (post == 2) != record.validated_output_sha256().is_some()
        {
            return Err(invalid(
                "loopback HTTP sequence or validation result differs",
            ));
        }
        if post == 1 && !call_ids.insert(record.call_id()) {
            return Err(invalid("loopback reused a function call id"));
        }
    }
    Ok(())
}

fn verify_config(
    layout: &SurfaceRuntimeLayout,
    expected_sha256: &str,
) -> Result<(), QualificationError> {
    let bytes = read_private_bounded(layout.config(), MAX_CONFIG_BYTES)?;
    if sha256(&bytes) != expected_sha256 {
        return Err(invalid("surface config changed during product execution"));
    }
    Ok(())
}

fn require_surface(
    layout: &SurfaceRuntimeLayout,
    expected: Surface,
) -> Result<(), QualificationError> {
    if layout.surface() != expected {
        return Err(invalid("runtime layout surface differs from session"));
    }
    Ok(())
}

async fn abort_with<T>(
    child: ProductChild,
    error: QualificationError,
) -> Result<T, QualificationError> {
    match child.abort().await {
        Ok(()) => Err(error),
        Err(cleanup) => Err(QualificationError::State(format!(
            "{error}; child cleanup also failed: {cleanup}"
        ))),
    }
}

fn invalid(message: impl Into<String>) -> QualificationError {
    QualificationError::Invalid(message.into())
}
