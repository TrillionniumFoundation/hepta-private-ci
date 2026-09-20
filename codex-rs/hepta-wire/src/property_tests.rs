use std::error::Error;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::WireEnvelope;
use crate::WireEnvelopeV2;
use crate::decode_frame;

struct Lcg(u64);

impl Lcg {
    fn next(&mut self) -> u64 {
        self.0 = self
            .0
            .wrapping_mul(6_364_136_223_846_793_005)
            .wrapping_add(1_442_695_040_888_963_407);
        self.0
    }

    fn byte(&mut self) -> u8 {
        self.next().to_be_bytes()[0]
    }
}

fn generated_id(rng: &mut Lcg, prefix: &str) -> Result<StableId, Box<dyn Error>> {
    const ALPHABET: &[u8] = b"abcdefghijklmnopqrstuvwxyz0123456789";
    let len = 1 + usize::from(rng.byte() % 24);
    let mut value = String::with_capacity(prefix.len() + len + 1);
    value.push_str(prefix);
    value.push('.');
    for _ in 0..len {
        let index = usize::from(rng.byte()) % ALPHABET.len();
        value.push(char::from(ALPHABET[index]));
    }
    Ok(StableId::new(value)?)
}

#[test]
fn deterministic_property_round_trips_v1_and_v2() -> Result<(), Box<dyn Error>> {
    let mut rng = Lcg(0x4850_5441_5749_5245);
    for case in 0..512_u64 {
        let schema = generated_id(&mut rng, "schema")?;
        let producer = generated_id(&mut rng, "producer")?;
        let generation = Generation::new(case + 1)?;
        let payload_len = 1 + usize::from(rng.byte()) * 8;
        let mut payload = vec![0_u8; payload_len];
        for byte in &mut payload {
            *byte = rng.byte();
        }

        let v1 = WireEnvelope::new(
            schema.clone(),
            producer.clone(),
            generation,
            payload.clone(),
        )?;
        let v1_bytes = v1.encode();
        assert_eq!(WireEnvelope::decode(&v1_bytes)?, v1);
        assert_eq!(v1.encode(), v1_bytes);

        let v2 = WireEnvelopeV2::new(schema, producer, generation, payload)?;
        let v2_bytes = v2.encode();
        assert_eq!(WireEnvelopeV2::decode(&v2_bytes)?, v2);
        assert_eq!(v2.encode(), v2_bytes);
    }
    Ok(())
}

#[test]
fn arbitrary_bounded_bytes_never_panic_the_frame_decoder() {
    let mut rng = Lcg(0x4452_4f50_2d46_555a);
    for _ in 0..4_096 {
        let len = usize::from(rng.byte()) * 4;
        let mut bytes = vec![0_u8; len];
        for byte in &mut bytes {
            *byte = rng.byte();
        }
        let _ = decode_frame(&bytes);
    }
}

#[test]
fn v2_same_payload_with_different_metadata_changes_digest() -> Result<(), Box<dyn Error>> {
    let payload = b"identical".to_vec();
    let left = WireEnvelopeV2::new(
        StableId::new("schema.left")?,
        StableId::new("producer")?,
        Generation::new(1)?,
        payload.clone(),
    )?;
    let right = WireEnvelopeV2::new(
        StableId::new("schema.right")?,
        StableId::new("producer")?,
        Generation::new(1)?,
        payload,
    )?;
    assert_ne!(left.frame_digest(), right.frame_digest());
    Ok(())
}
