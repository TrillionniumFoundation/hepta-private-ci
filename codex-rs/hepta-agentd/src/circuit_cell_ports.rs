//! Opt-in numerical representation and advisory action ports. The Circuit
//! owner still binds the exact bytes to a committed predecessor completion.

use std::collections::BTreeSet;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_neuron::CellDecisionReceiptV1;
use codex_hepta_neuron::CellPolicyEntryV1;
use codex_hepta_neuron::CellRepresentationV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CircuitCellErrorV1;
use crate::circuit_cell_binding::push_text;

const DOMAIN: &[u8] = b"hepta.circuit.cell-ports.v2\0";
const MAX_BYTES: usize = 65_536;

/// Actual behavior of the frozen Cell policy. This remains advisory; consumers
/// must use their own legal-action and effect owners before acting on it.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CircuitCellActionPortV1 {
    pub selected_candidate: StableId,
    pub confidence_ppm: u32,
    pub ood_ppm: u32,
    pub deadline_exceeded: bool,
    pub policy: Vec<CellPolicyEntryV1>,
}

/// Semantic output excludes operation IDs, checkpoints and measured costs so
/// repeated unchanged representations still trigger Circuit no-progress rules.
/// The separate completion receipt retains the original invocation and costs.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CircuitCellPortsV2 {
    pub scope_digest: Digest32,
    pub bundle_digest: Digest32,
    pub source_frontier: Digest32,
    pub state_schema_digest: Digest32,
    pub representation: CellRepresentationV1,
    pub action: CircuitCellActionPortV1,
}

pub fn circuit_cell_output_schema_v2() -> Sha256Digest {
    Sha256Digest::for_bytes(b"hepta.circuit.cell-ports.v2")
}

pub(crate) fn encode_ports(
    receipt: &CellDecisionReceiptV1,
    state_schema_digest: Digest32,
) -> Result<Vec<u8>, CircuitCellErrorV1> {
    receipt.representation.validate()?;
    let mut bytes = DOMAIN.to_vec();
    for digest in [
        receipt.scope.digest(),
        receipt.bundle_digest,
        receipt.source_frontier,
        state_schema_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    // Precision and channel layout are fixed by this schema, not caller flags.
    bytes.extend_from_slice(&(receipt.representation.drive_q24.len() as u32).to_be_bytes());
    for values in [
        &receipt.representation.drive_q24,
        &receipt.representation.prediction_q24,
    ] {
        for value in values {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
    }
    push_text(&mut bytes, receipt.selected_candidate.as_str());
    bytes.extend_from_slice(&receipt.confidence_ppm.to_be_bytes());
    bytes.extend_from_slice(&receipt.ood_ppm.to_be_bytes());
    bytes.push(u8::from(receipt.deadline_exceeded));
    bytes.extend_from_slice(&(receipt.policy.len() as u32).to_be_bytes());
    for entry in &receipt.policy {
        push_text(&mut bytes, entry.candidate_id.as_str());
        bytes.push(u8::from(entry.allowed));
        bytes.extend_from_slice(&entry.probability_ppm.to_be_bytes());
    }
    if bytes.len() > MAX_BYTES {
        return Err(CircuitCellErrorV1::InvalidReceipt);
    }
    Ok(bytes)
}

/// Validate shape and canonical encoding only. Authentic predecessor selection
/// comes from the Circuit owner's admission, never from parsing these bytes.
pub fn decode_circuit_cell_ports_v2(
    bytes: &[u8],
) -> Result<CircuitCellPortsV2, CircuitCellErrorV1> {
    if bytes.len() > MAX_BYTES {
        return Err(CircuitCellErrorV1::InvalidReceipt);
    }
    let mut reader = Reader(
        bytes
            .strip_prefix(DOMAIN)
            .ok_or(CircuitCellErrorV1::InvalidReceipt)?,
    );
    let scope_digest = reader.digest()?;
    let bundle_digest = reader.digest()?;
    let source_frontier = reader.digest()?;
    let state_schema_digest = reader.digest()?;
    let width = reader.count(/*max*/ 256)?;
    let representation = CellRepresentationV1 {
        drive_q24: (0..width).map(|_| reader.q24()).collect::<Result<_, _>>()?,
        prediction_q24: (0..width).map(|_| reader.q24()).collect::<Result<_, _>>()?,
    };
    representation.validate()?;
    let selected_candidate = reader.id()?;
    let confidence_ppm = reader.ppm()?;
    let ood_ppm = reader.ppm()?;
    let deadline_exceeded = reader.boolean()?;
    let count = reader.count(/*max*/ 256)?;
    let mut policy = Vec::with_capacity(count);
    let mut ids = BTreeSet::new();
    for _ in 0..count {
        let entry = CellPolicyEntryV1 {
            candidate_id: reader.id()?,
            allowed: reader.boolean()?,
            probability_ppm: reader.ppm()?,
        };
        if !ids.insert(entry.candidate_id.clone())
            || entry.probability_ppm
                != if entry.candidate_id == selected_candidate {
                    1_000_000
                } else {
                    0
                }
            || (!entry.allowed && entry.probability_ppm != 0)
        {
            return Err(CircuitCellErrorV1::InvalidReceipt);
        }
        policy.push(entry);
    }
    if !reader.0.is_empty() || !ids.contains(&selected_candidate) {
        return Err(CircuitCellErrorV1::InvalidReceipt);
    }
    Ok(CircuitCellPortsV2 {
        scope_digest,
        bundle_digest,
        source_frontier,
        state_schema_digest,
        representation,
        action: CircuitCellActionPortV1 {
            selected_candidate,
            confidence_ppm,
            ood_ppm,
            deadline_exceeded,
            policy,
        },
    })
}

struct Reader<'a>(&'a [u8]);

impl Reader<'_> {
    fn take<const N: usize>(&mut self) -> Result<[u8; N], CircuitCellErrorV1> {
        let Some((head, rest)) = self.0.split_at_checked(N) else {
            return Err(CircuitCellErrorV1::InvalidReceipt);
        };
        self.0 = rest;
        head.try_into()
            .map_err(|_| CircuitCellErrorV1::InvalidReceipt)
    }

    fn count(&mut self, max: usize) -> Result<usize, CircuitCellErrorV1> {
        let n = u32::from_be_bytes(self.take()?) as usize;
        if n > max {
            return Err(CircuitCellErrorV1::InvalidReceipt);
        }
        Ok(n)
    }

    fn ppm(&mut self) -> Result<u32, CircuitCellErrorV1> {
        self.count(/*max*/ 1_000_000).map(|value| value as u32)
    }

    fn digest(&mut self) -> Result<Digest32, CircuitCellErrorV1> {
        let digest = Digest32::from_array(self.take()?);
        if digest.is_zero() {
            return Err(CircuitCellErrorV1::InvalidReceipt);
        }
        Ok(digest)
    }

    fn q24(&mut self) -> Result<i64, CircuitCellErrorV1> {
        Ok(i64::from_be_bytes(self.take()?))
    }

    fn boolean(&mut self) -> Result<bool, CircuitCellErrorV1> {
        match self.take::<1>()?[0] {
            0 => Ok(false),
            1 => Ok(true),
            _ => Err(CircuitCellErrorV1::InvalidReceipt),
        }
    }

    fn id(&mut self) -> Result<StableId, CircuitCellErrorV1> {
        let n = self.count(/*max*/ 1024)?;
        let Some((head, rest)) = self.0.split_at_checked(n) else {
            return Err(CircuitCellErrorV1::InvalidReceipt);
        };
        self.0 = rest;
        StableId::new(std::str::from_utf8(head).map_err(|_| CircuitCellErrorV1::InvalidReceipt)?)
            .map_err(|_| CircuitCellErrorV1::InvalidReceipt)
    }
}
