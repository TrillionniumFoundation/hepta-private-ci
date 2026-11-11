//! Bounded retained original inputs. Decoding does not authenticate them: the
//! owner re-derives the full material through the actual source and compares all
//! bytes before returning a qualification. No verification time is serialized.

use codex_hepta_intelligence_eval::MAX_PRODUCT_EVALUATION_EXECUTION_BYTES_V1 as LIMIT;
use codex_hepta_intelligence_eval::ProductQualificationContextV1;
use codex_hepta_intelligence_eval::SignedEvaluationEvidenceV1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::OriginalProductQualificationErrorV1 as Error;

const MAGIC: &[u8; 8] = b"HPOQP001";

pub(super) struct SavedInputs {
    pub recorded_at: u64,
    pub binding: Digest32,
    pub context: ProductQualificationContextV1,
    pub evidence: SignedEvaluationEvidenceV1,
}

pub(super) fn encode(
    recorded_at: u64,
    binding: Digest32,
    context: &ProductQualificationContextV1,
    evidence: &SignedEvaluationEvidenceV1,
    material: &[u8],
) -> Result<Vec<u8>, Error> {
    let mut out = Writer(Vec::new());
    out.raw(MAGIC)?;
    out.raw(&recorded_at.to_be_bytes())?;
    out.raw(binding.as_array())?;
    for principal in [&context.generator, &context.evaluator] {
        out.id(&principal.principal_id)?;
        for digest in [
            principal.credential_chain_digest,
            principal.signing_key_digest,
            principal.scope_digest,
        ] {
            out.raw(digest.as_array())?;
        }
        for value in [
            principal.authority_epoch,
            principal.authenticated_at,
            principal.expires_at,
        ] {
            out.raw(&value.to_be_bytes())?;
        }
    }
    out.count(context.retention_receipt_digests.len())?;
    for digest in &context.retention_receipt_digests {
        out.raw(digest.as_array())?;
    }
    out.raw(context.unlearning_receipt_digest.as_array())?;
    for (expected, signed) in [
        (LearningEvidenceRoleV1::Generator, &evidence.generator_plan),
        (
            LearningEvidenceRoleV1::Evaluator,
            &evidence.evaluator_bundle,
        ),
    ] {
        if signed.role != expected {
            return Err(Error::Binding("original qualification roles"));
        }
        out.id(&signed.evidence_id)?;
        out.id(&signed.principal_id)?;
        for digest in [
            signed.trust_digest,
            signed.scope_digest,
            signed.objective_digest,
            signed.payload_digest,
        ] {
            out.raw(digest.as_array())?;
        }
        for value in [signed.authority_epoch, signed.issued_at, signed.expires_at] {
            out.raw(&value.to_be_bytes())?;
        }
        out.raw(&signed.signature)?;
    }
    out.count(material.len())?;
    out.raw(material)?;
    Ok(out.0)
}

pub(super) fn decode(bytes: &[u8]) -> Result<SavedInputs, Error> {
    if bytes.len() > LIMIT {
        return Err(Error::Binding("qualification record capacity"));
    }
    let mut input = Reader(bytes);
    if input.take(/*count*/ 8)? != MAGIC {
        return Err(Error::Binding("qualification record format"));
    }
    let recorded_at = input.u64()?;
    let binding = input.digest()?;
    let generator = input.principal()?;
    let evaluator = input.principal()?;
    let count = input.count()?;
    if count > input.0.len() / 32 {
        return Err(Error::Binding("qualification record count"));
    }
    let retention_receipt_digests = (0..count)
        .map(|_| input.digest())
        .collect::<Result<Vec<_>, _>>()?;
    let unlearning_receipt_digest = input.digest()?;
    let evidence = SignedEvaluationEvidenceV1 {
        generator_plan: input.signed(LearningEvidenceRoleV1::Generator)?,
        evaluator_bundle: input.signed(LearningEvidenceRoleV1::Evaluator)?,
    };
    let size = input.count()?;
    let _material = input.take(size)?;
    if !input.0.is_empty() || recorded_at == 0 || binding.is_zero() {
        return Err(Error::Binding("complete qualification record"));
    }
    Ok(SavedInputs {
        recorded_at,
        binding,
        context: ProductQualificationContextV1 {
            generator,
            evaluator,
            retention_receipt_digests,
            unlearning_receipt_digest,
        },
        evidence,
    })
}

struct Writer(Vec<u8>);
impl Writer {
    fn raw(&mut self, bytes: &[u8]) -> Result<(), Error> {
        if self
            .0
            .len()
            .checked_add(bytes.len())
            .is_none_or(|len| len > LIMIT)
        {
            return Err(Error::Binding("qualification record capacity"));
        }
        self.0.extend_from_slice(bytes);
        Ok(())
    }
    fn count(&mut self, count: usize) -> Result<(), Error> {
        let count = u32::try_from(count)
            .ok()
            .filter(|v| *v as usize <= LIMIT)
            .ok_or(Error::Binding("qualification record capacity"))?;
        self.raw(&count.to_be_bytes())
    }
    fn id(&mut self, id: &StableId) -> Result<(), Error> {
        self.count(id.as_str().len())?;
        self.raw(id.as_str().as_bytes())
    }
}

struct Reader<'a>(&'a [u8]);
impl<'a> Reader<'a> {
    fn take(&mut self, count: usize) -> Result<&'a [u8], Error> {
        let (head, rest) = self
            .0
            .split_at_checked(count)
            .ok_or(Error::Binding("truncated qualification record"))?;
        self.0 = rest;
        Ok(head)
    }
    fn count(&mut self) -> Result<usize, Error> {
        let value = u32::from_be_bytes(
            self.take(/*count*/ 4)?
                .try_into()
                .map_err(|_| Error::Binding("record count"))?,
        ) as usize;
        if value > LIMIT {
            return Err(Error::Binding("qualification record capacity"));
        }
        Ok(value)
    }
    fn u64(&mut self) -> Result<u64, Error> {
        Ok(u64::from_be_bytes(
            self.take(/*count*/ 8)?
                .try_into()
                .map_err(|_| Error::Binding("record integer"))?,
        ))
    }
    fn digest(&mut self) -> Result<Digest32, Error> {
        Ok(Digest32::from_array(
            self.take(/*count*/ 32)?
                .try_into()
                .map_err(|_| Error::Binding("record digest"))?,
        ))
    }
    fn id(&mut self) -> Result<StableId, Error> {
        let size = self.count()?;
        if !(1..=128).contains(&size) {
            return Err(Error::Binding("record identifier bound"));
        }
        let text = std::str::from_utf8(self.take(size)?)
            .map_err(|_| Error::Binding("record identifier"))?;
        StableId::new(text).map_err(|_| Error::Binding("record identifier"))
    }
    fn principal(&mut self) -> Result<AuthenticatedPrincipalV1, Error> {
        Ok(AuthenticatedPrincipalV1 {
            principal_id: self.id()?,
            credential_chain_digest: self.digest()?,
            signing_key_digest: self.digest()?,
            scope_digest: self.digest()?,
            authority_epoch: self.u64()?,
            authenticated_at: self.u64()?,
            expires_at: self.u64()?,
        })
    }
    fn signed(&mut self, role: LearningEvidenceRoleV1) -> Result<SignedLearningEvidenceV1, Error> {
        Ok(SignedLearningEvidenceV1 {
            evidence_id: self.id()?,
            principal_id: self.id()?,
            role,
            trust_digest: self.digest()?,
            scope_digest: self.digest()?,
            objective_digest: self.digest()?,
            payload_digest: self.digest()?,
            authority_epoch: self.u64()?,
            issued_at: self.u64()?,
            expires_at: self.u64()?,
            signature: self
                .take(/*count*/ 64)?
                .try_into()
                .map_err(|_| Error::Binding("record signature"))?,
        })
    }
}
