//! Controlled compiler adapter; task lifetime, not a second writer, is exercised.
use super::*;
use codex_hepta_agent_components::infer_core::SelfIterationModelRequestV1;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use tokio::sync::Notify;
struct Model;
impl SelfIterationModelPortV1 for Model {
    async fn assess(
        &mut self,
        _: SelfIterationModelRequestV1,
    ) -> Result<
        SelfIterationModelAssessmentV1,
        codex_hepta_agent_components::infer_core::SelfIterationModelErrorV1,
    > {
        panic!("fixture bypasses model effects")
    }
}
struct Assembler {
    calls: Arc<AtomicUsize>,
    started: Arc<Notify>,
    release: Arc<Notify>,
}
impl AgentdSelfIterationCandidateAssemblerV1 for Assembler {
    fn describe(&self, _: &IterationEnvelopeV1) -> Result<String, AgentdError> {
        Ok("actual bounded fixture".into())
    }
    async fn assemble(
        &mut self,
        _: IterationEnvelopeV1,
        _: &SelfIterationModelAssessmentV1,
    ) -> Result<AgentdSelfIterationCandidateV1, AgentdError> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        self.started.notify_one();
        self.release.notified().await;
        Err(invalid("actual fixture assembly terminal"))
    }
}
struct Owners;
impl AgentdSelfIterationIndependentOwnersV1 for Owners {
    async fn evaluate(
        &mut self,
        _: &AgentdSelfIterationCandidateV1,
        _: &AgentdSelfIterationRecordV1,
        _: &SelfIterationModelAssessmentV1,
    ) -> Result<AgentdSignedEvaluationV1, AgentdError> {
        panic!("no candidate")
    }
    async fn select(
        &mut self,
        _: &AgentdSelfIterationRecordV1,
        _: &SelfIterationModelAssessmentV1,
    ) -> Result<SignedLearningEvidenceV1, AgentdError> {
        panic!("no candidate")
    }
    async fn observe(
        &mut self,
        _: &AgentdSelfIterationRecordV1,
        _: &SelfIterationModelAssessmentV1,
    ) -> Result<(AgentdSelfIterationCanaryVerdictV1, SignedLearningEvidenceV1), AgentdError> {
        panic!("no candidate")
    }
}
#[tokio::test]
async fn cancelled_assembly_caller_retains_one_actual_task_and_its_terminal() {
    let calls = Arc::new(AtomicUsize::new(0));
    let started = Arc::new(Notify::new());
    let release = Arc::new(Notify::new());
    let assembler = Assembler {
        calls: Arc::clone(&calls),
        started: Arc::clone(&started),
        release: Arc::clone(&release),
    };
    let runtime = AgentdSelfIterationHandleV1::closed_test_handle();
    let mut cycle = AgentdSelfIterationModelCycleV1::new(Model, assembler, Owners, runtime);
    let digest = Digest32::of_bytes(b"fixture");
    let envelope = IterationEnvelopeV1 {
        envelope_id: StableId::new("fixture").expect("id"),
        base_commit: digest,
        base_tree: digest,
        objective_digest: digest,
        grammar_digest: digest,
        maximum_files: 1,
        maximum_diff_bytes: 16,
        maximum_candidates: 1,
        maximum_parallel_sandboxes: 1,
        expiry_unix_seconds: 100,
    };
    let proposal = SelfIterationModelAssessmentV1 {
        request_id: StableId::new("fixture.g").expect("id"),
        role: SelfIterationModelRoleV1::Generator,
        envelope_digest: envelope_digest(&envelope),
        candidate_digest: None,
        model_output: "fixture".into(),
        native_run_digest: digest,
        authority: codex_hepta_agent_components::types::AuthorityPosture::DENY_ALL,
    };
    {
        let run = cycle.construct_candidate(envelope.clone(), proposal.clone());
        tokio::pin!(run);
        tokio::select! {_=started.notified()=>{},result=&mut run=>panic!("must remain owned: {}",result.is_ok())}
    }
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert!(cycle.assembler.is_none());
    assert!(cycle.pending_candidate.is_some());
    release.notify_one();
    let result = cycle.construct_candidate(envelope, proposal).await;
    assert!(
        matches!(result,Err(AgentdError::Invalid(message)) if message=="actual fixture assembly terminal")
    );
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert!(cycle.assembler.is_some());
    assert!(cycle.pending_candidate.is_none());
}
