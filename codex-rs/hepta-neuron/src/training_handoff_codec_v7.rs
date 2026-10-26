use super::*;

const MAGIC: &[u8; 8] = b"HPTHOF07";

impl TrainingHandoffBundleV7 {
    #[must_use]
    pub fn encode(&self) -> Vec<u8> {
        let mut bytes = MAGIC.to_vec();
        bytes.extend_from_slice(self.protocol_digest.as_array());
        bytes.push(u8::from(self.predecessor_digest.is_some()));
        if let Some(previous) = self.predecessor_digest {
            bytes.extend_from_slice(previous.as_array());
        }
        push_bytes(&mut bytes, &self.serving.encode());
        bytes.extend_from_slice(&(self.checkpoints.len() as u16).to_be_bytes());
        for checkpoint in &self.checkpoints {
            push_bytes(&mut bytes, checkpoint.cell_id.as_str().as_bytes());
            push_bytes(&mut bytes, &checkpoint.state_metadata_json);
            push_bytes(&mut bytes, &checkpoint.controller_metadata_json);
            bytes.extend_from_slice(&(checkpoint.state_vector.len() as u16).to_be_bytes());
            for value in &checkpoint.state_vector {
                bytes.extend_from_slice(&value.to_bits().to_le_bytes());
            }
            bytes.push(checkpoint.planned_actions.len() as u8);
            for value in checkpoint.planned_actions.iter().flatten() {
                bytes.extend_from_slice(&value.to_bits().to_le_bytes());
            }
        }
        bytes
    }

    /// Require the independently admitted outer digest before any decoding.
    pub fn decode(bytes: &[u8], expected: Digest32) -> Result<Self, TrainingHandoffErrorV7> {
        if bytes.len() > MAX_TRAINING_HANDOFF_BYTES_V7
            || expected.is_zero()
            || Digest32::of_bytes(bytes) != expected
        {
            return Err(TrainingHandoffErrorV7::Digest);
        }
        let mut reader = Reader { bytes, offset: 0 };
        if reader.take(8)? != MAGIC {
            return Err(TrainingHandoffErrorV7::Encoding);
        }
        let protocol = Digest32::from_array(reader.fixed()?);
        let predecessor = match reader.take(1)?[0] {
            0 => None,
            1 => Some(Digest32::from_array(reader.fixed()?)),
            _ => return Err(TrainingHandoffErrorV7::Encoding),
        };
        let payload = reader.blob(crate::MAX_TRAINED_CELL_BYTES_V5)?;
        let serving = TrainedCellBundleV5::decode(payload, Digest32::of_bytes(payload))?;
        let count = u16::from_be_bytes(reader.fixed()?) as usize;
        if count != serving.heads().len() {
            return Err(TrainingHandoffErrorV7::Shape);
        }
        let mut checkpoints = Vec::with_capacity(count);
        for _ in 0..count {
            let cell = std::str::from_utf8(reader.blob(128)?)
                .map_err(|_| TrainingHandoffErrorV7::Encoding)?;
            let cell = StableId::new(cell).map_err(|_| TrainingHandoffErrorV7::Encoding)?;
            let metadata = reader.blob(MAX_CHECKPOINT_METADATA)?.to_vec();
            let controller = reader.blob(MAX_CHECKPOINT_METADATA)?.to_vec();
            let n = u16::from_be_bytes(reader.fixed()?) as usize;
            if !matches!(n, 108 | 156) {
                return Err(TrainingHandoffErrorV7::Shape);
            }
            let mut vector = Vec::with_capacity(n);
            for _ in 0..n {
                vector.push(f64::from_bits(u64::from_le_bytes(reader.fixed()?)));
            }
            let horizon = reader.take(1)?[0] as usize;
            if horizon > 8 {
                return Err(TrainingHandoffErrorV7::Shape);
            }
            let mut actions = Vec::with_capacity(horizon);
            for _ in 0..horizon {
                let mut row = Vec::with_capacity(n / 3);
                for _ in 0..n / 3 {
                    row.push(f64::from_bits(u64::from_le_bytes(reader.fixed()?)));
                }
                actions.push(row);
            }
            checkpoints.push(CellTrainingCheckpointV7::new(
                cell, metadata, vector, controller, actions,
            )?);
        }
        if reader.offset != bytes.len() {
            return Err(TrainingHandoffErrorV7::Encoding);
        }
        let bundle = Self::new(serving, protocol, predecessor, checkpoints)?;
        if bundle.content_digest != expected {
            return Err(TrainingHandoffErrorV7::Digest);
        }
        Ok(bundle)
    }
}

fn push_bytes(target: &mut Vec<u8>, value: &[u8]) {
    target.extend_from_slice(&(value.len() as u32).to_be_bytes());
    target.extend_from_slice(value);
}

pub(super) struct Reader<'a> {
    pub(super) bytes: &'a [u8],
    pub(super) offset: usize,
}
impl<'a> Reader<'a> {
    pub(super) fn take(&mut self, count: usize) -> Result<&'a [u8], TrainingHandoffErrorV7> {
        let end = self
            .offset
            .checked_add(count)
            .ok_or(TrainingHandoffErrorV7::Encoding)?;
        let value = self
            .bytes
            .get(self.offset..end)
            .ok_or(TrainingHandoffErrorV7::Encoding)?;
        self.offset = end;
        Ok(value)
    }
    pub(super) fn fixed<const N: usize>(&mut self) -> Result<[u8; N], TrainingHandoffErrorV7> {
        self.take(N)?
            .try_into()
            .map_err(|_| TrainingHandoffErrorV7::Encoding)
    }
    fn blob(&mut self, maximum: usize) -> Result<&'a [u8], TrainingHandoffErrorV7> {
        let count = u32::from_be_bytes(self.fixed()?) as usize;
        if count == 0 || count > maximum {
            return Err(TrainingHandoffErrorV7::Shape);
        }
        self.take(count)
    }
}
