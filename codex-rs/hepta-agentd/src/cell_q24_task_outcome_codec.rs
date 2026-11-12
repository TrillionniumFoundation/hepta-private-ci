//! Decode only the retained original production-v2 signing preimage. This is
//! untrusted data reconstruction, not authentication. The original LedgerWriter
//! must still validate any append; historical readback requires its actual
//! witnessed active record. No field, label, timestamp or signature is renewed.

use codex_hepta_types::FixedQ32;

use super::*;

pub(super) fn decode(bytes: &[u8]) -> Result<AuthenticatedOutcomeV1, Error> {
    let prefix = b"hepta.learning-ledger.production-outcome.v2";
    if bytes.len() > 16_384 || !bytes.starts_with(prefix) {
        return Err(Error::Binding("original Outcome signing preimage"));
    }
    let mut reader = Reader(&bytes[prefix.len()..]);
    let record_id = reader.id()?;
    let outcome_id = reader.id()?;
    let episode_id = reader.id()?;
    let observer = AuthenticatedPrincipalV1 {
        principal_id: reader.id()?,
        credential_chain_digest: reader.digest()?,
        signing_key_digest: reader.digest()?,
        scope_digest: reader.digest()?,
        authority_epoch: reader.u64()?,
        authenticated_at: reader.u64()?,
        expires_at: reader.u64()?,
    };
    let observed_at = reader.optional_u64()?;
    let value = match reader.take::<1>()?[0] {
        0 => None,
        1 => Some(FixedQ32::from_raw(i64::from_be_bytes(reader.take()?))),
        _ => return Err(Error::Binding("original Outcome value tag")),
    };
    let outcome = AuthenticatedOutcomeV1 {
        record_id,
        outcome_id,
        episode_id,
        observer,
        observed_at,
        value,
        unit_profile_digest: reader.digest()?,
        support_digest: reader.digest()?,
        watermark: OutcomeWatermarkV1 {
            latest_observable_at: reader.u64()?,
            expected_delay_profile_digest: reader.digest()?,
            terminality: match reader.take::<1>()?[0] {
                0 => OutcomeTerminalityV1::Pending,
                1 => OutcomeTerminalityV1::Censored,
                2 => OutcomeTerminalityV1::Terminal,
                _ => return Err(Error::Binding("original Outcome terminality tag")),
            },
            censoring_reason: reader.optional_id()?,
            correction_predecessor: reader.optional_id()?,
            finalized_at: reader.optional_u64()?,
        },
    };
    if !reader.0.is_empty() || outcome_signing_payload_v2(&outcome) != bytes {
        return Err(Error::Binding(
            "canonical complete original Outcome preimage",
        ));
    }
    Ok(outcome)
}

struct Reader<'a>(&'a [u8]);

impl Reader<'_> {
    fn take<const N: usize>(&mut self) -> Result<[u8; N], Error> {
        let bytes = self
            .0
            .get(..N)
            .ok_or(Error::Binding("truncated original Outcome"))?;
        let result = bytes
            .try_into()
            .map_err(|_| Error::Binding("original Outcome width"))?;
        self.0 = &self.0[N..];
        Ok(result)
    }

    fn u64(&mut self) -> Result<u64, Error> {
        Ok(u64::from_be_bytes(self.take()?))
    }

    fn digest(&mut self) -> Result<Digest32, Error> {
        Ok(Digest32::from_array(self.take()?))
    }

    fn id(&mut self) -> Result<StableId, Error> {
        let length =
            usize::try_from(self.u64()?).map_err(|_| Error::Binding("Outcome id length"))?;
        if !(1..=128).contains(&length) {
            return Err(Error::Binding("bounded original Outcome id"));
        }
        let bytes = self
            .0
            .get(..length)
            .ok_or(Error::Binding("truncated original Outcome id"))?;
        let value =
            std::str::from_utf8(bytes).map_err(|_| Error::Binding("original Outcome id UTF8"))?;
        let id = StableId::new(value).map_err(|_| Error::Binding("original Outcome id"))?;
        self.0 = &self.0[length..];
        Ok(id)
    }

    fn optional_u64(&mut self) -> Result<Option<u64>, Error> {
        match self.take::<1>()?[0] {
            0 => Ok(None),
            1 => self.u64().map(Some),
            _ => Err(Error::Binding("original Outcome optional time tag")),
        }
    }

    fn optional_id(&mut self) -> Result<Option<StableId>, Error> {
        match self.take::<1>()?[0] {
            0 => Ok(None),
            1 => self.id().map(Some),
            _ => Err(Error::Binding("original Outcome optional id tag")),
        }
    }
}
