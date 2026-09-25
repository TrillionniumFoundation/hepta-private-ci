//! Bounded current-state checkpoint replacement. This reclaims superseded
//! frames, not identities: retries and unknown outcomes remain recoverable.
use super::*;

impl DurableInferenceControl {
    pub fn journal_capacity_status(&self) -> JournalCapacityStatus {
        JournalCapacityStatus {
            journal_bytes: self.journal_bytes,
            maximum_journal_bytes: MAX_JOURNAL_BYTES,
            reserved_headroom_bytes: self.reserved_headroom_bytes,
            admissible_bytes: MAX_JOURNAL_BYTES
                .saturating_sub(self.journal_bytes)
                .saturating_sub(self.reserved_headroom_bytes),
            legacy_records: self.records.len(),
            native_records: self.native.records.len(),
        }
    }

    /// Rewrites superseded event history into one validated checkpoint per
    /// retained identity. The replacement inode is locked before rename, so
    /// the exclusive-writer invariant has no path-swap gap.
    pub fn compact_journal(&mut self) -> Result<JournalCompactionReceipt, Error> {
        if self.poisoned {
            return Err(Error::WriterUnavailable);
        }
        let before_bytes = self.journal_bytes;
        let image = self.checkpoint_image()?;
        self.replace_with_checkpoint_image(&image)?;
        Ok(JournalCompactionReceipt {
            before_bytes,
            after_bytes: self.journal_bytes,
            legacy_records: self.records.len(),
            native_records: self.native.records.len(),
            reserved_headroom_bytes: self.reserved_headroom_bytes,
        })
    }

    pub(super) fn append_fits(&self, bytes: u64, append: u64, after: u64) -> Result<bool, Error> {
        if fits_with_headroom(bytes, append, after)? {
            return Ok(true);
        }
        // Older journals admitted without per-request liability. Recover their
        // responsibility instead of trapping them at open or first release.
        // Only liability-reducing transitions may use this migration exception.
        let overcommitted = !fits_with_headroom(bytes, 0, self.reserved_headroom_bytes)?;
        Ok(overcommitted
            && after < self.reserved_headroom_bytes
            && fits_with_headroom(bytes, append, 0)?)
    }

    pub(super) fn checkpoint_image(&self) -> Result<Vec<u8>, Error> {
        let count = self.records.len() + self.native.records.len();
        let mut image = format!("{}{count}\n", checkpoint_frame::HEADER).into_bytes();
        for record in self.records.values() {
            validate_legacy_checkpoint(record)?;
            let json = serde_json::to_string(record)
                .map_err(|_| Error::CorruptJournal("legacy checkpoint encode"))?;
            push_image_line(&mut image, LEGACY_CHECKPOINT_PREFIX, &json)?;
        }
        self.native.append_checkpoint_lines(&mut image)?;
        push_image_line(&mut image, checkpoint_frame::END, "")?;
        Ok(image)
    }

    pub(super) fn replace_with_checkpoint_image(&mut self, image: &[u8]) -> Result<(), Error> {
        if image.len() as u64 > MAX_JOURNAL_BYTES
            || (image.len() as u64 > self.journal_bytes
                && !fits_with_headroom(image.len() as u64, 0, self.reserved_headroom_bytes)?)
        {
            // An expanded snapshot must not spend already-owned terminal bytes.
            // Shrinking an old overcommitted image is still allowed for drain.
            return Err(Error::CapacityExceeded);
        }
        let temporary_path = compaction_path(&self.path);
        match fs::remove_file(&temporary_path) {
            Ok(()) => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => return Err(error.into()),
        }
        let mut options = OpenOptions::new();
        options.create_new(true).read(true).write(true).append(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut replacement = options.open(&temporary_path)?;
        replacement
            .try_lock()
            .map_err(|_| Error::WriterUnavailable)?;
        let staged = replacement
            .write_all(image)
            .and_then(|()| replacement.flush())
            .and_then(|()| replacement.sync_all());
        if let Err(error) = staged {
            let _ = fs::remove_file(&temporary_path);
            return Err(error.into());
        }
        maybe_crash_compaction("before_rename");
        if let Err(error) = fs::rename(&temporary_path, &self.path) {
            let _ = fs::remove_file(&temporary_path);
            return Err(error.into());
        }
        // The replacement inode was locked before rename. Install it before the
        // directory fsync so even an indeterminate fsync result remains fenced.
        self.file = replacement;
        self.journal_bytes = image.len() as u64;
        maybe_crash_compaction("after_rename");
        #[cfg(unix)]
        let parent = self
            .path
            .parent()
            .filter(|parent| !parent.as_os_str().is_empty())
            .unwrap_or_else(|| Path::new("."));
        #[cfg(unix)]
        if let Err(error) = File::open(parent).and_then(|directory| directory.sync_all()) {
            self.poisoned = true;
            return Err(error.into());
        }
        Ok(())
    }
}

fn fits_with_headroom(
    current_bytes: u64,
    append_bytes: u64,
    required_headroom: u64,
) -> Result<bool, Error> {
    let total = current_bytes
        .checked_add(append_bytes)
        .and_then(|value| value.checked_add(required_headroom))
        .ok_or(Error::ArithmeticOverflow)?;
    Ok(total <= MAX_JOURNAL_BYTES)
}

pub(super) fn replace_headroom(current: u64, previous: u64, next: u64) -> Result<u64, Error> {
    current
        .checked_sub(previous)
        .and_then(|value| value.checked_add(next))
        .ok_or(Error::ArithmeticOverflow)
}

pub(super) fn required_headroom(
    records: &BTreeMap<String, RequestRecord>,
    native: &native::NativeJournal,
) -> Result<u64, Error> {
    let legacy = records.values().try_fold(0_u64, |total, record| {
        total
            .checked_add(legacy_record_headroom(record))
            .ok_or(Error::ArithmeticOverflow)
    })?;
    legacy
        .checked_add(native.required_headroom_bytes()?)
        .ok_or(Error::ArithmeticOverflow)
}

pub(super) fn legacy_record_headroom(record: &RequestRecord) -> u64 {
    match record.state {
        RequestState::Pending => LEGACY_TERMINAL_HEADROOM_BYTES,
        RequestState::Reserved => 12 * 1024,
        RequestState::Assigned => 8 * 1024,
        RequestState::Cancelling => 4 * 1024,
        RequestState::Completed
        | RequestState::Failed
        | RequestState::Cancelled
        | RequestState::Indeterminate => 0,
    }
}

pub(super) fn push_image_line(image: &mut Vec<u8>, prefix: &str, json: &str) -> Result<(), Error> {
    let line_bytes = prefix
        .len()
        .checked_add(json.len())
        .and_then(|value| value.checked_add(1))
        .ok_or(Error::ArithmeticOverflow)?;
    if line_bytes > MAX_JOURNAL_LINE_BYTES {
        return Err(Error::CapacityExceeded);
    }
    let next = image
        .len()
        .checked_add(line_bytes)
        .ok_or(Error::ArithmeticOverflow)?;
    if next as u64 > MAX_JOURNAL_BYTES {
        return Err(Error::CapacityExceeded);
    }
    image.extend_from_slice(prefix.as_bytes());
    image.extend_from_slice(json.as_bytes());
    image.push(b'\n');
    Ok(())
}

pub(super) fn compaction_path(path: &Path) -> PathBuf {
    let mut value = path.as_os_str().to_os_string();
    value.push(COMPACTION_TEMP_SUFFIX);
    PathBuf::from(value)
}

#[cfg(test)]
fn maybe_crash_compaction(stage: &str) {
    if std::env::var("HEPTA_INFERENCE_COMPACTION_CRASH_STAGE").as_deref() == Ok(stage) {
        std::process::exit(match stage {
            "before_rename" => 74,
            "after_rename" => 75,
            _ => 76,
        });
    }
}

#[cfg(not(test))]
fn maybe_crash_compaction(_stage: &str) {}

pub(super) fn replay_legacy_checkpoint(
    records: &mut BTreeMap<String, RequestRecord>,
    json: &str,
) -> Result<String, Error> {
    let record: RequestRecord = serde_json::from_str(json)
        .map_err(|_| Error::CorruptJournal("legacy checkpoint decode"))?;
    validate_legacy_checkpoint(&record)?;
    let request_id = record.request.request_id.clone();
    if records.insert(request_id.clone(), record).is_some() {
        return Err(Error::CorruptJournal("duplicate legacy checkpoint"));
    }
    Ok(request_id)
}

fn validate_legacy_checkpoint(record: &RequestRecord) -> Result<(), Error> {
    validate_request(0, &record.request)?;
    if let Some(reservation) = &record.reservation {
        validate_reservation(0, reservation)?;
        if reservation.maximum_tokens < record.request.maximum_tokens
            || record.consumed_tokens > reservation.maximum_tokens
        {
            return Err(Error::UsageExceeded);
        }
    }
    if let Some(assignment) = &record.assignment {
        validate_assignment(assignment)?;
    }
    if let Some(digest) = &record.terminal_observation_digest {
        validate_digest(digest, "legacy terminal observation")?;
    }
    let events = legacy_checkpoint_events(record)?;
    let mut replayed = BTreeMap::new();
    for event in &events {
        apply_event(&mut replayed, event, /*replay*/ true)?;
    }
    if replayed.get(&record.request.request_id) != Some(record) || replayed.len() != 1 {
        return Err(Error::CorruptJournal("legacy checkpoint state"));
    }
    Ok(())
}

fn legacy_checkpoint_events(record: &RequestRecord) -> Result<Vec<Event>, Error> {
    let request_id = record.request.request_id.clone();
    let mut events = vec![Event::Submit(record.request.clone())];
    let mut revision = 1_u64;
    if let Some(reservation) = &record.reservation {
        events.push(Event::Reserve {
            request_id: request_id.clone(),
            expected_revision: revision,
            reservation: reservation.clone(),
        });
        revision += 1;
    }
    if let Some(assignment) = &record.assignment {
        if record.reservation.is_none() {
            return Err(Error::CorruptJournal("legacy checkpoint assignment"));
        }
        events.push(Event::Assign {
            request_id: request_id.clone(),
            expected_revision: revision,
            assignment: assignment.clone(),
        });
        revision += 1;
    }
    if let Some(observation_digest) = &record.terminal_observation_digest {
        let reservation = record
            .reservation
            .as_ref()
            .ok_or(Error::CorruptJournal("legacy checkpoint reservation"))?;
        let assignment = record
            .assignment
            .as_ref()
            .ok_or(Error::CorruptJournal("legacy checkpoint assignment"))?;
        if record.revision == revision + 2 {
            events.push(Event::Cancel {
                request_id: request_id.clone(),
                expected_revision: revision,
            });
            revision += 1;
        } else if record.revision != revision + 1 {
            return Err(Error::CorruptJournal("legacy checkpoint revision"));
        }
        let terminal_observed = record.state != RequestState::Indeterminate;
        events.push(Event::Settle {
            request_id: request_id.clone(),
            expected_revision: revision,
            observation_digest: observation_digest.clone(),
            observation: TerminalObservation {
                request_id,
                reservation_id: reservation.reservation_id.clone(),
                worker_id: assignment.worker_id.clone(),
                worker_generation: assignment.worker_generation,
                model_digest: record.request.model_digest.clone(),
                payload_digest: record.request.payload_digest.clone(),
                terminal_observed,
                terminal_status: terminal_observed.then_some(record.state),
                output_digest: (record.state == RequestState::Completed)
                    .then(|| observation_digest.clone()),
                consumed_tokens: record.consumed_tokens,
                usage_units: record.usage_units,
            },
        });
        return Ok(events);
    }
    match record.state {
        RequestState::Pending if revision == 1 && record.revision == 1 => {}
        RequestState::Reserved if revision == 2 && record.revision == 2 => {}
        RequestState::Assigned if revision == 3 && record.revision == 3 => {}
        RequestState::Cancelling if revision == 3 && record.revision == 4 => {
            events.push(Event::Cancel {
                request_id,
                expected_revision: revision,
            });
        }
        RequestState::Cancelled
            if record.assignment.is_none() && record.revision == revision + 1 =>
        {
            events.push(Event::Cancel {
                request_id,
                expected_revision: revision,
            });
        }
        _ => return Err(Error::CorruptJournal("legacy checkpoint state")),
    }
    Ok(events)
}
