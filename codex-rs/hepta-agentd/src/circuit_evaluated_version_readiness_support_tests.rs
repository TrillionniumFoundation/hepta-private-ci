//! Explicit same-process server transport only; the real Version producer
//! still consumes this channel, checks actual D/T/B/S and reads its own C.
use super::*;
use crate::learning_iteration_evidence_client::command_test_support;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;

impl OriginalCircuitEvaluatedReadinessChannelV1 {
    pub(crate) fn fixture_original_stream(stream: UnixStream) -> anyhow::Result<Self> {
        let channel = HostAuthorityPeerChannel::from_stream(
            stream,
            HostAuthorityPeerPolicy {
                // SAFETY: this fixture admits only its own live UID/process.
                peer: HostIssuerPeer {
                    uid: unsafe { libc::geteuid() },
                    pid: std::process::id(),
                },
                timeout: Duration::from_millis(500),
                lifetime: Duration::from_secs(300),
                request_bound: 16_384,
                response_bound: 16_384,
            },
            command_test_support::pidfd()?,
        )?;
        Ok(Self { channel })
    }
}

impl OriginalCircuitRetainedVersionHostV1 {
    /// Only an event tells the test consumer that actual bootstrap completed.
    /// Both paths call the same original preparation and bounded serving loop;
    /// this does not skip a read, wait by sleeping or restart either deadline.
    pub(crate) async fn fixture_synchronized_evaluated_readiness(
        self: Arc<Self>,
        original: OriginalCircuitEvaluatedReadinessChannelV1,
        selection: OriginalCircuitEvaluatedSelectionReceiptV1,
        ready: tokio::sync::oneshot::Sender<()>,
    ) -> Result<u64, Error> {
        let permit = self
            .admit_original_readiness_server(&original)
            .inspect_err(|_error| {
                #[cfg(test)]
                record_readiness_failure(ReadinessDiagnosticStage::Admission, _error);
            })?;
        let queued = QueuedReadinessFence(Arc::new(AtomicBool::new(false)));
        let cancelled = Arc::clone(&queued.0);
        let result = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            let mut channel = original.channel;
            require_not_cancelled(&cancelled)
                .inspect_err(|_error| {
                    #[cfg(test)]
                    record_readiness_failure(ReadinessDiagnosticStage::Cancellation, _error);
                })?;
            self.require_lifetime()
                .inspect_err(|_error| {
                    #[cfg(test)]
                    record_readiness_failure(ReadinessDiagnosticStage::HostLifetime, _error);
                })?;
            channel
                .check_peer_lifetime()
                .inspect_err(|_error| {
                    #[cfg(test)]
                    {
                        let message: &[u8] = match _error {
                            HostIssuerTransportError::InvalidConfiguration => {
                                b"owner_diag_v1 stage=version_peer_lifetime class=invalid_configuration\n"
                            }
                            HostIssuerTransportError::PeerDenied => {
                                b"owner_diag_v1 stage=version_peer_lifetime class=peer_denied\n"
                            }
                            HostIssuerTransportError::Closed => {
                                b"owner_diag_v1 stage=version_peer_lifetime class=closed\n"
                            }
                            HostIssuerTransportError::InvalidRequest => {
                                b"owner_diag_v1 stage=version_peer_lifetime class=invalid_request\n"
                            }
                            HostIssuerTransportError::DeadlineElapsed => {
                                b"owner_diag_v1 stage=version_peer_lifetime class=deadline_elapsed\n"
                            }
                            HostIssuerTransportError::Unavailable => {
                                b"owner_diag_v1 stage=version_peer_lifetime class=unavailable\n"
                            }
                        };
                        let _ = std::io::Write::write(&mut std::io::stderr().lock(), message);
                    }
                })?;
            let reader = self
                .prepare_evaluated_readiness_reader(selection)
                .inspect_err(|_error| {
                    #[cfg(test)]
                    record_readiness_failure(ReadinessDiagnosticStage::PrepareReader, _error);
                })?;
            ready
                .send(())
                .inspect_err(|_| {
                    #[cfg(test)]
                    {
                        let _ = std::io::Write::write(
                            &mut std::io::stderr().lock(),
                            b"owner_diag_v1 stage=version_ready_send class=receiver_closed\n",
                        );
                    }
                })
                .map_err(|_| Error::Cancelled)?;
            self.serve_evaluated_readiness_frames(&mut channel, &reader, &cancelled)
        })
        .await
        .inspect_err(|_| {
            #[cfg(test)]
            {
                let _ = std::io::Write::write(
                    &mut std::io::stderr().lock(),
                    b"owner_diag_v1 stage=version_join class=join_error\n",
                );
            }
        })
        .map_err(|_| Error::CommitUncertain)?;
        drop(queued);
        result
    }
}

#[cfg(test)]
enum ReadinessDiagnosticStage {
    Admission,
    Cancellation,
    HostLifetime,
    PrepareReader,
}

#[cfg(test)]
fn record_readiness_failure(stage: ReadinessDiagnosticStage, error: &Error) {
    // Fixed tags only. Failed or partial diagnostic writes never replace the original error.
    // These synchronous writes can perturb timing; the original limits still apply.
    let prefix: &[u8] = match stage {
        ReadinessDiagnosticStage::Admission => b"owner_diag_v1 stage=version_admission ",
        ReadinessDiagnosticStage::Cancellation => b"owner_diag_v1 stage=version_cancellation ",
        ReadinessDiagnosticStage::HostLifetime => b"owner_diag_v1 stage=version_host_lifetime ",
        ReadinessDiagnosticStage::PrepareReader => b"owner_diag_v1 stage=version_prepare_reader ",
    };
    let class: &[u8] = match error {
        Error::Binding(_) => b"class=binding\n",
        Error::Busy => b"class=busy\n",
        Error::Unavailable => b"class=unavailable\n",
        Error::CommitUncertain => b"class=commit_uncertain\n",
        Error::ReadbackRequired => b"class=readback_required\n",
        Error::FinalUseDenied => b"class=final_use_denied\n",
        Error::Cancelled => b"class=cancelled\n",
        Error::Clock => b"class=clock\n",
        Error::Transport(_) => b"class=transport\n",
        Error::Issuer(_) => b"class=issuer\n",
        Error::Publication(_) => b"class=publication\n",
        Error::Material(_) => b"class=material\n",
        Error::Training(_) => b"class=training\n",
        Error::Evaluation(_) => b"class=evaluation\n",
        Error::Selection(_) => b"class=selection\n",
        Error::NextUse(_) => b"class=next_use\n",
        Error::SelectionCommand(_) => b"class=selection_command\n",
        Error::NextUseCommand(_) => b"class=next_use_command\n",
        Error::PublishedRead(_) => b"class=published_read\n",
        Error::SelectorRead(_) => b"class=selector_read\n",
        Error::Connection(_) => b"class=connection\n",
        Error::Source(_) => b"class=source\n",
        Error::Owner(_) => b"class=owner\n",
        Error::Artifact(_) => b"class=artifact\n",
        Error::Iteration(_) => b"class=iteration\n",
        Error::Snapshot(_) => b"class=snapshot\n",
        Error::Encoding(_) => b"class=encoding\n",
    };
    let mut stderr = std::io::stderr().lock();
    let _ = std::io::Write::write(&mut stderr, prefix);
    let _ = std::io::Write::write(&mut stderr, class);
    if let Error::Publication(original) = error {
        use crate::OriginalCircuitRetainedPublicationErrorV1 as PublicationError;

        let nested: &[u8] = match original {
            PublicationError::Binding(_) => {
                b"owner_diag_v2 stage=version_publication class=binding\n"
            }
            PublicationError::DeadlineExceeded => {
                b"owner_diag_v2 stage=version_publication class=deadline_exceeded\n"
            }
            PublicationError::Clock => b"owner_diag_v2 stage=version_publication class=clock\n",
            PublicationError::Cancelled => {
                b"owner_diag_v2 stage=version_publication class=cancelled\n"
            }
            PublicationError::CommitUncertain(_) => {
                b"owner_diag_v2 stage=version_publication class=commit_uncertain\n"
            }
            PublicationError::Training(_) => {
                b"owner_diag_v2 stage=version_publication class=training\n"
            }
            PublicationError::Evaluation(_) => {
                b"owner_diag_v2 stage=version_publication class=evaluation\n"
            }
            PublicationError::Owner(_) => b"owner_diag_v2 stage=version_publication class=owner\n",
            PublicationError::Iteration(_) => {
                b"owner_diag_v2 stage=version_publication class=iteration\n"
            }
            PublicationError::Evidence(_) => {
                b"owner_diag_v2 stage=version_publication class=evidence\n"
            }
        };
        let _ = std::io::Write::write(&mut stderr, nested);
    }
}
