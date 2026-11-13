//! Normal late candidate entry, using a Root listener after daemon UID drop.

use std::collections::{BTreeMap, BTreeSet};
use std::ffi::{OsStr, OsString};
use std::fs::File;
use std::os::unix::net::UnixDatagram;
use std::path::PathBuf;
use codex_hepta_agentd::{CellQ24ModelFilesV1, RootResidentCandidateEnrollmentInputsV3};
use tokio_util::sync::CancellationToken;

pub(super) enum Command { Fresh, Recover }

pub(super) fn run(mut options: BTreeMap<OsString, OsString>, command: Command) -> Result<(), Box<dyn std::error::Error>> {
    let mut take = |key: &str| options.remove(OsStr::new(key)).ok_or("missing required resident enrollment option");
    let config = PathBuf::from(take("--config")?);
    let deployment = PathBuf::from(take("--resident-deployment")?);
    let trust = PathBuf::from(take("--learning-trust")?);
    let stages = take("--candidate-stage-handoff-fd")?;
    let enrollment = take("--resident-enrollment-handoff-fd")?;
    let root_pidfd = take("--resident-root-pidfd")?;
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
    if !options.is_empty() { return Err("unknown resident enrollment option".into()); }
    let mut claimed = BTreeSet::new();
    let stages = super::inherited_descriptor(&stages, &mut claimed)?;
    let enrollment = super::inherited_descriptor(&enrollment, &mut claimed)?;
    let root_pidfd = super::inherited_descriptor(&root_pidfd, &mut claimed)?;
    let consumer_pidfd = super::inherited_descriptor(&consumer_pidfd, &mut claimed)?;
    let base = super::inherited_descriptor(&base, &mut claimed)?;
    let encoder = super::inherited_descriptor(&encoder, &mut claimed)?;
    let heads = super::inherited_descriptor(&heads, &mut claimed)?;
    let organ = organ.as_deref().map(|fd| super::inherited_descriptor(fd, &mut claimed)).transpose()?;
    let cell = cell.as_deref().map(|fd| super::inherited_descriptor(fd, &mut claimed)).transpose()?;
    let original = RootResidentCandidateEnrollmentInputsV3 {
        stage_handoff: UnixDatagram::from(stages),
        enrollment_handoff: UnixDatagram::from(enrollment),
        original_root_pidfd: root_pidfd,
        original_consumer_pidfd: consumer_pidfd,
        baseline_files: CellQ24ModelFilesV1 {
            base: File::from(base), organ_adapter: organ.map(File::from), cell_adapter: cell.map(File::from),
            encoder: File::from(encoder), heads: File::from(heads),
        },
    };
    tokio::runtime::Builder::new_current_thread().enable_all().build()?.block_on(async move {
        let mut terminate = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())?;
        let prepare = async move {
            match readback {
                Some(readback) => codex_hepta_agentd::recover_host_resident_candidate_enrollment_v3(
                    &config, &deployment, &trust, original, &readback,
                ).await,
                None => codex_hepta_agentd::prepare_host_resident_candidate_enrollment_v3(
                    &config, &deployment, &trust, original,
                ).await,
            }
        };
        tokio::pin!(prepare);
        let service = tokio::select! {
            result = &mut prepare => result?,
            signal = tokio::signal::ctrl_c() => {
                signal?;
                return Err("resident enrollment preparation interrupted; same-operation readback required".into());
            }
            _ = terminate.recv() => {
                return Err("resident enrollment preparation interrupted; same-operation readback required".into());
            }
        };
        let cancellation = CancellationToken::new();
        let work = codex_hepta_agentd::RootResidentCandidateEnrollmentServiceV3::run(service, cancellation.clone());
        tokio::pin!(work);
        tokio::select! {
            result = &mut work => result?,
            signal = tokio::signal::ctrl_c() => {
                cancellation.cancel(); let result = work.await; signal?; result?;
            }
            _ = terminate.recv() => { cancellation.cancel(); work.await?; }
        }
        Ok::<(), Box<dyn std::error::Error>>(())
    })
}
