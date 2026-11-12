//! Root CLI custody for the terminal Source notification. Paths exist only in
//! this protected metadata file; a peer command carries no inputs or capability.

use super::super::super::generation_publication::deployment::files::MetadataFile;
use super::super::super::generation_publication::deployment::files::OriginalFile;
use super::*;

#[path = "authority_host_historical_source_deployment_data.rs"]
mod data;
use data::SourceDeploymentData;

const DEPLOYMENT_PURPOSE: &str = "runtime.circuit.single-q24-source-deployment.v1";

impl PreparedHostAuthoritySession {
    /// Retain original readonly inputs before serving the original Initial
    /// session. The unique capability stays in that same Root runtime; A may
    /// only request capture after dropping all Source and witness writers.
    pub fn enable_initial_source_capture_from_deployment(&mut self, path: &Path) -> io::Result<()> {
        crate::authority_host_service::generation_initial::original_root()?;
        let (descriptor, bytes) = MetadataFile::open_metadata(path)?;
        let data: SourceDeploymentData =
            serde_json::from_slice(&bytes).map_err(io::Error::other)?;
        if data.schema_version != 1 || data.purpose != DEPLOYMENT_PURPOSE {
            return Err(io::Error::other(
                "original single Q24 Source deployment required",
            ));
        }
        let journal = OriginalFile::open_original(&data.source_journal)?;
        let witness = OriginalFile::open_original(&data.source_witness)?;
        let cell = data
            .cell_files
            .as_ref()
            .map(data::RootCellFilesData::open_original_cell_inputs)
            .transpose()?;
        let ledger = data
            .ledger_deployment
            .as_ref()
            .map(|path| {
                crate::authority_host_runtime::RootHistoricalLedgerDeploymentV1::open_original(path)
            })
            .transpose()?;
        let inputs = data.into_inputs(
            &self.registration.registered_identity.identity()?,
            journal.original_descriptor()?,
            witness.original_descriptor()?,
        )?;
        descriptor.require_metadata_unchanged()?;
        journal.require_original_file()?;
        witness.require_original_file()?;
        let capability = self.enable_initial_source_capture(inputs)?;
        if let Some(cell) = cell {
            self.install_initial_source_cell(cell)?;
        }
        if let Some(ledger) = ledger {
            self.install_initial_source_ledger(ledger)?;
        }
        let initial = self
            .initial_publication
            .as_mut()
            .ok_or_else(|| io::Error::other("original Initial runtime missing"))?;
        let source = initial
            .source_capture
            .as_ref()
            .ok_or_else(|| io::Error::other("original Source runtime missing"))?;
        let installed = (|| {
            if !Arc::ptr_eq(&source.phase, &capability.phase)
                || !Arc::ptr_eq(&source.end, &capability.end)
            {
                return Err(io::Error::other(
                    "source capability belongs to another runtime",
                ));
            }
            let retained = initial
                .peer_source_capture
                .get_mut()
                .map_err(|_| io::Error::other("Root source capability slot poisoned"))?;
            if retained.is_some() {
                return Err(io::Error::other("Root source capability already installed"));
            }
            descriptor.require_metadata_unchanged()?;
            journal.require_original_file()?;
            witness.require_original_file()?;
            *retained = Some(capability);
            Ok(())
        })();
        if installed.is_err() {
            source.close();
        }
        installed
    }
}
