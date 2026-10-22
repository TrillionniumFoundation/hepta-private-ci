use super::*;

const MAX_BYTES: usize = 64 * 1024;

struct Encoder {
    bytes: Vec<u8>,
    artifacts: usize,
}

impl Encoder {
    fn new(domain: &[u8]) -> Self {
        Self {
            bytes: domain.to_vec(),
            artifacts: 0,
        }
    }

    fn raw(&mut self, bytes: &[u8]) -> Result<(), ProductionLedgerError> {
        if bytes.len() > MAX_BYTES.saturating_sub(self.bytes.len()) {
            return Err(invalid("procedure canonical evidence exceeds 64 KiB"));
        }
        self.bytes.extend_from_slice(bytes);
        Ok(())
    }

    fn number(&mut self, value: u64) -> Result<(), ProductionLedgerError> {
        self.raw(&value.to_be_bytes())
    }

    fn text(&mut self, value: &str) -> Result<(), ProductionLedgerError> {
        if value.is_empty() || value.len() > 1024 {
            return Err(invalid("procedure text must contain 1..=1024 UTF-8 bytes"));
        }
        self.number(value.len() as u64)?;
        self.raw(value.as_bytes())
    }

    fn id(&mut self, id: &StableId) -> Result<(), ProductionLedgerError> {
        self.text(id.as_str())
    }

    fn digest(&mut self, digest: Digest32) -> Result<(), ProductionLedgerError> {
        if digest.is_zero() {
            return Err(invalid("procedure digest must be nonzero"));
        }
        self.raw(digest.as_array())
    }

    fn count(&mut self, count: usize, maximum: usize) -> Result<(), ProductionLedgerError> {
        if count > maximum {
            return Err(invalid("procedure collection exceeds bound"));
        }
        self.number(count as u64)
    }

    fn ids(&mut self, ids: &[StableId]) -> Result<(), ProductionLedgerError> {
        self.count(ids.len(), 8)?;
        let mut seen = BTreeSet::new();
        for id in ids {
            if !seen.insert(id) {
                return Err(invalid("duplicate procedure artifact identity"));
            }
            self.id(id)?;
        }
        Ok(())
    }

    fn arguments(
        &mut self,
        arguments: &[ProcedureArgumentV1],
    ) -> Result<(), ProductionLedgerError> {
        self.count(arguments.len(), 16)?;
        let mut previous = None;
        for argument in arguments {
            if previous.is_some_and(|name| name >= &argument.name) {
                return Err(invalid("procedure arguments must have unique sorted names"));
            }
            self.id(&argument.name)?;
            self.text(&argument.value)?;
            previous = Some(&argument.name);
        }
        Ok(())
    }

    fn artifact(&mut self, artifact: &ProcedureArtifactV1) -> Result<(), ProductionLedgerError> {
        self.artifacts += 1;
        if self.artifacts > 64 {
            return Err(invalid("procedure evidence exceeds 64 artifact references"));
        }
        self.id(&artifact.id)?;
        self.digest(artifact.content_digest)?;
        self.number(artifact.byte_length)
    }

    fn artifacts(
        &mut self,
        artifacts: &[ProcedureArtifactV1],
    ) -> Result<(), ProductionLedgerError> {
        self.count(artifacts.len(), 8)?;
        for artifact in artifacts {
            self.artifact(artifact)?;
        }
        Ok(())
    }

    fn checks(&mut self, checks: &[ProcedureCheckV1]) -> Result<(), ProductionLedgerError> {
        self.count(checks.len(), 32)?;
        let mut seen = BTreeSet::new();
        for check in checks {
            if !seen.insert(&check.id) {
                return Err(invalid("duplicate procedure predicate identity"));
            }
            self.id(&check.id)?;
            self.text(&check.predicate)?;
            self.arguments(&check.arguments)?;
        }
        Ok(())
    }
}

fn encode_contract(
    evidence: &ProcedureExecutionEvidenceV1,
) -> Result<Encoder, ProductionLedgerError> {
    if evidence.steps.is_empty()
        || evidence.preconditions.is_empty()
        || evidence.success_criteria.is_empty()
    {
        return Err(invalid(
            "procedure requires steps, preconditions and success criteria",
        ));
    }
    let mut encoder = Encoder::new(b"hepta.procedure.contract.v1");
    encoder.id(&evidence.procedure_id)?;
    encoder.id(&evidence.profile_id)?;
    encoder.artifact(&evidence.environment.runtime)?;
    encoder.artifact(&evidence.environment.executable)?;
    match &evidence.environment.model {
        ProcedureModelV1::NoModel => encoder.raw(&[0])?,
        ProcedureModelV1::Artifact(artifact) => {
            encoder.raw(&[1])?;
            encoder.artifact(artifact)?;
        }
    }
    encoder.arguments(&evidence.environment.context)?;
    encoder.artifact(&evidence.checker)?;
    encoder.count(evidence.steps.len(), 32)?;
    let mut seen = BTreeSet::new();
    for step in &evidence.steps {
        if !seen.insert(&step.id) {
            return Err(invalid("duplicate procedure step identity"));
        }
        encoder.id(&step.id)?;
        encoder.id(&step.operation)?;
        encoder.arguments(&step.arguments)?;
        encoder.ids(&step.input_artifacts)?;
        encoder.ids(&step.output_artifacts)?;
    }
    encoder.checks(&evidence.preconditions)?;
    encoder.checks(&evidence.success_criteria)?;
    Ok(encoder)
}

pub(super) fn contract(
    evidence: &ProcedureExecutionEvidenceV1,
) -> Result<Vec<u8>, ProductionLedgerError> {
    Ok(encode_contract(evidence)?.bytes)
}

pub(super) fn execution(
    evidence: &ProcedureExecutionEvidenceV1,
) -> Result<Vec<u8>, ProductionLedgerError> {
    let contract = encode_contract(evidence)?;
    let mut encoder = Encoder::new(b"hepta.procedure.execution-evidence.v1");
    encoder.artifacts = contract.artifacts;
    encoder.number(contract.bytes.len() as u64)?;
    encoder.raw(&contract.bytes)?;
    encoder.id(&evidence.decision_record_id)?;
    encoder.id(&evidence.episode_id)?;
    encoder.digest(evidence.run_snapshot_digest)?;
    encoder.id(&evidence.observer_id)?;
    for time in [
        evidence.execution_started_at,
        evidence.execution_finished_at,
        evidence.observer_checked_at,
    ] {
        encoder.number(time)?;
    }
    for checks in [&evidence.preconditions, &evidence.success_criteria] {
        encoder.count(checks.len(), 32)?;
        for check in checks {
            encoder.number(check.observed_at)?;
            encoder.raw(&[match check.result {
                ProcedureCheckResultV1::Unknown => 0,
                ProcedureCheckResultV1::Failed => 1,
                ProcedureCheckResultV1::Satisfied => 2,
            }])?;
            encoder.artifacts(&check.observations)?;
        }
    }
    encoder.count(evidence.trace.len(), 32)?;
    for trace in &evidence.trace {
        encoder.id(&trace.step_id)?;
        encoder.number(u64::from(trace.sequence))?;
        encoder.number(trace.started_at)?;
        encoder.number(trace.finished_at)?;
        encoder.raw(&[match trace.disposition {
            ProcedureStepDispositionV1::Skipped => 0,
            ProcedureStepDispositionV1::Failed => 1,
            ProcedureStepDispositionV1::Completed => 2,
        }])?;
        encoder.artifacts(&trace.inputs)?;
        encoder.artifacts(&trace.outputs)?;
    }
    encoder.artifacts(&evidence.final_outputs)?;
    Ok(encoder.bytes)
}
