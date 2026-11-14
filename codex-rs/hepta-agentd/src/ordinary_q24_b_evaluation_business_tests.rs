//! Independent physical business observations in their declared binary unit.
//! A process status, Q24 score or successful write call is never the outcome:
//! the Observer reopens the requested file and checks the declared contract.
#![cfg(test)]

use std::fs::File;
use std::io;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::time::Instant;

use codex_hepta_types::Digest32;
use serde::Serialize;

use super::OriginalBusinessCase;
use super::data::ACTIONS;
use super::data::ONE;
use super::data::TRAIN_WINDOW;
use super::data::TrainingRow;

#[derive(Serialize)]
struct BusinessObservation<'a> {
    schema: u8,
    unit: &'static str,
    contract: OriginalBusinessCase,
    decision: &'a str,
    action: &'a str,
    requested: [u8; 32],
    observed: Option<[u8; 32]>,
    outcome_q32: i64,
    observed_at_seconds: u64,
}

pub(super) fn now() -> io::Result<u64> {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|value| value.as_secs())
        .map_err(io::Error::other)
}

pub(super) fn wait_after(seconds: u64, end: Instant) -> io::Result<u64> {
    loop {
        if Instant::now() >= end {
            return Err(io::Error::other("original B source end elapsed"));
        }
        let observed = now()?;
        if observed > seconds {
            return Ok(observed);
        }
        std::thread::sleep(std::time::Duration::from_millis(5));
    }
}

pub(super) fn write_once(path: &Path, bytes: &[u8]) -> io::Result<()> {
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    drop(file);
    let mut actual = Vec::new();
    File::open(path)?.read_to_end(&mut actual)?;
    if actual != bytes {
        return Err(io::Error::other("original business persistence differs"));
    }
    File::open(
        path.parent()
            .ok_or_else(|| io::Error::other("original business parent missing"))?,
    )?
    .sync_all()
}

pub(super) fn observe(
    directory: &Path,
    case: OriginalBusinessCase,
    decision: &str,
    action: &str,
    end: Instant,
) -> io::Result<(i64, u64, [u8; 32])> {
    if Instant::now() >= end
        || !ACTIONS.contains(&action)
        || !decision
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
    {
        return Err(io::Error::other(
            "bounded original business request required",
        ));
    }
    let payload = [
        b"ordinary-independent-file-request-v1\0".as_slice(),
        decision.as_bytes(),
    ]
    .concat();
    let path = directory.join(format!("{decision}.requested"));
    match std::fs::symlink_metadata(&path) {
        Err(error) if error.kind() == io::ErrorKind::NotFound => {}
        _ => return Err(io::Error::other("original business request already exists")),
    }
    match action {
        "persist" => write_once(&path, &payload)?,
        "skip" => {}
        _ => return Err(io::Error::other("original action was not preregistered")),
    }
    let observed = match std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(&path)
    {
        Ok(mut file) => {
            let mut actual = Vec::new();
            Read::by_ref(&mut file)
                .take(4097)
                .read_to_end(&mut actual)?;
            if actual.len() > 4096 {
                return Err(io::Error::other("business observation oversized"));
            }
            Some(Digest32::of_bytes(&actual).into_array())
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => None,
        Err(error) => return Err(error),
    };
    let requested = Digest32::of_bytes(&payload).into_array();
    let met = match case {
        OriginalBusinessCase::Adopt => observed == Some(requested),
        OriginalBusinessCase::EvaluatedNoUpdate => observed.is_none(),
    };
    let outcome_q32 = if met { ONE } else { 0 };
    let observed_at_seconds = now()?;
    let bytes = serde_json::to_vec(&BusinessObservation {
        schema: 1,
        unit: "binary-request-contract-satisfied-v1",
        contract: case,
        decision,
        action,
        requested,
        observed,
        outcome_q32,
        observed_at_seconds,
    })
    .map_err(io::Error::other)?;
    write_once(&directory.join(format!("{decision}.evidence")), &bytes)?;
    if Instant::now() >= end {
        return Err(io::Error::other("original observation exceeded end"));
    }
    Ok((
        outcome_q32,
        observed_at_seconds,
        Digest32::of_bytes(&bytes).into_array(),
    ))
}

pub(super) fn prepare_training(
    directory: &Path,
    case: OriginalBusinessCase,
    end: Instant,
) -> io::Result<Vec<TrainingRow>> {
    let mut rows = Vec::new();
    for index in 0..16 {
        let decision_id = format!("ordinary-b-training-{index}");
        let action = ACTIONS[index % ACTIONS.len()];
        let (outcome_q32, observed_at_seconds, original_evidence) =
            observe(directory, case, &decision_id, action, end)?;
        rows.push(TrainingRow {
            decision_id,
            principal_lineage: format!("ordinary-b-earlier-principal-{index}"),
            episode_lineage: format!("ordinary-b-earlier-episode-{index}"),
            window_id: TRAIN_WINDOW.into(),
            action_id: action.into(),
            outcome_q32,
            observed_at_seconds,
            original_evidence,
        });
    }
    Ok(rows)
}

pub(super) fn require_earlier_row(
    directory: &Path,
    case: OriginalBusinessCase,
    row: &TrainingRow,
) -> io::Result<()> {
    let path = directory.join(format!("{}.evidence", row.decision_id));
    let file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path)?;
    let mut bytes = Vec::new();
    file.take(4097).read_to_end(&mut bytes)?;
    let observed: serde_json::Value = serde_json::from_slice(&bytes).map_err(io::Error::other)?;
    if bytes.len() > 4096
        || Digest32::of_bytes(&bytes).into_array() != row.original_evidence
        || observed["decision"] != row.decision_id
        || observed["action"] != row.action_id
        || observed["contract"] != serde_json::to_value(case).map_err(io::Error::other)?
        || observed["outcome_q32"] != row.outcome_q32
        || observed["observed_at_seconds"] != row.observed_at_seconds
    {
        return Err(io::Error::other(
            "original earlier independent business evidence differs",
        ));
    }
    Ok(())
}
