//! Explicit host consumer: binding metadata goes to the independent issuer;
//! provider token enters on stdin; only a digest receipt leaves on stdout.
use std::collections::BTreeSet;
use std::io::Read;
use std::time::Duration;

use codex_hepta_bao_adapter::BaoClient;
use codex_hepta_bao_adapter::BaoReadRequest;
use codex_hepta_bao_adapter::BaoToken;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use serde::Deserialize;
use zeroize::Zeroizing;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct HostConfig {
    endpoint: String,
    ca_pem_file: String,
    signer_id: String,
    verifying_key: [u8; 32],
    authority_state_dir: String,
    authority_epoch: u64,
    revocation_revision: u64,
    revoked_grant_ids: BTreeSet<String>,
    request: BaoReadRequest,
    grant: Option<SignedFinalUseGrant>,
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args.len() != 2 || !matches!(args[0].as_str(), "binding" | "consume") {
        return Err("usage: consume_secret {binding|consume} HOST_CONFIG.json; consume reads provider token from stdin".into());
    }
    let config: HostConfig = serde_json::from_slice(&bounded_file(&args[1], 32 * 1024)?)?;
    let ca = bounded_file(&config.ca_pem_file, 128 * 1024)?;
    let token = if args[0] == "consume" {
        let mut bytes = Zeroizing::new(Vec::new());
        std::io::stdin().take(8193).read_to_end(&mut bytes)?;
        if bytes.len() > 8192 {
            return Err("provider token exceeds 8192 bytes".into());
        }
        let token = std::str::from_utf8(&bytes)?
            .trim_end_matches(['\r', '\n'])
            .to_owned();
        BaoToken::new(token)?
    } else {
        BaoToken::new("metadata-only-no-dispatch".into())?
    };
    let client = BaoClient::new(&config.endpoint, &ca, token, Duration::from_secs(10))?;
    if args[0] == "binding" {
        serde_json::to_writer_pretty(std::io::stdout(), &client.binding(&config.request)?)?;
        println!();
        return Ok(());
    }
    let authority = FinalUseAuthority::open_state_dir(
        std::path::Path::new(&config.authority_state_dir),
        config.signer_id,
        config.verifying_key,
        FinalUseRevocations {
            authority_epoch: config.authority_epoch,
            revision: config.revocation_revision,
            revoked_grant_ids: config.revoked_grant_ids,
        },
    )?;
    let grant = config
        .grant
        .ok_or("consume requires an independently signed grant")?;
    let receipt = client
        .consume_kv_v2(&authority, &grant, &config.request, |secret| {
            // Replace this deliberately local consumer with the registered provider
            // in the host composition root. Do not return or log the secret.
            if secret.is_empty() { Err(()) } else { Ok(()) }
        })
        .await?;
    serde_json::to_writer_pretty(std::io::stdout(), &receipt)?;
    println!();
    Ok(())
}

fn bounded_file(path: &str, maximum: usize) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
    let mut bytes = Vec::new();
    std::fs::File::open(path)?
        .take((maximum + 1) as u64)
        .read_to_end(&mut bytes)?;
    if bytes.len() > maximum {
        return Err("configuration input exceeds its bound".into());
    }
    Ok(bytes)
}
