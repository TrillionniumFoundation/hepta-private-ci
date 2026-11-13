//! Consumes the actual pair once into its old command factory. Only the Source
//! reader changes transport; the original LedgerWriter, freeze, signers,
//! admission bits and all four command connection permits remain unchanged.

#[path = "cell_q24_material_prefreeze_source.rs"]
mod prefreeze;

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use codex_hepta_neuron::FileAnchorWitnessStore;
use super::*;
use crate::{AgentdRootAuthorityPeer, OriginalCellQ24MaterialCommandErrorV1,
    OriginalCellQ24MaterialCommandOwnerV1};

impl<EW: AnchorWitnessStore, DW: AnchorWitnessStore> OriginalCellQ24MaterialReceiptOwnersV1<EW, DW> {
    /// The host supplies a real connection to the same protected Root task and
    /// its actual pidfd. Root independently binds this Material process from
    /// its supervisor contract; the daemon's consumer identity is insufficient.
    /// No Source path, Source witness, decoded receipt or new ledger is accepted.
    pub fn into_original_root_source_command_owner(
        self, stream: UnixStream, root: AgentdRootAuthorityPeer, root_pidfd: OwnedFd,
        nonce: [u8; 16], identity: AgentdIdentity, ledger: Arc<Mutex<LedgerWriter>>,
        baseline: Arc<LoadedCellQ24ModelV1>, timeout: Duration, lifetime: Duration,
    ) -> Result<OriginalCellQ24MaterialCommandOwnerV1<EW, DW, FileAnchorWitnessStore>,
        OriginalCellQ24MaterialCommandErrorV1>
    {
        let source = CircuitTaskSourceReadbackV1::from_original_material_root_stream(
            stream, root, root_pidfd, self.config.clone(), identity.clone(), nonce, timeout, lifetime,
        ).map_err(|error| OriginalCellQ24MaterialCommandErrorV1::Dataset(
            CellQ24DatasetErrorV1::Source(error)))?;
        OriginalCellQ24MaterialReceiptOwnersV1::into_command_owner(
            self, source, identity, ledger, baseline,
        )
    }
}
