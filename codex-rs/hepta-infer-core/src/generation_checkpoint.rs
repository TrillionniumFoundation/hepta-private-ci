//! Checkpoint the existing generation state without reconstructing a live token.
use super::*;

impl GenerationJournal {
    pub(in crate::durable_control) fn append_checkpoint_lines(
        &self,
        image: &mut Vec<u8>,
    ) -> Result<(), Error> {
        for record in self.records.values() {
            validate_checkpoint(record)?;
            let json = serde_json::to_string(record)
                .map_err(|_| Error::CorruptJournal("generation checkpoint encode"))?;
            super::super::push_image_line(image, CHECKPOINT_PREFIX, &json)?;
        }
        Ok(())
    }

    pub(in crate::durable_control) fn replay_checkpoint(
        &mut self,
        json: &str,
    ) -> Result<String, Error> {
        let record: GenerationRecordV1 = serde_json::from_str(json)
            .map_err(|_| Error::CorruptJournal("generation checkpoint decode"))?;
        validate_checkpoint(&record)?;
        let request_id = record.binding.request_id.clone();
        if self.records.insert(request_id.clone(), record).is_some() {
            return Err(Error::CorruptJournal("duplicate generation checkpoint"));
        }
        Ok(request_id)
    }
}

fn validate_checkpoint(record: &GenerationRecordV1) -> Result<(), Error> {
    let id = record.binding.request_id.clone();
    let mut events = vec![Event::Admit {
        binding: record.binding.clone(),
        observed_at_micros: record.admitted_at_micros,
    }];
    if let Some(observed_at_micros) = record.dispatched_at_micros {
        events.push(Event::Dispatch {
            request_id: id.clone(),
            observed_at_micros,
        });
    }
    if record.cancel_requested {
        events.push(Event::Cancel {
            request_id: id.clone(),
        });
    }
    if let Some(result) = &record.result {
        events.push(if record.aborted_before_dispatch {
            Event::AbortBeforeDispatch {
                request_id: id.clone(),
                result: result.clone(),
            }
        } else {
            Event::Result {
                request_id: id.clone(),
                result: result.clone(),
            }
        });
    }
    let mut replay = GenerationJournal::default();
    for event in events {
        let next = replay.next_record(event)?;
        replay.records.insert(id.clone(), next);
    }
    if replay.records.get(&id) != Some(record) || replay.records.len() != 1 {
        return Err(Error::CorruptJournal("generation checkpoint state"));
    }
    Ok(())
}
