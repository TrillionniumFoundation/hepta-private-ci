use serde::Deserialize;
use serde::Serialize;

pub const MAX_KERNEL_EVIDENCE_ENVELOPE_BYTES: usize = 48 * 1024;
pub const MAX_KERNEL_EVIDENCE_REQUIRED_ROLES: usize = 32;
const KERNEL_EVIDENCE_PAGE_PREFIX: &str = "page:v1:";
const KERNEL_EVIDENCE_PROFILE_PREFIX: &str = "profile:v1:";

/// Signed qualification evidence append request. The signature is over the
/// canonical kernel.evidence envelope, not this transport wrapper.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct KernelEvidenceAppendIngress {
    pub issuer_id: String,
    pub key_epoch: u64,
    pub message_id: String,
    pub sequence: u64,
    pub expires_at_ms: u64,
    pub signature_hex: String,
    pub envelope_json: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct KernelEvidenceCandidateV1 {
    pub candidate_id: String,
    pub source_commit: String,
    pub source_tree: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct KernelEvidenceQueryV1 {
    pub candidate: KernelEvidenceCandidateV1,
    pub claim_class: String,
}

/// Decoded claim class, exclusive sequence cursor and bounded page limit.
/// This names the existing tuple; it is selector data, not an authority grant.
pub type KernelEvidencePageSelector<'a> = (&'a str, Option<u64>, u16);

impl KernelEvidenceQueryV1 {
    /// Product pages remain comfortably below the 48 KiB frame even when every
    /// reference uses maximum identifiers. The store itself retains the wider
    /// 512-row internal compatibility limit.
    pub const MAX_PAGE_LIMIT: u16 = 128;

    pub fn paged(
        candidate: KernelEvidenceCandidateV1,
        claim_class: &str,
        after_seq: Option<u64>,
        limit: u16,
    ) -> Result<Self, String> {
        validate_selector_token(claim_class, "claim class")?;
        if limit == 0 || limit > Self::MAX_PAGE_LIMIT {
            return Err(format!(
                "kernel evidence page limit must be between 1 and {}",
                Self::MAX_PAGE_LIMIT
            ));
        }
        Ok(Self {
            candidate,
            claim_class: format!(
                "{KERNEL_EVIDENCE_PAGE_PREFIX}{claim_class}:{}:{limit}",
                after_seq.unwrap_or(0)
            ),
        })
    }

    /// Returns the strict page selector. A plain claim class is a legacy full
    /// query. Anything entering the reserved `page:` namespace but not matching
    /// the exact grammar is rejected instead of falling back.
    pub fn page_selector(&self) -> Result<Option<KernelEvidencePageSelector<'_>>, String> {
        if !self.claim_class.starts_with("page:") {
            return Ok(None);
        }
        let parts = self.claim_class.split(':').collect::<Vec<_>>();
        if parts.len() != 5 || parts[0] != "page" || parts[1] != "v1" {
            return Err("malformed kernel evidence page selector".to_string());
        }
        validate_selector_token(parts[2], "claim class")?;
        if parts[3].is_empty() || !parts[3].bytes().all(|byte| byte.is_ascii_digit()) {
            return Err("kernel evidence page cursor must be an unsigned decimal".to_string());
        }
        let after_seq = parts[3]
            .parse::<u64>()
            .map_err(|_| "kernel evidence page cursor exceeds u64".to_string())?;
        if parts[4].is_empty() || !parts[4].bytes().all(|byte| byte.is_ascii_digit()) {
            return Err("kernel evidence page limit must be an unsigned decimal".to_string());
        }
        let limit = parts[4]
            .parse::<u16>()
            .map_err(|_| "kernel evidence page limit exceeds u16".to_string())?;
        if limit == 0 || limit > Self::MAX_PAGE_LIMIT {
            return Err(format!(
                "kernel evidence page limit must be between 1 and {}",
                Self::MAX_PAGE_LIMIT
            ));
        }
        Ok(Some((
            parts[2],
            (after_seq != 0).then_some(after_seq),
            limit,
        )))
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct KernelEvidenceVerifyV1 {
    pub candidate: KernelEvidenceCandidateV1,
    pub claim_class: String,
    pub required_roles: Vec<String>,
}

impl KernelEvidenceVerifyV1 {
    /// A profiled request names one registered owner policy; it cannot carry a
    /// caller-provided role subset in parallel.
    pub fn profiled(candidate: KernelEvidenceCandidateV1, profile: &str) -> Result<Self, String> {
        validate_selector_token(profile, "verification profile")?;
        Ok(Self {
            candidate,
            claim_class: format!("{KERNEL_EVIDENCE_PROFILE_PREFIX}{profile}"),
            required_roles: Vec::new(),
        })
    }

    pub fn profile_name(&self) -> Result<Option<&str>, String> {
        if !self.claim_class.starts_with("profile:") {
            return Ok(None);
        }
        let parts = self.claim_class.split(':').collect::<Vec<_>>();
        if parts.len() != 3 || parts[0] != "profile" || parts[1] != "v1" {
            return Err("malformed kernel evidence verification profile selector".to_string());
        }
        validate_selector_token(parts[2], "verification profile")?;
        if !self.required_roles.is_empty() {
            return Err(
                "profiled kernel evidence verification cannot include caller-defined roles"
                    .to_string(),
            );
        }
        Ok(Some(parts[2]))
    }
}

/// JSON is the canonical serde representation of the kernel.evidence native
/// result. Keeping storage-owned enums out of this transport crate avoids a
/// protocol -> state-store dependency while preserving strict frame bounds.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct KernelEvidenceResult {
    pub json: String,
}

fn validate_selector_token(value: &str, label: &str) -> Result<(), String> {
    if value.is_empty()
        || value.len() > 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_lowercase() || byte == b'_')
    {
        return Err(format!(
            "kernel evidence {label} must be 1..=64 lowercase ASCII letters/underscores"
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn candidate() -> KernelEvidenceCandidateV1 {
        KernelEvidenceCandidateV1 {
            candidate_id: "candidate:one".to_string(),
            source_commit: "a".repeat(40),
            source_tree: "b".repeat(40),
        }
    }

    #[test]
    fn page_selector_round_trips_and_rejects_malformed_reserved_forms() {
        let request = KernelEvidenceQueryV1::paged(candidate(), "exact_source", Some(42), 64)
            .expect("page request");
        assert_eq!(
            request.page_selector().expect("parse page"),
            Some(("exact_source", Some(42), 64))
        );
        let first =
            KernelEvidenceQueryV1::paged(candidate(), "exact_source", None, 1).expect("first page");
        assert_eq!(
            first.page_selector().expect("parse first page"),
            Some(("exact_source", None, 1))
        );
        for claim_class in [
            "page:v1:exact_source:bad:1",
            "page:v1:exact_source:1:0",
            "page:v1:exact_source:1:129",
            "page:v2:exact_source:1:1",
            "page:v1:ExactSource:1:1",
        ] {
            let request = KernelEvidenceQueryV1 {
                candidate: candidate(),
                claim_class: claim_class.to_string(),
            };
            assert!(request.page_selector().is_err(), "accepted {claim_class}");
        }
    }

    #[test]
    fn profile_selector_cannot_smuggle_roles_or_unknown_grammar() {
        let request = KernelEvidenceVerifyV1::profiled(candidate(), "mandatory_tests_reviewed")
            .expect("profile request");
        assert_eq!(
            request.profile_name().expect("profile parse"),
            Some("mandatory_tests_reviewed")
        );
        let mut with_roles = request;
        with_roles.required_roles.push("generator".to_string());
        assert!(with_roles.profile_name().is_err());
        let malformed = KernelEvidenceVerifyV1 {
            candidate: candidate(),
            claim_class: "profile:v2:mandatory_tests_reviewed".to_string(),
            required_roles: Vec::new(),
        };
        assert!(malformed.profile_name().is_err());
    }
}
