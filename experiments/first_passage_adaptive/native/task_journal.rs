//! Immutable research-sidecar records linked to native sparse-owner anchors.
//! Missing outcomes remain indeterminate; this is not production TaskFlow state.
use serde_json::Value;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;

pub fn write_once(path: &Path, value: &Value) -> Result<(), String> {
    let mut bytes = serde_json::to_vec(value).map_err(|error| error.to_string())?;
    bytes.push(b'\n');
    if path.exists() {
        if std::fs::read(path).map_err(|error| error.to_string())? != bytes {
            return Err("immutable task-sidecar identity conflict".into());
        }
        return Ok(());
    }
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|error| error.to_string())?;
    file.write_all(&bytes)
        .and_then(|()| file.sync_all())
        .map_err(|error| error.to_string())?;
    Ok(())
}

pub fn before(
    store: &Path,
    request: &Value,
    request_digest: &str,
) -> Result<Option<Value>, String> {
    let sequence = request["sequence"].as_u64().ok_or("missing sequence")?;
    let directory = store.join("task-sidecars");
    std::fs::create_dir_all(&directory).map_err(|error| error.to_string())?;
    let response_path = directory.join(format!("response-{sequence:04}.json"));
    if response_path.exists() {
        let response: Value = serde_json::from_slice(
            &std::fs::read(response_path).map_err(|error| error.to_string())?,
        )
        .map_err(|error| error.to_string())?;
        if response["request_digest"] != request_digest {
            return Err("completed request payload changed".into());
        }
        return Ok(Some(response));
    }
    if sequence > 1 {
        let prior: Value = serde_json::from_slice(
            &std::fs::read(directory.join(format!("response-{:04}.json", sequence - 1)))
                .map_err(|_| "previous task outcome is unresolved; no new execution allowed")?,
        )
        .map_err(|error| error.to_string())?;
        if prior["state"] != request["state"]
            || prior["owner"]["checkpoint_after"] != request["checkpoint_digest"]
            || prior["fpt_checkpoint_digest"] != request["fpt_predecessor_digest"]
        {
            return Err("external task/FPT state does not match previous committed receipt".into());
        }
        let current: Value = serde_json::from_str(
            request["fpt_checkpoint_json"]
                .as_str()
                .ok_or("missing complete FPT checkpoint")?,
        )
        .map_err(|error| error.to_string())?;
        let prior_request: Value = serde_json::from_slice(
            &std::fs::read(directory.join(format!("request-{:04}.json", sequence - 1)))
                .map_err(|_| "previous immutable request is missing")?,
        )
        .map_err(|error| error.to_string())?;
        let prior_checkpoint: Value = serde_json::from_str(
            prior_request["fpt_checkpoint_json"]
                .as_str()
                .ok_or("previous complete FPT checkpoint is missing")?,
        )
        .map_err(|error| error.to_string())?;
        // The first model identity is supplied by the trusted Python simulator.
        // Compare the actual parsed parameters thereafter: a caller cannot keep
        // an old digest while substituting a different physical model.
        if prior["fpt_model_digest"] != current["model_digest"]
            || prior_checkpoint["parameters"] != current["parameters"]
        {
            return Err("selected FPT model changed within a run".into());
        }
    }
    write_once(
        &directory.join(format!("request-{sequence:04}.json")),
        request,
    )?;
    Ok(None)
}

pub fn after(store: &Path, sequence: u64, response: &Value) -> Result<(), String> {
    write_once(
        &store
            .join("task-sidecars")
            .join(format!("response-{sequence:04}.json")),
        response,
    )
}
