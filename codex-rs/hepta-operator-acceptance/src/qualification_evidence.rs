use std::collections::BTreeMap;
use std::path::Path;

use crate::AcceptanceError;
use crate::durable::sha256;
use crate::manifest_inventory::VerifiedManifest;
use crate::model::CandidateBinding;
use crate::model::FrozenProductBinding;
use crate::model::OracleBinding;
use crate::model::QualificationReceiptBinding;
use crate::qualification_runs::validate_soak;

pub(crate) const CANDIDATE_HEAD: &str = "3110c5aba5daa0af1498b3eec85272011589ce8e";
pub(crate) const CANDIDATE_TREE: &str = "90164e397240e3e5e85027876394df7045991ff6";
pub(crate) const CANDIDATE_BASE: &str = "89a335ed50258dc9dc5b3d7f410db61b431244f9";
pub(crate) const CANDIDATE_BUNDLE_SHA256: &str =
    "eb57cf87d7b85b85722d0ad3802ee414717e460d933c8acd4665decaf795592b";
const QUALIFICATION_MANIFEST_SHA256: &str =
    "9ed5fcc120af363f89c83969ac29956722f66c780d4b9bb7e86a27d7965d663f";
const QUALIFICATION_MANIFEST_ENTRIES: usize = 1_786;
const QUALIFICATION_STATUS_SHA256: &str =
    "8c913bf997fbed194c165694993b329eaff5cd4ba1436571781f0c32d3da43dc";
const GIT_TREE_MANIFEST_SHA256: &str =
    "6d5f8c9e6d61a326cb1f6c585f0a2ca15edd151f8e6944be24502301626c54ca";
const TRACKED_CONTENT_MANIFEST_SHA256: &str =
    "cf2cd0b8c473a3c98fbccf572d2d23489e080a068429e298eb3fe0b9eb85c914";
const SOAK_SUMMARY_SHA256: &str =
    "093d1a1ddf554e90551e27b2fde11c7ba4f9ce9b6603e263c163bf023d60e0ec";
const PRODUCT_AUDIT_MANIFEST_SHA256: &str =
    "21e9bef2e8ea60dce76c9d6c78871afd64db13bc050921ca42f9b95bff295be2";
const PRODUCT_AUDIT_MANIFEST_ENTRIES: usize = 6;
pub(crate) const PRODUCT_SOURCE_COMMIT: &str = "2f704dc7c1172cefca908852456beccf4d02a5d1";
pub(crate) const PRODUCT_SOURCE_TREE: &str = "7be9a382b2610790838eef874cb4d381b5025490";
pub(crate) const PRODUCT_BINARY_RELATIVE_PATH: &str = "hepta-2f704dc7c1-aarch64-apple-darwin";
pub(crate) const PRODUCT_BINARY_SHA256: &str =
    "8843df374eac70246a9398feaf25045558ac0aa7a25e6af92d186df7d7b3434c";
const PRODUCT_BINARY_SIZE_BYTES: u64 = 556_410_456;
const PRODUCT_PLATFORM: &str = "aarch64-apple-darwin";
const QUALIFICATION_RECEIPT_ID: &str = "qualification-3110c5aba5-final-20260810T192902Z";
const QUALIFICATION_MANIFEST_ROOT_KIND: &str = "sha256_of_sha256sums_bytes";
pub(crate) const ORACLE_CORPUS_SHA256: &str =
    "dfe4f04d26895a6fabfb8435b77d7e807f57379fbb8d2a96c85af747e996cda7";
pub(crate) const NORMALIZED_RECEIPT_SHA256: &str =
    "8904f0cc74e8a1b465eb75c7cd0c3f6ebef916c414dc9f5b6610d5822e9f68c0";
pub(crate) const ORACLE_SAMPLE_ID_SHA256: &str =
    "426468e3c420e5557f2edbbb0adfc845b611c00416112c1ed95d99219fa9c5ef";

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct EvidenceBinding {
    pub candidate: CandidateBinding,
    pub frozen_product: FrozenProductBinding,
    pub oracle: OracleBinding,
    pub qualification_receipt: QualificationReceiptBinding,
}

pub(crate) fn load_evidence(
    qualification_root: &Path,
    product_audit_root: &Path,
) -> Result<EvidenceBinding, AcceptanceError> {
    let qualification = VerifiedManifest::load(
        qualification_root,
        QUALIFICATION_MANIFEST_SHA256,
        QUALIFICATION_MANIFEST_ENTRIES,
    )?;
    let product = VerifiedManifest::load(
        product_audit_root,
        PRODUCT_AUDIT_MANIFEST_SHA256,
        PRODUCT_AUDIT_MANIFEST_ENTRIES,
    )?;
    if qualification.root.join("SUPERSEDED.txt").exists() {
        return Err(invalid("the qualification receipt is superseded"));
    }
    validate_status(&qualification)?;
    validate_candidate_identity(&qualification)?;
    validate_product_audit(&product)?;
    let runs = validate_soak(&qualification, &product.root)?;
    Ok(EvidenceBinding {
        candidate: CandidateBinding {
            base: CANDIDATE_BASE.to_string(),
            bundle_sha256: CANDIDATE_BUNDLE_SHA256.to_string(),
            head: CANDIDATE_HEAD.to_string(),
            tree: CANDIDATE_TREE.to_string(),
        },
        frozen_product: FrozenProductBinding {
            audit_manifest_entry_count: PRODUCT_AUDIT_MANIFEST_ENTRIES,
            audit_manifest_sha256: PRODUCT_AUDIT_MANIFEST_SHA256.to_string(),
            audit_root: path_string(&product.root)?,
            binary_relative_path: PRODUCT_BINARY_RELATIVE_PATH.to_string(),
            binary_sha256: PRODUCT_BINARY_SHA256.to_string(),
            binary_size_bytes: PRODUCT_BINARY_SIZE_BYTES,
            platform: PRODUCT_PLATFORM.to_string(),
            source_commit: PRODUCT_SOURCE_COMMIT.to_string(),
            source_tree: PRODUCT_SOURCE_TREE.to_string(),
        },
        oracle: OracleBinding {
            commit: PRODUCT_SOURCE_COMMIT.to_string(),
            corpus_sha256: ORACLE_CORPUS_SHA256.to_string(),
            expected_normalized_receipt_sha256: NORMALIZED_RECEIPT_SHA256.to_string(),
            sample_id_sha256: ORACLE_SAMPLE_ID_SHA256.to_string(),
            tree: PRODUCT_SOURCE_TREE.to_string(),
        },
        qualification_receipt: QualificationReceiptBinding {
            candidate_bundle_sha256: CANDIDATE_BUNDLE_SHA256.to_string(),
            git_tree_manifest_sha256: GIT_TREE_MANIFEST_SHA256.to_string(),
            manifest_entry_count: QUALIFICATION_MANIFEST_ENTRIES,
            manifest_root_kind: QUALIFICATION_MANIFEST_ROOT_KIND.to_string(),
            manifest_sha256: QUALIFICATION_MANIFEST_SHA256.to_string(),
            receipt_id: QUALIFICATION_RECEIPT_ID.to_string(),
            receipt_root: path_string(&qualification.root)?,
            runs,
            soak_summary_sha256: SOAK_SUMMARY_SHA256.to_string(),
            status_sha256: QUALIFICATION_STATUS_SHA256.to_string(),
            tracked_content_manifest_sha256: TRACKED_CONTENT_MANIFEST_SHA256.to_string(),
        },
    })
}

fn validate_status(manifest: &VerifiedManifest) -> Result<(), AcceptanceError> {
    let bytes = manifest.bytes("qualification-status.txt")?;
    if sha256(&bytes) != QUALIFICATION_STATUS_SHA256 {
        return Err(invalid("qualification status differs from its pin"));
    }
    let status = parse_key_values(&bytes)?;
    if status.len() != 55 {
        return Err(invalid("qualification status key count differs"));
    }
    for (key, expected) in [
        ("schema", "hepta_shadow_qualification_status_v1"),
        ("candidate_head", CANDIDATE_HEAD),
        ("candidate_tree", CANDIDATE_TREE),
        ("candidate_base", CANDIDATE_BASE),
        ("candidate_bundle_sha256", CANDIDATE_BUNDLE_SHA256),
        ("git_tree_manifest_sha256", GIT_TREE_MANIFEST_SHA256),
        (
            "tracked_content_manifest_sha256",
            TRACKED_CONTENT_MANIFEST_SHA256,
        ),
        ("candidate_frozen", "true"),
        ("candidate_worktree_clean", "true"),
        ("mac_exact", "true"),
        ("mac_live_product_exact_closure", "true"),
        ("linux_exact", "true"),
        ("nix_exact", "true"),
        ("shadow_soak", "true"),
        ("shadow_soak_runs", "3"),
        ("shadow_soak_bounded", "true"),
        ("shadow_soak_sustainable", "true"),
        ("shadow_soak_exact_closure", "true"),
        ("windows_gate_run", "false"),
        ("github_gate_run", "false"),
        ("memory_gate_run", "false"),
        ("proof_gate_run", "false"),
        ("s2_gate_run", "false"),
        ("s5_gate_run", "false"),
        ("authority", "false"),
        ("enforce", "false"),
        ("operator_acceptance", "false"),
        ("outbound", "false"),
        ("promotion", "false"),
        ("qualification_authority", "false"),
        ("retirement", "false"),
    ] {
        require_value(&status, key, expected)?;
    }
    Ok(())
}

fn validate_candidate_identity(manifest: &VerifiedManifest) -> Result<(), AcceptanceError> {
    let values = parse_key_values(&manifest.bytes("candidate-identity.txt")?)?;
    for (key, expected) in [
        ("candidate_head", CANDIDATE_HEAD),
        ("candidate_tree", CANDIDATE_TREE),
        ("upstream_base", CANDIDATE_BASE),
        ("worktree_clean", "true"),
    ] {
        require_value(&values, key, expected)?;
    }
    manifest.require_hash(
        "hepta-3110c5aba5daa0af1498b3eec85272011589ce8e.bundle",
        CANDIDATE_BUNDLE_SHA256,
    )?;
    manifest.require_hash("git-tree-list.manifest", GIT_TREE_MANIFEST_SHA256)?;
    manifest.require_hash(
        "tracked-worktree-content-sha256.manifest",
        TRACKED_CONTENT_MANIFEST_SHA256,
    )
}

fn validate_product_audit(manifest: &VerifiedManifest) -> Result<(), AcceptanceError> {
    let values = parse_key_values(&manifest.bytes("source-state.log")?)?;
    for (key, expected) in [
        ("source_commit", PRODUCT_SOURCE_COMMIT),
        ("source_tree", PRODUCT_SOURCE_TREE),
        ("frozen_oracle_worktree_head", PRODUCT_SOURCE_COMMIT),
        ("frozen_oracle_worktree_tree", PRODUCT_SOURCE_TREE),
        ("frozen_oracle_worktree_status", "clean"),
        ("post_build_source_checks", "passed"),
        ("source_has_git_metadata", "false"),
        ("generator_overlay_present", "false"),
    ] {
        require_value(&values, key, expected)?;
    }
    let binary = manifest
        .entry(PRODUCT_BINARY_RELATIVE_PATH)
        .ok_or_else(|| invalid("frozen product binary is absent from audit manifest"))?;
    if binary.sha256 != PRODUCT_BINARY_SHA256 || binary.size_bytes != PRODUCT_BINARY_SIZE_BYTES {
        return Err(invalid(
            "frozen product binary differs from its source audit pin",
        ));
    }
    Ok(())
}

fn parse_key_values(bytes: &[u8]) -> Result<BTreeMap<String, String>, AcceptanceError> {
    let text = std::str::from_utf8(bytes).map_err(|_| invalid("key/value receipt is not UTF-8"))?;
    if !text.ends_with('\n') {
        return Err(invalid("key/value receipt is not newline terminated"));
    }
    let mut values = BTreeMap::new();
    for line in text.lines() {
        let (key, value) = line
            .split_once('=')
            .ok_or_else(|| invalid("key/value receipt contains a malformed line"))?;
        if key.is_empty() || value.is_empty() || value.contains('=') {
            return Err(invalid("key/value receipt contains an invalid field"));
        }
        if values.insert(key.to_string(), value.to_string()).is_some() {
            return Err(invalid("key/value receipt contains a duplicate field"));
        }
    }
    Ok(values)
}

fn require_value(
    values: &BTreeMap<String, String>,
    key: &str,
    expected: &str,
) -> Result<(), AcceptanceError> {
    if values.get(key).map(String::as_str) != Some(expected) {
        return Err(invalid(format!("qualification field differs: {key}")));
    }
    Ok(())
}

fn path_string(path: &Path) -> Result<String, AcceptanceError> {
    path.to_str()
        .map(str::to_string)
        .ok_or_else(|| invalid("canonical evidence path is not UTF-8"))
}

fn invalid(message: impl Into<String>) -> AcceptanceError {
    AcceptanceError::Invalid(message.into())
}
