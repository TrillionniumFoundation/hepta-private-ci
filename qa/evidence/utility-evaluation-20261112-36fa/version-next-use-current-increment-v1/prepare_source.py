#!/usr/bin/env python3
"""Create an isolated next-use current-read increment. No Rust execution."""
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = Path('/tmp/hepta-36fa-provider-registration-protection-candidate-v1/inputs/candidate')
PREFIX = Path('codex-rs/hepta-agentd/src')
FILES = [
    'circuit_learning_read_service.rs',
    'circuit_retained_version_next_use_readback.rs',
    'circuit_evaluated_next_use_read_channel_support_tests.rs',
    'circuit_evaluated_version_next_use_readback_support_tests.rs',
    'circuit_evaluated_version_next_use_readback_tests.rs',
]

def replace_once(text, before, after):
    assert text.count(before) == 1, before[:120]
    return text.replace(before, after, 1)

for name in FILES:
    raw = (BASE / PREFIX / name).read_bytes()
    for directory in ('before', 'after'):
        dest = HERE / directory / PREFIX / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)

path = HERE / 'after' / PREFIX / FILES[0]
text = path.read_text()
text = replace_once(text, 'use std::time::Instant;\n', '')
start = text.index('    /// The same prebound original channel, attenuated to the evaluated S cut.')
stop = text.index('    pub(super) fn response(', start)
text = text[:start] + '''    /// One readonly response for the original Version's five-cut C reader.
    /// The concrete Version serving lane brackets this with its actual full
    /// predecessor/publication observations under the same Version state lock.
    pub(crate) fn original_evaluated_next_use_response(
        &self,
        bytes: &[u8],
        request_id: u64,
    ) -> Result<Vec<u8>, Error> {
        self.require_original_evaluated_next_use_profile()?;
        self.response(bytes, request_id)
    }

    /// The distinct readiness response still performs only the original C
    /// observation. Missing/Pending neither executes C nor authorizes work.
    pub(crate) fn original_evaluated_next_use_readiness_response(
        &self,
        bytes: &[u8],
        request_id: u64,
    ) -> Result<Vec<u8>, Error> {
        self.require_original_evaluated_next_use_profile()?;
        self.readiness_response(bytes, request_id)
    }

    fn require_original_evaluated_next_use_profile(&self) -> Result<(), Error> {
        if !matches!(&self.context, ReadProfile::Evaluated(_))
            || self.context.mode()? != wire::Mode::NextUse
        {
            return Err(Error::Binding("evaluated Version NextUse-only read purpose"));
        }
        Ok(())
    }

''' + text[stop:]
path.write_text(text)

path = HERE / 'after' / PREFIX / FILES[1]
text = path.read_text()
text = replace_once(text,
    'use codex_hepta_contracts::HostAuthorityPeerChannel;\n',
    'use codex_hepta_contracts::HostAuthorityPeerChannel;\nuse codex_hepta_contracts::HostIssuerTransportError;\n')
text = replace_once(text, '''enum NextUseReadPurpose {
    Readback,
    CompletionReadiness,
}''', '''enum NextUseReadPurpose {
    Readback,
    CompletionReadiness,
    #[cfg(test)]
    CompletionReadinessDeadlineProbe {
        end: Instant,
        cross_end_after_original_read: bool,
        response_observed: Arc<std::sync::atomic::AtomicBool>,
    },
}''')
start = text.index('            let reader = self.build_original_evaluated_next_use_reader(selection)?;')
stop = text.index('        })\n        .await', start)
text = text[:start] + '''            let reader = self.build_original_evaluated_next_use_reader(selection.clone())?;
            self.require_lifetime()?;
            channel.check_peer_lifetime()?;
            self.serve_original_evaluated_next_use_loop(
                &selection, &reader, &mut channel, &purpose,
            )
''' + text[stop:]
marker = '    fn build_original_evaluated_next_use_reader(\n'
assert text.count(marker) == 1
new = '''    fn serve_original_evaluated_next_use_loop(
        &self,
        selection: &OriginalCircuitEvaluatedSelectionReceiptV1,
        reader: &OriginalNextUseReader,
        channel: &mut HostAuthorityPeerChannel,
        purpose: &NextUseReadPurpose,
    ) -> Result<u64, Error> {
        let end = match purpose {
            #[cfg(test)]
            NextUseReadPurpose::CompletionReadinessDeadlineProbe { end, .. } => (*end).min(self.end),
            _ => self.end,
        };
        for request_id in 1..=128 {
            let mut failure = None;
            let exchanged = channel.exchange(|bytes| {
                let original = (|| {
                    if Instant::now() >= end {
                        return Err(Error::Unavailable);
                    }
                    let bytes = self.original_evaluated_next_use_response(
                        selection, reader, purpose, bytes, request_id,
                    )?;
                    if Instant::now() >= end {
                        return Err(Error::Unavailable);
                    }
                    Ok(bytes)
                })();
                original.map_err(|error| {
                    failure = Some(error);
                    HostIssuerTransportError::InvalidRequest
                })
            });
            match exchanged {
                Ok(true) => {}
                Ok(false) => return Ok(request_id - 1),
                Err(error) => return Err(failure.unwrap_or(Error::Transport(error))),
            }
        }
        Err(Error::Unavailable)
    }

    fn original_evaluated_next_use_response(
        &self,
        selection: &OriginalCircuitEvaluatedSelectionReceiptV1,
        reader: &OriginalNextUseReader,
        purpose: &NextUseReadPurpose,
        bytes: &[u8],
        request_id: u64,
    ) -> Result<Vec<u8>, Error> {
        self.require_lifetime()?;
        if self.purpose != RetainedVersionPurposeV1::EvaluatedNoUpdate
            || self.original_final_use_outcome() != RetainedVersionFinalUseOutcomeV1::Published
        {
            return Err(Error::ReadbackRequired);
        }
        // This concrete owner retains the same T/E clients and same C. The
        // lock spans both full live reads and the actual C response. No
        // caller-supplied checker, cached freshness token or retry is used.
        let state = self.state.try_lock().map_err(|_| Error::Busy)?;
        let before = self.read_original(&state)?;
        if before.publication().is_none() {
            return Err(Error::ReadbackRequired);
        }
        let cut = state.cut.as_ref().ok_or(Error::Unavailable)?;
        let evaluated = cut.evaluated.as_ref().ok_or(Error::ReadbackRequired)?;
        let original_context = selection.original_context();
        if original_context.snapshot() != evaluated.snapshot()
            || original_context.receipt_context_binding() != evaluated.receipt_context_binding()
        {
            return Err(Error::Binding("same original Version T/E and Selection cut"));
        }
        selection.original_receipt_predecessors(super::super::now()?)
            .map_err(|error| Error::Owner(crate::AgentdError::Invalid(error.to_string())))?;
        let original = match purpose {
            NextUseReadPurpose::Readback =>
                OriginalCircuitLearningReadOwnerV1::original_evaluated_next_use_response(
                    reader, bytes, request_id,
                ),
            NextUseReadPurpose::CompletionReadiness =>
                OriginalCircuitLearningReadOwnerV1::original_evaluated_next_use_readiness_response(
                    reader, bytes, request_id,
                ),
            #[cfg(test)]
            NextUseReadPurpose::CompletionReadinessDeadlineProbe { .. } =>
                OriginalCircuitLearningReadOwnerV1::original_evaluated_next_use_readiness_response(
                    reader, bytes, request_id,
                ),
        }.map_err(|error| Error::Owner(crate::AgentdError::Invalid(error.to_string())))?;
        #[cfg(test)]
        if let NextUseReadPurpose::CompletionReadinessDeadlineProbe {
            end, cross_end_after_original_read, response_observed,
        } = purpose {
            reader.fixture_observe_original_next_use_response(
                (*end).min(self.end), *cross_end_after_original_read, Arc::clone(response_observed),
            );
        }
        let after = self.read_original(&state)?;
        if before != after || after.publication().is_none() {
            return Err(Error::CommitUncertain);
        }
        cut.require_fresh(super::super::now()?, PublicationAccess::Readback)?;
        selection.original_receipt_predecessors(super::super::now()?)
            .map_err(|error| Error::Owner(crate::AgentdError::Invalid(error.to_string())))?;
        self.require_lifetime()?;
        if self.original_final_use_outcome() != RetainedVersionFinalUseOutcomeV1::Published {
            return Err(Error::ReadbackRequired);
        }
        Ok(original)
    }

'''
text = text.replace(marker, new + marker, 1)
path.write_text(text)

path = HERE / 'after' / PREFIX / FILES[2]
path.write_text('''//! Observe only after the Version handler produced the actual C response.
//! Yielding narrows the test deadline within the original 500 ms envelope;
//! no response, owner, clock value or successful freshness result is supplied.

use super::*;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Instant;

impl<C: AnchorWitnessStore, S: AnchorWitnessStore> OriginalCircuitLearningReadOwnerV1<C, S> {
    pub(crate) fn fixture_observe_original_next_use_response(
        &self,
        end: Instant,
        cross_end_after_original_read: bool,
        response_observed: Arc<AtomicBool>,
    ) {
        response_observed.store(true, Ordering::Release);
        if cross_end_after_original_read {
            while Instant::now() < end {
                std::thread::yield_now();
            }
        }
    }
}
''')

path = HERE / 'after' / PREFIX / FILES[3]
text = path.read_text()
text = replace_once(text,
    'let reader = self.build_original_evaluated_next_use_reader(selection)?;',
    'let reader = self.build_original_evaluated_next_use_reader(selection.clone())?;')
text = replace_once(text, '''            reader.fixture_evaluated_next_use_deadline_channel(
                &mut channel, end, !already_expired, response_observed,
            ).map_err(|error| Error::Owner(crate::AgentdError::Invalid(error.to_string())))''', '''            self.serve_original_evaluated_next_use_loop(
                &selection, &reader, &mut channel,
                &NextUseReadPurpose::CompletionReadinessDeadlineProbe {
                    end, cross_end_after_original_read: !already_expired, response_observed,
                },
            )''')
path.write_text(text)

path = HERE / 'after' / PREFIX / FILES[4]
text = path.read_text()
text += '''
async fn b_withdrawal_after_admission_case(readiness: bool) -> anyhow::Result<()> {
    let mut case = Box::pin(NextUseCase::ready()).await?;
    let result: anyhow::Result<()> = async {
        if readiness {
            case.start_readiness()?;
            anyhow::ensure!(case.readiness.as_ref().context("original readiness lane")?
                .read_current().await?.is_none(), "actual first response admits pending C");
        } else {
            let publication = execute(case.task()?, 1).await?;
            let actual = read_receipt(case.task()?, &case.fixture()?.definition, &publication)?;
            anyhow::ensure!(actual.bundle_digest == case.fixture()?.bundle.digest()?,
                "the original C completed with the retained baseline");
            case.start_readback()?;
            let first = case.live.as_ref().context("original next-use lane")?
                .read_current().await?;
            anyhow::ensure!(matches!(first.observation(),
                LearningIterationObservationV1::RetainedModelNextUse { .. }),
                "actual completed response proves this channel was already admitted");
        }
        let revision = case.task()?.cell.snapshot(&case.fixture()?.source_c.scope)?.revision;
        case.fixture.as_deref_mut().context("original B owner")?.host.retention_b.withdraw_target()?;
        let before = case.original_bytes()?;
        let (refused, fenced) = if readiness {
            let client = case.readiness.as_ref().context("same admitted readiness lane")?;
            (client.read_current().await.map(|_| ()), client.read_current().await.map(|_| ()))
        } else {
            let client = case.live.as_ref().context("same admitted next-use lane")?;
            (client.read_current().await.map(|_| ()), client.read_current().await.map(|_| ()))
        };
        drop(case.readiness.take());
        drop(case.live.take());
        let served = case.servers.pop().context("same original serving lane")?.await?;
        anyhow::ensure!(refused.is_err(), "later B withdrawal cannot reuse a successful admission");
        anyhow::ensure!(matches!(fenced, Err(ReadError::Unavailable)),
            "the rejected original channel remains consumed without retry");
        anyhow::ensure!(matches!(served,
            Err(VersionError::Publication(crate::OriginalCircuitRetainedPublicationErrorV1::Evaluation(
                crate::OriginalCellEvaluationCommandErrorV1::CommitUncertain
            )))
        ), "the concrete Version preserves the actual original B/E current-read failure");
        anyhow::ensure!(case.original_bytes()? == before,
            "failed later reads cannot rewrite evidence or repair B");
        anyhow::ensure!(case.task()?.cell.snapshot(&case.fixture()?.source_c.scope)?.revision == revision,
            "readonly failure neither starts C nor dispatches it again");
        Ok(())
    }.await;
    finish_case(result, case).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn version_owned_readiness_rechecks_actual_b_after_channel_admission() -> anyhow::Result<()> {
    Box::pin(b_withdrawal_after_admission_case(true)).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn version_owned_next_use_rechecks_actual_b_after_channel_admission() -> anyhow::Result<()> {
    Box::pin(b_withdrawal_after_admission_case(false)).await
}
'''
path.write_text(text)
print('Prepared five isolated postimages; no formatter, compiler or test invoked.')
