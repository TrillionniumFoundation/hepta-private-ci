//! An explicit saved Model pin is accepted only by a new original readonly
//! Root authorization. It cannot enter fresh admission or reconstruct a
//! writable stage. The first reply still performs original Model CURRENT.

use super::AgentdRootAuthorityPeer;
use super::AgentdRootResidentLearningClientV3;
use super::ClientOriginV3;
use super::Duration;
use super::Error;
use super::LearningEvidenceVerifierV1;
use super::LearningIterationSnapshotV1;
use super::OwnedFd;
use super::ResidentReadbackPinV3;
use super::RootResidentLearningConnectionV3;
use super::RootResidentLearningProfileV3;
use super::RootResidentLearningReadbackAuthorizationV3;
use super::SignedLearningEvidenceV1;
use super::UnixStream;

impl AgentdRootResidentLearningClientV3 {
    #[expect(
        clippy::too_many_arguments,
        reason = "The published positional API remains available to existing callers."
    )]
    pub fn recover_original_model_root_stream(
        stream: UnixStream,
        root: AgentdRootAuthorityPeer,
        held_root_pidfd: OwnedFd,
        profile: RootResidentLearningProfileV3,
        authorization: RootResidentLearningReadbackAuthorizationV3,
        verifier: LearningEvidenceVerifierV1,
        expected: (
            LearningIterationSnapshotV1,
            Vec<SignedLearningEvidenceV1>,
            Vec<u8>,
        ),
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        let (snapshot, attestations, model) = expected;
        Self::bind(
            RootResidentLearningConnectionV3 {
                stream,
                root,
                held_root_pidfd,
            },
            profile,
            verifier,
            ClientOriginV3::Readback(Box::new(authorization)),
            Some(ResidentReadbackPinV3 {
                snapshot,
                attestations,
                model: Some(model),
            }),
            timeout,
            lifetime,
        )
    }

    /// Accepts the original peer transport as a single value.
    pub fn recover_original_model_root_connection(
        connection: RootResidentLearningConnectionV3,
        profile: RootResidentLearningProfileV3,
        authorization: RootResidentLearningReadbackAuthorizationV3,
        verifier: LearningEvidenceVerifierV1,
        expected: (
            LearningIterationSnapshotV1,
            Vec<SignedLearningEvidenceV1>,
            Vec<u8>,
        ),
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        Self::recover_original_model_root_stream(
            connection.stream,
            connection.root,
            connection.held_root_pidfd,
            profile,
            authorization,
            verifier,
            expected,
            timeout,
            lifetime,
        )
    }
}
