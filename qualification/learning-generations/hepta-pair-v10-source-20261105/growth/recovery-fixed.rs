use super::*;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum GrowthProgress {
    /// Before any request-local context or owner-state lookup.
    BeforeContext,
    /// Before each bounded target/time ancestor header and record pair.
    HeaderAncestor {
        index: usize,
    },
    BeforeWork,
    /// Existing full W1 replay boundaries; these do not certify a public CPU budget.
    Work(pon_work::VerificationProgress),
    Execution(pon_executor::ExecutionProgress),
    BeforePersistence,
    /// Before each original admission-delta INSERT, in canonical delta order.
    AdmissionDeltaWrite {
        index: usize,
    },
    /// Existing final delta-row readback checkpoints: before reading, after
    /// every 256 rows, and after the complete read. This is not a row counter.
    AdmissionDeltaReadback {
        checkpoint: usize,
    },
    AccountNode,
    /// Existing original-parent multiproof verification boundaries.
    ParentProof(multiproof::MultiproofProgress),
    /// Proof-derived root computation inside the unchanged M06 callback.
    CommitmentProof(multiproof::MultiproofProgress),
    /// Independent final successor recomputation before persistence.
    FinalSuccessorProof(multiproof::MultiproofProgress),
    /// Before each pair of ancestor reads, in the existing fork-walk order.
    ReorgAncestor {
        index: usize,
    },
    /// Before each ordered undo/apply journal write pair.
    ReorgWrite {
        index: usize,
    },
    /// Before each steps/events row read, including EOF, then the reorg singleton.
    ReorgReadback {
        index: usize,
    },
    BeforeCommit,
    BeforeObservation,
    /// Before each actual active-membership SQL lookup; its original budget remains.
    MembershipRead {
        index: u64,
    },
    ObservationDelta,
    BeforeObservationTask,
    ObservationReady,
}

// Operation-local read counters, never a retained validity or resource grant.
#[derive(Debug, Default)]
pub(super) struct ColdJournalReads {
    pub(super) typed_events: u64,
    pub(super) semantic_events: u64,
    pub(super) latest_steps: u64,
    pub(super) latest_events: u64,
    pub(super) peak_event_rows: usize,
}

impl Node {
    pub fn make_growth_consensus_maintenance(
        &self,
        parent_id: Hash,
        transactions: Vec<Vec<u8>>,
        miner: Hash,
        timestamp: u64,
        max_attempts: u64,
    ) -> Result<GrowthPacket> {
        self.growth_guard()?;
        ensure(
            transactions.len() <= 256 && max_attempts > 0,
            "PACKET_LIMIT",
        )?;
        let read = self.db.unchecked_transaction()?;
        let parent = self.growth_parent(parent_id)?;
        let owners = requested(&parent, &transactions, miner)?;
        let (accounts, _) =
            multiproof::from_native_database(&self.db, &parent.checkpoint, &owners, &|_| {
                Ok::<_, archive::ArchiveError>(())
            })
            .map_err(archive_error)?;
        let height = parent.height.checked_add(1).ok_or("HEIGHT")?;
        let mut packet = GrowthPacket {
            header: GrowthHeader {
                ledger: Header {
                    network: self.settings.network(),
                    parameters: self.settings.parameters(),
                    parent: parent_id,
                    height,
                    timestamp,
                    target: self.growth_target(parent_id)?,
                    miner,
                    transactions: sequence_root("transactions", &transactions),
                    state: [0; 32],
                    receipts: [0; 32],
                    work_task: continuity_v1::maintenance_task()?,
                    nonce: 0,
                },
                witness: GrowthPacket::witness_digest(&accounts)?,
            },
            transactions,
            accounts,
            proof: vec![0; pon_work::PROOF_BYTES],
        };
        // Includes all actual bytes before spending on work search.
        packet.encode()?;
        let executed = execute(&self.settings, &parent, &packet, &|_| Ok(()))?;
        packet.header.ledger.state = executed.state.commitment.id;
        packet.header.ledger.receipts = sequence_root("receipts", &executed.receipts);
        self.growth_guard()?;
        read.rollback()?;
        let (a, b) = continuity_v1::maintenance_matrices();
        let task =
            pon_work::PreparedTask::new(&a, &b).map_err(|e| Error::from(format!("WORK:{e:?}")))?;
        for nonce in 0..max_attempts {
            packet.header.ledger.nonce = nonce;
            packet.proof = task
                .prove(packet.header.challenge())
                .map_err(|e| Error::from(format!("WORK:{e:?}")))?;
            match pon_work::verify(
                packet.header.challenge(),
                packet.header.ledger.work_task,
                packet.header.ledger.target,
                &packet.proof,
            ) {
                Ok(_) => {
                    self.growth_guard()?;
                    return Ok(packet);
                }
                Err(pon_work::WorkError::Target) => continue,
                Err(error) => return Err(format!("WORK:{error:?}").into()),
            }
        }
        Err("SEARCH_EXHAUSTED".into())
    }

    pub(super) fn check_growth_header(
        &self,
        packet: &GrowthPacket,
        observed_now: u64,
    ) -> Result<()> {
        self.check_growth_header_with_progress(packet, observed_now, &|_| Ok(()))
    }
    pub(super) fn check_growth_header_with_progress(
        &self,
        packet: &GrowthPacket,
        observed_now: u64,
        progress: &(impl Fn(GrowthProgress) -> Result<()> + Sync),
    ) -> Result<()> {
        let h = &packet.header.ledger;
        ensure(
            h.network == self.settings.network() && h.parameters == self.settings.parameters(),
            "NETWORK",
        )?;
        let parent = self.record(h.parent)?;
        ensure(
            parent.height.checked_add(1) == Some(h.height) && h.height <= i64::MAX as u64,
            "HEIGHT",
        )?;
        let height = consensus::BranchTargetHeight::after(parent.height)?;
        // Target and median time use the same immutable parent-first window.
        // Each precheck/reacquire/transaction check still reads it afresh; only
        // duplicate SQL reads within this one check are removed.
        let recent = self.growth_recent_with_progress(h.parent, progress)?;
        ensure(
            h.target == self.growth_target_from_recent(height, &recent)?,
            "TARGET",
        )?;
        ensure(
            h.transactions == sequence_root("transactions", &packet.transactions),
            "ROOT",
        )?;
        ensure(
            h.work_task == continuity_v1::maintenance_task()?,
            "CONTINUITY_MAINTENANCE",
        )?;
        let times: Vec<_> = recent.iter().take(11).map(|p| p.0).collect();
        consensus::check_time(
            h.timestamp,
            &times,
            observed_now,
            self.settings.limit("future_skew_seconds")?,
        )
    }

    pub fn admit_growth(&mut self, packet: &GrowthPacket, observed_now: u64) -> Result<Hash> {
        self.admit_growth_with_progress(packet, observed_now, &|_| Ok(()))
    }
    pub fn admit_growth_with_progress(
        &mut self,
        packet: &GrowthPacket,
        observed_now: u64,
        progress: &(impl Fn(GrowthProgress) -> Result<()> + Sync),
    ) -> Result<Hash> {
        if let Some(id) =
            self.precheck_growth_admission_with_progress(packet, observed_now, progress)?
        {
            return Ok(id);
        }
        let checked = GrowthWorkCheckedPacket::verify_with_progress(packet.clone(), progress)?;
        self.admit_growth_work_checked_with_progress(checked, observed_now, progress)
    }

    /// Bounded current-owner context only. A successful absence result conveys
    /// no reusable parent-State or clock authority across owner-lock release.
    pub(crate) fn precheck_growth_admission_with_progress(
        &self,
        packet: &GrowthPacket,
        observed_now: u64,
        progress: &(impl Fn(GrowthProgress) -> Result<()> + Sync),
    ) -> Result<Option<Hash>> {
        progress(GrowthProgress::BeforeContext)?;
        self.growth_guard()?;
        let bytes = packet.encode()?;
        self.check_growth_header_with_progress(packet, observed_now, progress)?;
        let id = packet.id()?;
        let previous: Option<Vec<u8>> = self
            .db
            .query_row(
                "SELECT packet FROM blocks WHERE id=?",
                [id.as_slice()],
                |r| r.get(0),
            )
            .optional()?;
        let existing = if let Some(previous) = previous {
            ensure(previous == bytes, "DUPLICATE_CONTENT")?;
            Some(id)
        } else {
            None
        };
        // A foreign writer can change an already-read ancestor while the
        // current owner is checking another header. Recheck the audited epoch
        // after the complete read, including the duplicate fast return; a
        // local window is never an authority to use a changed storage epoch.
        self.growth_guard()?;
        Ok(existing)
    }

    /// The caller must reacquire the original Node owner after W1 verification.
    /// Consume the private immutable packet, then repeat current context/time
    /// checks and bind the actual parent inside the original write transaction.
    /// A verified mathematical work relation is never a cached admission verdict.
    pub(crate) fn admit_growth_work_checked_with_progress(
        &mut self,
        checked: GrowthWorkCheckedPacket,
        observed_now: u64,
        progress: &(impl Fn(GrowthProgress) -> Result<()> + Sync),
    ) -> Result<Hash> {
        self.admit_growth_work_checked_with_worker_accounting(checked, observed_now, progress, &())
    }

    /// Public paid dispatch supplies its original scoped worker meter here.
    /// Revalidation, SQL mutation and the durable commit keep the same owner.
    pub(crate) fn admit_growth_work_checked_with_worker_accounting(
        &mut self,
        checked: GrowthWorkCheckedPacket,
        observed_now: u64,
        progress: &(impl Fn(GrowthProgress) -> Result<()> + Sync),
        accounting: &dyn pon_executor::ExecutionWorkerAccounting,
    ) -> Result<Hash> {
        let (packet, _verified_work) = checked.into_parts();
        if let Some(id) =
            self.precheck_growth_admission_with_progress(&packet, observed_now, progress)?
        {
            return Ok(id);
        }
        let bytes = packet.encode()?;
        let id = packet.id()?;
        let h = &packet.header.ledger;
        // The single owner rebinds the parent in its actual write transaction.
        let tx = rusqlite::Transaction::new_unchecked(
            &self.db,
            rusqlite::TransactionBehavior::Immediate,
        )?;
        self.growth_guard()?;
        self.check_growth_header_with_progress(&packet, observed_now, progress)?;
        let active_before = self.active()?;
        let parent = self.growth_parent(h.parent)?;
        let mut executed = execute_observed_with_workers(
            &self.settings,
            &parent,
            &packet,
            None,
            (self.workers, accounting),
            progress,
        )?;
        ensure(
            h.state == executed.state.commitment.id
                && h.receipts == sequence_root("receipts", &executed.receipts),
            "ROOT",
        )?;
        let chainwork = self
            .record(h.parent)?
            .work
            .checked_add(consensus::required_work(h.target)?)?;
        progress(GrowthProgress::BeforePersistence)?;
        ensure(
            tx.execute(
                "INSERT INTO blocks VALUES(?,?,?,?,?,?)",
                params![
                    id.as_slice(),
                    h.parent.as_slice(),
                    h.height,
                    chainwork.bytes().as_slice(),
                    &bytes,
                    h.state.as_slice(),
                ],
            )? == 1,
            "STORAGE_WRITE",
        )?;
        for (index, (key, before, after)) in executed.deltas.iter().enumerate() {
            progress(GrowthProgress::AdmissionDeltaWrite { index })?;
            ensure(
                tx.execute(
                    "INSERT INTO deltas VALUES(?,?,?,?)",
                    params![id.as_slice(), key, before, after],
                )? == 1,
                "STORAGE_WRITE",
            )?;
        }
        let accounts = native_store::apply_growth(
            &tx,
            parent.source.accounts(),
            &executed.deltas,
            &mut || progress(GrowthProgress::AccountNode),
        )?;
        ensure(
            accounts.digest == executed.state.commitment.permanent_account_root
                && accounts.count == executed.state.commitment.permanent_account_count
                && accounts.balance == executed.state.commitment.permanent_account_balance,
            "GROWTH_COW_MISMATCH",
        )?;
        executed.state.accounts = accounts;
        save(&tx, id, &executed.state)?;
        // Exact write-set and parent/root readback before the only durable commit.
        // Preserve the original cursor's bounded checkpoints and the caller's
        // control error; cancellation rolls back this same write transaction.
        let mut readback_checkpoint = 0;
        ensure(
            self.delta_rows_with_progress(id, &mut || {
                progress(GrowthProgress::AdmissionDeltaReadback {
                    checkpoint: readback_checkpoint,
                })?;
                readback_checkpoint += 1;
                Ok(())
            })? == executed.deltas
                && self.growth_load_packet(id)?.encode()? == bytes
                && self.growth_parent(h.parent)?.source.stored == parent.source.stored
                && self.growth_parent(id)?.source.stored == executed.state
                && self.active()? == active_before,
            "STORAGE_WRITE",
        )?;
        progress(GrowthProgress::BeforeCommit)?;
        self.growth_guard()?;
        tx.commit()?;
        Ok(id)
    }

    pub(in crate::store) fn growth_recover(&mut self) -> Result<Hash> {
        self.growth_guard()?;
        let best: Vec<u8> = self.db.query_row(
            "SELECT id FROM blocks ORDER BY chainwork DESC,height,id LIMIT 1",
            [],
            |r| r.get(0),
        )?;
        self.growth_activate(bytes32(best)?)
    }
    pub(in crate::store) fn growth_activate(&mut self, target: Hash) -> Result<Hash> {
        self.growth_activate_with_progress(target, &|_| Ok(()))
    }
    pub fn growth_activate_with_progress(
        &mut self,
        target: Hash,
        progress: &impl Fn(GrowthProgress) -> Result<()>,
    ) -> Result<Hash> {
        // Even an already-active or lower-work target belongs to this caller's
        // operation. Observe cancellation before any owner/SQLite lookup.
        progress(GrowthProgress::BeforeContext)?;
        self.growth_guard()?;
        let tx = rusqlite::Transaction::new_unchecked(
            &self.db,
            rusqlite::TransactionBehavior::Immediate,
        )?;
        // A foreign writer may commit between the first epoch check and BEGIN
        // IMMEDIATE. Rebind after the write lock, including the no-op return.
        self.growth_guard()?;
        let (old, generation) = self.active()?;
        if self.record(target)?.work <= self.record(old)?.work {
            tx.rollback()?;
            return Ok(old);
        }
        self.growth_parent(old)?;
        self.growth_parent(target)?;
        let next = generation
            .checked_add(1)
            .filter(|n| *n <= i64::MAX as u64)
            .ok_or("GENERATION")?;
        let mut left = old;
        let mut right = target;
        let mut undo = Vec::new();
        let mut apply = Vec::new();
        let mut ancestor_index = 0;
        while left != right {
            progress(GrowthProgress::ReorgAncestor {
                index: ancestor_index,
            })?;
            ancestor_index += 1;
            let l = self.record(left)?;
            let r = self.record(right)?;
            if l.height >= r.height {
                undo.push(left);
                left = l.parent.ok_or("GROWTH_ANCESTRY")?;
            } else {
                apply.push(right);
                right = r.parent.ok_or("GROWTH_ANCESTRY")?;
            }
        }
        let changes = undo
            .iter()
            .map(|id| (0u64, *id))
            .chain(apply.iter().rev().map(|id| (1u64, *id)));
        let change_count = undo.len() + apply.len();
        tx.execute("DELETE FROM steps", [])?;
        for (index, (kind, id)) in changes.clone().enumerate() {
            progress(GrowthProgress::ReorgWrite { index })?;
            ensure(
                tx.execute(
                    "INSERT INTO steps VALUES(?,?,?)",
                    params![index as u64, kind, id.as_slice()],
                )? == 1,
                "STORAGE_WRITE",
            )?;
            ensure(
                tx.execute(
                    "INSERT INTO events VALUES(?,?,?,?)",
                    params![next, index as u64, kind, id.as_slice()],
                )? == 1,
                "STORAGE_WRITE",
            )?;
        }
        ensure(tx.execute("INSERT INTO reorg VALUES(1,?,?,?,?,1) ON CONFLICT(singleton) DO UPDATE SET old_tip=excluded.old_tip,new_tip=excluded.new_tip,generation=excluded.generation,cursor=excluded.cursor,done=excluded.done",
            params![old.as_slice(),target.as_slice(),next,change_count as u64])? == 1, "STORAGE_WRITE")?;
        ensure(tx.execute("UPDATE active SET tip=?,generation=?,state_slot=? WHERE singleton=1 AND tip=? AND generation=?",
            params![target.as_slice(),next,next,old.as_slice(),generation])? == 1, "STALE_VIEW")?;
        ensure(
            self.active()? == (target, next)
                && self.slot()? == next
                && load(&tx, target)?.commitment.id == self.record(target)?.root,
            "STORAGE_WRITE",
        )?;
        self.growth_check_latest_journal_with_progress(old, target, next, changes, progress)?;
        progress(GrowthProgress::BeforeCommit)?;
        self.growth_guard()?;
        tx.commit()?;
        Ok(target)
    }

    #[cfg(test)]
    pub(super) fn growth_check_latest_journal(
        &self,
        old: Hash,
        target: Hash,
        generation: u64,
        changes: &[(u64, Hash)],
    ) -> Result<()> {
        self.growth_check_latest_journal_with_progress(
            old,
            target,
            generation,
            changes.iter().copied(),
            &|_| Ok(()),
        )
    }

    fn growth_check_latest_journal_with_progress(
        &self,
        old: Hash,
        target: Hash,
        generation: u64,
        changes: impl Iterator<Item = (u64, Hash)> + Clone,
        progress: &impl Fn(GrowthProgress) -> Result<()>,
    ) -> Result<()> {
        let change_count = changes.clone().count();
        let mut matches = true;
        let mut index = 0;
        for (sql, selected_generation) in [
            (
                "SELECT ordinal,kind,block FROM steps ORDER BY ordinal",
                None,
            ),
            (
                "SELECT ordinal,kind,block FROM events WHERE generation=? ORDER BY ordinal",
                Some(generation),
            ),
        ] {
            let mut statement = self.db.prepare(sql)?;
            let mut rows = match selected_generation {
                Some(generation) => statement.query([generation])?,
                None => statement.query([])?,
            };
            let mut expected = changes.clone().enumerate();
            loop {
                progress(GrowthProgress::ReorgReadback { index })?;
                index += 1;
                let Some(row) = rows.next()? else {
                    matches &= expected.next().is_none();
                    break;
                };
                let actual: (u64, u64, Vec<u8>) = (row.get(0)?, row.get(1)?, row.get(2)?);
                matches &= expected.next().is_some_and(|(ordinal, (kind, id))| {
                    actual.0 == ordinal as u64 && actual.1 == kind && actual.2 == id
                });
            }
        }
        progress(GrowthProgress::ReorgReadback { index })?;
        let reorg: (Vec<u8>, Vec<u8>, u64, u64, u64) = self.db.query_row(
            "SELECT old_tip,new_tip,generation,cursor,done FROM reorg WHERE singleton=1",
            [],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?)),
        )?;
        ensure(
            matches
                && reorg
                    == (
                        old.to_vec(),
                        target.to_vec(),
                        generation,
                        change_count as u64,
                        1,
                    ),
            "GROWTH_REORG_JOURNAL",
        )
    }

    pub(super) fn growth_check_journal(&self) -> Result<ColdJournalReads> {
        // The caller retains the original cold-open read transaction throughout
        // both passes and final readback. Collect used to convert ALL SQL rows
        // before checking any journal rule. Keep that error priority without
        // retaining the history; fixed_blob preserves type errors and copies at
        // most33 bytes even from a corrupt oversized stored cell.
        let mut observation = ColdJournalReads::default();
        let mut statement = self.db.prepare(
            "SELECT generation,ordinal,kind,block FROM events ORDER BY generation,ordinal",
        )?;
        {
            let mut rows = statement.query([])?;
            while let Some(row) = rows.next()? {
                let _: (u64, u64, u64, Vec<u8>) = (
                    row.get(0)?,
                    row.get(1)?,
                    row.get(2)?,
                    super::super::fixed_blob::<32>(row, 3)?,
                );
                observation.typed_events += 1;
                observation.peak_event_rows = 1;
            }
        }
        let mut tip = self.settings.genesis();
        let mut generation = 0u64;
        let mut old = tip;
        let mut changes = 0u64;
        let mut rows = statement.query([])?;
        while let Some(row) = rows.next()? {
            let (g, ordinal, kind): (u64, u64, u64) = (row.get(0)?, row.get(1)?, row.get(2)?);
            let raw = super::super::fixed_blob::<32>(row, 3)?;
            observation.semantic_events += 1;
            if g != generation {
                ensure(g == generation + 1, "GROWTH_REORG_JOURNAL")?;
                generation = g;
                old = tip;
                changes = 0;
            }
            ensure(ordinal == changes, "GROWTH_REORG_JOURNAL")?;
            let id = bytes32(raw)?;
            match kind {
                0 => {
                    ensure(tip == id, "GROWTH_REORG_JOURNAL")?;
                    tip = self.record(id)?.parent.ok_or("GROWTH_REORG_JOURNAL")?;
                }
                1 => {
                    ensure(self.record(id)?.parent == Some(tip), "GROWTH_REORG_JOURNAL")?;
                    tip = id;
                }
                _ => return Err("GROWTH_REORG_JOURNAL".into()),
            }
            changes += 1;
        }
        drop(rows);
        drop(statement);
        ensure(
            self.active()? == (tip, generation) && self.slot()? == generation,
            "GROWTH_REORG_JOURNAL",
        )?;
        if generation > 0 {
            self.growth_check_cold_latest_journal(old, tip, generation, changes, &mut observation)?;
        } else {
            let rows: u64 = self.db.query_row(
                "SELECT (SELECT count(*) FROM reorg)+(SELECT count(*) FROM steps)",
                [],
                |r| r.get(0),
            )?;
            ensure(rows == 0, "GROWTH_REORG_JOURNAL")?;
        }
        Ok(observation)
    }

    fn growth_check_cold_latest_journal(
        &self,
        old: Hash,
        target: Hash,
        generation: u64,
        count: u64,
        observation: &mut ColdJournalReads,
    ) -> Result<()> {
        // All events already passed typed and semantic checks in this same read
        // snapshot. Compare actual rows, including both EOFs; no digest replaces
        // the exact latest journal. The hot callback-bearing checker is unchanged.
        let mut steps = self
            .db
            .prepare("SELECT ordinal,kind,block FROM steps ORDER BY ordinal")?;
        let mut events = self
            .db
            .prepare("SELECT ordinal,kind,block FROM events WHERE generation=? ORDER BY ordinal")?;
        let mut steps = steps.query([])?;
        let mut events = events.query([generation])?;
        let mut matches = true;
        let mut index = 0u64;
        loop {
            let step = steps
                .next()?
                .map(|row| -> rusqlite::Result<_> {
                    Ok((
                        row.get::<_, u64>(0)?,
                        row.get::<_, u64>(1)?,
                        super::super::fixed_blob::<32>(row, 2)?,
                    ))
                })
                .transpose()?;
            let event = events
                .next()?
                .map(|row| -> rusqlite::Result<_> {
                    Ok((
                        row.get::<_, u64>(0)?,
                        row.get::<_, u64>(1)?,
                        super::super::fixed_blob::<32>(row, 2)?,
                    ))
                })
                .transpose()?;
            if step.is_none() && event.is_none() {
                break;
            }
            observation.latest_steps += u64::from(step.is_some());
            observation.latest_events += u64::from(event.is_some());
            observation.peak_event_rows = observation
                .peak_event_rows
                .max(usize::from(step.is_some()) + usize::from(event.is_some()));
            matches &= step.as_ref().is_some_and(|row| row.0 == index)
                && event.as_ref().is_some_and(|row| row.0 == index)
                && step == event;
            index += 1;
        }
        let reorg: (Vec<u8>, Vec<u8>, u64, u64, u64) = self.db.query_row(
            "SELECT old_tip,new_tip,generation,cursor,done FROM reorg WHERE singleton=1",
            [],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?)),
        )?;
        ensure(
            matches
                && index == count
                && reorg == (old.to_vec(), target.to_vec(), generation, count, 1),
            "GROWTH_REORG_JOURNAL",
        )
    }

    /// Cold integrity is deliberately separate from request latency. Every retained
    /// branch is reexecuted against its parent witness, and every retained root is
    /// checked against real COW nodes before the operation epoch is published.
    pub(in crate::store) fn growth_cold_open(&mut self, recover: bool) -> Result<()> {
        profile::require(&self.settings)?;
        let read = self.db.unchecked_transaction()?;
        let version: u64 = self.db.query_row("PRAGMA data_version", [], |r| r.get(0))?;
        let expected =
            growth_commitment_from_complete_state_v2(&self.settings, &self.settings.initial)
                .map_err(execution_error)?;
        let genesis = self.growth_parent(self.settings.genesis())?;
        let genesis_record = self.record(self.settings.genesis())?;
        let genesis_packet: Option<Vec<u8>> = self.db.query_row(
            "SELECT packet FROM blocks WHERE id=?",
            [self.settings.genesis().as_slice()],
            |r| r.get(0),
        )?;
        ensure(
            genesis_record.height == 0
                && genesis_record.parent.is_none()
                && genesis_packet.is_none()
                && genesis.source.stored.commitment == *expected.observation()
                && genesis.source.stored.working == working(&self.settings.initial)
                && genesis.source.stored.parent_commitment.is_none()
                && genesis.source.stored.deltas == delta_hash(&[])?
                && self.record(self.settings.genesis())?.work == consensus::Work::default(),
            "GROWTH_GENESIS",
        )?;
        let rows: Vec<Hash> = self
            .db
            .prepare("SELECT id FROM blocks ORDER BY height,id")?
            .query_map([], |r| r.get::<_, Vec<u8>>(0))?
            .map(|r| bytes32(r?))
            .collect::<Result<_>>()?;
        let mut checked = BTreeSet::from([self.settings.genesis()]);
        let mut roots = vec![genesis.source.stored.accounts];
        for id in rows {
            if id == self.settings.genesis() {
                continue;
            }
            let packet = self.growth_load_packet(id)?;
            let h = &packet.header.ledger;
            ensure(checked.contains(&h.parent), "GROWTH_ANCESTRY")?;
            self.check_growth_header(&packet, u64::MAX)?;
            pon_work::verify(
                packet.header.challenge(),
                h.work_task,
                h.target,
                &packet.proof,
            )
            .map_err(|e| Error::from(format!("WORK:{e:?}")))?;
            let parent = self.growth_parent(h.parent)?;
            let executed = execute(&self.settings, &parent, &packet, &|_| Ok(()))?;
            let stored = self.growth_parent(id)?;
            let record = self.record(id)?;
            ensure(
                record.parent == Some(h.parent)
                    && record.height == h.height
                    && record.root == h.state
                    && record.work
                        == self
                            .record(h.parent)?
                            .work
                            .checked_add(consensus::required_work(h.target)?)?
                    && executed.state.commitment == stored.source.stored.commitment
                    && executed.state.working == stored.source.stored.working
                    && executed.state.parent_commitment == stored.source.stored.parent_commitment
                    && executed.state.deltas == stored.source.stored.deltas
                    && self.delta_rows_with_progress(id, &mut || Ok(()))? == executed.deltas
                    && h.receipts == sequence_root("receipts", &executed.receipts),
                "GROWTH_COLD_REPLAY",
            )?;
            roots.push(stored.source.stored.accounts);
            checked.insert(id);
        }
        native_store::audit_growth_roots(&self.db, &roots)?;
        let states: u64 = self
            .db
            .query_row("SELECT count(*) FROM growth_states", [], |r| r.get(0))?;
        let orphans: u64 = self.db.query_row("SELECT count(*) FROM deltas d LEFT JOIN blocks b ON b.id=d.block WHERE b.id IS NULL OR b.height=0", [], |r| r.get(0))?;
        let legacy_rows: u64 = self.db.query_row(
            "SELECT (SELECT count(*) FROM kv)+(SELECT count(*) FROM snapshots)",
            [],
            |r| r.get(0),
        )?;
        ensure(
            states == checked.len() as u64 && orphans == 0 && legacy_rows == 0,
            "GROWTH_STORAGE_PARTITION",
        )?;
        ensure(checked.contains(&self.active()?.0), "GROWTH_ACTIVE_ROOT")?;
        self.growth_check_journal()?;
        let expected_schema = schema(&self.db)?;
        read.rollback()?;
        let after: u64 = self.db.query_row("PRAGMA data_version", [], |r| r.get(0))?;
        ensure(version == after, "GROWTH_STORAGE_EPOCH_CHANGED")?;
        self.growth_epoch = Some(Epoch {
            version,
            schema: expected_schema,
        });
        if recover {
            self.growth_recover()?;
        }
        Ok(())
    }
}
