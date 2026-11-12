//! Explicit same-process transport and future B clock for mechanisms only.
//! All successful material bytes originate in the actual consumed Panel host.
use std::os::fd::FromRawFd;

use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_neuron::CellBackendManifestV2;
use codex_hepta_neuron::CellRuntimeSnapshotV2;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

use super::super::codec::Body;
use super::super::codec::Reader;
use super::*;
use crate::OriginalCellEvaluationHostV1;

type Peer = std::thread::JoinHandle<anyhow::Result<u64>>;
type Pause = (std::sync::mpsc::Sender<()>, std::sync::mpsc::Receiver<()>);

fn fixture_channel(stream: UnixStream) -> anyhow::Result<HostAuthorityPeerChannel> {
    // SAFETY: pidfd_open receives this retained test process and zero flags.
    let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, std::process::id(), 0) };
    if raw < 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    // SAFETY: the successful syscall returned one fresh owned descriptor.
    let pidfd = unsafe { OwnedFd::from_raw_fd(raw as i32) };
    Ok(HostAuthorityPeerChannel::from_stream(
        stream,
        HostAuthorityPeerPolicy {
            peer: HostIssuerPeer {
                // SAFETY: geteuid has no preconditions or borrowed memory.
                uid: unsafe { libc::geteuid() },
                pid: std::process::id(),
            },
            timeout: Duration::from_secs(/*secs*/ 30),
            lifetime: Duration::from_secs(/*secs*/ 300),
            request_bound: 16_384,
            response_bound: 16_384,
        },
        pidfd,
    )?)
}

impl OriginalCellEvaluationHostV1 {
    pub(crate) fn fixture_model_material_commands(
        self: &Arc<Self>,
        expected: Option<Receipt>,
        fault: &'static str,
        pause: Option<Pause>,
    ) -> anyhow::Result<(OriginalCellEvaluationModelMaterialClientV1, Peer)> {
        let current = self
            .owners
            .try_lock()
            .map_err(|_| anyhow::anyhow!("original Evaluator lock"))?
            .current_time()?;
        let (stream, server) = UnixStream::pair()?;
        let connection = OriginalCellEvaluationModelMaterialConnectionV1 {
            channel: fixture_channel(stream)?,
            initial: self.context.initial()?,
            scope: self.context.scope.clone(),
            registration: self.context.registration.clone(),
            verifier: self.context.verifier.clone(),
            observed_at: current,
        };
        connection.require_initial(
            &self.context.initial()?,
            &self.context.scope,
            &self.context.registration,
            &self.context.verifier,
        )?;
        let mut other_initial = self.context.initial()?;
        other_initial.request.evaluation_profile = Digest32::ZERO;
        assert!(
            connection
                .require_initial(
                    &other_initial,
                    &self.context.scope,
                    &self.context.registration,
                    &self.context.verifier
                )
                .is_err()
        );
        let client = OriginalCellEvaluationModelMaterialClientV1 {
            channel: Mutex::new(Some(Channel {
                peer: connection.channel,
                next: 1,
            })),
            context: self.context.clone(),
            expected: Mutex::new(expected),
            binding: wire::context_binding(&self.context, current)?,
            observed_at: current,
            retained: Mutex::new(None),
        };
        let owner = Arc::clone(self);
        let channel = fixture_channel(server)?;
        let peer =
            std::thread::spawn(move || owner.fixture_model_material_server(channel, fault, pause));
        Ok((client, peer))
    }

    pub(crate) fn fixture_model_material_renewed_evaluation(
        &self,
        original: &Receipt,
        current: u64,
    ) -> anyhow::Result<Receipt> {
        let mut signed = original.attestation().clone();
        signed.expires_at = signed
            .expires_at
            .checked_add(1)
            .ok_or_else(|| anyhow::anyhow!("original test signature expiry"))?;
        signed.signature = SigningKey::from_bytes(&[42; 32])
            .sign(&signed.signing_bytes())
            .to_bytes();
        let renewed = super::super::super::wire::authenticate_completed(
            &self.context,
            original.snapshot().clone(),
            signed,
            current,
        )?;
        assert_ne!(&renewed, original);
        Ok(renewed)
    }

    pub(crate) fn fixture_model_material_advance_original_cell(&self) -> anyhow::Result<()> {
        let mut owners = self
            .owners
            .try_lock()
            .map_err(|_| anyhow::anyhow!("original Evaluator lock"))?;
        let cell = &mut owners.panel.primary.candidate;
        let before = cell.read_current_checkpoint()?;
        let snapshot = cell.snapshot()?.clone();
        let mut charge = cell
            .task_cost()?
            .entries()
            .first()
            .cloned()
            .ok_or_else(|| anyhow::anyhow!("original Cell cost evidence"))?;
        charge.event_id = Digest32::of_bytes(b"explicit-late-Model-material-cost").into_array();
        cell.record_cost(charge)?;
        assert_ne!(cell.read_current_checkpoint()?, before);
        // A real, acknowledged CURRENT change must be rejected even when
        // every byte of the originally signed snapshot remains unchanged.
        assert_eq!(cell.snapshot()?, &snapshot);
        Ok(())
    }

    pub(crate) async fn fixture_model_material_cancel_queued(
        self: &Arc<Self>,
    ) -> anyhow::Result<()> {
        let current = self
            .owners
            .try_lock()
            .map_err(|_| anyhow::anyhow!("original Evaluator lock"))?
            .current_time()?;
        let (client, peer) = self.fixture_model_material_commands(
            /*expected*/ None, "original", /*pause*/ None,
        )?;
        tokio::task::spawn_blocking(move || -> anyhow::Result<()> {
            let runtime = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .max_blocking_threads(/*val*/ 1)
                .build()?;
            runtime.block_on(async move {
                let (occupied, waiting) = tokio::sync::oneshot::channel();
                let (release, blocked) = std::sync::mpsc::channel();
                let blocker = tokio::task::spawn_blocking(move || -> anyhow::Result<()> {
                    let _ = occupied.send(());
                    blocked
                        .recv()
                        .map_err(|_| anyhow::anyhow!("release queued material read"))?;
                    Ok(())
                });
                waiting.await?;
                let mut request = Box::pin(client.read_current_with_clock(|| Ok(current)));
                let pending = std::future::poll_fn(|cx| {
                    std::task::Poll::Ready(
                        std::future::Future::poll(request.as_mut(), cx).is_pending(),
                    )
                })
                .await;
                drop(request);
                release.send(())?;
                blocker.await??;
                assert!(pending, "the actual readonly request was queued");
                assert!(matches!(
                    client.read_current().await,
                    Err(Error::Unavailable)
                ));
                drop(client);
                assert_eq!(peer.join().expect("original material peer")?, 0);
                Ok(())
            })
        })
        .await
        .map_err(|_| anyhow::anyhow!("queued material runtime"))?
    }
}

impl OriginalCellEvaluationModelMaterialClientV1 {
    pub(crate) async fn fixture_read_current_at(
        &self,
        current: u64,
    ) -> Result<OriginalCellEvaluationModelMaterialV1, Error> {
        self.read_current_with_clock(|| Ok(current)).await
    }

    pub(crate) fn fixture_exhaust_original_material_session(&self) -> anyhow::Result<()> {
        self.channel
            .try_lock()
            .map_err(|_| anyhow::anyhow!("original material channel"))?
            .as_mut()
            .ok_or_else(|| anyhow::anyhow!("missing original material channel"))?
            .next = 129;
        Ok(())
    }
}

impl OriginalCellEvaluationModelMaterialV1 {
    pub(crate) fn fixture_original_material_pages(&self) -> usize {
        self.bytes.len().div_ceil(PAGE_BYTES)
    }

    pub(crate) fn fixture_original_material_preimages(&self, current: u64) -> anyhow::Result<()> {
        self.authenticate_current(current)?;
        let checked = verify::material(&self.context, &self.evaluation, &self.bytes, current)?;
        assert!(
            !checked.qualified,
            "actual B and nonempty retention are Ineligible in this fixture"
        );
        assert!(matches!(
            self.require_original_model_input(
                &self.context.training,
                &self.context.training_evidence,
                current
            ),
            Err(Error::Binding("NoUpdate has no model proposal"))
        ));
        let body = Body::decode(&self.bytes)?;
        assert_eq!(body.members.len(), 2);
        assert!(self.fixture_original_material_pages() > 1);
        assert!(self.fixture_original_material_pages() <= MAX_PAGES);
        let raw = &body.members[0];
        // These are unmodified bytes from the actual Product Qualification
        // producer, not a value encoded by this reader or a reconstructed seal.
        // Locate its two u64-counted lists independently of ids_u64.
        let mut qualification = Reader::new(&raw.qualification);
        qualification.literal(b"hepta.intelligence-eval.product-qualification.v4")?;
        qualification.take(/*count*/ 7 * 32)?;
        for _ in 0..3 {
            qualification.id()?;
        }
        qualification.u8()?;
        let failed_start = qualification.offset;
        let failed_count = usize::try_from(qualification.u64()?)?;
        anyhow::ensure!(failed_count <= 1024, "actual failed metric count");
        let failed = (0..failed_count)
            .map(|_| qualification.id())
            .collect::<Result<Vec<_>, _>>()?;
        let failed_end = qualification.offset;
        qualification.id()?;
        qualification.principal()?;
        qualification.principal()?;
        assert_eq!(qualification.u8()?, 0);
        let snapshots_start = qualification.offset;
        let snapshots_count = usize::try_from(qualification.u64()?)?;
        anyhow::ensure!(
            (1..=1024).contains(&snapshots_count),
            "actual snapshot count"
        );
        let snapshots = (0..snapshots_count)
            .map(|_| qualification.id())
            .collect::<Result<Vec<_>, _>>()?;
        let snapshots_end = qualification.offset;
        assert_eq!([qualification.u8()?, qualification.u8()?], [0, 0]);
        qualification.finish()?;
        for (start, end, expected) in [
            (failed_start, failed_end, failed),
            (snapshots_start, snapshots_end, snapshots),
        ] {
            let original = &raw.qualification[start..end];
            let mut reader = Reader::new(original);
            assert_eq!(reader.ids_u64()?, expected);
            reader.finish()?;
            assert!(Reader::new(&original[..7]).ids_u64().is_err());
            for count in [u64::try_from(expected.len())? + 1, 1025, u64::MAX] {
                // Keep the complete original material; alter only this count.
                let mut changed = Body::decode(&self.bytes)?;
                changed.members[0].qualification[start..start + 8]
                    .copy_from_slice(&count.to_be_bytes());
                assert!(
                    verify::material(&self.context, &self.evaluation, &changed.encode()?, current,)
                        .is_err(),
                    "changed original Qualification count at {start}: {count}"
                );
            }
            // Reject a u32 fallback even when all identifiers and other
            // authenticated bytes are retained exactly.
            let mut changed = Body::decode(&self.bytes)?;
            drop(changed.members[0].qualification.drain(start..start + 4));
            assert!(
                verify::material(&self.context, &self.evaluation, &changed.encode()?, current,)
                    .is_err()
            );
        }
        // Independently locate the two actual HPEXEV01 identifier fields.
        // Its u16 lengths differ from the u32 Product signing payload.
        let (_, signed) = crate::learning_owner_evidence::decode(&raw.execution)?;
        let mut execution = Reader::new(&raw.execution_record);
        execution.literal(b"HPEXEV01")?;
        for expected in [&signed.evidence_id, &signed.principal_id] {
            let start = execution.offset;
            let length = usize::from(u16::from_be_bytes(execution.take(2)?.try_into()?));
            anyhow::ensure!((1..=128).contains(&length), "actual execution identifier");
            let identifier = std::str::from_utf8(execution.take(length)?)?;
            assert_eq!(identifier, expected.as_str());
            let original = &raw.execution_record[start..execution.offset];
            let mut reader = Reader::new(original);
            assert_eq!(reader.id_u16()?, *expected);
            reader.finish()?;
            for end in [0, 1, original.len() - 1] {
                assert!(Reader::new(&original[..end]).id_u16().is_err());
            }
            for length in [0, u16::try_from(length)? + 1, 129, u16::MAX] {
                let mut changed = Body::decode(&self.bytes)?;
                changed.members[0].execution_record[start..start + 2]
                    .copy_from_slice(&length.to_be_bytes());
                assert!(
                    verify::material(&self.context, &self.evaluation, &changed.encode()?, current)
                        .is_err(),
                    "changed original execution identifier at {start}: {length}"
                );
            }
            // All original bytes remain, but a u32 prefix must not be accepted.
            let mut changed = Body::decode(&self.bytes)?;
            drop(
                changed.members[0]
                    .execution_record
                    .splice(start..start, [0, 0]),
            );
            assert!(
                verify::material(&self.context, &self.evaluation, &changed.encode()?, current)
                    .is_err()
            );
        }
        let record: serde_json::Value = serde_json::from_slice(&raw.record)?;
        let candidate: CellBackendManifestV2 =
            serde_json::from_value(record["candidate"]["manifest"].clone())?;
        let baseline: CellBackendManifestV2 =
            serde_json::from_value(record["fixed_expert"]["manifest"].clone())?;
        let candidate_cut = Digest32::from_array(serde_json::from_value(
            record["candidate"]["journal_cut"].clone(),
        )?);
        let baseline_cut = Digest32::from_array(serde_json::from_value(
            record["fixed_expert"]["journal_cut"].clone(),
        )?);
        let generator = self.context.authenticate(current)?;
        let original = super::super::member::verify(
            raw,
            &self.context,
            self.context.registration.primary(),
            &generator,
            current,
        )?;
        let training = self
            .context
            .training
            .receipts
            .last()
            .expect("actual Training");
        // The literal pre-refactor local algorithm, with the same actual
        // original inputs. No Qualified receipt or Model seal is synthesized.
        let local = Digest32::of_parts(&[
            b"hepta.cell.q24.model-proposal-material.v1\0",
            training.evidence_digest.as_array(),
            &serde_json::to_vec(&candidate)?,
            &serde_json::to_vec(&baseline)?,
            candidate_cut.as_array(),
            baseline_cut.as_array(),
            original.plan.as_array(),
            original.qualification.as_array(),
        ]);
        assert_eq!(checked.material, local);
        assert_ne!(
            local,
            crate::cell_q24_model_material::original_model_material_digest(
                training.evidence_digest,
                &baseline,
                &candidate,
                candidate_cut,
                baseline_cut,
                original.plan,
                original.qualification,
            )?
        );
        // Alter a byte in each authenticated preimage independently; keeping
        // claimed digests and the original signatures cannot make it valid.
        for field in 0..16 {
            let mut body = Body::decode(&self.bytes)?;
            let member = &mut body.members[0];
            let value = match field {
                0 => &mut member.record,
                1 => &mut member.holdout,
                2 => &mut member.plan,
                3 => &mut member.request,
                4 => &mut member.decision,
                5 => &mut member.qualification,
                6 => &mut member.estimand,
                7 => &mut member.roles,
                8 => &mut member.generator,
                9 => &mut member.evaluator,
                10 => &mut member.execution,
                11 => &mut member.execution_record,
                12 => &mut member.cohort,
                13 => &mut member.freeze,
                14 => &mut member.snapshots,
                _ => &mut body.evaluation,
            };
            let last = value.last_mut().expect("nonempty original preimage");
            *last ^= 1;
            assert!(
                verify::material(&self.context, &self.evaluation, &body.encode()?, current)
                    .is_err(),
                "changed original preimage {field}"
            );
        }
        // Merely well-formed scopes are not evidence. Each complete snapshot
        // must hash to the original signed arm using the pre-existing domain.
        for arm in 0..2 {
            for mutation in ["scope", "state", "prefix", "generation"] {
                let mut changed = Body::decode(&self.bytes)?;
                let snapshots: [CellRuntimeSnapshotV2; 2] =
                    serde_json::from_slice(&changed.members[0].snapshots)?;
                let mut substitute = snapshots.clone();
                match mutation {
                    "scope" => substitute[arm].scope.run_id = "substituted-original-run".into(),
                    "state" => substitute[arm].state.push(1),
                    "prefix" => substitute[arm].prefix.push(1),
                    "generation" => substitute[arm].generation += 1,
                    _ => unreachable!(),
                }
                if mutation != "scope" {
                    assert_eq!(substitute[arm].scope, snapshots[arm].scope);
                }
                changed.members[0].snapshots = serde_json::to_vec(&substitute)?;
                assert!(
                    matches!(
                        verify::material(
                            &self.context,
                            &self.evaluation,
                            &changed.encode()?,
                            current,
                        ),
                        Err(Error::Binding(
                            "same signed original Cell snapshot preimage"
                        ))
                    ),
                    "changed original arm {arm} {mutation}"
                );
            }
        }
        let mut incomplete = Body::decode(&self.bytes)?;
        let snapshots: [CellRuntimeSnapshotV2; 2] =
            serde_json::from_slice(&incomplete.members[0].snapshots)?;
        incomplete.members[0].snapshots = serde_json::to_vec(&[&snapshots[0]])?;
        assert!(
            verify::material(
                &self.context,
                &self.evaluation,
                &incomplete.encode()?,
                current
            )
            .is_err()
        );
        let mut truncated = Body::decode(&self.bytes)?;
        truncated.members[0].snapshots.pop();
        assert!(
            verify::material(
                &self.context,
                &self.evaluation,
                &truncated.encode()?,
                current
            )
            .is_err()
        );
        let mut oversized = Body::decode(&self.bytes)?;
        oversized.members[0].snapshots = vec![b' '; 65_537];
        assert!(matches!(
            oversized.encode(),
            Err(Error::Binding("bounded original material field"))
        ));
        let mut legacy = self.bytes.clone();
        legacy[..8].copy_from_slice(b"HECMM001");
        assert!(
            Body::decode(&legacy).is_err(),
            "no legacy unsigned-scope fallback"
        );

        // A valid new Evaluator envelope naming a different snapshot is still
        // not the original completed E. This is an adversarial signed value,
        // not a manufactured Qualification, Cell, or accepted owner result.
        let mut substituted = Body::decode(&self.bytes)?;
        let mut snapshots: [CellRuntimeSnapshotV2; 2] =
            serde_json::from_slice(&substituted.members[0].snapshots)?;
        snapshots[0].state.push(1);
        substituted.members[0].snapshots = serde_json::to_vec(&snapshots)?;
        let mut record: serde_json::Value = serde_json::from_slice(&substituted.members[0].record)?;
        record["candidate"]["snapshot_digest"] = serde_json::to_value(snapshots[0].digest()?)?;
        substituted.members[0].record = serde_json::to_vec(&record)?;
        let mut changed_receipt = self.evaluation.receipt().clone();
        changed_receipt.evidence_digest = Digest32::of_bytes(&substituted.members[0].record);
        let payload = learning_iteration_receipt_signing_bytes_v1(&changed_receipt)?;
        let mut signed = self.evaluation.attestation().clone();
        signed.payload_digest = Digest32::of_bytes(&payload);
        signed.signature = SigningKey::from_bytes(&[42; 32])
            .sign(&signed.signing_bytes())
            .to_bytes();
        self.context.verifier.verify(
            codex_hepta_learning_ledger::LearningEvidenceRoleV1::Evaluator,
            &signed,
            &payload,
            current,
        )?;
        let mut changed_cut =
            codex_hepta_learning_artifacts::LearningIterationCoordinatorV1::from_snapshot(
                self.context.training.clone(),
            )?;
        changed_cut.record(changed_receipt, signed.issued_at)?;
        let changed_evaluation = super::super::super::wire::authenticate_completed(
            &self.context,
            changed_cut.snapshot().clone(),
            signed,
            current,
        )?;
        assert_ne!(&changed_evaluation, &self.evaluation);
        substituted.context = wire::binding(&self.context, &changed_evaluation, current)?;
        substituted.snapshot =
            crate::learning_iteration_checkpoint::encode_original_owner_snapshot_v1(
                changed_evaluation.snapshot(),
            )?;
        substituted.evaluation =
            crate::learning_owner_evidence::encode(&payload, changed_evaluation.attestation())?;
        assert!(matches!(
            verify::material(
                &self.context,
                &self.evaluation,
                &substituted.encode()?,
                current,
            ),
            Err(Error::Binding(
                "exact original Evaluation payload in material"
            ))
        ));
        let mut missing = Body::decode(&self.bytes)?;
        missing.members.pop();
        assert!(missing.encode().is_err());
        let mut reordered = Body::decode(&self.bytes)?;
        reordered.members.swap(0, 1);
        assert!(
            verify::material(
                &self.context,
                &self.evaluation,
                &reordered.encode()?,
                current
            )
            .is_err()
        );
        let mut renewed_context = self.context.clone();
        renewed_context.training_evidence.expires_at += 1;
        renewed_context.training_evidence.signature = SigningKey::from_bytes(&[41; 32])
            .sign(&renewed_context.training_evidence.signing_bytes())
            .to_bytes();
        // Verify legal Generator re-signing over the actual unchanged T first.
        renewed_context.verifier.verify(
            codex_hepta_learning_ledger::LearningEvidenceRoleV1::Generator,
            &renewed_context.training_evidence,
            &learning_iteration_receipt_signing_bytes_v1(training)?,
            current,
        )?;
        assert!(
            verify::material(&renewed_context, &self.evaluation, &self.bytes, current).is_err()
        );
        assert!(
            self.authenticate_current(self.evaluation.attestation().expires_at)
                .is_err()
        );
        assert!(self.authenticate_current(self.observed_at - 1).is_err());
        Ok(())
    }
}
