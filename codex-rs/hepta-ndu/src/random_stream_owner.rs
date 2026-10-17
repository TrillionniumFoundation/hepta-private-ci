//! Product admission owner for deterministic NDU random-stream manifests.

use std::error::Error;
use std::fmt;

use codex_hepta_types::BoundedText;
use codex_hepta_types::CanonicalFieldV1;
use codex_hepta_types::CanonicalValueV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::MAX_MANIFEST_ENUM_BYTES_V1;
use codex_hepta_types::MAX_MANIFEST_VERSION_BYTES_V1;
use codex_hepta_types::NonAuthorizingPosture;
use codex_hepta_types::RandomStreamManifestV1;
use codex_hepta_types::StableId;
use codex_hepta_types::canonical_digest_v1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduRandomStreamPolicyV1 {
    algorithm_namespace: BoundedText<MAX_MANIFEST_ENUM_BYTES_V1>,
    root_seed_digest: Digest32,
    generator_id: BoundedText<MAX_MANIFEST_ENUM_BYTES_V1>,
    generator_version: BoundedText<MAX_MANIFEST_VERSION_BYTES_V1>,
    maximum_counter_span: u64,
    policy_digest: Digest32,
}

impl NduRandomStreamPolicyV1 {
    pub fn new(
        algorithm_namespace: &str,
        root_seed_digest: Digest32,
        generator_id: &str,
        generator_version: &str,
        maximum_counter_span: u64,
    ) -> Result<Self, NduRandomStreamOwnerErrorV1> {
        if root_seed_digest.is_zero() || maximum_counter_span == 0 {
            return Err(NduRandomStreamOwnerErrorV1::InvalidPolicy);
        }
        let algorithm_namespace = bounded_manifest_enum(algorithm_namespace)?;
        let generator_id = bounded_manifest_enum(generator_id)?;
        let generator_version = BoundedText::try_from_str(generator_version)
            .map_err(|_| NduRandomStreamOwnerErrorV1::InvalidPolicy)?;
        let type_id = StableId::new("utility.ndu:random-stream-policy-v1")
            .map_err(|_| NduRandomStreamOwnerErrorV1::InvalidPolicy)?;
        let fields = [
            CanonicalFieldV1 {
                name: "algorithm_namespace",
                value: CanonicalValueV1::Text(algorithm_namespace.as_str()),
            },
            CanonicalFieldV1 {
                name: "generator_id",
                value: CanonicalValueV1::Text(generator_id.as_str()),
            },
            CanonicalFieldV1 {
                name: "generator_version",
                value: CanonicalValueV1::Text(generator_version.as_str()),
            },
            CanonicalFieldV1 {
                name: "maximum_counter_span",
                value: CanonicalValueV1::U64(maximum_counter_span),
            },
            CanonicalFieldV1 {
                name: "root_seed_digest",
                value: CanonicalValueV1::Digest(root_seed_digest),
            },
        ];
        let policy_digest = canonical_digest_v1(&type_id, 1, &fields)
            .map_err(|_| NduRandomStreamOwnerErrorV1::InvalidPolicy)?;
        Ok(Self {
            algorithm_namespace,
            root_seed_digest,
            generator_id,
            generator_version,
            maximum_counter_span,
            policy_digest,
        })
    }

    #[must_use]
    pub const fn root_seed_digest(&self) -> Digest32 {
        self.root_seed_digest
    }

    #[must_use]
    pub const fn policy_digest(&self) -> Digest32 {
        self.policy_digest
    }
}

fn bounded_manifest_enum(
    value: &str,
) -> Result<BoundedText<MAX_MANIFEST_ENUM_BYTES_V1>, NduRandomStreamOwnerErrorV1> {
    let bytes = value.as_bytes();
    if bytes.is_empty()
        || bytes.len() > MAX_MANIFEST_ENUM_BYTES_V1
        || !bytes[0].is_ascii_lowercase()
        || !bytes[bytes.len() - 1].is_ascii_alphanumeric()
        || bytes.iter().any(|byte| {
            !(byte.is_ascii_lowercase()
                || byte.is_ascii_digit()
                || matches!(byte, b'.' | b'_' | b'-' | b':'))
        })
    {
        return Err(NduRandomStreamOwnerErrorV1::InvalidPolicy);
    }
    BoundedText::try_from_str(value).map_err(|_| NduRandomStreamOwnerErrorV1::InvalidPolicy)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduRandomStreamAdmissionV1 {
    manifest_digest: Digest32,
    policy_digest: Digest32,
    root_seed_digest: Digest32,
    episode_id: StableId,
    decision_id: StableId,
    stream_id: StableId,
    counter_start: u64,
    counter_end_exclusive: u64,
    authority: NonAuthorizingPosture,
}

impl NduRandomStreamAdmissionV1 {
    #[must_use]
    pub const fn manifest_digest(&self) -> Digest32 {
        self.manifest_digest
    }

    #[must_use]
    pub const fn policy_digest(&self) -> Digest32 {
        self.policy_digest
    }

    #[must_use]
    pub const fn root_seed_digest(&self) -> Digest32 {
        self.root_seed_digest
    }

    #[must_use]
    pub fn episode_id(&self) -> &StableId {
        &self.episode_id
    }

    #[must_use]
    pub fn decision_id(&self) -> &StableId {
        &self.decision_id
    }

    #[must_use]
    pub fn stream_id(&self) -> &StableId {
        &self.stream_id
    }

    #[must_use]
    pub const fn counter_start(&self) -> u64 {
        self.counter_start
    }

    #[must_use]
    pub const fn counter_end_exclusive(&self) -> u64 {
        self.counter_end_exclusive
    }

    #[must_use]
    pub const fn authority(&self) -> NonAuthorizingPosture {
        self.authority
    }
}

pub fn admit_ndu_random_stream_manifest_v1(
    policy: &NduRandomStreamPolicyV1,
    manifest: &RandomStreamManifestV1,
    expected_episode_id: &StableId,
    expected_decision_id: &StableId,
) -> Result<NduRandomStreamAdmissionV1, NduRandomStreamOwnerErrorV1> {
    manifest
        .validate()
        .map_err(|_| NduRandomStreamOwnerErrorV1::InvalidManifest)?;
    if manifest.algorithm_namespace() != policy.algorithm_namespace.as_str()
        || manifest.root_seed_digest() != policy.root_seed_digest
        || manifest.generator_id() != policy.generator_id.as_str()
        || manifest.generator_version() != policy.generator_version.as_str()
    {
        return Err(NduRandomStreamOwnerErrorV1::PolicyMismatch);
    }
    if manifest.episode_id() != expected_episode_id
        || manifest.decision_id() != expected_decision_id
    {
        return Err(NduRandomStreamOwnerErrorV1::OwnerBindingMismatch);
    }
    let span = manifest
        .counter_end_exclusive()
        .checked_sub(manifest.counter_start())
        .ok_or(NduRandomStreamOwnerErrorV1::InvalidManifest)?;
    if span == 0 || span > policy.maximum_counter_span {
        return Err(NduRandomStreamOwnerErrorV1::CounterSpanExceeded);
    }
    let manifest_digest = manifest
        .semantic_digest()
        .map_err(|_| NduRandomStreamOwnerErrorV1::InvalidManifest)?;
    Ok(NduRandomStreamAdmissionV1 {
        manifest_digest,
        policy_digest: policy.policy_digest,
        root_seed_digest: manifest.root_seed_digest(),
        episode_id: manifest.episode_id().clone(),
        decision_id: manifest.decision_id().clone(),
        stream_id: manifest.stream_id().clone(),
        counter_start: manifest.counter_start(),
        counter_end_exclusive: manifest.counter_end_exclusive(),
        authority: NonAuthorizingPosture::DENY_ALL,
    })
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduRandomStreamOwnerErrorV1 {
    InvalidPolicy,
    InvalidManifest,
    PolicyMismatch,
    OwnerBindingMismatch,
    CounterSpanExceeded,
}

impl fmt::Display for NduRandomStreamOwnerErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for NduRandomStreamOwnerErrorV1 {}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn assert_policy_matches_manifest(
        algorithm_namespace: &str,
        generator_id: &str,
        generator_version: &str,
    ) {
        let seed = digest("seed");
        let policy = NduRandomStreamPolicyV1::new(
            algorithm_namespace,
            seed,
            generator_id,
            generator_version,
            /*maximum_counter_span*/ 8,
        );
        let manifest = RandomStreamManifestV1::new(
            id("manifest"),
            seed,
            algorithm_namespace,
            id("episode"),
            id("decision"),
            id("stream"),
            /*counter_start*/ 0,
            /*counter_end_exclusive*/ 8,
            generator_id,
            generator_version,
        );
        assert_eq!(policy.is_ok(), manifest.is_ok());
        if let (Ok(policy), Ok(manifest)) = (policy, manifest) {
            let admitted = admit_ndu_random_stream_manifest_v1(
                &policy,
                &manifest,
                &id("episode"),
                &id("decision"),
            )
            .expect("matching manifest admission");
            assert_eq!(admitted.policy_digest(), policy.policy_digest());
        }
    }

    #[test]
    fn policy_enum_rules_and_byte_limits_match_native_manifest() {
        for token in [
            "", "7", "UPPER", "_g", "g-", "g:", "g g", "g\0", "g1", "g:g", "g", "é",
        ] {
            assert_policy_matches_manifest(token, "g", "1");
            assert_policy_matches_manifest("utility.ndu", token, "1");
        }
        for length in [63, 64, 65] {
            let token = "g".repeat(length);
            assert_policy_matches_manifest(&token, "g", "1");
            assert_policy_matches_manifest("utility.ndu", &token, "1");
        }
    }

    #[test]
    fn policy_version_utf8_bounds_match_native_manifest_without_enum_rules() {
        for version in ["", "\0", "1\0", "1\n", " ", "e\u{301}"] {
            assert_policy_matches_manifest("utility.ndu", "g", version);
        }
        for length in [63, 64, 65] {
            assert_policy_matches_manifest("utility.ndu", "g", &"v".repeat(length));
        }
        for version in [
            "🧪".repeat(15) + "abc",
            "🧪".repeat(16),
            "🧪".repeat(16) + "a",
        ] {
            assert_policy_matches_manifest("utility.ndu", "g", &version);
        }
    }

    #[test]
    fn owner_binds_seed_policy_episode_decision_and_counter_window() {
        let seed = digest("root-seed");
        let policy =
            NduRandomStreamPolicyV1::new("utility.ndu", seed, "chacha20-counter", "1.0.0", 1_024)
                .expect("policy");
        let manifest = RandomStreamManifestV1::new(
            id("manifest-1"),
            seed,
            "utility.ndu",
            id("episode-1"),
            id("decision-1"),
            id("stream-1"),
            10,
            20,
            "chacha20-counter",
            "1.0.0",
        )
        .expect("manifest");
        let receipt = admit_ndu_random_stream_manifest_v1(
            &policy,
            &manifest,
            &id("episode-1"),
            &id("decision-1"),
        )
        .expect("admission");
        assert_eq!(
            receipt.manifest_digest(),
            manifest.semantic_digest().expect("digest")
        );
        assert_eq!(receipt.root_seed_digest(), seed);
        assert_eq!(receipt.authority(), NonAuthorizingPosture::DENY_ALL);
    }

    #[test]
    fn owner_rejects_cross_decision_replay() {
        let seed = digest("seed");
        let policy =
            NduRandomStreamPolicyV1::new("utility.ndu", seed, "generator", "1", 8).expect("policy");
        let manifest = RandomStreamManifestV1::new(
            id("manifest"),
            seed,
            "utility.ndu",
            id("episode"),
            id("decision-a"),
            id("stream"),
            0,
            1,
            "generator",
            "1",
        )
        .expect("manifest");
        assert_eq!(
            admit_ndu_random_stream_manifest_v1(
                &policy,
                &manifest,
                &id("episode"),
                &id("decision-b"),
            ),
            Err(NduRandomStreamOwnerErrorV1::OwnerBindingMismatch)
        );
    }

    #[test]
    fn owner_rejects_root_seed_substitution() {
        let policy = NduRandomStreamPolicyV1::new(
            "utility.ndu",
            digest("approved-seed"),
            "generator",
            "1",
            8,
        )
        .expect("policy");
        let manifest = RandomStreamManifestV1::new(
            id("manifest"),
            digest("substituted-seed"),
            "utility.ndu",
            id("episode"),
            id("decision"),
            id("stream"),
            0,
            1,
            "generator",
            "1",
        )
        .expect("manifest");
        assert_eq!(
            admit_ndu_random_stream_manifest_v1(
                &policy,
                &manifest,
                &id("episode"),
                &id("decision"),
            ),
            Err(NduRandomStreamOwnerErrorV1::PolicyMismatch)
        );
    }
}
