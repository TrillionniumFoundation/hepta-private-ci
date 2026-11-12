//! Candidate metadata and original head bytes are DATA for the independent
//! source's actual policy. Neither decoding nor notification authenticates B,
//! releases a holdout or replaces Complete's original physical/signature checks.

use std::fs::File;
use std::io;
use std::os::fd::AsRawFd;
use std::os::unix::fs::FileExt;
use std::os::unix::fs::MetadataExt;
use std::time::Instant;

use base64::Engine;
use base64::prelude::BASE64_STANDARD_NO_PAD;
use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use crate::learning_iteration_checkpoint::decode_original_bundle_data;
use crate::learning_iteration_checkpoint::encode_original_bundle_data;
use crate::root_independent_b_protocol::PreparedPlanData;
use crate::root_independent_b_protocol::digest;

const PURPOSE: &str = "runtime.learning.independent-b-candidate-data.v1";

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct CandidateNotice {
    schema: u8,
    purpose: String,
    pub(crate) binding: String,
    pub(crate) plan: PreparedPlanData,
    pub(crate) registered_at_seconds: u64,
    baseline: String,
    candidate: String,
}

/// A current Root candidate observation supplied to the original independent
/// source. All getters return data; no role, writer or evaluation is conferred.
pub struct OriginalRootBCandidateDataV1 {
    initial: Digest32,
    binding: Digest32,
    scope: Digest32,
    training_head: Digest32,
    registered_at_seconds: u64,
    candidate: CellCompatibilityBundleV1,
    baseline: CellCompatibilityBundleV1,
    heads: Vec<u8>,
    original_end: Instant,
}

impl OriginalRootBCandidateDataV1 {
    pub fn initial(&self) -> Digest32 {
        self.initial
    }
    pub fn binding(&self) -> Digest32 {
        self.binding
    }
    pub fn scope(&self) -> Digest32 {
        self.scope
    }
    pub fn training_head(&self) -> Digest32 {
        self.training_head
    }
    pub fn registered_at_seconds(&self) -> u64 {
        self.registered_at_seconds
    }
    pub fn candidate_bundle(&self) -> &CellCompatibilityBundleV1 {
        &self.candidate
    }
    pub fn baseline_bundle(&self) -> &CellCompatibilityBundleV1 {
        &self.baseline
    }
    pub fn candidate_heads(&self) -> &[u8] {
        &self.heads
    }
    pub fn original_end(&self) -> Instant {
        self.original_end
    }
}

impl CandidateNotice {
    pub(crate) fn from_original_training(
        binding: Digest32,
        training: &LearningIterationSnapshotV1,
        plan: PreparedPlanData,
        registered_at_seconds: u64,
    ) -> io::Result<Self> {
        let coordinator = LearningIterationCoordinatorV1::from_snapshot(training.clone())
            .map_err(io::Error::other)?;
        let candidate = coordinator
            .candidate()
            .ok_or_else(|| io::Error::other("original B candidate missing"))?;
        if training.head_digest.to_string() != plan.training_head
            || candidate.digest().map_err(io::Error::other)?.to_string() != plan.candidate_bundle
            || training.request.evaluation_profile.to_string() != plan.profile
            || registered_at_seconds == 0
        {
            return Err(io::Error::other(
                "original B candidate notice differs from Training",
            ));
        }
        Ok(Self {
            schema: 1,
            purpose: PURPOSE.into(),
            binding: binding.to_string(),
            plan,
            registered_at_seconds,
            baseline: BASE64_STANDARD_NO_PAD.encode(
                encode_original_bundle_data(&training.request.selected_bundle)
                    .map_err(io::Error::other)?,
            ),
            candidate: BASE64_STANDARD_NO_PAD
                .encode(encode_original_bundle_data(candidate).map_err(io::Error::other)?),
        })
    }

    pub(crate) fn encode(&self) -> io::Result<Vec<u8>> {
        let bytes = serde_json::to_vec(self).map_err(io::Error::other)?;
        if bytes.is_empty() || bytes.len() > super::root_independent_b_notice::BOUND {
            return Err(io::Error::other(
                "bounded original B candidate notice required",
            ));
        }
        Ok(bytes)
    }

    pub(crate) fn read_original_data(
        bytes: &[u8],
        file: &File,
        bootstrap: &crate::root_independent_b_source_protocol::SourceBootstrap,
        end: Instant,
        mut require_original: impl FnMut() -> io::Result<()>,
    ) -> io::Result<OriginalRootBCandidateDataV1> {
        if bytes.is_empty() || bytes.len() > super::root_independent_b_notice::BOUND {
            return Err(io::Error::other(
                "bounded original B candidate data required",
            ));
        }
        let data: Self = serde_json::from_slice(bytes).map_err(io::Error::other)?;
        if data.encode()? != bytes
            || data.schema != 1
            || data.purpose != PURPOSE
            || data.binding != bootstrap.binding
            || data.plan.initial != bootstrap.initial
            || data.registered_at_seconds != bootstrap.registered_at_seconds
            || Instant::now() >= end
        {
            return Err(io::Error::other(
                "original candidate notice binding differs",
            ));
        }
        let decode = |encoded: &str| -> io::Result<CellCompatibilityBundleV1> {
            let raw = BASE64_STANDARD_NO_PAD
                .decode(encoded)
                .map_err(io::Error::other)?;
            if BASE64_STANDARD_NO_PAD.encode(&raw) != encoded {
                return Err(io::Error::other("original bundle data is not canonical"));
            }
            decode_original_bundle_data(&raw).map_err(io::Error::other)
        };
        let baseline = decode(&data.baseline)?;
        let candidate = decode(&data.candidate)?;
        let lineage = candidate
            .training_lineage
            .as_ref()
            .ok_or_else(|| io::Error::other("original candidate Training lineage absent"))?;
        let mut components = baseline.components.clone();
        components.heads = candidate.components.heads;
        if candidate.digest().map_err(io::Error::other)?.to_string() != data.plan.candidate_bundle
            || lineage.source_bundle != baseline.digest().map_err(io::Error::other)?
            || lineage.evaluation_profile != digest(&data.plan.profile)?
            || components != candidate.components
        {
            return Err(io::Error::other("original candidate bundle data differs"));
        }
        digest(&data.plan.plan_digest)?;
        digest(&data.plan.comparison_digest)?;
        require_candidate_file(file, bootstrap)?;
        file.try_lock_shared().map_err(io::Error::other)?;
        let observed = (|| {
            let mut previous = None;
            for _ in 0..2 {
                require_original()?;
                if Instant::now() >= end {
                    return Err(io::Error::other("original candidate end elapsed"));
                }
                require_candidate_file(file, bootstrap)?;
                let before = file.metadata()?;
                let length = usize::try_from(before.len()).map_err(io::Error::other)?;
                if length == 0 || length > 32_780 {
                    return Err(io::Error::other(
                        "original candidate head data is absent or oversized",
                    ));
                }
                let mut heads = vec![0; length];
                file.read_exact_at(&mut heads, /*offset*/ 0)?;
                let after = file.metadata()?;
                if stamp(&before) != stamp(&after)
                    || previous.as_ref().is_some_and(|old| old != &heads)
                    || Digest32::of_bytes(&heads) != candidate.components.heads
                {
                    return Err(io::Error::other(
                        "original candidate physical image changed",
                    ));
                }
                crate::cell_composed_q24::require_original_head_data(&heads)
                    .map_err(io::Error::other)?;
                previous = Some(heads);
            }
            require_original()?;
            require_candidate_file(file, bootstrap)?;
            if Instant::now() >= end {
                return Err(io::Error::other("original candidate end elapsed"));
            }
            previous.ok_or_else(|| io::Error::other("original candidate was not observed"))
        })();
        let unlocked = file.unlock();
        let heads = observed?;
        unlocked?;
        Ok(OriginalRootBCandidateDataV1 {
            initial: digest(&data.plan.initial)?,
            binding: digest(&data.binding)?,
            scope: digest(&data.plan.scope)?,
            training_head: digest(&data.plan.training_head)?,
            registered_at_seconds: data.registered_at_seconds,
            candidate,
            baseline,
            heads,
            original_end: end,
        })
    }
}

pub(crate) fn require_candidate_file(
    file: &File,
    bootstrap: &crate::root_independent_b_source_protocol::SourceBootstrap,
) -> io::Result<()> {
    // SAFETY: F_GETFL only observes this original owned descriptor.
    let flags = unsafe { libc::fcntl(file.as_raw_fd(), libc::F_GETFL) };
    if flags < 0 {
        return Err(io::Error::last_os_error());
    }
    let metadata = file.metadata()?;
    if flags & libc::O_ACCMODE != libc::O_RDONLY
        || flags & (libc::O_PATH | libc::O_APPEND) != 0
        || !metadata.is_file()
        || metadata.uid() != 0
        || metadata.nlink() != 1
        || metadata.mode() & 0o7777 != 0o600
        || metadata.dev() != bootstrap.candidate_data_device
        || metadata.ino() != bootstrap.candidate_data_inode
        || metadata.len() > 32_780
    {
        return Err(io::Error::other(
            "original read-only candidate data custody differs",
        ));
    }
    Ok(())
}

fn stamp(metadata: &std::fs::Metadata) -> (u64, i64, i64, i64, i64) {
    (
        metadata.len(),
        metadata.mtime(),
        metadata.mtime_nsec(),
        metadata.ctime(),
        metadata.ctime_nsec(),
    )
}
