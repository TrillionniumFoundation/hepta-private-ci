//! Typed local feature operations use inference.control's existing journal and
//! exclusive writer. A dispatch fence is durable before physical execution;
//! unresolved fences never authorize a repeat after a crash.
use std::collections::BTreeMap;

use serde::Deserialize;
use serde::Serialize;

use crate::NeuronFeatureReceiptV1;
use crate::NeuronFeatureRequestV1;
use crate::NeuronFeatureTerminalStatusV1;
use crate::neuron_feature_request_digest_v1;
use crate::verify_neuron_feature_receipt_v1;

use super::DurableInferenceControl;
use super::Error;

#[path = "feature_archive_store.rs"]
pub(super) mod archive_store;
#[path = "feature_control_codec.rs"]
mod codec;
pub(super) const JOURNAL_PREFIX: &str = "feature-v1|";

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FeatureOperationStateV1 {
    Reserved,
    Dispatched,
    Observed(Box<NeuronFeatureReceiptV1>),
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FeatureOperationRecordV1 {
    pub request: NeuronFeatureRequestV1,
    pub state: FeatureOperationStateV1,
}

/// Issued only by the first committed Reserved -> Dispatched transition. It is
/// consumed by the physical host; neither replay nor request data constructs it.
pub struct FeatureDispatchPermitV1 {
    request: NeuronFeatureRequestV1,
}
impl FeatureDispatchPermitV1 {
    pub fn into_request(self) -> NeuronFeatureRequestV1 {
        self.request
    }
}

#[derive(Debug, Default)]
pub(super) struct FeatureJournal {
    pub(super) records: BTreeMap<String, FeatureOperationRecordV1>,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(tag = "event", rename_all = "snake_case", deny_unknown_fields)]
enum Event {
    Reserve {
        request: codec::Request,
    },
    Dispatch {
        request_id: String,
        request_digest: String,
    },
    Observe {
        request_id: String,
        receipt: codec::Receipt,
    },
}

impl DurableInferenceControl {
    pub fn reserve_feature(
        &mut self,
        request: NeuronFeatureRequestV1,
    ) -> Result<FeatureOperationRecordV1, Error> {
        neuron_feature_request_digest_v1(&request)
            .map_err(|_| Error::InvalidDigest("typed feature request"))?;
        let id = request.request_id.as_str();
        if let Some(current) = self.features.records.get(id) {
            return if current.request == request {
                Ok(current.clone())
            } else {
                Err(Error::Conflict)
            };
        }
        if let Some(current) = archive_store::lookup(&self.path, id)? {
            return if current.request == request {
                Ok(current)
            } else {
                Err(Error::Conflict)
            };
        }
        if self.records.contains_key(id)
            || self.native.records.contains_key(id)
            || super::archive_store::lookup(&self.path, id)?.is_some()
        {
            return Err(Error::Conflict);
        }
        if self.records.len() + self.native.records.len() + self.features.records.len()
            >= self.capacity
            || self.journal_bytes
                > super::MAX_JOURNAL_BYTES - 2 * super::MAX_JOURNAL_LINE_BYTES as u64
        {
            return Err(Error::CapacityExceeded);
        }
        let event = Event::Reserve {
            request: (&request).into(),
        };
        self.commit_feature(event)?;
        self.feature_record(&request)?.ok_or(Error::RequestNotFound)
    }

    pub fn dispatch_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<FeatureDispatchPermitV1, Error> {
        let current = self
            .feature_record(request)?
            .ok_or(Error::RequestNotFound)?;
        if current.state != FeatureOperationStateV1::Reserved {
            return Err(Error::InvalidTransition);
        }
        self.commit_feature(Event::Dispatch {
            request_id: request.request_id.to_string(),
            request_digest: neuron_feature_request_digest_v1(request)
                .map_err(|_| Error::InvalidDigest("typed feature dispatch"))?
                .to_string(),
        })?;
        Ok(FeatureDispatchPermitV1 {
            request: request.clone(),
        })
    }

    pub fn observe_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
        receipt: &NeuronFeatureReceiptV1,
    ) -> Result<(), Error> {
        verify_neuron_feature_receipt_v1(request, receipt)
            .map_err(|_| Error::InvalidDigest("typed feature observation"))?;
        if receipt.status == NeuronFeatureTerminalStatusV1::Indeterminate {
            return Err(Error::TerminalObservationMissing);
        }
        let current = self
            .feature_record(request)?
            .ok_or(Error::RequestNotFound)?;
        if let FeatureOperationStateV1::Observed(previous) = current.state {
            return if previous.as_ref() == receipt {
                Ok(())
            } else {
                Err(Error::Conflict)
            };
        }
        self.commit_feature(Event::Observe {
            request_id: request.request_id.to_string(),
            receipt: receipt.into(),
        })
    }

    /// Original operation truth only. Absence is not a no-dispatch proof.
    pub fn feature_record(
        &self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<Option<FeatureOperationRecordV1>, Error> {
        if self.poisoned {
            return Err(Error::WriterUnavailable);
        }
        neuron_feature_request_digest_v1(request)
            .map_err(|_| Error::InvalidDigest("typed feature query"))?;
        let value = match self.features.records.get(request.request_id.as_str()) {
            Some(value) => Some(value.clone()),
            None => archive_store::lookup(&self.path, request.request_id.as_str())?,
        };
        match value {
            Some(value) if value.request != *request => Err(Error::Conflict),
            value => Ok(value),
        }
    }

    fn commit_feature(&mut self, event: Event) -> Result<(), Error> {
        let encoded = serde_json::to_string(&event)
            .map_err(|_| Error::CorruptJournal("typed feature encode"))?;
        let next = self.features.prepare(event)?;
        self.append(&format!("{JOURNAL_PREFIX}{encoded}\n"))?;
        self.features
            .records
            .insert(next.request.request_id.to_string(), next);
        Ok(())
    }
}

impl FeatureJournal {
    pub(super) fn replay(&mut self, json: &str) -> Result<(), Error> {
        self.apply(
            serde_json::from_str(json)
                .map_err(|_| Error::CorruptJournal("typed feature decode"))?,
        )
    }
    fn apply(&mut self, event: Event) -> Result<(), Error> {
        let next = self.prepare(event)?;
        self.records
            .insert(next.request.request_id.to_string(), next);
        Ok(())
    }
    // Copy only the affected bounded record. Journal history is never cloned
    // on each feature dispatch or observation.
    fn prepare(&self, event: Event) -> Result<FeatureOperationRecordV1, Error> {
        match event {
            Event::Reserve { request } => {
                let request = request.decode()?;
                let id = request.request_id.to_string();
                if self.records.contains_key(&id) {
                    return Err(Error::Conflict);
                }
                Ok(FeatureOperationRecordV1 {
                    request,
                    state: FeatureOperationStateV1::Reserved,
                })
            }
            Event::Dispatch {
                request_id,
                request_digest,
            } => {
                let mut record = self
                    .records
                    .get(&request_id)
                    .ok_or(Error::RequestNotFound)?
                    .clone();
                if record.state != FeatureOperationStateV1::Reserved
                    || neuron_feature_request_digest_v1(&record.request)
                        .map_err(|_| Error::CorruptJournal("typed feature request"))?
                        .to_string()
                        != request_digest
                {
                    return Err(Error::InvalidTransition);
                }
                record.state = FeatureOperationStateV1::Dispatched;
                Ok(record)
            }
            Event::Observe {
                request_id,
                receipt,
            } => {
                let mut record = self
                    .records
                    .get(&request_id)
                    .ok_or(Error::RequestNotFound)?
                    .clone();
                if record.state != FeatureOperationStateV1::Dispatched {
                    return Err(Error::InvalidTransition);
                }
                let receipt = receipt.decode(&record.request)?;
                if receipt.status == NeuronFeatureTerminalStatusV1::Indeterminate {
                    return Err(Error::TerminalObservationMissing);
                }
                record.state = FeatureOperationStateV1::Observed(Box::new(receipt));
                Ok(record)
            }
        }
    }
}

#[cfg(test)]
#[path = "feature_control_tests.rs"]
mod tests;
