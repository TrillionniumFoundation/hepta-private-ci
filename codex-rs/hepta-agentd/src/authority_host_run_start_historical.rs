//! One guarded historical join. The callback includes the complete current
//! recipient context; original files stay held until physical postchecks end.

use super::*;
use crate::AgentdIdentity;

enum ReadState {
    AwaitingBinding,
    Bound(AgentdIdentity),
    Verifying,
    Complete {
        files: Arc<RootInitialRunStartFilesV1>,
        identity: AgentdIdentity,
        frame: RunStartReadOnlyFrameV1,
    },
}

/// Only borrowed inside the existing refusal arm. It is neither a grant nor a
/// constructor from caller receipts. One real physical read must complete.
pub(crate) struct RootOriginalRunStartReadV1<'a> {
    retained: &'a RootRetainedRunStartDataV1,
    end: Instant,
    state: Mutex<ReadState>,
    failed: AtomicBool,
}

impl RootRetainedRunStartDataV1 {
    pub(crate) fn with_original_run_start_data<T>(
        &self,
        end: Instant,
        action: impl FnOnce(&RootOriginalRunStartReadV1<'_>) -> io::Result<T>,
    ) -> io::Result<T> {
        RootDataRefusalV1::inspect(&self.refusal, || {
            require_end(end)?;
            self.state.require_exact_unchecked()?;
            let read = RootOriginalRunStartReadV1 {
                retained: self,
                end,
                state: Mutex::new(ReadState::AwaitingBinding),
                failed: AtomicBool::new(false),
            };
            let value = action(&read)?;
            // The actual recipient context, including its postchecks, returned
            // before this final physical read and the original end check.
            read.finish()?;
            Ok(value)
        })
    }
}

impl RootOriginalRunStartReadV1<'_> {
    pub(crate) fn require_original_publisher(
        &self,
        identity: &AgentdIdentity,
        target: &CellGenerationOwnerBindingV1,
        publisher: &CognitiveCheckpointPeerLifetime,
        publisher_epoch: u64,
        initial_profile: &str,
        writer: &str,
        target_files: &str,
    ) -> io::Result<()> {
        let mut state = self.state.try_lock().map_err(|_| {
            self.failed.store(true, Ordering::Release);
            io::Error::other("original RunStart join busy")
        })?;
        if !matches!(
            std::mem::replace(&mut *state, ReadState::Verifying),
            ReadState::AwaitingBinding
        ) {
            return Err(io::Error::other(
                "original RunStart binding already consumed",
            ));
        }
        require_end(self.end)?;
        self.retained.state.require_exact_unchecked()?;
        let original = &self.retained.state.expected.original;
        if original.identity
            != crate::neuron_generation_process_identity_digest_v1(identity)
                .map_err(io::Error::other)?
                .to_string()
            || original.spawn_generation != identity.spawn_generation
            || &original.target != target
            || target.scope().agent_id != identity.agent_id.as_str()
            || &original.publisher != publisher
            || original.publisher_epoch != publisher_epoch
            || publisher_epoch == 0
            || original.initial_profile != initial_profile
            || original.writer != writer
            || original.target_files != target_files
        {
            return Err(io::Error::other(
                "original RunStart retained publisher differs",
            ));
        }
        *state = ReadState::Bound(identity.clone());
        Ok(())
    }

    pub(crate) fn read_original_publication(
        &self,
        files: Arc<RootInitialRunStartFilesV1>,
        identity: &AgentdIdentity,
    ) -> io::Result<RunStartReadOnlyFrameV1> {
        let mut state = self.state.try_lock().map_err(|_| {
            self.failed.store(true, Ordering::Release);
            io::Error::other("original RunStart join busy")
        })?;
        let ReadState::Bound(bound_identity) = std::mem::replace(&mut *state, ReadState::Verifying)
        else {
            return Err(io::Error::other(
                "one bound RunStart physical read required",
            ));
        };
        if &bound_identity != identity {
            return Err(io::Error::other("original RunStart read identity differs"));
        }
        require_end(self.end)?;
        let frame = self
            .retained
            .read_original_publication_unchecked(&files, identity)?;
        require_end(self.end)?;
        *state = ReadState::Complete {
            files,
            identity: bound_identity,
            frame: frame.clone(),
        };
        Ok(frame)
    }

    pub(crate) fn retained_digest(&self) -> io::Result<Digest32> {
        let mut state = self.state.try_lock().map_err(|_| {
            self.failed.store(true, Ordering::Release);
            io::Error::other("original RunStart join busy")
        })?;
        let complete = std::mem::replace(&mut *state, ReadState::Verifying);
        if !matches!(complete, ReadState::Complete { .. }) {
            return Err(io::Error::other("complete RunStart physical read required"));
        }
        require_end(self.end)?;
        self.retained.state.require_exact_unchecked()?;
        let digest = store::record_digest(&self.retained.state.expected)?;
        *state = complete;
        Ok(digest)
    }

    fn finish(&self) -> io::Result<()> {
        let mut state = self.state.try_lock().map_err(|_| {
            self.failed.store(true, Ordering::Release);
            io::Error::other("original RunStart join busy")
        })?;
        let ReadState::Complete {
            files,
            identity,
            frame,
        } = std::mem::replace(&mut *state, ReadState::Verifying)
        else {
            return Err(io::Error::other(
                "historical RunStart physical read unfinished",
            ));
        };
        require_end(self.end)?;
        if self
            .retained
            .read_original_publication_unchecked(&files, &identity)?
            != frame
        {
            return Err(io::Error::other(
                "historical RunStart changed across recipient context",
            ));
        }
        self.retained.state.require_exact_unchecked()?;
        if self.failed.load(Ordering::Acquire) {
            return Err(io::Error::other("historical RunStart join already failed"));
        }
        require_end(self.end)
    }
}
