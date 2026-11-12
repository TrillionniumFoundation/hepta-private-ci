//! Wire faults are applied after the actual original host has read its owners.
//! No test response can create an old Qualification or Model receipt seal.
use pretty_assertions::assert_eq;

use super::*;

type Pause = (std::sync::mpsc::Sender<()>, std::sync::mpsc::Receiver<()>);

impl OriginalCellEvaluationHostV1 {
    pub(crate) fn fixture_model_material_server(
        self: Arc<Self>,
        mut channel: HostAuthorityPeerChannel,
        fault: &'static str,
        mut pause: Option<Pause>,
    ) -> anyhow::Result<u64> {
        if fault == "original" && pause.is_none() {
            return Ok(self.serve_model_material_channel(&mut channel, &AtomicBool::new(false))?);
        }
        let mut session = Session::new(self.as_ref());
        let cancelled = AtomicBool::new(false);
        let mut begins = 0;
        for request_id in 1..=128_u64 {
            let mut lost = false;
            let exchanged = channel.exchange(|bytes| {
                let request: wire::Request = serde_json::from_slice(bytes)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                if matches!(&request.read, wire::Read::Begin) {
                    begins += 1;
                }
                let bytes = self
                    .model_material_response(bytes, request_id, &mut session, &cancelled)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                let mut response: wire::Response = serde_json::from_slice(&bytes)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                if matches!(&request.read, wire::Read::Begin)
                    && (begins > 1 || fault.starts_with("cold-"))
                {
                    match fault {
                        "after-missing" | "cold-missing" => {
                            response.outcome = wire::Outcome::Missing
                        }
                        "after-pending" | "cold-pending" => {
                            response.outcome = wire::Outcome::Pending
                        }
                        _ => (),
                    }
                }
                match &mut response.outcome {
                    wire::Outcome::Page {
                        index,
                        offset,
                        total,
                        bytes,
                        ..
                    } => match fault {
                        "wrong-order" => *index += 1,
                        "wrong-total" => *total = MAX_BYTES + 1,
                        "wrong-offset" => *offset += 1,
                        "wrong-last" if *offset + PAGE_BYTES >= *total => {
                            bytes.pop();
                        }
                        _ => (),
                    },
                    wire::Outcome::Completed { .. } if fault == "lose-finish" => {
                        lost = true;
                        return Err(HostIssuerTransportError::Unavailable);
                    }
                    _ => (),
                }
                let encoded = serde_json::to_vec(&response)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                if encoded.len() > 16_384 {
                    return Err(HostIssuerTransportError::InvalidRequest);
                }
                Ok(encoded)
            });
            if lost {
                anyhow::ensure!(
                    exchanged.is_err(),
                    "only final ACK is lost after actual second CURRENT"
                );
                return Ok(request_id);
            }
            if !exchanged? {
                return Ok(request_id - 1);
            }
            channel.check_peer_lifetime()?;
            self.finish_model_material_response(&mut session)?;
            if request_id == 1 {
                if let Some((ready, release)) = pause.take() {
                    ready.send(())?;
                    release.recv_timeout(Duration::from_secs(/*secs*/ 30))?;
                }
            }
        }
        anyhow::bail!("original material session exhausted");
    }

    pub(crate) fn fixture_model_material_format_bounds() -> anyhow::Result<()> {
        // These are framing-only values, never evidence or a completed cap.
        // Exercise actual full serde responses at the last legal sequence id.
        for size in [PAGE_BYTES + 1, MAX_BYTES] {
            let bytes = vec![7; size];
            let digest = Digest32::of_bytes(&bytes);
            let mut active = Transfer {
                id: 1,
                bytes,
                digest,
                next_page: 0,
                context: Digest32::ZERO,
            };
            let count = size.div_ceil(PAGE_BYTES);
            for index in 0..count {
                let outcome = page(&mut active, index)?;
                let wire::Outcome::Page {
                    offset,
                    total,
                    bytes,
                    ..
                } = &outcome
                else {
                    anyhow::bail!("actual page result");
                };
                assert_eq!(*offset, index * PAGE_BYTES);
                assert_eq!(*total, size);
                assert_eq!(
                    STANDARD_NO_PAD.decode(bytes)?.len(),
                    PAGE_BYTES.min(size - *offset)
                );
                let response = wire::Response {
                    request: wire::Request::new(
                        /*id*/ 128,
                        Digest32::ZERO,
                        wire::Read::Page {
                            transfer: 1,
                            index: index as u32,
                        },
                    ),
                    outcome,
                };
                assert!(serde_json::to_vec(&response)?.len() <= 16_384);
            }
            assert!(page(&mut active, count).is_err());
        }
        assert!(Body::decode(&vec![0; MAX_BYTES + 1]).is_err());
        assert!(
            wire::Request::new(/*id*/ 129, Digest32::ZERO, wire::Read::Begin)
                .require(/*id*/ 129, Digest32::ZERO)
                .is_err()
        );
        Ok(())
    }
}
