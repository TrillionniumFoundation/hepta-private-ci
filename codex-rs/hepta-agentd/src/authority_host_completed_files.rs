//! Seven fixed original journal pairs. No caller chooses a stage at read time,
//! and no key, writer, recovery, truncation or repair enters this reader.

use std::io;
use std::time::Instant;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::completed_journal::CompletedJournalData;
use super::completed_journal::CompletedJournalFiles;
use super::completed_journal::CompletedJournalObservation;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct CompletedFilesData {
    freeze: CompletedJournalData,
    experience: CompletedJournalData,
    dataset: CompletedJournalData,
    training_receipt: CompletedJournalData,
    local_decision: CompletedJournalData,
    selection: CompletedJournalData,
    next_use: CompletedJournalData,
}

pub(super) struct CompletedFiles(Vec<CompletedJournalFiles>);

impl CompletedFiles {
    pub(super) fn retain_original(
        data: CompletedFilesData,
        objective: Digest32,
    ) -> io::Result<Self> {
        let mut files: Vec<CompletedJournalFiles> = Vec::with_capacity(7);
        for data in [
            data.freeze,
            data.experience,
            data.dataset,
            data.training_receipt,
            data.local_decision,
            data.selection,
            data.next_use,
        ] {
            let file = CompletedJournalFiles::retain_original(data, objective)?;
            if files.iter().any(|previous| file.aliases(previous)) {
                return Err(io::Error::other("completed-learning original roles alias"));
            }
            files.push(file);
        }
        Ok(Self(files))
    }

    pub(super) fn require_empty(&self) -> io::Result<()> {
        for file in &self.0 {
            file.require_empty()?;
        }
        Ok(())
    }

    pub(super) fn freeze(&self) -> io::Result<&CompletedJournalFiles> {
        self.0
            .first()
            .ok_or_else(|| io::Error::other("original freeze descriptor missing"))
    }

    pub(super) fn with_original_records<T>(
        &self,
        end: Instant,
        action: impl FnOnce(&[CompletedJournalObservation]) -> io::Result<T>,
    ) -> io::Result<T> {
        with_rest(&self.0, end, &mut Vec::with_capacity(7), &mut Some(action))
    }
}

fn with_rest<T, F>(
    files: &[CompletedJournalFiles],
    end: Instant,
    observations: &mut Vec<CompletedJournalObservation>,
    action: &mut Option<F>,
) -> io::Result<T>
where
    F: FnOnce(&[CompletedJournalObservation]) -> io::Result<T>,
{
    let Some((first, rest)) = files.split_first() else {
        if observations.len() != 7 {
            return Err(io::Error::other("all original completed journals required"));
        }
        return action
            .take()
            .ok_or_else(|| io::Error::other("completed read already consumed"))?(
            observations
        );
    };
    CompletedJournalFiles::with_original_records(first, end, |observed| {
        observations.push(observed.clone());
        let result = with_rest(rest, end, observations, action);
        observations.pop();
        result
    })
}
