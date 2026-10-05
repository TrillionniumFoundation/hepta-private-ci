//! Read-only access to the existing physically protected artifact CURRENT.
//! Every use reopens the original owner; this holds no writer, fence or key.

use std::path::PathBuf;

use codex_hepta_agent_components::learning_artifacts::ArtifactOwnerTrustV1;
use codex_hepta_agent_components::learning_artifacts::DatasetWithdrawalRegistry;
use codex_hepta_agent_components::learning_artifacts::ReadOnlyArtifactCurrentOwnerV1;
use codex_hepta_agent_components::learning_artifacts::VerifiedCurrentRegistryViewV1;

/// A source can only be constructed from the real protected owner. Trust and
/// withdrawal changes require an explicit new composition; a changed frontier
/// never falls back to a previously verified snapshot.
pub struct CurrentArtifactRegistrySourceV1 {
    source: Source,
}

enum Source {
    Protected {
        root: PathBuf,
        trust: Box<ArtifactOwnerTrustV1>,
        withdrawals: DatasetWithdrawalRegistry,
    },
    #[cfg(test)]
    Fixture(
        std::sync::Arc<dyn Fn(u64) -> Result<VerifiedCurrentRegistryViewV1, String> + Send + Sync>,
    ),
}

impl CurrentArtifactRegistrySourceV1 {
    pub fn open(
        root: PathBuf,
        trust: ArtifactOwnerTrustV1,
        withdrawals: DatasetWithdrawalRegistry,
    ) -> Result<Self, String> {
        let source = Self {
            source: Source::Protected {
                root,
                trust: Box::new(trust),
                withdrawals,
            },
        };
        source.current()?;
        Ok(source)
    }

    /// The public consumer cannot supply an earlier verification time.
    pub fn current(&self) -> Result<VerifiedCurrentRegistryViewV1, String> {
        let now = crate::authbus_ingress::now_ms().map_err(|error| error.to_string())?;
        self.read_at(now)
    }

    // Only the daemon's private clock/final-admission guard calls this method.
    pub(crate) fn read_at(&self, now: u64) -> Result<VerifiedCurrentRegistryViewV1, String> {
        let current = match &self.source {
            Source::Protected {
                root,
                trust,
                withdrawals,
            } => ReadOnlyArtifactCurrentOwnerV1::open_with_current_registry_view(
                root,
                trust.as_ref().clone(),
                withdrawals.clone(),
                now,
            )
            .map(|(_owner, current)| current)
            .map_err(|error| error.to_string())?,
            #[cfg(test)]
            Source::Fixture(reader) => reader(now)?,
        };
        current
            .revalidate_at(now)
            .map_err(|error| error.to_string())?;
        Ok(current)
    }

    #[cfg(test)]
    pub(crate) fn fixture(
        reader: impl Fn(u64) -> Result<VerifiedCurrentRegistryViewV1, String> + Send + Sync + 'static,
    ) -> Self {
        Self {
            source: Source::Fixture(std::sync::Arc::new(reader)),
        }
    }
}
