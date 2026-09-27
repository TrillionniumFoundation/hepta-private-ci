//! Explicit, bounded startup-before-attachment publication command.

use std::ffi::OsString;
use std::path::PathBuf;

use codex_hepta_agentd::AgentdIdentity;

#[derive(Debug, Eq, PartialEq)]
struct PublicationFiles {
    request: PathBuf,
    descriptor: PathBuf,
    issuer: PathBuf,
    signers: PathBuf,
}

pub enum PublicationCliDisposition {
    NotRequested,
    Completed,
}

pub async fn run_if_requested(
    identity: &AgentdIdentity,
) -> anyhow::Result<PublicationCliDisposition> {
    let args = std::env::args_os().skip(1).collect::<Vec<_>>();
    let Some(files) = parse_publication_files(&args)? else {
        return Ok(PublicationCliDisposition::NotRequested);
    };
    #[cfg(unix)]
    {
        let result = identity.run_evidence_publication_request(
            &files.request, &files.descriptor, &files.issuer, &files.signers,
        ).await?;
        println!("{result}");
        Ok(PublicationCliDisposition::Completed)
    }
    #[cfg(not(unix))]
    {
        let _ = (identity, files);
        anyhow::bail!("production evidence publication requires Unix ownership checks")
    }
}

fn parse_publication_files(args: &[OsString]) -> anyhow::Result<Option<PublicationFiles>> {
    if !args.iter().any(|arg| arg == "--evidence-publication-request-file") {
        return Ok(None);
    }
    anyhow::ensure!(args.len() == 9, "publication mode requires exactly four file pairs and --evidence-mode=production");
    let mut request = None;
    let mut descriptor = None;
    let mut issuer = None;
    let mut signers = None;
    let mut production = false;
    let mut args = args.iter();
    while let Some(flag) = args.next() {
        if flag == "--evidence-mode=production" {
            anyhow::ensure!(!production, "duplicate production mode");
            production = true;
            continue;
        }
        let slot = if flag == "--evidence-publication-request-file" {
            &mut request
        } else if flag == "--evidence-production-config-file" {
            &mut descriptor
        } else if flag == "--evidence-trust-file" {
            &mut issuer
        } else if flag == "--evidence-frontier-signer-trust-file" {
            &mut signers
        } else {
            anyhow::bail!("unsupported publication-mode flag {flag:?}");
        };
        anyhow::ensure!(slot.is_none(), "duplicate publication file flag {flag:?}");
        let path = PathBuf::from(args.next().ok_or_else(|| anyhow::anyhow!("missing path for {flag:?}"))?);
        anyhow::ensure!(path.is_absolute(), "publication paths must be absolute");
        *slot = Some(path);
    }
    anyhow::ensure!(production, "publication requires explicit production mode");
    let files = PublicationFiles {
        request: request.ok_or_else(|| anyhow::anyhow!("missing publication request"))?,
        descriptor: descriptor.ok_or_else(|| anyhow::anyhow!("missing production descriptor"))?,
        issuer: issuer.ok_or_else(|| anyhow::anyhow!("missing issuer trust"))?,
        signers: signers.ok_or_else(|| anyhow::anyhow!("missing frontier signer trust"))?,
    };
    let unique = [&files.request, &files.descriptor, &files.issuer, &files.signers]
        .into_iter().collect::<std::collections::BTreeSet<_>>();
    anyhow::ensure!(unique.len() == 4, "publication file roles must be distinct");
    Ok(Some(files))
}

#[cfg(test)]
#[path = "evidence_publication_cli_tests.rs"]
mod tests;
