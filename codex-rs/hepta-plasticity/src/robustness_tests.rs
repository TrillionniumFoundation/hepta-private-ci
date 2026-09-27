use std::fs::OpenOptions;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use crate::*;

struct TempFile {
    path: PathBuf,
}

impl TempFile {
    fn new(label: &str, index: usize) -> Self {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        Self {
            path: std::env::temp_dir().join(format!(
                "hepta-plasticity-robustness-{label}-{}-{nonce}-{index}.bin",
                std::process::id()
            )),
        }
    }

    fn create_with(&self, bytes: &[u8]) -> std::fs::File {
        let mut file = OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(&self.path)
            .expect("create robustness file");
        file.write_all(bytes).expect("write robustness bytes");
        file.sync_all().expect("sync robustness bytes");
        file.seek(SeekFrom::Start(0)).expect("rewind robustness file");
        file
    }
}

impl Drop for TempFile {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.path);
    }
}

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid id")
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn window() -> ProposalWindowV2 {
    ProposalWindowV2 {
        window_id: id("window:robustness"),
        window_digest: digest(b"window"),
    }
}

fn profile() -> ParameterGeneratorProfileV3 {
    let artifact = digest(b"artifact");
    let proposal_window = window();
    let rules = ["a", "b"]
        .into_iter()
        .map(|name| ParameterMutationRuleV1 {
            parameter_id: id(&format!("parameter:{name}")),
            layer_id: id("layer:1"),
            surface: ParameterMutationSurfaceV1::LearnableParameter,
            minimum_delta: FixedQ32::from_raw(-1_000),
            maximum_delta: FixedQ32::from_raw(1_000),
        })
        .collect();
    ParameterGeneratorProfileV3 {
        selected_artifact_digest: artifact,
        window: proposal_window.clone(),
        norm_layers: vec![LayerNormDenominatorV2 {
            layer_id: id("layer:1"),
            baseline_squared_l2_raw_q64: 1_000_000_000_000,
        }],
        mutation_policy: build_parameter_mutation_policy_v1(
            id("policy:robustness"),
            digest(b"grammar"),
            artifact,
            proposal_window,
            rules,
        )
        .expect("policy"),
        update_scales: vec![FixedQ32::from_raw(1), FixedQ32::from_raw(2)],
        signals: vec![
            ParameterPlasticitySignalV3 {
                layer_id: id("layer:1"),
                parameter_id: id("parameter:b"),
                eligibility: FixedQ32::from_raw(2),
                modulator: FixedQ32::from_raw(3),
                learning_rate: FixedQ32::from_raw(4),
                lower_bound: FixedQ32::from_raw(-1_000),
                upper_bound: FixedQ32::from_raw(1_000),
                evidence_digest: digest(b"signal-b"),
            },
            ParameterPlasticitySignalV3 {
                layer_id: id("layer:1"),
                parameter_id: id("parameter:a"),
                eligibility: FixedQ32::from_raw(5),
                modulator: FixedQ32::from_raw(6),
                learning_rate: FixedQ32::from_raw(7),
                lower_bound: FixedQ32::from_raw(-1_000),
                upper_bound: FixedQ32::from_raw(1_000),
                evidence_digest: digest(b"signal-a"),
            },
        ],
    }
}

#[test]
fn candidate_and_profile_order_do_not_change_generated_identity() {
    let canonical = generate_parameter_candidates_v3(profile()).expect("canonical generation");
    let mut reordered = profile();
    reordered.norm_layers.reverse();
    reordered.update_scales.reverse();
    reordered.signals.reverse();
    reordered.mutation_policy.rules.reverse();
    let observed = generate_parameter_candidates_v3(reordered).expect("reordered generation");
    assert_eq!(canonical, observed);
}

#[test]
fn generator_and_coverage_digests_bind_semantic_mutations() {
    let baseline_profile = profile();
    let baseline_generated =
        generate_parameter_candidates_v3(baseline_profile.clone()).expect("baseline generation");
    let baseline_coverage = build_generator_coverage_receipt_v1(
        &baseline_profile,
        digest(b"expected-set"),
        2,
        digest(b"owner-frontier"),
        Vec::new(),
    )
    .expect("baseline coverage");

    let mut scale = baseline_profile.clone();
    scale.update_scales[0] = FixedQ32::from_raw(3);
    let scale_generated = generate_parameter_candidates_v3(scale.clone()).expect("scale change");
    assert_ne!(baseline_generated.generator_digest, scale_generated.generator_digest);
    let scale_coverage = build_generator_coverage_receipt_v1(
        &scale,
        digest(b"expected-set"),
        2,
        digest(b"owner-frontier"),
        Vec::new(),
    )
    .expect("scale coverage");
    assert_ne!(baseline_coverage.receipt_digest, scale_coverage.receipt_digest);

    let owner_coverage = build_generator_coverage_receipt_v1(
        &baseline_profile,
        digest(b"expected-set"),
        2,
        digest(b"other-owner-frontier"),
        Vec::new(),
    )
    .expect("owner coverage");
    assert_ne!(baseline_coverage.receipt_digest, owner_coverage.receipt_digest);

    let inventory_coverage = build_generator_coverage_receipt_v1(
        &baseline_profile,
        digest(b"other-expected-set"),
        2,
        digest(b"owner-frontier"),
        Vec::new(),
    )
    .expect("inventory coverage");
    assert_ne!(baseline_coverage.receipt_digest, inventory_coverage.receipt_digest);
}

#[test]
fn corrupt_parameter_registry_bytes_fail_closed_without_panicking() {
    for length in 1..=256 {
        let fixture = TempFile::new("parameter", length);
        let mut state = u64::try_from(length).expect("length") | 1;
        let mut bytes = Vec::with_capacity(length);
        for _ in 0..length {
            state ^= state << 13;
            state ^= state >> 7;
            state ^= state << 17;
            bytes.push(state as u8);
        }
        let file = fixture.create_with(&bytes);
        let result = DurableProposalRegistry::open(file, digest(b"scope"), 7, 8);
        assert!(result.is_err(), "corrupt length {length} unexpectedly opened");
    }
}

#[test]
fn corrupt_topology_registry_bytes_fail_closed_without_panicking() {
    for length in 1..=256 {
        let fixture = TempFile::new("topology", length);
        let bytes = (0..length)
            .map(|index| ((index * 37 + length * 11) & 0xff) as u8)
            .collect::<Vec<_>>();
        let file = fixture.create_with(&bytes);
        let result = DurableTopologyProposalRegistryV1::resume_unacknowledged_bootstrap(
            file,
            digest(b"scope"),
            9,
            8,
        );
        assert!(result.is_err(), "corrupt length {length} unexpectedly opened");
    }
}
