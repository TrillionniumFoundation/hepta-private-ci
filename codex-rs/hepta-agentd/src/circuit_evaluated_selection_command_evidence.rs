//! Existing read-only S evidence purpose. The same command host must first
//! obtain an actual S result; a missing pin cannot cause execution or a claim.

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_neuron::AnchorWitnessStore;

use super::super::readback_binding;
use super::Error;
use super::OriginalCircuitEvaluatedSelectionCommandOwnerV1;
use crate::OriginalCircuitEvaluatedSelectionRemoteSourcesV1;
use crate::OriginalCircuitSelectionReceiptOwnerV1;

impl<W: AnchorWitnessStore + Send + 'static> OriginalCircuitEvaluatedSelectionCommandOwnerV1<W> {
    pub(super) fn serve_evidence_channel(
        &self,
        channel: &mut HostAuthorityPeerChannel,
    ) -> Result<u64, Error> {
        for request_id in 1..=128_u64 {
            if !channel
                .exchange(|bytes| {
                    self.evidence_response(bytes, request_id)
                        .inspect_err(|_error| {
                            #[cfg(test)]
                            {
                                let message: &[u8] = match _error {
                                    Error::Binding(_) => {
                                        b"owner_diag_v1 stage=s_command_callback class=binding\n"
                                    }
                                    Error::Unavailable => {
                                        b"owner_diag_v1 stage=s_command_callback class=unavailable\n"
                                    }
                                    Error::CommitUncertain => {
                                        b"owner_diag_v1 stage=s_command_callback class=commit_uncertain\n"
                                    }
                                    Error::ReadbackRequired => {
                                        b"owner_diag_v1 stage=s_command_callback class=readback_required\n"
                                    }
                                    Error::Busy => {
                                        b"owner_diag_v1 stage=s_command_callback class=busy\n"
                                    }
                                    Error::Missing => {
                                        b"owner_diag_v1 stage=s_command_callback class=missing\n"
                                    }
                                    Error::Pending => {
                                        b"owner_diag_v1 stage=s_command_callback class=pending\n"
                                    }
                                    Error::DeadlineExceeded => {
                                        b"owner_diag_v1 stage=s_command_callback class=deadline_exceeded\n"
                                    }
                                    Error::Transport(_) => {
                                        b"owner_diag_v1 stage=s_command_callback class=transport\n"
                                    }
                                    Error::Owner(_) => {
                                        b"owner_diag_v1 stage=s_command_callback class=owner\n"
                                    }
                                    Error::Retention(_) => {
                                        b"owner_diag_v1 stage=s_command_callback class=retention\n"
                                    }
                                    Error::Readback(_) => {
                                        b"owner_diag_v1 stage=s_command_callback class=readback\n"
                                    }
                                    Error::Iteration(_) => {
                                        b"owner_diag_v1 stage=s_command_callback class=iteration\n"
                                    }
                                    Error::Evidence(_) => {
                                        b"owner_diag_v1 stage=s_command_callback class=evidence\n"
                                    }
                                    Error::Checkpoint(_) => {
                                        b"owner_diag_v1 stage=s_command_callback class=checkpoint\n"
                                    }
                                    Error::Encoding(_) => {
                                        b"owner_diag_v1 stage=s_command_callback class=encoding\n"
                                    }
                                };
                                let _ = std::io::Write::write(
                                    &mut std::io::stderr().lock(),
                                    message,
                                );
                            }
                        })
                        .map_err(|_| HostIssuerTransportError::InvalidRequest)
                })
                .inspect_err(|_error| {
                    #[cfg(test)]
                    {
                        let message: &[u8] = match _error {
                            HostIssuerTransportError::InvalidConfiguration => {
                                b"owner_diag_v1 stage=s_command_exchange class=invalid_configuration\n"
                            }
                            HostIssuerTransportError::PeerDenied => {
                                b"owner_diag_v1 stage=s_command_exchange class=peer_denied\n"
                            }
                            HostIssuerTransportError::Closed => {
                                b"owner_diag_v1 stage=s_command_exchange class=closed\n"
                            }
                            HostIssuerTransportError::InvalidRequest => {
                                b"owner_diag_v1 stage=s_command_exchange class=invalid_request\n"
                            }
                            HostIssuerTransportError::DeadlineElapsed => {
                                b"owner_diag_v1 stage=s_command_exchange class=deadline_elapsed\n"
                            }
                            HostIssuerTransportError::Unavailable => {
                                b"owner_diag_v1 stage=s_command_exchange class=unavailable\n"
                            }
                        };
                        let _ = std::io::Write::write(&mut std::io::stderr().lock(), message);
                    }
                })?
            {
                return Ok(request_id - 1);
            }
        }
        Err(Error::Unavailable)
    }

    pub(super) fn evidence_response(
        &self,
        bytes: &[u8],
        request_id: u64,
    ) -> Result<Vec<u8>, Error> {
        let selection = self
            .retained
            .try_lock()
            .map_err(|_| Error::Busy)?
            .as_ref()
            .ok_or(Error::Missing)?
            .clone();
        let binding = readback_binding::ReadbackBinding::from_original_pins(
            &selection,
            self.initial_head,
            selection.original_receipt_binding(),
        );
        let (request, started_at) = binding.before_read(bytes, request_id)?;
        let original = {
            let mut owner = self.owner.try_lock().map_err(|_| Error::Busy)?;
            self.runtime.block_on(
                OriginalCircuitSelectionReceiptOwnerV1::readback_evaluated_remote_selection(
                    &mut owner,
                    OriginalCircuitEvaluatedSelectionRemoteSourcesV1 {
                        snapshot: self.context.original.snapshot(),
                        live: &self.live,
                        trainer: &self.trainer,
                        evaluator: &self.evaluator,
                    },
                ),
            )?
        };
        Ok(binding.after_read(request, started_at, original)?)
    }
}
