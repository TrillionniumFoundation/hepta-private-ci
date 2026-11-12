//! Selection and NextUse retain the actual Root-enrolled principals and files.
//! Only the completed ordinary C source can activate these receipt owners.

use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use ed25519_dalek::SigningKey;
use serde::Deserialize;

use super::OriginalFiles;
use super::owners::OpenMode;
use super::owners::OriginalJournal;
use super::owners::SigningFilesData;
use crate::AgentdError;
use crate::OriginalCircuitFeatureLearningHandoffV1;
use crate::OriginalCircuitFeatureLearningSourcesV1;
use crate::OriginalGenerationLearningSigningFilesV1;
use crate::root_historical_task_read_client::OriginalHistoricalStageAuthoritiesV1;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct GenerationFilesData {
    selection: SigningFilesData,
    next_use: SigningFilesData,
    selection_mode: OpenMode,
    next_use_mode: OpenMode,
}

struct OriginalSigningFiles {
    journal: OriginalJournal,
    key: SigningKey,
    signer: TrustedLearningSignerV1,
    lifetime: u64,
}

pub(super) struct OriginalGenerationFiles {
    selection: OriginalSigningFiles,
    next_use: OriginalSigningFiles,
    verifier: LearningEvidenceVerifierV1,
    selection_mode: OpenMode,
    next_use_mode: OpenMode,
}

impl GenerationFilesData {
    pub(super) fn open_original(
        self,
        files: &mut OriginalFiles,
        authorities: &OriginalHistoricalStageAuthoritiesV1,
    ) -> Result<OriginalGenerationFiles, AgentdError> {
        let objective = authorities.verifier.objective_digest();
        // Both actual keys and all file identities are admitted before either
        // new witness can be initialized. There is no missing-file fallback.
        let (selection, selection_key) = self.selection.open_original(
            files,
            &authorities.selector,
            objective,
            self.selection_mode,
        )?;
        let (next_use, next_key) = self.next_use.open_original(
            files,
            &authorities.next_use_observer,
            objective,
            self.next_use_mode,
        )?;
        Ok(OriginalGenerationFiles {
            selection: OriginalSigningFiles {
                journal: selection,
                key: selection_key,
                signer: authorities.selector.clone(),
                lifetime: self.selection.signature_lifetime_seconds,
            },
            next_use: OriginalSigningFiles {
                journal: next_use,
                key: next_key,
                signer: authorities.next_use_observer.clone(),
                lifetime: self.next_use.signature_lifetime_seconds,
            },
            verifier: authorities.verifier.clone(),
            selection_mode: self.selection_mode,
            next_use_mode: self.next_use_mode,
        })
    }
}

impl OriginalSigningFiles {
    fn into_original_input(self) -> Result<OriginalGenerationLearningSigningFilesV1, AgentdError> {
        let (file, witness) = self.journal.open_witness()?;
        Ok(OriginalGenerationLearningSigningFilesV1 {
            file,
            witness,
            signer: self.signer,
            key: self.key,
            maximum_signature_lifetime_seconds: self.lifetime,
        })
    }
}

impl OriginalGenerationFiles {
    pub(super) fn into_original_handoff(
        self,
        source: OriginalCircuitFeatureLearningSourcesV1,
    ) -> Result<OriginalCircuitFeatureLearningHandoffV1, AgentdError> {
        Ok(OriginalCircuitFeatureLearningHandoffV1 {
            source,
            selection: self.selection.into_original_input()?,
            next_use: self.next_use.into_original_input()?,
            verifier: self.verifier,
            selection_mode: self.selection_mode.original(),
            next_use_mode: self.next_use_mode.original(),
        })
    }
}
