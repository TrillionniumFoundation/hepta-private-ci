//! Bounded canonical data encoding, never a decoder for an old owner or seal.
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::Error;
use super::MAX_BYTES;
use super::MAX_MEMBERS;

pub(super) struct Body {
    pub context: Digest32,
    pub panel: Digest32,
    pub snapshot: Vec<u8>,
    pub evaluation: Vec<u8>,
    pub members: Vec<Member>,
}

pub(super) struct Member {
    pub binding: Digest32,
    pub execution_namespace: Digest32,
    pub qualification_namespace: Digest32,
    pub metrics: u32,
    pub record: Vec<u8>,
    pub snapshots: Vec<u8>,
    pub holdout: Vec<u8>,
    pub plan: Vec<u8>,
    pub request: Vec<u8>,
    pub decision: Vec<u8>,
    pub qualification: Vec<u8>,
    pub estimand: Vec<u8>,
    pub roles: Vec<u8>,
    pub generator: Vec<u8>,
    pub evaluator: Vec<u8>,
    pub execution: Vec<u8>,
    pub execution_record: Vec<u8>,
    pub cohort: Vec<u8>,
    pub freeze: Vec<u8>,
}

impl Body {
    pub(super) fn encode(&self) -> Result<Vec<u8>, Error> {
        if !(2..=MAX_MEMBERS).contains(&self.members.len()) {
            return Err(Error::Binding("complete bounded original panel material"));
        }
        let mut bytes = b"HECMM002".to_vec();
        bytes.extend_from_slice(self.context.as_array());
        bytes.extend_from_slice(self.panel.as_array());
        put_bytes(&mut bytes, &self.snapshot)?;
        put_bytes(&mut bytes, &self.evaluation)?;
        bytes.extend_from_slice(&(self.members.len() as u32).to_be_bytes());
        for member in &self.members {
            for digest in [
                member.binding,
                member.execution_namespace,
                member.qualification_namespace,
            ] {
                bytes.extend_from_slice(digest.as_array());
            }
            bytes.extend_from_slice(&member.metrics.to_be_bytes());
            for part in [
                &member.record,
                &member.snapshots,
                &member.holdout,
                &member.plan,
                &member.request,
                &member.decision,
                &member.qualification,
                &member.estimand,
                &member.roles,
                &member.generator,
                &member.evaluator,
                &member.execution,
                &member.execution_record,
                &member.cohort,
                &member.freeze,
            ] {
                put_bytes(&mut bytes, part)?;
            }
        }
        if bytes.len() > MAX_BYTES {
            return Err(Error::Binding("total original material bound"));
        }
        Ok(bytes)
    }

    pub(super) fn decode(bytes: &[u8]) -> Result<Self, Error> {
        if bytes.len() > MAX_BYTES {
            return Err(Error::Binding("total original material bound"));
        }
        let mut reader = Reader::new(bytes);
        reader.literal(b"HECMM002")?;
        let context = reader.digest()?;
        let panel = reader.digest()?;
        let snapshot = reader.bytes()?.to_vec();
        let evaluation = reader.bytes()?.to_vec();
        let count = reader.count(MAX_MEMBERS)?;
        if count < 2 {
            return Err(Error::Binding("nonempty original retention material"));
        }
        let mut members = Vec::with_capacity(count);
        for _ in 0..count {
            members.push(Member {
                binding: reader.digest()?,
                execution_namespace: reader.digest()?,
                qualification_namespace: reader.digest()?,
                metrics: reader.u32()?,
                record: reader.bytes()?.to_vec(),
                snapshots: reader.bytes()?.to_vec(),
                holdout: reader.bytes()?.to_vec(),
                plan: reader.bytes()?.to_vec(),
                request: reader.bytes()?.to_vec(),
                decision: reader.bytes()?.to_vec(),
                qualification: reader.bytes()?.to_vec(),
                estimand: reader.bytes()?.to_vec(),
                roles: reader.bytes()?.to_vec(),
                generator: reader.bytes()?.to_vec(),
                evaluator: reader.bytes()?.to_vec(),
                execution: reader.bytes()?.to_vec(),
                execution_record: reader.bytes()?.to_vec(),
                cohort: reader.bytes()?.to_vec(),
                freeze: reader.bytes()?.to_vec(),
            });
        }
        reader.finish()?;
        let body = Self {
            context,
            panel,
            snapshot,
            evaluation,
            members,
        };
        if body.encode()? != bytes {
            return Err(Error::Binding("canonical original material"));
        }
        Ok(body)
    }
}

fn put_bytes(bytes: &mut Vec<u8>, part: &[u8]) -> Result<(), Error> {
    if part.len() > 65_536
        || bytes
            .len()
            .checked_add(part.len() + 4)
            .is_none_or(|len| len > MAX_BYTES)
    {
        return Err(Error::Binding("bounded original material field"));
    }
    bytes.extend_from_slice(&(part.len() as u32).to_be_bytes());
    bytes.extend_from_slice(part);
    Ok(())
}

pub(super) struct Reader<'a> {
    bytes: &'a [u8],
    pub offset: usize,
}
impl<'a> Reader<'a> {
    pub(super) fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, offset: 0 }
    }
    pub(super) fn take(&mut self, count: usize) -> Result<&'a [u8], Error> {
        let end = self
            .offset
            .checked_add(count)
            .ok_or(Error::Binding("material length overflow"))?;
        let value = self
            .bytes
            .get(self.offset..end)
            .ok_or(Error::Binding("truncated original material"))?;
        self.offset = end;
        Ok(value)
    }
    pub(super) fn literal(&mut self, expected: &[u8]) -> Result<(), Error> {
        if self.take(expected.len())? != expected {
            return Err(Error::Binding("original commitment domain"));
        }
        Ok(())
    }
    pub(super) fn u8(&mut self) -> Result<u8, Error> {
        Ok(self.take(1)?[0])
    }
    pub(super) fn u32(&mut self) -> Result<u32, Error> {
        Ok(u32::from_be_bytes(
            self.take(4)?
                .try_into()
                .map_err(|_| Error::Binding("material integer"))?,
        ))
    }
    pub(super) fn u64(&mut self) -> Result<u64, Error> {
        Ok(u64::from_be_bytes(
            self.take(8)?
                .try_into()
                .map_err(|_| Error::Binding("material integer"))?,
        ))
    }
    pub(super) fn digest(&mut self) -> Result<Digest32, Error> {
        Ok(Digest32::from_array(
            self.take(32)?
                .try_into()
                .map_err(|_| Error::Binding("material digest"))?,
        ))
    }
    pub(super) fn count(&mut self, maximum: usize) -> Result<usize, Error> {
        let count = self.u32()? as usize;
        if count > maximum {
            return Err(Error::Binding("bounded original material count"));
        }
        Ok(count)
    }
    pub(super) fn bytes(&mut self) -> Result<&'a [u8], Error> {
        let count = self.count(65_536)?;
        self.take(count)
    }
    pub(super) fn id(&mut self) -> Result<StableId, Error> {
        let length = self.count(128)?;
        let value = std::str::from_utf8(self.take(length)?)
            .map_err(|_| Error::Binding("material identifier"))?;
        StableId::new(value).map_err(|_| Error::Binding("material identifier"))
    }
    pub(super) fn ids(&mut self) -> Result<Vec<StableId>, Error> {
        (0..self.count(1024)?).map(|_| self.id()).collect()
    }
    pub(super) fn principal(&mut self) -> Result<AuthenticatedPrincipalV1, Error> {
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
    pub(super) fn finish(self) -> Result<(), Error> {
        if self.offset != self.bytes.len() {
            return Err(Error::Binding("trailing original material"));
        }
        Ok(())
    }
}
