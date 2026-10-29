//! Qualification presentation only; receipts continue to bind full raw bytes.

use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use serde_json::Value;
use serde_json::json;

pub(crate) fn bounded_terminal_output(
    exit_code: Option<i32>,
    stdout: &[u8],
    stderr: &[u8],
    retained: Value,
    item_limit: usize,
) -> Result<String> {
    // Both harnesses wrap this JSON as a string. Reserve room for JSON quoting,
    // the original call id and either native or Codex's input_text envelope.
    // The independent capture auditor still checks each actual serialized item.
    let text_limit = item_limit.checked_div(2).and_then(|size| size.checked_sub(512))
        .context("model item budget cannot retain a reference")?;
    let full = json!({"exit_code":exit_code,"stdout":String::from_utf8_lossy(stdout),
        "stderr":String::from_utf8_lossy(stderr)}).to_string();
    if full.len() <= text_limit {
        return Ok(full);
    }
    let mut out: String = String::from_utf8_lossy(stdout).chars().take(text_limit).collect();
    let mut err: String = String::from_utf8_lossy(stderr).chars().take(text_limit).collect();
    loop {
        let output = json!({"exit_code":exit_code,"stdout":out,"stderr":err,
            "presentation":{"schema":"hepta.runtime-output-excerpt.v1",
                "limit_bytes":item_limit,"text_budget_bytes":text_limit,
                "truncated":true,"retained":retained}}).to_string();
        if output.len() <= text_limit {
            return Ok(output);
        }
        if out.is_empty() && err.is_empty() {
            bail!("original-owner output reference exceeds presentation budget");
        }
        let selected = if out.len() >= err.len() { &mut out } else { &mut err };
        *selected = selected.chars().take(selected.chars().count() / 2).collect();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn preserves_reference_and_bounds_both_real_wire_envelopes() -> Result<()> {
        let stdout = "x\"\\\n\0中文".repeat(8192).into_bytes();
        let stderr = vec![0xff; 8192];
        let retained = json!({"job_id":"original-job","stdout_bytes":stdout.len(),"stderr_bytes":stderr.len()});
        let output = bounded_terminal_output(Some(0), &stdout, &stderr, retained.clone(), 4096)?;
        let parsed: Value = serde_json::from_str(&output)?;
        assert_eq!(parsed["presentation"]["retained"], retained);
        assert_eq!(parsed["presentation"]["truncated"], true);
        assert!(String::from_utf8_lossy(&stdout).starts_with(parsed["stdout"].as_str().context("stdout excerpt")?));
        let call_id = "c".repeat(512);
        for item in [
            json!({"type":"function_call_output","call_id":call_id,"output":output}),
            json!({"type":"function_call_output","call_id":call_id,"output":[{"type":"input_text","text":output}]}),
        ] {
            assert!(serde_json::to_vec(&item)?.len() <= 4096);
        }
        Ok(())
    }

    #[test]
    fn unchanged_short_output_and_unrepresentable_metadata() -> Result<()> {
        let output = bounded_terminal_output(Some(1), b"", b"real failure", json!({}), 4096)?;
        assert_eq!(serde_json::from_str::<Value>(&output)?, json!({"exit_code":1,"stdout":"","stderr":"real failure"}));
        assert!(bounded_terminal_output(Some(0), &vec![b'x'; 8192], b"", json!({"job_id":"x".repeat(4096)}), 4096).is_err());
        Ok(())
    }
}
