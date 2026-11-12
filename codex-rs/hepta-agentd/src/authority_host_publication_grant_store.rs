//! One durable nonce attempt for an original prepared V2 publication.
//! Every operation is inside the publication's independent refusal arm.
//! Recovery opens only; even an Available record never authorizes new signing.

use codex_hepta_contracts::RootAuthorityDirectory;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use super::*;

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(tag = "phase", rename_all = "snake_case", deny_unknown_fields)]
enum GrantPhase {
    Available {},
    Attempted {},
    Issued { signed: SignedFinalUseGrant },
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct GrantRecord {
    schema: u8,
    purpose: String,
    original: ReservedPublicationProfile,
    state: GrantPhase,
}

pub(super) struct RegisteredPublicationGrant {
    store: HostAuthorityFrontierStore<GrantRecord>,
    owner: String,
    original: ReservedPublicationProfile,
    mode: RootGenerationPublicationModeV1,
    attempted: AtomicBool,
}

impl RegisteredPublicationGrant {
    pub(super) fn enroll(
        root: Arc<RootAuthorityDirectory>,
        original: &ReservedPublicationProfile,
        mode: RootGenerationPublicationModeV1,
    ) -> io::Result<Self> {
        let profile = ReservedPublicationProfile::original_for_version(
            original,
            PublicationVersion::DurableV2,
        )?;
        let owner = format!(
            "publication-grant/{}",
            Digest32::of_bytes(profile.learning_operation.as_bytes())
        );
        let store = match mode {
            RootGenerationPublicationModeV1::Reserve => HostAuthorityFrontierStore::initialize(
                root,
                owner.clone(),
                GrantRecord {
                    schema: 1,
                    purpose: "runtime.learning.prepared-publication-grant.v1".into(),
                    original: original.clone(),
                    state: GrantPhase::Available {},
                },
            ),
            RootGenerationPublicationModeV1::Recover => {
                HostAuthorityFrontierStore::open(root, owner.clone())
            }
        }
        .map_err(io::Error::other)?;
        let retained = Self {
            store,
            owner,
            original: original.clone(),
            mode,
            attempted: AtomicBool::new(false),
        };
        retained.require_exact()?;
        Ok(retained)
    }

    pub(super) fn require_exact(&self) -> io::Result<()> {
        let record = self.load_original()?;
        match record.state {
            GrantPhase::Available {} => Ok(()),
            GrantPhase::Attempted {} => Err(io::Error::other(
                "original FinalUse signing attempt is uncertain; never re-sign",
            )),
            GrantPhase::Issued { signed } => self.require_binding(&signed),
        }
    }

    pub(super) fn begin(&self) -> io::Result<()> {
        if self.mode != RootGenerationPublicationModeV1::Reserve
            || self.attempted.swap(true, Ordering::AcqRel)
        {
            return Err(io::Error::other(
                "recovery cannot issue a new FinalUse nonce",
            ));
        }
        let before = self.load_original()?;
        if before.state != (GrantPhase::Available {}) {
            return Err(io::Error::other(
                "original FinalUse signing was already attempted",
            ));
        }
        let mut attempted = before.clone();
        attempted.state = GrantPhase::Attempted {};
        self.store
            .compare_and_set(&self.owner, &before, &attempted)
            .map_err(io::Error::other)?;
        if self.load_original()? != attempted {
            return Err(io::Error::other(
                "original FinalUse attempt readback differs",
            ));
        }
        Ok(())
    }

    pub(super) fn finish(&self, signed: &SignedFinalUseGrant) -> io::Result<()> {
        if self.mode != RootGenerationPublicationModeV1::Reserve
            || !self.attempted.load(Ordering::Acquire)
        {
            return Err(io::Error::other(
                "only the original signing attempt can finish",
            ));
        }
        self.require_binding(signed)?;
        let before = self.load_original()?;
        if before.state != (GrantPhase::Attempted {}) {
            return Err(io::Error::other("original FinalUse attempt was replaced"));
        }
        let mut issued = before.clone();
        issued.state = GrantPhase::Issued {
            signed: signed.clone(),
        };
        self.store
            .compare_and_set(&self.owner, &before, &issued)
            .map_err(io::Error::other)?;
        if self.load_original()? != issued {
            return Err(io::Error::other(
                "original signed FinalUse readback differs",
            ));
        }
        Ok(())
    }

    fn require_binding(&self, signed: &SignedFinalUseGrant) -> io::Result<()> {
        let profile = ReservedPublicationProfile::original_for_version(
            &self.original,
            PublicationVersion::DurableV2,
        )?;
        if signed.grant.binding != profile.intent.binding().map_err(io::Error::other)? {
            return Err(io::Error::other("original signed FinalUse intent differs"));
        }
        signed.grant.signing_bytes().map_err(io::Error::other)?;
        Ok(())
    }

    fn load_original(&self) -> io::Result<GrantRecord> {
        let record = self.store.load(&self.owner).map_err(io::Error::other)?;
        if record.schema != 1
            || record.purpose != "runtime.learning.prepared-publication-grant.v1"
            || record.original != self.original
        {
            return Err(io::Error::other(
                "original publication grant record differs",
            ));
        }
        Ok(record)
    }
}
