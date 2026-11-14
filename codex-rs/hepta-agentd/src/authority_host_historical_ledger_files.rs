//! All four original files remain in Root custody before A begins. Post-drain
//! reads retain four independent shared locks and never open an old writer.

use std::os::unix::fs::FileExt;

use codex_hepta_intelligence_eval::ProductEvaluationExecutionAnchorV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStateV1;
use codex_hepta_intelligence_eval::ReadOnlyProductEvaluationExecutionStoreV1;
use codex_hepta_learning_ledger::LedgerReadOnlyCutV1;
use codex_hepta_learning_ledger::ReadOnlyLedgerViewV1;
use codex_hepta_neuron::CellDecisionReceiptV1;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::observe_original_file_anchor_v1;

use super::super::*;
use crate::authority_host_runtime::RootHistoricalLedgerDeploymentV1;
use crate::cell_q24_task_ledger::history::OriginalTaskLedgerHistoryContextV1;
use crate::cell_q24_task_ledger::history::OriginalTaskLedgerHistoryDataV1;

pub(crate) struct OriginalLedgerFiles {
    pub(super) deployment: RootHistoricalLedgerDeploymentV1,
    files: [File; 4],
    pins: [FilePin; 4],
    uid: u32,
    gid: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(super) struct OriginalLedgerObservation {
    pub(super) cut: LedgerReadOnlyCutV1,
    pub(super) signature_anchor: JournalAnchor,
    pub(super) signature_images: [(u64, Digest32); 2],
    pub(super) facts: OriginalTaskLedgerHistoryDataV1,
}

pub(super) enum OriginalLedgerReadModeV1 {
    Capture,
    Retained {
        ledger: LedgerReadOnlyCutV1,
        signatures: JournalAnchor,
    },
}

/// These four independent open descriptions survive the entire original Root
/// context. The HEPTEX reader has a fifth descriptor, so its local unlock never
/// releases Root's actual signature-journal lock.
pub(super) struct OriginalLedgerReadGuard {
    ledger: ReadOnlyLedgerViewV1,
    signatures: ReadOnlyProductEvaluationExecutionStoreV1,
    signature_files: [File; 2],
    scope: JournalScope,
    generation: Generation,
    records: usize,
    anchor: JournalAnchor,
}

impl OriginalLedgerFiles {
    pub(crate) fn retain_original_ledger(
        deployment: RootHistoricalLedgerDeploymentV1,
        uid: u32,
        gid: u32,
    ) -> io::Result<Self> {
        original_root()?;
        if uid == 0 || gid == 0 {
            return Err(io::Error::other("original non-Root Ledger owner required"));
        }
        let descriptors = deployment.original_descriptors()?;
        let mut files = Vec::with_capacity(4);
        let mut pins = Vec::with_capacity(4);
        for descriptor in &descriptors {
            let (file, pin) = FilePin::readonly(descriptor, uid, gid)?;
            if pins.iter().any(|previous: &FilePin| {
                (previous.device, previous.inode) == (pin.device, pin.inode)
            }) {
                return Err(io::Error::other(
                    "four distinct original Ledger files required",
                ));
            }
            files.push(file);
            pins.push(pin);
        }
        let held = Self {
            deployment,
            files: files
                .try_into()
                .map_err(|_| io::Error::other("original Ledger file count"))?,
            pins: pins
                .try_into()
                .map_err(|_| io::Error::other("original Ledger pin count"))?,
            uid,
            gid,
        };
        held.require_original_files()?;
        Ok(held)
    }

    pub(super) fn file_pins(&self) -> &[FilePin; 4] {
        &self.pins
    }

    /// Before Initial enrollment ACK, A has not initialized any of these four
    /// files. A missing or nonempty original is not repaired or reinterpreted.
    pub(super) fn require_empty_baseline(&self) -> io::Result<()> {
        self.require_original_files()?;
        let held = self.open_original_descriptors()?;
        for file in &held {
            file.try_lock_shared().map_err(io::Error::other)?;
        }
        for _ in 0..2 {
            self.require_original_files()?;
            for file in &held {
                if file.metadata()?.len() != 0 {
                    return Err(io::Error::other(
                        "original first-A Ledger baseline is not empty",
                    ));
                }
            }
        }
        Ok(())
    }

    pub(super) fn open_original_terminal(
        &self,
        context: &OriginalTaskLedgerHistoryContextV1<'_>,
        mode: OriginalLedgerReadModeV1,
    ) -> io::Result<OriginalLedgerReadGuard> {
        self.require_original_files()?;
        let [ledger, witness, signatures, signature_witness] = self.open_original_descriptors()?;
        let data = &self.deployment.ledger;
        let (ledger, expected_signatures) = match mode {
            OriginalLedgerReadModeV1::Capture => (
                ReadOnlyLedgerViewV1::observe_closed(
                    ledger,
                    witness,
                    context.ledger_binding,
                    data.maximum_records,
                )
                .map_err(io::Error::other)?,
                None,
            ),
            OriginalLedgerReadModeV1::Retained {
                ledger: expected,
                signatures,
            } => (
                ReadOnlyLedgerViewV1::open_at_retained_cut(
                    ledger,
                    witness,
                    context.ledger_binding,
                    data.maximum_records,
                    expected,
                )
                .map_err(io::Error::other)?,
                Some(signatures),
            ),
        };
        signatures.try_lock_shared().map_err(io::Error::other)?;
        signature_witness
            .try_lock_shared()
            .map_err(io::Error::other)?;
        let scope = JournalScope {
            scope_digest: Digest32::from_array(data.signature_witness.scope),
            objective_digest: context.verifier.objective_digest(),
        };
        let generation =
            Generation::new(data.signature_witness.generation).map_err(io::Error::other)?;
        let records = data.signature_witness.maximum_records;
        let anchor =
            observe_original_file_anchor_v1(&signature_witness, scope, generation, records)
                .map_err(io::Error::other)?
                .ok_or_else(|| io::Error::other("original signature witness missing"))?;
        if anchor.sequence != 5 || expected_signatures.is_some_and(|expected| expected != anchor) {
            return Err(io::Error::other(
                "exact original Decision/Outcome signature cut required",
            ));
        }
        let (reader, _) = FilePin::readonly(&self.files[2], self.uid, self.gid)?;
        let reader = ReadOnlyProductEvaluationExecutionStoreV1::open(
            reader,
            context.signature_binding().map_err(io::Error::other)?,
            ProductEvaluationExecutionAnchorV1 {
                sequence: anchor.sequence - 1,
                history_digest: anchor.checkpoint_digest,
            },
        )
        .map_err(io::Error::other)?;
        self.require_original_files()?;
        Ok(OriginalLedgerReadGuard {
            ledger,
            signatures: reader,
            signature_files: [signatures, signature_witness],
            scope,
            generation,
            records,
            anchor,
        })
    }

    fn open_original_descriptors(&self) -> io::Result<[File; 4]> {
        let mut files = Vec::with_capacity(4);
        for file in &self.files {
            files.push(FilePin::readonly(file, self.uid, self.gid)?.0);
        }
        files
            .try_into()
            .map_err(|_| io::Error::other("original Ledger file count"))
    }

    pub(super) fn require_original_files(&self) -> io::Result<()> {
        original_root()?;
        self.deployment.require_original_files()?;
        for (file, pin) in self.files.iter().zip(&self.pins) {
            if &FilePin::read(file, self.uid, self.gid)? != pin {
                return Err(io::Error::other(
                    "original Ledger descriptor custody changed",
                ));
            }
        }
        Ok(())
    }
}

impl OriginalLedgerReadGuard {
    pub(super) fn observe_original_terminal(
        &mut self,
        context: &OriginalTaskLedgerHistoryContextV1<'_>,
        publication: &crate::CircuitTaskSourcePublicationV1,
        cell: &CellDecisionReceiptV1,
        now: u64,
    ) -> io::Result<OriginalLedgerObservation> {
        let before = self.signature_images()?;
        let ledger = self.ledger.observe().map_err(io::Error::other)?;
        let keys = context.execution_keys().map_err(io::Error::other)?;
        let mut envelopes = Vec::with_capacity(2);
        for key in &keys {
            let ProductEvaluationExecutionStateV1::Completed(bytes) =
                self.signatures.readback(key).map_err(io::Error::other)?
            else {
                return Err(io::Error::other(
                    "original Ledger signature remains pending",
                ));
            };
            envelopes.push(bytes);
        }
        let facts = context
            .verify_original_terminal(
                &ledger,
                publication,
                cell,
                &envelopes[0],
                &envelopes[1],
                now,
            )
            .map_err(io::Error::other)?;
        if self.ledger.observe().map_err(io::Error::other)? != ledger
            || self.signature_images()? != before
        {
            return Err(io::Error::other(
                "original Ledger files changed during verification",
            ));
        }
        Ok(OriginalLedgerObservation {
            cut: ledger.cut,
            signature_anchor: self.anchor,
            signature_images: before,
            facts,
        })
    }

    pub(super) fn require_unchanged(
        &mut self,
        expected: &OriginalLedgerObservation,
    ) -> io::Result<()> {
        if self.ledger.observe().map_err(io::Error::other)?.cut != expected.cut
            || self.anchor != expected.signature_anchor
            || self.signature_images()? != expected.signature_images
        {
            return Err(io::Error::other(
                "original Ledger cut changed after Root context",
            ));
        }
        Ok(())
    }

    fn signature_images(&self) -> io::Result<[(u64, Digest32); 2]> {
        let before = [
            image(&self.signature_files[0], 32 * 1024 * 1024)?,
            image(&self.signature_files[1], 1024 * 1024)?,
        ];
        let anchor = observe_original_file_anchor_v1(
            &self.signature_files[1],
            self.scope,
            self.generation,
            self.records,
        )
        .map_err(io::Error::other)?;
        if anchor != Some(self.anchor)
            || image(&self.signature_files[0], 32 * 1024 * 1024)? != before[0]
            || image(&self.signature_files[1], 1024 * 1024)? != before[1]
        {
            return Err(io::Error::other("original signature cut changed"));
        }
        Ok(before)
    }
}

fn image(file: &File, maximum: u64) -> io::Result<(u64, Digest32)> {
    let before = file.metadata()?;
    if !before.is_file() || before.nlink() != 1 || before.len() > maximum {
        return Err(io::Error::other("bounded original signature file required"));
    }
    let mut bytes = vec![0; before.len() as usize];
    file.read_exact_at(&mut bytes, /*offset*/ 0)?;
    let after = file.metadata()?;
    let stamp = |metadata: &std::fs::Metadata| {
        (
            metadata.dev(),
            metadata.ino(),
            metadata.uid(),
            metadata.gid(),
            metadata.mode(),
            metadata.nlink(),
            metadata.len(),
            metadata.mtime(),
            metadata.mtime_nsec(),
            metadata.ctime(),
            metadata.ctime_nsec(),
        )
    };
    if stamp(&before) != stamp(&after) {
        return Err(io::Error::other(
            "original signature file changed during read",
        ));
    }
    Ok((before.len(), Digest32::of_bytes(&bytes)))
}
