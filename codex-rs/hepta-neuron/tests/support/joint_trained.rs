//! Complete historical width32 Joint descendant, recovered without new training.
//! The public input is the historical synthetic mechanism case. These weights
//! do not qualify natural-task quality, optimizer resume or the missing parent.

use std::io;

use codex_hepta_types::Digest32;

use super::synthetic::Assets;

pub(crate) const PROVENANCE: &str = include_str!("../fixtures/joint-trained-v1.json");
const PROVENANCE_SHA256: &str = "f2dbd68ab42137d7c604d9026fa60757304fdde4688ba4e17ef6f42fd927e704";
const WEIGHTS_SHA256: &str = "41ce6de8a9095e1ef6b8756c3117a160ed40acfad8b297390de95083664d223e";
const PUBLIC_SHA256: &str = "86c55417fdf2abdd065fc9828c40260aed0ded4a0d607c551e15b2f6b5fd2c00";
const WEIGHTS_BYTES: usize = 4_778_937;
const CHUNKS: [&[u8]; 13] = [
    include_bytes!("../fixtures/joint-trained-weights-000.bin"),
    include_bytes!("../fixtures/joint-trained-weights-001.bin"),
    include_bytes!("../fixtures/joint-trained-weights-002.bin"),
    include_bytes!("../fixtures/joint-trained-weights-003.bin"),
    include_bytes!("../fixtures/joint-trained-weights-004.bin"),
    include_bytes!("../fixtures/joint-trained-weights-005.bin"),
    include_bytes!("../fixtures/joint-trained-weights-006.bin"),
    include_bytes!("../fixtures/joint-trained-weights-007.bin"),
    include_bytes!("../fixtures/joint-trained-weights-008.bin"),
    include_bytes!("../fixtures/joint-trained-weights-009.bin"),
    include_bytes!("../fixtures/joint-trained-weights-010.bin"),
    include_bytes!("../fixtures/joint-trained-weights-011.bin"),
    include_bytes!("../fixtures/joint-trained-weights-012.bin"),
];
const PUBLIC: &[u8] = include_bytes!("../fixtures/joint-trained-public.hps");

pub(crate) fn assets() -> io::Result<Assets> {
    let mut weights = Vec::with_capacity(WEIGHTS_BYTES);
    for chunk in CHUNKS {
        if chunk.is_empty() || chunk.len() > 393_216 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "trained weight chunk bound",
            ));
        }
        weights.extend_from_slice(chunk);
    }
    if weights.len() != WEIGHTS_BYTES
        || Digest32::of_bytes(&weights).to_string() != WEIGHTS_SHA256
        || PUBLIC.len() != 78_188
        || Digest32::of_bytes(PUBLIC).to_string() != PUBLIC_SHA256
        || Digest32::of_bytes(PROVENANCE.as_bytes()).to_string() != PROVENANCE_SHA256
    {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "trained asset identity mismatch",
        ));
    }
    // Assets is only a pair of byte vectors. The existing independent wire
    // reader accepts these exact hashes; it does not synthesize trained data.
    Ok(Assets {
        weights,
        public: PUBLIC.to_vec(),
    })
}
