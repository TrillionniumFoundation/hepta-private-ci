//! Exact read-only policy projection from the original Source publication.
//! This is data, not a Cell receipt, effect grant, model output or reward.

use codex_hepta_neuron::CellPolicyEntryV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::CircuitTaskSourcePublicationV1;
use super::Error;

#[derive(Debug, Eq, PartialEq)]
pub(crate) struct CircuitTaskPolicyProjectionV1 {
    selected: StableId,
    entries: Vec<CellPolicyEntryV1>,
    checkpoint_before: Digest32,
}

impl CircuitTaskPolicyProjectionV1 {
    pub(crate) fn selected(&self) -> &StableId {
        &self.selected
    }

    pub(crate) fn entries(&self) -> &[CellPolicyEntryV1] {
        &self.entries
    }

    /// Exact committed original predecessor. The paired evaluation profile only
    /// admits the existing fresh empty Cell state, represented by ZERO.
    pub(crate) fn checkpoint_before(&self) -> Digest32 {
        self.checkpoint_before
    }
}

pub(super) fn read(
    publication: &CircuitTaskSourcePublicationV1,
) -> Result<CircuitTaskPolicyProjectionV1, Error> {
    let input = publication.input();
    let mut result = Reader::new(publication.result_bytes(), b"HCSTRES1")?;
    result.blob()?; // Original canonical input, checked by Source read_publication.
    result.blob()?; // Original complete Circuit history.
    if result.blob()? != publication.output() {
        return Err(Error::InvalidBinding);
    }
    result.blob()?; // Circuit run and completion records, retained by Source.
    let mut decision = Reader::new(
        result.blob()?,
        b"hepta.circuit.committed-cell-decision.v1\0",
    )?;
    if decision.id()? != input.operation_id
        || decision.id()? != input.scope.agent_id
        || decision.id()? != input.scope.cell_id
        || decision.id()? != input.scope.run_id
    {
        return Err(Error::InvalidBinding);
    }
    let selected = decision.id()?;
    decision.digest()?; // Full operation and semantic bindings remain in Source.
    decision.digest()?;
    if decision.digest()? != input.scope.principal_digest
        || decision.digest()? != publication.bundle_digest()
        || decision.digest()? != input.source_frontier
    {
        return Err(Error::InvalidBinding);
    }
    let checkpoint_before = decision.digest()?;
    if decision.digest()? != publication.checkpoint_digest() {
        return Err(Error::InvalidBinding);
    }
    decision.digest()?; // Model-output audit digest is never a label.
    let confidence = decision.u32()?;
    let ood = decision.u32()?;
    if confidence > 1_000_000 || ood > 1_000_000 || decision.take::<1>()? != [0] {
        return Err(Error::InvalidBinding);
    }
    for _ in 0..7 {
        decision.take::<8>()?; // Original cost, not an evaluation outcome.
    }
    let count = decision.u32()? as usize;
    if !(1..=64).contains(&count) || count != input.candidates.len() {
        return Err(Error::InvalidBinding);
    }
    let mut entries = Vec::with_capacity(count);
    for mask in &input.candidates {
        let candidate_id = decision.id()?;
        let allowed = match decision.take::<1>()? {
            [0] => false,
            [1] => true,
            _ => return Err(Error::InvalidBinding),
        };
        let probability_ppm = decision.u32()?;
        // The current original Cell producer is exactly deterministic. Do not
        // turn zero support into a small positive propensity or renormalize it.
        let expected = if candidate_id == selected {
            1_000_000
        } else {
            0
        };
        if candidate_id != mask.candidate_id
            || allowed != mask.allowed
            || probability_ppm != expected
            || (probability_ppm != 0 && !allowed)
            || entries
                .iter()
                .any(|entry: &CellPolicyEntryV1| entry.candidate_id == candidate_id)
        {
            return Err(Error::InvalidBinding);
        }
        entries.push(CellPolicyEntryV1 {
            candidate_id,
            allowed,
            probability_ppm,
        });
    }
    if !entries
        .iter()
        .any(|entry| entry.candidate_id == selected && entry.allowed)
        || decision.take::<1>()? != [0]
    {
        return Err(Error::InvalidBinding);
    }
    decision.end()?;
    if result.blob()?.is_empty() {
        return Err(Error::InvalidBinding);
    }
    result.end()?;

    let mut output = Reader::new(
        publication.output(),
        b"hepta.circuit.cell-policy-output.v1\0",
    )?;
    if output.digest()? != input.scope.digest()
        || output.digest()? != publication.bundle_digest()
        || output.id()? != selected
        || output.u32()? != confidence
        || output.u32()? != ood
        || output.take::<1>()? != [0]
        || output.u32()? as usize != entries.len()
    {
        return Err(Error::InvalidBinding);
    }
    for entry in &entries {
        if output.id()? != entry.candidate_id
            || output.take::<1>()? != [u8::from(entry.allowed)]
            || output.u32()? != entry.probability_ppm
        {
            return Err(Error::InvalidBinding);
        }
    }
    output.end()?;
    Ok(CircuitTaskPolicyProjectionV1 { selected, entries, checkpoint_before })
}

struct Reader<'a>(&'a [u8]);

impl<'a> Reader<'a> {
    fn new(bytes: &'a [u8], prefix: &[u8]) -> Result<Self, Error> {
        if bytes.is_empty() || bytes.len() > 65_536 {
            return Err(Error::InvalidBinding);
        }
        Ok(Self(
            bytes.strip_prefix(prefix).ok_or(Error::InvalidBinding)?,
        ))
    }

    fn take<const N: usize>(&mut self) -> Result<[u8; N], Error> {
        let (value, remaining) = self.0.split_at_checked(N).ok_or(Error::InvalidBinding)?;
        self.0 = remaining;
        value.try_into().map_err(|_| Error::InvalidBinding)
    }

    fn u32(&mut self) -> Result<u32, Error> {
        Ok(u32::from_be_bytes(self.take()?))
    }

    fn blob(&mut self) -> Result<&'a [u8], Error> {
        let length = self.u32()? as usize;
        let (value, remaining) = self
            .0
            .split_at_checked(length)
            .ok_or(Error::InvalidBinding)?;
        self.0 = remaining;
        Ok(value)
    }

    fn id(&mut self) -> Result<StableId, Error> {
        StableId::new(std::str::from_utf8(self.blob()?).map_err(|_| Error::InvalidBinding)?)
            .map_err(|_| Error::InvalidBinding)
    }

    fn digest(&mut self) -> Result<Digest32, Error> {
        Ok(Digest32::from_array(self.take()?))
    }

    fn end(self) -> Result<(), Error> {
        if self.0.is_empty() {
            Ok(())
        } else {
            Err(Error::InvalidBinding)
        }
    }
}
