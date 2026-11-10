//! Exact bounded wire/numerical semantics for the composed control backend.

use std::fs::File;
use std::io::Read;
use std::io::Seek;

use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_types::Digest32;

pub(super) const Q: i64 = 1 << 24;
const H: i64 = 8 * Q;
const MAX_ASSET: u64 = 32_780;

#[derive(Eq, PartialEq)]
pub(super) struct Matrix {
    pub(super) rows: usize,
    pub(super) cols: usize,
    pub(super) values: Vec<i64>,
}

impl Matrix {
    pub(super) fn decode(bytes: &[u8]) -> Result<Self, CellGenerationErrorV2> {
        if bytes.len() < 12 || &bytes[..8] != b"HQ24M001" {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        let rows = usize::from(u16::from_le_bytes([bytes[8], bytes[9]]));
        let cols = usize::from(u16::from_le_bytes([bytes[10], bytes[11]]));
        if !(1..=64).contains(&rows) || !(1..=64).contains(&cols) {
            return Err(CellGenerationErrorV2::Capacity);
        }
        let values = values(&bytes[12..], rows * cols)?;
        Ok(Self { rows, cols, values })
    }

    pub(super) fn apply(&self, input: &[i64]) -> Vec<i64> {
        self.values
            .chunks_exact(self.cols)
            .map(|row| {
                // Width <= 64 and each operand <= 8*2^24: |sum| <= 2^60,
                // well within i128. Private matrices cannot bypass the decoder.
                let sum: i128 = row
                    .iter()
                    .zip(input)
                    .map(|(a, b)| i128::from(*a) * i128::from(*b))
                    .sum();
                // Every layer truncates toward zero once after the integer dot;
                // no float conversion or implementation-dependent accumulation.
                (sum / i128::from(Q)).clamp(-i128::from(H), i128::from(H)) as i64
            })
            .collect()
    }
}

#[derive(Eq, PartialEq)]
pub(super) struct Adapter {
    pub(super) down: Matrix,
    pub(super) up: Matrix,
}

impl Adapter {
    pub(super) fn decode(bytes: &[u8], base: &Matrix) -> Result<Self, CellGenerationErrorV2> {
        if bytes.len() < 12 || &bytes[..8] != b"HQ24A001" {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        let split = usize::from(u16::from_le_bytes([bytes[8], bytes[9]]));
        if bytes[10..12] != [0, 0] || split > bytes.len() - 12 {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        let down = Matrix::decode(&bytes[12..12 + split])?;
        let up = Matrix::decode(&bytes[12 + split..])?;
        if down.rows > 16 || down.cols != base.cols || up.cols != down.rows || up.rows != base.rows
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        Ok(Self { down, up })
    }
}

pub(super) fn read(mut file: File) -> Result<(Vec<u8>, Digest32), CellGenerationErrorV2> {
    let metadata = file
        .metadata()
        .map_err(|_| CellGenerationErrorV2::Unavailable)?;
    if !metadata.is_file() || metadata.len() == 0 || metadata.len() > MAX_ASSET {
        return Err(CellGenerationErrorV2::Capacity);
    }
    file.rewind()
        .map_err(|_| CellGenerationErrorV2::Unavailable)?;
    let mut bytes = Vec::new();
    file.take(MAX_ASSET + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| CellGenerationErrorV2::Unavailable)?;
    if bytes.is_empty() || bytes.len() > MAX_ASSET as usize {
        return Err(CellGenerationErrorV2::Capacity);
    }
    let digest = Digest32::of_bytes(&bytes);
    Ok((bytes, digest))
}

pub(super) fn input(bytes: &[u8], width: usize) -> Result<Vec<i64>, CellGenerationErrorV2> {
    if bytes.len() < 10
        || &bytes[..8] != b"HQ24I001"
        || usize::from(u16::from_le_bytes([bytes[8], bytes[9]])) != width
    {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    values(&bytes[10..], width)
}

fn values(bytes: &[u8], count: usize) -> Result<Vec<i64>, CellGenerationErrorV2> {
    if bytes.len() != count * 8 {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    bytes
        .chunks_exact(8)
        .map(|chunk| {
            let value = i64::from_le_bytes(
                chunk
                    .try_into()
                    .map_err(|_| CellGenerationErrorV2::InvalidBinding)?,
            );
            if !(-H..=H).contains(&value) {
                return Err(CellGenerationErrorV2::InvalidBinding);
            }
            Ok(value)
        })
        .collect()
}

pub(super) fn combine(base: &mut [i64], organ: &[i64], cell: &[i64]) {
    for (index, value) in base.iter_mut().enumerate() {
        *value = (i128::from(*value) + i128::from(organ[index]) + i128::from(cell[index]))
            .clamp(-i128::from(H), i128::from(H)) as i64;
    }
}
