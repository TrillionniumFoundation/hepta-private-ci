use std::error::Error;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::WireEnvelope;
use crate::WireEnvelopeV2;
use crate::decode_envelope;

fn next(seed: &mut u64) -> u64 {
    *seed = seed
        .wrapping_mul(6_364_136_223_846_793_005)
        .wrapping_add(1_442_695_040_888_963_407);
    *seed
}

fn generated_payload(seed: &mut u64) -> Result<Vec<u8>, Box<dyn Error>> {
    let length = usize::try_from(next(seed) % 2048 + 1)?;
    let bytes = (0..length)
        .map(|_| u8::try_from(next(seed) & 0xff))
        .collect::<Result<Vec<_>, _>>()?;
    Ok(bytes)
}

#[test]
fn generated_valid_envelopes_round_trip_canonically() -> Result<(), Box<dyn Error>> {
    let mut seed = 0x9e37_79b9_7f4a_7c15;
    for case in 0..256_u64 {
        let schema = StableId::new(format!("hepta.property.schema.{case}"))?;
        let producer = StableId::new(format!("hepta.property.producer.{case}"))?;
        let generation = Generation::new(next(&mut seed) | 1)?;
        let payload = generated_payload(&mut seed)?;

        let v1 = WireEnvelope::new(
            schema.clone(),
            producer.clone(),
            generation,
            payload.clone(),
        )?;
        let v1_bytes = v1.encode();
        assert_eq!(WireEnvelope::decode(&v1_bytes), Ok(v1));

        let v2 = WireEnvelopeV2::new(schema, producer, generation, payload)?;
        let v2_bytes = v2.encode();
        assert_eq!(WireEnvelopeV2::decode(&v2_bytes), Ok(v2));
        assert_eq!(decode_envelope(&v2_bytes)?.encode(), v2_bytes);
    }
    Ok(())
}

#[test]
fn generated_arbitrary_byte_corpus_never_panics() -> Result<(), Box<dyn Error>> {
    let mut seed = 0xd1b5_4a32_d192_ed03;
    for _ in 0..4096 {
        let length = usize::try_from(next(&mut seed) % 768)?;
        let bytes = (0..length)
            .map(|_| u8::try_from(next(&mut seed) & 0xff))
            .collect::<Result<Vec<_>, _>>()?;
        let _ = decode_envelope(&bytes);
    }
    Ok(())
}
