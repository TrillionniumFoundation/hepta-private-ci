//! PQ configuration for the original ordinary public-initial business controls.
//! These local test services do not establish independent deployment custody.

use super::*;
use crate::final_use_authorizer::IndependentPqIssuer;
use crate::final_use_authorizer::independent_ordinary_test_authorizer_v2;
use crate::final_use_authorizer::independent_ordinary_test_authorizer_v2_after_load;

pub(super) async fn ordinary_inputs(
    worker: SmolLmNeuralReadConfigV1,
    root: &Path,
    expected_claims: u8,
) -> TestResult<(
    SmolLmInitialHostInputsV1,
    IndependentPqIssuer,
    tempfile::TempDir,
)> {
    inputs_with_postload_time(worker, root, expected_claims, None).await
}

pub(super) async fn ordinary_inputs_after_load(
    worker: SmolLmNeuralReadConfigV1,
    root: &Path,
    expected_claims: u8,
    late_ms: u64,
) -> TestResult<(
    SmolLmInitialHostInputsV1,
    IndependentPqIssuer,
    tempfile::TempDir,
)> {
    inputs_with_postload_time(worker, root, expected_claims, Some(late_ms)).await
}

async fn inputs_with_postload_time(
    worker: SmolLmNeuralReadConfigV1,
    root: &Path,
    expected_claims: u8,
    late_ms: Option<u64>,
) -> TestResult<(
    SmolLmInitialHostInputsV1,
    IndependentPqIssuer,
    tempfile::TempDir,
)> {
    fs::create_dir(root)?;
    fs::set_permissions(root, fs::Permissions::from_mode(0o700))?;
    let authority = tempfile::tempdir()?;
    let (authorizer, issuer) = match late_ms {
        Some(late_ms) => {
            independent_ordinary_test_authorizer_v2_after_load(
                authority.path(),
                usize::from(expected_claims),
                root.join("inference.control"),
                late_ms,
            )
            .await
        }
        None => {
            independent_ordinary_test_authorizer_v2(authority.path(), usize::from(expected_claims))
                .await
        }
    }
    .map_err(issuer_error)?;
    drop(authorizer);
    let path = root.join("authority.json");
    fs::copy(authority.path().join("pq-config.json"), &path)?;
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600))?;
    let now = u64::try_from(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)?
            .as_millis(),
    )?;
    Ok((
        SmolLmInitialHostInputsV1 {
            worker,
            worker_id: "selected-initial-native-worker".to_owned(),
            resource_grant: ResourceGrant {
                grant_id: "selected-initial-resource".to_owned(),
                authority_epoch: 9,
                generation: 1,
                expires_at_ms: now + 900000,
                revoked: false,
                maximum_models: 1,
                maximum_active_requests: 1,
                maximum_memory_bytes: 8 * 1024 * 1024 * 1024,
                semantic_digest: digest("controlled-initial-resource").to_string(),
            },
            inference_journal: root.join("inference.control"),
            inference_journal_capacity: 8,
            final_use_authorizer_config: path,
        },
        issuer,
        authority,
    ))
}

pub(super) fn archive_pq_authority(authority: &tempfile::TempDir, output: &Path) -> TestResult<()> {
    let target = output.join(
        authority
            .path()
            .file_name()
            .ok_or("authority directory name")?,
    );
    fs::create_dir(&target)?;
    for item in fs::read_dir(authority.path().join("pq-state"))? {
        let item = item?;
        if item.file_type()?.is_file() {
            fs::copy(item.path(), target.join(item.file_name()))?;
        }
    }
    fs::copy(
        authority.path().join("external-frontier.json"),
        target.join("external-frontier.json"),
    )?;
    Ok(())
}
