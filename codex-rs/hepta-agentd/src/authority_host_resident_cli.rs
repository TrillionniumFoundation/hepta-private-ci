//! Fixed candidate-service command for the original Root authority executable.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::ffi::OsStr;
use std::ffi::OsString;
use std::fs::File;
use std::os::unix::net::UnixDatagram;
use std::os::unix::net::UnixStream;
use std::path::PathBuf;

use codex_hepta_agentd::CellQ24ModelFilesV1;
use codex_hepta_agentd::RootResidentCandidateProcessInputsV3;
use tokio_util::sync::CancellationToken;

pub(super) enum Command {
    Fresh,
    Recover,
}

pub(super) fn run(
    mut options: BTreeMap<OsString, OsString>,
    command: Command,
) -> Result<(), Box<dyn std::error::Error>> {
    let mut take = |key: &str| {
        options
            .remove(OsStr::new(key))
            .ok_or("missing required resident option")
    };
    let config = PathBuf::from(take("--config")?);
    let deployment = PathBuf::from(take("--resident-deployment")?);
    let trust = PathBuf::from(take("--learning-trust")?);
    let handoff = take("--candidate-stage-handoff-fd")?;
    let consumer = take("--resident-consumer-fd")?;
    let consumer_pidfd = take("--resident-consumer-pidfd")?;
    let base = take("--baseline-base-fd")?;
    let encoder = take("--baseline-encoder-fd")?;
    let heads = take("--baseline-heads-fd")?;
    let readback = match command {
        Command::Fresh => None,
        Command::Recover => Some(PathBuf::from(take("--resident-readback")?)),
    };
    let organ = options.remove(OsStr::new("--baseline-organ-fd"));
    let cell = options.remove(OsStr::new("--baseline-cell-fd"));
    if !options.is_empty() {
        return Err("unknown resident option or fresh/readback purpose mismatch".into());
    }
    // Adopt every inherited numeric slot before a file open, clone or runtime
    // can reuse a missing number. The original parser retains sole ownership.
    let mut claimed = BTreeSet::new();
    let handoff = super::inherited_descriptor(&handoff, &mut claimed)?;
    let consumer = super::inherited_descriptor(&consumer, &mut claimed)?;
    let consumer_pidfd = super::inherited_descriptor(&consumer_pidfd, &mut claimed)?;
    let base = super::inherited_descriptor(&base, &mut claimed)?;
    let encoder = super::inherited_descriptor(&encoder, &mut claimed)?;
    let heads = super::inherited_descriptor(&heads, &mut claimed)?;
    let organ = organ
        .as_deref()
        .map(|fd| super::inherited_descriptor(fd, &mut claimed))
        .transpose()?;
    let cell = cell
        .as_deref()
        .map(|fd| super::inherited_descriptor(fd, &mut claimed))
        .transpose()?;
    let original = RootResidentCandidateProcessInputsV3 {
        stage_handoff: UnixDatagram::from(handoff),
        consumer_stream: UnixStream::from(consumer),
        original_consumer_pidfd: consumer_pidfd,
        baseline_files: CellQ24ModelFilesV1 {
            base: File::from(base),
            organ_adapter: organ.map(File::from),
            cell_adapter: cell.map(File::from),
            encoder: File::from(encoder),
            heads: File::from(heads),
        },
    };
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    runtime.block_on(async move {
        let mut terminate = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())?;
        let cancellation = CancellationToken::new();
        let service = match readback {
            Some(readback) => codex_hepta_agentd::recover_host_resident_candidate_v3(
                &config,
                &deployment,
                &trust,
                original,
                &readback,
            )?,
            None => codex_hepta_agentd::prepare_host_resident_candidate_v3(
                &config,
                &deployment,
                &trust,
                original,
            )?,
        };
        let work = codex_hepta_agentd::RootResidentCandidateServiceV1::run(service, cancellation.clone());
        tokio::pin!(work);
        tokio::select! {
            result = &mut work => result?,
            signal = tokio::signal::ctrl_c() => {
                cancellation.cancel();
                let result = work.await;
                signal?;
                result?;
            }
            _ = terminate.recv() => {
                cancellation.cancel();
                work.await?;
            }
        }
        Ok::<(), Box<dyn std::error::Error>>(())
    })
}
