//! Original file-owner scope checks with explicit test-only issuer custody.
//! These are mechanism tests, not production Root or ordinary-A qualification.

use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_neuron::CellGenerationCurrentV1;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use pretty_assertions::assert_eq;

use super::OriginalVersion;
use crate::AgentdError;
use crate::neuron_generation_current::NeuronGenerationUpdatePublicationV1;
use crate::neuron_generation_current::test_support::Fixture;
use crate::neuron_generation_current::test_support::Journal;
use crate::neuron_generation_current::test_support::RECORDS;
use crate::neuron_generation_current::test_support::TestClock;
use crate::neuron_generation_current::test_support::config;
use crate::neuron_generation_update_live::AgentdGenerationUpdateAuthoritiesV1;
use crate::neuron_generation_update_live::LiveGenerationCurrent;

// The real Live guard still checks Control, Artifact and FinalUse. This test
// fault can only make its original time read fail; it cannot supply a Current.
struct PostcheckClock {
    original: Arc<TestClock>,
    remaining: AtomicUsize,
}

impl AuthorityClock for PostcheckClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        let remaining = self.remaining.load(Ordering::SeqCst);
        if remaining == 0 {
            return Err(AuthorityTrustError::Unavailable);
        }
        if remaining != usize::MAX {
            self.remaining.fetch_sub(1, Ordering::SeqCst);
        }
        self.original.now_unix_ms()
    }
}

struct Case {
    fixture: Fixture,
    journal: Journal,
    binding: CellGenerationOwnerBindingV1,
    clock: Arc<PostcheckClock>,
}

impl Case {
    fn new() -> anyhow::Result<Self> {
        let fixture = Fixture::new_initial(config()?, "initial-current-scope")?;
        let target = fixture.target_create()?;
        let journal = CellGenerationJournalV2::open_guarded(
            target.file,
            target.witness,
            target.config,
            target.max_records,
            fixture.current.clone(),
        )?;
        let prepared = fixture.initial_prepared("initial-current-scope")?;
        let expected = prepared.final_use_binding().clone();
        let mut selected = fixture.selection()?;
        let signed = fixture.sign(&expected)?;
        let publication = {
            let mut artifacts = fixture
                .artifacts
                .lock()
                .map_err(|_| anyhow::anyhow!("original Artifact lock"))?;
            fixture.current.publish_initial(
                &prepared,
                &journal,
                &mut selected,
                NeuronGenerationUpdatePublicationV1 {
                    artifacts: &mut artifacts,
                    authority: &fixture.authority,
                    signed: &signed,
                    clock: fixture.clock.as_ref(),
                },
            )?
        };
        let clock = Arc::new(PostcheckClock {
            original: fixture.clock.clone(),
            remaining: AtomicUsize::new(usize::MAX),
        });
        let authorities = AgentdGenerationUpdateAuthoritiesV1::new(
            fixture.artifacts.clone(),
            fixture.authority.clone(),
            clock.clone(),
        )?;
        let guard: Arc<dyn CellGenerationCurrentV1> = LiveGenerationCurrent::new_initial(
            fixture.current.clone(),
            authorities,
            selected,
            publication,
            expected,
        )?;
        let journal = journal.rebind_current(guard)?;
        let binding = CellGenerationOwnerBindingV1::new(&fixture.target_config, RECORDS)?;
        let case = Self {
            fixture,
            journal,
            binding,
            clock,
        };
        OriginalVersion::require_original_task(&case.journal, &case.binding, true)?;
        Ok(case)
    }

    fn different_binding(&self) -> anyhow::Result<CellGenerationOwnerBindingV1> {
        let mut changed = self.fixture.target_config.clone();
        changed.task_digest[0] ^= 1;
        Ok(CellGenerationOwnerBindingV1::new(&changed, RECORDS)?)
    }

    fn journal_and_current_bytes(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        [
            "target-journal",
            "target-witness",
            "current.json",
            "final-use-frontier.json",
        ]
        .into_iter()
        .map(|name| self.fixture.bytes(name))
        .collect()
    }
}

#[test]
fn original_initial_task_scope_requires_its_actual_binding() -> anyhow::Result<()> {
    let case = Case::new()?;
    let before = case.journal_and_current_bytes()?;
    let different = case.different_binding()?;
    assert_ne!(different, case.binding);
    let error =
        OriginalVersion::require_original_task(&case.journal, &different, true).unwrap_err();
    assert!(matches!(
        error,
        AgentdError::Invalid(message)
            if message == "ordinary published Feature task binding differs"
    ));
    assert_eq!(case.journal_and_current_bytes()?, before);
    OriginalVersion::require_original_task(&case.journal, &case.binding, true)?;
    assert_eq!(case.journal_and_current_bytes()?, before);
    Ok(())
}

#[test]
fn original_initial_task_scope_refuses_actual_drain_and_artifact_withdrawal() -> anyhow::Result<()>
{
    let mut case = Case::new()?;
    case.journal.drain()?;
    assert!(case.journal.is_drained()?);
    let drained = case.journal_and_current_bytes()?;
    let error =
        OriginalVersion::require_original_task(&case.journal, &case.binding, true).unwrap_err();
    assert!(matches!(
        error,
        AgentdError::Invalid(message)
            if message == "ordinary published Feature task is drained"
    ));
    OriginalVersion::require_original_task(&case.journal, &case.binding, false)?;
    assert_eq!(case.journal_and_current_bytes()?, drained);
    case.fixture.withdraw()?;
    let error =
        OriginalVersion::require_original_task(&case.journal, &case.binding, false).unwrap_err();
    assert!(matches!(
        error,
        AgentdError::Invalid(message) if message == "Unavailable"
    ));
    assert_eq!(case.journal_and_current_bytes()?, drained);
    Ok(())
}

#[test]
fn original_initial_task_scope_checks_live_postcondition_after_local_error() -> anyhow::Result<()> {
    let case = Case::new()?;
    let different = case.different_binding()?;
    let before = case.journal_and_current_bytes()?;
    // Establish the exact local-error branch with the original guard healthy.
    let local =
        OriginalVersion::require_original_task(&case.journal, &different, true).unwrap_err();
    assert!(matches!(
        local,
        AgentdError::Invalid(message)
            if message == "ordinary published Feature task binding differs"
    ));
    // The first real Live check still reads its original clock successfully.
    // Only the later postcheck loses that clock. Returning the earlier local
    // error would show that the actual postcheck was incorrectly skipped.
    assert_eq!(case.clock.remaining.swap(1, Ordering::SeqCst), usize::MAX);
    let error =
        OriginalVersion::require_original_task(&case.journal, &different, true).unwrap_err();
    assert!(matches!(
        error,
        AgentdError::Invalid(message) if message == "Unavailable"
    ));
    assert_eq!(case.clock.remaining.load(Ordering::SeqCst), 0);
    assert_eq!(case.journal_and_current_bytes()?, before);
    Ok(())
}
