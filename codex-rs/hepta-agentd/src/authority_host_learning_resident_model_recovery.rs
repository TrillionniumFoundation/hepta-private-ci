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
use super::RootResidentLearningProfileV3;
use super::RootResidentLearningReadbackAuthorizationV3;
use super::SignedLearningEvidenceV1;
use super::UnixStream;

impl AgentdRootResidentLearningClientV3 {
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
            stream,
            root,
            held_root_pidfd,
            profile,
            verifier,
            ClientOriginV3::Readback(authorization),
            Some(ResidentReadbackPinV3 {
                snapshot,
                attestations,
                model: Some(model),
            }),
            timeout,
            lifetime,
        )
    }
}
