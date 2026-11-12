//! Fixed resident operation wire. Requests contain no snapshot, labels,
//! signatures, store name, deadline, role selection or authority replacement.

use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::RootResidentLearningObservationV3;
use super::authentication;
use super::profile::RootResidentLearningProfileV3;
use super::runtime::ResidentRuntimeObservationV3;
use crate::LearningIterationRuntimeErrorV1 as Error;
use crate::learning_iteration_checkpoint::decode_original_owner_snapshot_v1;
use crate::learning_iteration_checkpoint::encode_original_owner_snapshot_v1;

pub(super) const OPERATION: &str = "runtime.learning.resident.v3";
pub(super) const BOUND: usize = 16_384;

#[derive(Clone, Copy, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum Action {
    Admit,
    Readback,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Request {
    pub schema: u8,
    pub operation: String,
    pub request_id: u64,
    pub profile: String,
    pub authorization: String,
    pub action: Action,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Response {
    pub schema: u8,
    pub operation: String,
    pub request_id: u64,
    pub profile: String,
    pub authorization: String,
    pub action: Action,
    pub result: Reply,
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum Reply {
    Current { snapshot: Option<String>, evidence: Vec<String>, dispatch_pending: bool },
    Uncertain,
    Unavailable,
}

pub(super) fn encode_current(
    observation: ResidentRuntimeObservationV3,
) -> Result<Reply, Error> {
    let snapshot = observation.snapshot.as_ref().map(|snapshot|
        encode_original_owner_snapshot_v1(snapshot)
            .map(|bytes| STANDARD_NO_PAD.encode(bytes))
            .map_err(Error::Checkpoint)
    ).transpose()?;
    let evidence = observation.attestations.iter().map(|signed|
        crate::learning_owner_evidence::encode(&[], signed)
            .map(|bytes| STANDARD_NO_PAD.encode(bytes))
            .map_err(|_| Error::Unavailable)
    ).collect::<Result<Vec<_>, _>>()?;
    Ok(Reply::Current { snapshot, evidence, dispatch_pending: observation.dispatch_pending })
}

pub(super) fn decode_current(
    reply: Reply,
    profile: &RootResidentLearningProfileV3,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<RootResidentLearningObservationV3, Error> {
    let Reply::Current { snapshot, evidence, dispatch_pending } = reply else {
        return Err(match reply {
            Reply::Uncertain => Error::CommitUncertain,
            _ => Error::Unavailable,
        });
    };
    if evidence.len() > 5 {
        return Err(Error::WrongScope);
    }
    let snapshot = snapshot.map(|encoded| {
        if encoded.len() > 10_924 {
            return Err(Error::WrongScope);
        }
        let bytes = STANDARD_NO_PAD.decode(&encoded).map_err(|_| Error::WrongScope)?;
        if STANDARD_NO_PAD.encode(&bytes) != encoded {
            return Err(Error::WrongScope);
        }
        decode_original_owner_snapshot_v1(&bytes).map_err(Error::Checkpoint)
    }).transpose()?;
    let attestations = evidence.into_iter().map(|encoded| {
        if encoded.len() > BOUND {
            return Err(Error::WrongScope);
        }
        let bytes = STANDARD_NO_PAD.decode(&encoded).map_err(|_| Error::WrongScope)?;
        if STANDARD_NO_PAD.encode(&bytes) != encoded {
            return Err(Error::WrongScope);
        }
        let (payload, evidence) = crate::learning_owner_evidence::decode(&bytes)
            .map_err(|_| Error::WrongScope)?;
        if !payload.is_empty() {
            return Err(Error::WrongScope);
        }
        Ok(evidence)
    }).collect::<Result<Vec<_>, _>>()?;
    match &snapshot {
        Some(snapshot) => authentication::verify_attestations(
            profile, verifier, snapshot, &attestations, now,
        )?,
        None if !attestations.is_empty() || dispatch_pending => return Err(Error::WrongScope),
        None => {}
    }
    Ok(RootResidentLearningObservationV3 { snapshot, attestations, dispatch_pending })
}

pub(super) fn require_original_prefix(
    previous: &Option<(LearningIterationSnapshotV1, Vec<SignedLearningEvidenceV1>)>,
    current: &RootResidentLearningObservationV3,
) -> Result<(), Error> {
    if let Some((previous, evidence)) = previous {
        let snapshot = current.snapshot.as_ref().ok_or(Error::CommitUncertain)?;
        if snapshot.request != previous.request || snapshot.owners != previous.owners
            || !snapshot.receipts.starts_with(&previous.receipts)
            || !current.attestations.starts_with(evidence)
        {
            return Err(Error::CommitUncertain);
        }
    }
    Ok(())
}

pub(super) fn request(
    action: Action,
    id: u64,
    profile: Digest32,
    authorization: Digest32,
) -> Request {
    Request { schema: 3, operation: OPERATION.into(), request_id: id,
        profile: profile.to_string(), authorization: authorization.to_string(), action }
}
