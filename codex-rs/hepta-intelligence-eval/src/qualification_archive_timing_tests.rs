//! Wire-layout checks only; these bytes are not authenticated time evidence.

use super::*;
use crate::ObservedFutureWindowV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;

#[test]
fn boxed_archived_timing_retains_unboxed_wire_layout_and_strict_decode() {
    let id = |value: &str| StableId::new(value).expect("fixture id");
    for seed in [1_u8, 9] {
        let digest = Digest32::of_bytes(&[seed]);
        let timing = LongitudinalTimeEvidenceV1 {
            frozen_unix_micros: u64::from(seed),
            windows: vec![ObservedFutureWindowV1 {
                window_id: id("window"),
                snapshot_id: id("snapshot"),
                starts_unix_micros: 20,
                ends_unix_micros: 40,
                observation_count: 4,
                observed_source_cut: digest,
            }],
            observer: SignedLearningEvidenceV1 {
                evidence_id: id("evidence"),
                principal_id: id("observer"),
                role: LearningEvidenceRoleV1::Observer,
                trust_digest: digest,
                scope_digest: digest,
                objective_digest: digest,
                authority_epoch: 1,
                issued_at: 50,
                expires_at: 90,
                payload_digest: digest,
                signature: [seed; 64],
            },
        };
        let minimum_window_micros = 10_u64;
        let archived = ArchivedTiming::capture(ProductTimingEvidenceV1::SystemLongitudinal {
            timing: &timing,
            minimum_window_micros,
        });
        let mut original = codec::Writer::default();
        1_u8.write(&mut original).expect("original variant tag");
        timing
            .write(&mut original)
            .expect("original by-value timing");
        minimum_window_micros
            .write(&mut original)
            .expect("original minimum");
        let mut current = codec::Writer::default();
        archived.write(&mut current).expect("boxed timing");
        let bytes = current.finish();
        assert_eq!(bytes, original.finish());

        let mut reader = codec::Reader::new(&bytes).expect("bounded bytes");
        assert_eq!(
            ArchivedTiming::read(&mut reader).expect("round trip"),
            archived
        );
        reader.finish().expect("complete consumption");
        for cut in 0..bytes.len() {
            let mut reader = codec::Reader::new(&bytes[..cut]).expect("bounded prefix");
            assert!(ArchivedTiming::read(&mut reader).is_err());
        }
        let mut unknown = bytes;
        unknown[0] = 2;
        let mut reader = codec::Reader::new(&unknown).expect("bounded changed tag");
        assert!(ArchivedTiming::read(&mut reader).is_err());
    }
}
