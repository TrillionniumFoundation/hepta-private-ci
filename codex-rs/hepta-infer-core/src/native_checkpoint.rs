//! Validate one retained native identity without replaying its entire history.
use super::*;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct NativeCheckpoint {
    maximum_in_flight: usize,
    record: NativeRunRecord,
}

#[derive(Serialize)]
struct NativeCheckpointRef<'a> {
    maximum_in_flight: usize,
    record: &'a NativeRunRecord,
}

impl NativeJournal {
    pub(in crate::durable_control) fn required_headroom_bytes(&self) -> Result<u64, Error> {
        self.records.values().try_fold(0_u64, |total, record| {
            total
                .checked_add(record_headroom(record))
                .ok_or(Error::ArithmeticOverflow)
        })
    }

    pub(in crate::durable_control) fn append_checkpoint_lines(
        &self,
        image: &mut Vec<u8>,
    ) -> Result<(), Error> {
        let maximum_in_flight = if self.records.is_empty() {
            if self.maximum_in_flight.is_some() || self.active_reservations != 0 {
                return Err(Error::CorruptJournal("native empty checkpoint counters"));
            }
            return Ok(());
        } else {
            self.maximum_in_flight
                .ok_or(Error::CorruptJournal("native checkpoint limit"))?
        };
        for record in self.records.values() {
            validate_checkpoint_record(record, maximum_in_flight)?;
            let checkpoint = NativeCheckpointRef {
                maximum_in_flight,
                record,
            };
            let json = serde_json::to_string(&checkpoint)
                .map_err(|_| Error::CorruptJournal("native checkpoint encode"))?;
            super::super::push_image_line(image, CHECKPOINT_PREFIX, &json)?;
        }
        Ok(())
    }

    pub(in crate::durable_control) fn replay_checkpoint(
        &mut self,
        json: &str,
    ) -> Result<String, Error> {
        let checkpoint: NativeCheckpoint = serde_json::from_str(json)
            .map_err(|_| Error::CorruptJournal("native checkpoint decode"))?;
        validate_checkpoint_record(&checkpoint.record, checkpoint.maximum_in_flight)?;
        if self
            .maximum_in_flight
            .is_some_and(|value| value != checkpoint.maximum_in_flight)
        {
            return Err(Error::CorruptJournal("native checkpoint limit"));
        }
        let request_id = checkpoint.record.request.request_id.clone();
        if self.records.contains_key(&request_id) {
            return Err(Error::CorruptJournal("duplicate native checkpoint"));
        }
        self.maximum_in_flight = Some(checkpoint.maximum_in_flight);
        if checkpoint.record.state != NativeReservationState::Released {
            self.active_reservations = self
                .active_reservations
                .checked_add(1)
                .ok_or(Error::ArithmeticOverflow)?;
            if self.active_reservations > checkpoint.maximum_in_flight {
                return Err(Error::CapacityExceeded);
            }
        }
        self.records.insert(request_id.clone(), checkpoint.record);
        Ok(request_id)
    }
}

pub(in crate::durable_control) fn record_headroom(record: &NativeRunRecord) -> u64 {
    match record.state {
        NativeReservationState::Reserved => TERMINAL_HEADROOM_BYTES,
        NativeReservationState::Dispatching => TERMINAL_HEADROOM_BYTES - 32 * 1024,
        NativeReservationState::Running | NativeReservationState::Indeterminate => {
            TERMINAL_HEADROOM_BYTES - 64 * 1024
        }
        NativeReservationState::Cancelling => TERMINAL_HEADROOM_BYTES - 96 * 1024,
        NativeReservationState::Released => {
            if record.observation.as_ref().is_some_and(|observation| {
                observation.terminal_observed && observation.observed_output_tokens.is_none()
            }) {
                // Execution is released, but the first real usage observation
                // still owns bounded persistence capacity. Never invent zero.
                USAGE_HEADROOM_BYTES
            } else {
                0
            }
        }
    }
}

fn validate_checkpoint_record(
    record: &NativeRunRecord,
    maximum_in_flight: usize,
) -> Result<(), Error> {
    let events = checkpoint_events(record, maximum_in_flight)?;
    let mut replayed = NativeJournal::default();
    for event in events {
        replayed.apply(event)?;
    }
    let current = replayed
        .records
        .get_mut(&record.request.request_id)
        .ok_or(Error::CorruptJournal("native checkpoint missing"))?;
    if current.revision > record.revision
        || (current.revision < record.revision && record.observation.is_none())
    {
        return Err(Error::CorruptJournal("native checkpoint revision"));
    }
    // Repeated observations can refine usage without changing the state shape.
    // Keep the exact durable revision, but never replay revision-count copies.
    current.revision = record.revision;
    if current != record || replayed.records.len() != 1 {
        return Err(Error::CorruptJournal("native checkpoint state"));
    }
    Ok(())
}

fn checkpoint_events(
    record: &NativeRunRecord,
    maximum_in_flight: usize,
) -> Result<Vec<Event>, Error> {
    let request_id = record.request.request_id.clone();
    let initial = match &record.prepared_input {
        Some(input) => Event::ReservePrepared {
            request: record.request.clone(),
            maximum_in_flight,
            input: input.clone(),
        },
        None => Event::Reserve {
            request: record.request.clone(),
            maximum_in_flight,
        },
    };
    let mut events = vec![initial];
    if let Some(dispatch) = &record.dispatch {
        events.push(Event::Dispatch {
            request_id: request_id.clone(),
            dispatch: dispatch.clone(),
        });
    } else {
        if record.turn_id.is_some()
            || record.dispatch_rejection.is_some()
            || record.observation.is_some()
            || record.cancel_requested
        {
            return Err(Error::CorruptJournal("native checkpoint without dispatch"));
        }
        if let Some(reason) = &record.pre_dispatch_stop {
            events.push(Event::Stop {
                request_id,
                reason: reason.clone(),
            });
        }
        return Ok(events);
    }
    if let Some(reason) = &record.pre_dispatch_stop {
        if record.turn_id.is_some()
            || record.dispatch_rejection.is_some()
            || record.observation.is_some()
            || record.cancel_requested
        {
            return Err(Error::CorruptJournal("native checkpoint stopped dispatch"));
        }
        events.push(Event::AbortBeforeEffect {
            request_id,
            reason: reason.clone(),
        });
        return Ok(events);
    }
    if let Some(rejection) = &record.dispatch_rejection {
        events.push(Event::RejectBeforeStart {
            request_id: request_id.clone(),
            rejection: rejection.clone(),
        });
    }
    if let Some(output) = &record.observation {
        if record.state == NativeReservationState::Cancelling {
            events.push(Event::Observe {
                request_id: request_id.clone(),
                output: output.clone(),
            });
            events.push(Event::Cancel { request_id });
        } else {
            if record.cancel_requested {
                events.push(Event::Cancel {
                    request_id: request_id.clone(),
                });
            }
            events.push(Event::Observe {
                request_id,
                output: output.clone(),
            });
        }
    } else {
        match record.state {
            NativeReservationState::Dispatching => {}
            NativeReservationState::Running => {
                events.push(Event::Started {
                    request_id,
                    turn_id: record
                        .turn_id
                        .clone()
                        .ok_or(Error::CorruptJournal("native checkpoint turn"))?,
                });
            }
            NativeReservationState::Cancelling => {
                if let Some(turn_id) = &record.turn_id {
                    events.push(Event::Started {
                        request_id: request_id.clone(),
                        turn_id: turn_id.clone(),
                    });
                }
                events.push(Event::Cancel { request_id });
            }
            NativeReservationState::Indeterminate
                if record
                    .dispatch_rejection
                    .as_ref()
                    .is_some_and(|rejection| !rejection.retry_safe_before_admission) => {}
            NativeReservationState::Released
                if record
                    .dispatch_rejection
                    .as_ref()
                    .is_some_and(|rejection| rejection.retry_safe_before_admission) => {}
            _ => return Err(Error::CorruptJournal("native checkpoint state")),
        }
    }
    Ok(events)
}
