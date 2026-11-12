//! Actual original Material/Trainer handlers. Same-UID socket admission and
//! independent terminal labels are explicit fixtures, never deployment custody.
use super::*;
use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_contracts::HostIssuerTransportError;
use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::thread::JoinHandle;

pub(super) struct Completed {
    pub fixture: MaterialCommandFixture,
    pub owner: Arc<Host>,
    pub peers: Peers,
    pub dataset: crate::OriginalCellQ24MaterialCommandReceiptV1,
    pub training: crate::OriginalCellQ24TrainingCommandReceiptV1,
}

pub(super) async fn completed_candidate() -> anyhow::Result<Completed> {
    let fixture = MaterialCommandFixture::candidate_pages().await?;
    let (owner, peers) = support::owner(&fixture, Origin::Fresh)?;
    let dataset = complete_material(&fixture).await?;
    let (client, server) = connected(
        Arc::clone(&owner),
        context(&fixture, &dataset),
        Origin::Fresh,
        /*expected*/ None,
    )?;
    let training = client
        .execute_training(Arc::new(AtomicBool::new(/*v*/ false)))
        .await?;
    assert!(matches!(
        training.receipt().observation,
        LearningIterationObservationV1::Training {
            artifact_bytes: 4_108,
            ..
        }
    ));
    assert_eq!(finish(client, server)?, 1);
    Ok(Completed {
        fixture,
        owner,
        peers,
        dataset,
        training,
    })
}

impl Completed {
    pub fn close(self) -> anyhow::Result<[u64; 4]> {
        drop(self.owner);
        let counts = finish_material(self.peers)?;
        drop(self.fixture);
        Ok(counts)
    }
}

#[derive(Clone, Copy, Debug)]
pub(super) enum Fault {
    Original,
    WrongPage,
    WrongCompletion,
    WrongOffset,
    WrongTotal,
    CorruptHeads,
    CloseAfterFirst,
    WrongFinishDigest,
    DropFinishAck,
}

pub(super) struct ResponseGate {
    pub reached: Arc<tokio::sync::Notify>,
    pub release: std::sync::mpsc::Receiver<()>,
}

pub(super) struct PagePeer {
    pub frames: Arc<AtomicU64>,
    server: JoinHandle<anyhow::Result<u64>>,
}

impl PagePeer {
    pub fn finish(self) -> anyhow::Result<u64> {
        self.server
            .join()
            .expect("original Candidate page producer")
    }
}

/// Prebind the one original descriptor before its opaque T is supplied.
/// Each frame calls the real retained handler; only Begin and Finish read the
/// native owners. Faults alter only an actual original handler reply.
pub(super) fn page_peer(
    owner: Arc<Host>,
    config: crate::OriginalCellQ24MaterialReceiptConfigV1,
    origin: Origin,
    expected: Option<crate::OriginalCellQ24TrainingCommandReceiptV1>,
    fault: Fault,
    gate: Option<ResponseGate>,
    lifetime: Duration,
) -> anyhow::Result<(crate::OriginalCellQ24TrainingCommandConnectionV1, PagePeer)> {
    let (connection, mut channel) = match origin {
        Origin::Fresh => connection::fresh_peer(config, lifetime)?,
        Origin::Recovered => connection::recovered_peer(
            config,
            expected.map(|value| (value.receipt().clone(), value.attestation().clone())),
            lifetime,
        )?,
    };
    let frames = Arc::new(AtomicU64::new(0));
    let observed = Arc::clone(&frames);
    let server = std::thread::spawn(move || -> anyhow::Result<u64> {
        let mut session = candidate_wire::Session::new();
        for request_id in 1..=128_u64 {
            let mut disposition = candidate_wire::SessionDisposition::CloseReadback;
            let mut original_error = None;
            let exchanged = channel.exchange(|bytes| {
                observed.fetch_add(1, Ordering::AcqRel);
                let (bytes, next) = owner
                    .candidate_material_response(bytes, request_id, &mut session)
                    .map_err(|error| {
                        original_error = Some(error);
                        HostIssuerTransportError::InvalidRequest
                    })?;
                disposition = next;
                let mut response: candidate_wire::Response = serde_json::from_slice(&bytes)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                if request_id == 1 {
                    if let Some(gate) = &gate {
                        gate.reached.notify_one();
                        gate.release
                            .recv()
                            .map_err(|_| HostIssuerTransportError::Unavailable)?;
                    }
                    match fault {
                        Fault::WrongPage => response.request.page += 1,
                        Fault::WrongCompletion => {
                            response.request.completion =
                                Digest32::of_bytes(b"another full T").to_string();
                        }
                        Fault::WrongOffset | Fault::WrongTotal | Fault::CorruptHeads => {
                            let candidate_wire::MaterialResult::Page {
                                offset,
                                total,
                                heads,
                                ..
                            } = &mut response.result
                            else {
                                return Err(HostIssuerTransportError::InvalidRequest);
                            };
                            match fault {
                                Fault::WrongOffset => *offset += 1,
                                Fault::WrongTotal => *total -= 1,
                                Fault::CorruptHeads => {
                                    let mut raw = STANDARD_NO_PAD
                                        .decode(&*heads)
                                        .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                                    raw[100] ^= 1;
                                    *heads = STANDARD_NO_PAD.encode(raw);
                                }
                                _ => unreachable!(),
                            }
                        }
                        Fault::Original | Fault::CloseAfterFirst
                        | Fault::WrongFinishDigest | Fault::DropFinishAck => {}
                    }
                }
                if response.request.phase == candidate_wire::Phase::Finish {
                    match fault {
                        Fault::WrongFinishDigest => {
                            let candidate_wire::MaterialResult::Finished { heads_digest, .. } =
                                &mut response.result else {
                                    return Err(HostIssuerTransportError::InvalidRequest);
                                };
                            *heads_digest = Digest32::of_bytes(b"wrong whole Candidate Finish").to_string();
                        }
                        Fault::DropFinishAck => return Err(HostIssuerTransportError::Unavailable),
                        _ => {}
                    }
                }
                serde_json::to_vec(&response).map_err(|_| HostIssuerTransportError::InvalidRequest)
            });
            match exchanged {
                Ok(false) => return Ok(request_id - 1),
                Ok(true) => {}
                Err(error) => {
                    return Err(original_error
                        .map(anyhow::Error::from)
                        .unwrap_or_else(|| anyhow::Error::from(error)));
                }
            }
            if disposition == candidate_wire::SessionDisposition::CloseReadback
                || matches!(fault, Fault::CloseAfterFirst)
            {
                return Ok(request_id);
            }
        }
        anyhow::bail!("original Candidate connection frame budget exhausted")
    });
    Ok((connection, PagePeer { frames, server }))
}

pub(super) fn bind(
    connection: crate::OriginalCellQ24TrainingCommandConnectionV1,
    fixture: &MaterialCommandFixture,
    dataset: crate::OriginalCellQ24MaterialCommandReceiptV1,
    training: crate::OriginalCellQ24TrainingCommandReceiptV1,
) -> anyhow::Result<crate::OriginalCellQ24CandidateReadbackClientV1> {
    Ok(connection.bind_original_candidate_material(
        dataset,
        training,
        fixture.training_baseline(),
    )?)
}

pub(super) fn request(
    context: &crate::OriginalCellQ24TrainingCommandContextV1,
) -> anyhow::Result<candidate_wire::Request> {
    Ok(candidate_wire::Request::new(
        context,
        context.binding()?,
        Digest32::of_bytes(b"no asserted Training completion"),
        /*request_id*/ 1,
        /*page*/ 0,
    )?)
}

pub(super) async fn raw_page(
    owner: Arc<Host>,
    request: candidate_wire::Request,
) -> anyhow::Result<(candidate_wire::Response, candidate_wire::SessionDisposition)> {
    tokio::task::spawn_blocking(move || -> anyhow::Result<_> {
        let mut session = candidate_wire::Session::new();
        let (bytes, disposition) = owner.candidate_material_response(
            &serde_json::to_vec(&request)?,
            request.request_id,
            &mut session,
        )?;
        Ok((serde_json::from_slice(&bytes)?, disposition))
    })
    .await?
}
