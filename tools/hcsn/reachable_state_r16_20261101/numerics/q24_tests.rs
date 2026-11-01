use super::q24_checkpoint::{decode, encode};
use super::q24_core::{Emission, Kernel, Memory, Probability, SCALE, apportion};
use super::q24_sha256::{digest, hexadecimal};

fn memory(weights: &[u128]) -> Memory {
    Memory {
        addresses: vec![apportion(weights).unwrap()],
        completed: 0,
        clock_ticks: 0,
    }
}

#[test]
fn tiny_positive_support_is_kept_and_structural_zero_is_kept() {
    let p = apportion(&[(1u128 << 80) - 1, 1, 0]).unwrap();
    assert_eq!(
        p,
        Probability {
            counts: vec![SCALE, 0, 0],
            support: vec![true, true, false],
            error_units: 1
        }
    );
}

#[test]
fn nonuniform_rounding_is_normalized_and_radius_is_valid() {
    for seed in 1..100u128 {
        let weights = (0u128..40)
            .map(|index| (seed * (index + 1).pow(3)) % 997)
            .collect::<Vec<_>>();
        let p = apportion(&weights).unwrap();
        assert_eq!(p.counts.iter().sum::<u32>(), SCALE);
        assert!(p.error_units <= 3 * weights.len() as u32);
        assert!(
            weights
                .iter()
                .zip(&p.support)
                .all(|(weight, support)| (*weight > 0) == *support)
        );
    }
}

#[test]
fn impossible_or_overflowing_inputs_are_rejected() {
    assert_eq!(apportion(&[0, 0]), Err("zero probability mass"));
    assert_eq!(apportion(&[u128::MAX, 1]), Err("weight sum overflow"));
    assert_eq!(
        apportion(&[u128::MAX]),
        Err("apportionment product overflow")
    );
    assert_eq!(apportion(&[]), Err("unsupported probability dimension"));
}

#[test]
fn propagation_and_write_are_exact_on_integer_permutations() {
    let kernel = Kernel::new(
        &[
            vec![0, 1, 0, 0],
            vec![1, 0, 0, 0],
            vec![0, 0, 0, 1],
            vec![0, 0, 1, 0],
        ],
        17,
    )
    .unwrap();
    let mut p = memory(&[1, 0, 0, 0]);
    p.advance(&kernel, 0).unwrap();
    assert_eq!(
        p,
        Memory {
            addresses: vec![Probability {
                counts: vec![0, SCALE, 0, 0],
                support: vec![false, true, false, false],
                error_units: 0
            }],
            completed: 1,
            clock_ticks: 17
        }
    );
    p.write(0, 0, 2).unwrap();
    assert_eq!(p.addresses, memory(&[1, 0, 0, 0]).addresses);
}

#[test]
fn observation_preserves_rare_support_but_refuses_uncertified_precision() {
    let emission = Emission::new(&[vec![1, 0], vec![0, 1]]).unwrap();
    let mut p = memory(&[(1u128 << 80) - 1, 1]);
    let original = p.clone();
    assert_eq!(
        p.observe(0, &emission, 1, SCALE / 100),
        Err("precision required: positive observation below Q24 resolution")
    );
    assert_eq!(p, original);
    assert_eq!(
        p.observe(0, &emission, 1, 2 * SCALE),
        Err("precision required: positive observation below Q24 resolution")
    );
    assert_eq!(p, original);
}

#[test]
fn impossible_observation_and_bad_address_do_not_mutate() {
    let emission = Emission::new(&[vec![1, 0], vec![1, 0]]).unwrap();
    let mut p = memory(&[1, 1]);
    let original = p.clone();
    assert_eq!(
        p.observe(0, &emission, 1, 2 * SCALE),
        Err("impossible observation")
    );
    assert_eq!(
        p.observe(8, &emission, 0, 2 * SCALE),
        Err("unknown address")
    );
    assert_eq!(p.write(0, 9, 2), Err("invalid typed write"));
    assert_eq!(p, original);
}

#[test]
fn budget_and_clock_failures_are_atomic_across_addresses() {
    let kernel = Kernel::new(&[vec![1, 3], vec![2, 5]], 1).unwrap();
    let mut p = memory(&[1, 0]);
    p.addresses.push(apportion(&[1, 1]).unwrap());
    let original = p.clone();
    assert_eq!(
        p.advance(&kernel, 0),
        Err("precision required: transition error budget")
    );
    assert_eq!(p, original);
    p.clock_ticks = u64::MAX;
    let overflow = p.clone();
    assert_eq!(p.advance(&kernel, 2 * SCALE), Err("clock overflow"));
    assert_eq!(p, overflow);
}

#[test]
fn checkpoint_preserves_model_and_full_state_then_continues_identically() {
    let kernel = Kernel::new(&[vec![19, 1], vec![2, 7]], 125).unwrap();
    let mut full = memory(&[1, 0]);
    for _ in 0..7 {
        full.advance(&kernel, 2 * SCALE).unwrap();
    }
    let bytes = encode(&full, &[7; 32]).unwrap();
    let mut resumed = decode(&bytes, &[7; 32], 1, 2).unwrap();
    assert_eq!(resumed, full);
    for _ in 0..23 {
        full.advance(&kernel, 2 * SCALE).unwrap();
        resumed.advance(&kernel, 2 * SCALE).unwrap();
    }
    assert_eq!(resumed, full);
    assert_eq!(encode(&resumed, &[7; 32]), encode(&full, &[7; 32]));
}

#[test]
fn checksum_model_dimension_and_semantically_invalid_state_are_rejected() {
    let bytes = encode(&memory(&[1, 1]), &[3; 32]).unwrap();
    assert_eq!(
        decode(&bytes, &[4; 32], 1, 2),
        Err("checkpoint model mismatch")
    );
    assert_eq!(
        decode(&bytes[..bytes.len() - 1], &[3; 32], 1, 2),
        Err("checkpoint schema or length mismatch")
    );
    let mut corrupt = bytes.clone();
    corrupt[70] ^= 1;
    assert_eq!(
        decode(&corrupt, &[3; 32], 1, 2),
        Err("checkpoint checksum mismatch")
    );
    corrupt = bytes.clone();
    corrupt[40..44].copy_from_slice(&2u32.to_le_bytes());
    let length = corrupt.len() - 32;
    let checksum = digest(&corrupt[..length]);
    corrupt[length..].copy_from_slice(&checksum);
    assert_eq!(
        decode(&corrupt, &[3; 32], 1, 2),
        Err("checkpoint dimension mismatch")
    );
    corrupt[40..44].copy_from_slice(&1u32.to_le_bytes());
    corrupt[68..72].copy_from_slice(&0u32.to_le_bytes());
    let checksum = digest(&corrupt[..length]);
    corrupt[length..].copy_from_slice(&checksum);
    assert_eq!(
        decode(&corrupt, &[3; 32], 1, 2),
        Err("invalid normalized Q24 probability")
    );
}

#[test]
fn sha256_matches_published_vectors_across_padding_boundary() {
    assert_eq!(
        hexadecimal(&digest(b"")),
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    );
    assert_eq!(
        hexadecimal(&digest(b"abc")),
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    );
    assert_eq!(
        hexadecimal(&digest(
            b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"
        )),
        "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1"
    );
}
