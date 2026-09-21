use std::ffi::OsString;
use std::path::PathBuf;
use std::sync::Arc;

use codex_hepta_agentd::AgentdConfig;
use codex_hepta_agentd::AgentdIntelligenceProductRunnerV1;
use codex_hepta_agentd::IntelligenceAuthorityVerifierV1;
use codex_utils_absolute_path::AbsolutePathBuf;

fn main() -> anyhow::Result<()> {
    let mut config = AgentdConfig::from_process_environment()?;
    let codex_home = AbsolutePathBuf::from_absolute_path(&config.identity().home_root)?;
    codex_utils_home_dir::set_process_codex_home_override(codex_home)?;
    codex_arg0::arg0_dispatch_or_else(move |arg0_paths| async move {
        // Helper re-execs must reach arg0 dispatch before daemon-only flags.
        let mut authbus_trust_file = None;
        let mut intelligence_authority_file = None;
        let mut intelligence_authority_signer = None;
        let mut intelligence_authority_verifying_key = None;
        let mut args = std::env::args_os().skip(1);
        while let Some(flag) = args.next() {
            let flag = flag
                .into_string()
                .map_err(|_| anyhow::anyhow!("Agentd argument flag must be UTF-8"))?;
            let value = args
                .next()
                .ok_or_else(|| anyhow::anyhow!("{flag} requires a value"))?;
            match flag.as_str() {
                "--authbus-trust-file" => authbus_trust_file = Some(PathBuf::from(value)),
                "--intelligence-authority-file" => {
                    intelligence_authority_file = Some(PathBuf::from(value))
                }
                "--intelligence-authority-signer" => {
                    intelligence_authority_signer = Some(
                        value
                            .into_string()
                            .map_err(|_| anyhow::anyhow!("intelligence signer must be UTF-8"))?,
                    )
                }
                "--intelligence-authority-verifying-key" => {
                    intelligence_authority_verifying_key = Some(parse_verifying_key_hex(value)?)
                }
                _ => return Err(anyhow::anyhow!("unknown Agentd argument: {flag}")),
            }
        }
        if let Some(path) = authbus_trust_file {
            config = config.with_authbus_trust_file(path);
        }
        match (
            intelligence_authority_file,
            intelligence_authority_signer,
            intelligence_authority_verifying_key,
        ) {
            (None, None, None) => {}
            (Some(path), Some(signer_id), Some(verifying_key)) => {
                let runner = AgentdIntelligenceProductRunnerV1::new(
                    path,
                    IntelligenceAuthorityVerifierV1 {
                        signer_id,
                        verifying_key,
                    },
                )?;
                config = config.with_intelligence_product_runner(Arc::new(runner))?;
            }
            _ => {
                return Err(anyhow::anyhow!(
                    "--intelligence-authority-file, --intelligence-authority-signer and --intelligence-authority-verifying-key must be supplied together"
                ));
            }
        }
        codex_hepta_agentd::run(config, arg0_paths).await?;
        Ok(())
    })
}

fn parse_verifying_key_hex(value: OsString) -> anyhow::Result<[u8; 32]> {
    let value = value
        .into_string()
        .map_err(|_| anyhow::anyhow!("intelligence verifying key must be UTF-8 hex"))?;
    anyhow::ensure!(
        value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit()),
        "intelligence verifying key must contain exactly 64 hex characters"
    );
    let mut output = [0_u8; 32];
    for (index, slot) in output.iter_mut().enumerate() {
        let offset = index * 2;
        *slot = u8::from_str_radix(&value[offset..offset + 2], 16)
            .map_err(|_| anyhow::anyhow!("invalid intelligence verifying key hex"))?;
    }
    Ok(output)
}
