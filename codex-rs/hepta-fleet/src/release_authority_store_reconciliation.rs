//! One additional bounded recovery proposal. Neither unresolved proposal is
//! overwritten, erased or automatically resent after an uncertain response.

use super::ATTEMPT;
use super::AuthorityFiles;
use super::JOURNAL;
use super::MAX_AUTHORITY_BYTES;
use super::PROPOSAL;
use super::entry_exists;
use super::read_private;
use super::sync;
use super::write_private;
use crate::FleetRegistryError;
use crate::release_authority::invalid;

const RECONCILIATION_PROPOSAL: &str = "intent-reconciliation-proposal.v1.json";
const RECONCILIATION_ATTEMPT: &str = "intent-reconciliation-attempt.v1.json";

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct IntentRecoveryFiles {
    pub journal: Vec<u8>,
    pub original_attempt: Option<Vec<u8>>,
    pub original_proposal: Option<Vec<u8>>,
    pub replacement_attempt: Option<Vec<u8>>,
    pub replacement_proposal: Option<Vec<u8>>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum IntentRecoveryWinner {
    OriginalProposal,
    ReplacementProposal,
    Published,
}

impl AuthorityFiles {
    pub fn has_intent_reconciliation(&self) -> Result<bool, FleetRegistryError> {
        Ok(entry_exists(&self.root.join(RECONCILIATION_ATTEMPT))?
            || entry_exists(&self.root.join(RECONCILIATION_PROPOSAL))?)
    }

    pub fn intent_recovery_files(&self) -> Result<IntentRecoveryFiles, FleetRegistryError> {
        let read = |name: &str, bound| -> Result<Option<Vec<u8>>, FleetRegistryError> {
            let path = self.root.join(name);
            if entry_exists(&path)? {
                Ok(Some(read_private(&path, bound)?))
            } else {
                Ok(None)
            }
        };
        Ok(IntentRecoveryFiles {
            journal: self.journal()?,
            original_attempt: read(ATTEMPT, 16 * 1024)?,
            original_proposal: read(PROPOSAL, MAX_AUTHORITY_BYTES)?,
            replacement_attempt: read(RECONCILIATION_ATTEMPT, 16 * 1024)?,
            replacement_proposal: read(RECONCILIATION_PROPOSAL, MAX_AUTHORITY_BYTES)?,
        })
    }

    pub fn prepare_intent_reconciliation(
        &self,
        journal: &[u8],
        attempt: &[u8],
    ) -> Result<(), FleetRegistryError> {
        if journal.len() > MAX_AUTHORITY_BYTES || attempt.len() > 16 * 1024 {
            return Err(invalid(
                "intent reconciliation exceeds the existing record bounds",
            ));
        }
        if self.has_intent_reconciliation()? {
            return Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired);
        }
        // create_new preserves both the original records and any partial
        // second preparation. Only a future exact winner can clear them.
        write_private(&self.root.join(RECONCILIATION_PROPOSAL), journal)?;
        sync(&self.root)?;
        #[cfg(test)]
        stop_after_proposal_for_test()?;
        write_private(&self.root.join(RECONCILIATION_ATTEMPT), attempt)?;
        sync(&self.root)
    }

    pub fn retain_exact_intent_reconciliation_attempt(
        &self,
        attempt: &[u8],
    ) -> Result<(), FleetRegistryError> {
        if attempt.len() > 16 * 1024 || !entry_exists(&self.root.join(RECONCILIATION_PROPOSAL))? {
            return Err(invalid("missing bounded reconciliation proposal"));
        }
        let path = self.root.join(RECONCILIATION_ATTEMPT);
        if entry_exists(&path)? {
            if read_private(&path, 16 * 1024)? != attempt {
                return Err(FleetRegistryError::ReleaseAuthorityRollback);
            }
        } else {
            write_private(&path, attempt)?;
            sync(&self.root)?;
        }
        Ok(())
    }

    /// Caller has verified the complete current external frontier and every
    /// remaining record. Cleanup begins only after the winning journal is
    /// durable. The replacement attempt is removed last, so interrupted
    /// cleanup remains recognizable by completed-only recovery.
    pub fn finish_intent_winner(
        &self,
        winner: IntentRecoveryWinner,
    ) -> Result<(), FleetRegistryError> {
        let source = match winner {
            IntentRecoveryWinner::OriginalProposal => Some(PROPOSAL),
            IntentRecoveryWinner::ReplacementProposal => Some(RECONCILIATION_PROPOSAL),
            IntentRecoveryWinner::Published => None,
        };
        if let Some(source) = source {
            std::fs::rename(self.root.join(source), self.root.join(JOURNAL))?;
        }
        sync(&self.root)?;
        for name in [PROPOSAL, RECONCILIATION_PROPOSAL, ATTEMPT] {
            let path = self.root.join(name);
            if entry_exists(&path)? {
                std::fs::remove_file(path)?;
            }
        }
        sync(&self.root)?;
        let last = self.root.join(RECONCILIATION_ATTEMPT);
        if entry_exists(&last)? {
            std::fs::remove_file(last)?;
        }
        sync(&self.root)
    }
}

#[cfg(test)]
std::thread_local! {
    static STOP_AFTER_PROPOSAL: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
}

#[cfg(test)]
pub(crate) fn fail_once_after_reconciliation_proposal() {
    STOP_AFTER_PROPOSAL.set(true);
}

#[cfg(test)]
fn stop_after_proposal_for_test() -> Result<(), FleetRegistryError> {
    if STOP_AFTER_PROPOSAL.replace(false) {
        return Err(
            std::io::Error::other("injected stop after durable reconciliation proposal").into(),
        );
    }
    Ok(())
}
