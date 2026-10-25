use super::*;

const MAGIC: &[u8; 8] = b"HPTACV05";

impl TrainedCellBundleV5 {
    /// Canonical exact float64 wire format, including tensor order and bindings.
    #[must_use]
    pub fn encode(&self) -> Vec<u8> {
        let mut bytes = MAGIC.to_vec();
        push_id(&mut bytes, &self.artifact_id);
        bytes.extend_from_slice(&self.generation.get().to_be_bytes());
        bytes.extend_from_slice(self.encoder_digest.as_array());
        for value in &self.projection {
            bytes.extend_from_slice(&value.to_bits().to_be_bytes());
        }
        bytes.extend_from_slice(&(self.heads.len() as u16).to_be_bytes());
        for head in &self.heads {
            push_id(&mut bytes, &head.cell_id);
            bytes.extend_from_slice(head.training_state_digest.as_array());
            bytes.extend_from_slice(head.feature_identity_digest.as_array());
            bytes.push(match head.mode {
                TrainedCellModeV5::Linear => 0,
                TrainedCellModeV5::Gated { .. } => 1,
            });
            for value in head.weights.iter().flatten().chain(head.bias.iter()) {
                bytes.extend_from_slice(&value.to_bits().to_be_bytes());
            }
            if let TrainedCellModeV5::Gated { a, g } = &head.mode {
                for value in a.iter().chain(g.iter()) {
                    bytes.extend_from_slice(&value.to_bits().to_be_bytes());
                }
            }
        }
        bytes
    }

    /// Require an independently pinned digest before allocating or interpreting
    /// the bounded payload. Extra bytes and alternate encodings are rejected.
    pub fn decode(bytes: &[u8], expected_digest: Digest32) -> Result<Self, TrainedCellErrorV5> {
        if bytes.len() > MAX_TRAINED_CELL_BYTES_V5
            || expected_digest.is_zero()
            || Digest32::of_bytes(bytes) != expected_digest
        {
            return Err(TrainedCellErrorV5::Digest);
        }
        let mut reader = Reader { bytes, offset: 0 };
        if reader.take(8)? != MAGIC {
            return Err(TrainedCellErrorV5::Encoding);
        }
        let artifact_id = reader.id()?;
        let generation = Generation::new(u64::from_be_bytes(reader.fixed()?))
            .map_err(|_| TrainedCellErrorV5::Encoding)?;
        let encoder_digest = Digest32::from_array(reader.fixed()?);
        let mut projection = Vec::with_capacity(384 * 8);
        for _ in 0..384 * 8 {
            projection.push(reader.float()?);
        }
        let count = u16::from_be_bytes(reader.fixed()?) as usize;
        if count == 0 || count > MAX_TRAINED_CELLS_V5 {
            return Err(TrainedCellErrorV5::Shape);
        }
        let mut heads = Vec::with_capacity(count);
        for _ in 0..count {
            let cell_id = reader.id()?;
            let training = Digest32::from_array(reader.fixed()?);
            let feature = Digest32::from_array(reader.fixed()?);
            let tag = reader.take(1)?[0];
            let mut weights = [[0.0; 4]; 8];
            let mut bias = [0.0; 4];
            for value in weights.iter_mut().flatten().chain(bias.iter_mut()) {
                *value = reader.float()?;
            }
            let mode = match tag {
                0 => TrainedCellModeV5::Linear,
                1 => {
                    let mut a = [0.0; 8];
                    let mut g = [0.0; 8];
                    for value in a.iter_mut().chain(g.iter_mut()) {
                        *value = reader.float()?;
                    }
                    TrainedCellModeV5::Gated { a, g }
                }
                _ => return Err(TrainedCellErrorV5::Encoding),
            };
            heads.push(TrainedCellHeadV5::new(
                cell_id, training, feature, weights, bias, mode,
            )?);
        }
        if reader.offset != bytes.len() {
            return Err(TrainedCellErrorV5::Encoding);
        }
        let bundle = Self::new(artifact_id, generation, encoder_digest, projection, heads)?;
        if bundle.content_digest != expected_digest {
            return Err(TrainedCellErrorV5::Digest);
        }
        Ok(bundle)
    }
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    let value = id.as_str().as_bytes();
    bytes.extend_from_slice(&(value.len() as u16).to_be_bytes());
    bytes.extend_from_slice(value);
}

struct Reader<'a> {
    bytes: &'a [u8],
    offset: usize,
}
impl<'a> Reader<'a> {
    fn take(&mut self, count: usize) -> Result<&'a [u8], TrainedCellErrorV5> {
        let end = self
            .offset
            .checked_add(count)
            .ok_or(TrainedCellErrorV5::Encoding)?;
        let value = self
            .bytes
            .get(self.offset..end)
            .ok_or(TrainedCellErrorV5::Encoding)?;
        self.offset = end;
        Ok(value)
    }
    fn fixed<const N: usize>(&mut self) -> Result<[u8; N], TrainedCellErrorV5> {
        self.take(N)?
            .try_into()
            .map_err(|_| TrainedCellErrorV5::Encoding)
    }
    fn float(&mut self) -> Result<f64, TrainedCellErrorV5> {
        Ok(f64::from_bits(u64::from_be_bytes(self.fixed()?)))
    }
    fn id(&mut self) -> Result<StableId, TrainedCellErrorV5> {
        let count = u16::from_be_bytes(self.fixed()?) as usize;
        let value =
            std::str::from_utf8(self.take(count)?).map_err(|_| TrainedCellErrorV5::Encoding)?;
        StableId::new(value).map_err(|_| TrainedCellErrorV5::Encoding)
    }
}
