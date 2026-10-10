//! Unix transport to the four *external* committed-effect owners.
//!
//! Unlike an in-process fixture, this adapter never signs, synthesizes or
//! executes a local stand-in for Artifact CAS, migration, CNS or Supervisor.
//! An execute RPC may have succeeded before transport failure. The coordinator
//! must persist the intent first and subsequently reconcile, never retry it.
//! Verification is a fresh read of the original owner, not an echo of a hash.
//!
//! This transport alone does not establish production activation. Each service
//! behind a socket must implement durable idempotency, committed receipt
//! signing and independent state inspection.

use std::collections::BTreeSet;
use std::fs;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::FileTypeExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;

use serde::Deserialize;
use serde::Serialize;
use thiserror::Error;

use super::cell_split_execution_owner::CellSplitExecutionErrorV1;
use super::cell_split_execution_owner::CellSplitExecutionIntentV1;
use super::cell_split_execution_owner::CellSplitExecutionPlanV1;
use super::cell_split_execution_owner::CellSplitExecutionPortV1;
use super::cell_split_execution_owner::CellSplitExecutionReceiptV1;
use crate::AcceptanceError;
use crate::durable::canonical_json;
use crate::durable::secure_root;
use crate::durable::sha256;

const RPC_SCHEMA: &str = "hepta.learning.cell-split.external-effect-rpc.v1";
const RPC_LIMIT: usize = 128 * 1024;
const RPC_TIMEOUT: Duration = Duration::from_secs(5);
const OWNER_COUNT: usize = 4;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitUnixEndpointV1 {
    pub owner_id: String,
    pub socket_path: PathBuf,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum RpcOperationV1 {
    Execute,
    ReadCommitted,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RpcRequestV1 {
    schema: String,
    operation: RpcOperationV1,
    intent: CellSplitExecutionIntentV1,
    plan: CellSplitExecutionPlanV1,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RpcResponseV1 {
    schema: String,
    operation: RpcOperationV1,
    intent: CellSplitExecutionIntentV1,
    owner_id: String,
    receipt: Option<CellSplitExecutionReceiptV1>,
    failure: Option<String>,
}

#[derive(Debug, Error)]
pub enum CellSplitUnixPortErrorV1 {
    #[error("invalid cell split external owner endpoint or RPC: {0}")]
    Invalid(&'static str),
    #[error("cell split remote owner rejected operation: {0}")]
    Remote(String),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Codec(#[from] serde_json::Error),
    #[error(transparent)]
    Durable(#[from] AcceptanceError),
    #[error(transparent)]
    Plan(#[from] CellSplitExecutionErrorV1),
}

/// Exactly four distinct owner sockets in a single canonical, private
/// directory. Socket-file replacement is checked before and after connection.
/// This is local transport authentication only; the coordinator separately
/// verifies all four pinned, distinct Ed25519 owner signatures.
pub struct CellSplitUnixPortV1 {
    root: PathBuf,
    plan: CellSplitExecutionPlanV1,
    plan_digest: String,
    endpoints: [CellSplitUnixEndpointV1; OWNER_COUNT],
}

impl CellSplitUnixPortV1 {
    pub fn new(
        root: &Path,
        plan: CellSplitExecutionPlanV1,
        endpoints: [CellSplitUnixEndpointV1; OWNER_COUNT],
    ) -> Result<Self, CellSplitUnixPortErrorV1> {
        plan.validate()?;
        let plan_digest = sha256(&canonical_json(&plan)?);
        let root = secure_root(root, "external effect socket root")?;
        let mut ids = BTreeSet::new();
        let mut paths = BTreeSet::new();
        for (index, endpoint) in endpoints.iter().enumerate() {
            if endpoint.owner_id != plan.owner_ids[index]
                || endpoint.owner_id.is_empty()
                || endpoint.owner_id.len() > 256
                || !endpoint
                    .owner_id
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
                || !ids.insert(endpoint.owner_id.clone())
                || !paths.insert(endpoint.socket_path.clone())
            {
                return Err(CellSplitUnixPortErrorV1::Invalid(
                    "owners, identities and socket paths must be unique",
                ));
            }
            Self::check_socket(&root, &endpoint.socket_path)?;
        }
        Ok(Self {
            root,
            plan,
            plan_digest,
            endpoints,
        })
    }

    fn check_socket(root: &Path, socket: &Path) -> Result<fs::Metadata, CellSplitUnixPortErrorV1> {
        if !socket.is_absolute() || socket.parent() != Some(root) {
            return Err(CellSplitUnixPortErrorV1::Invalid(
                "owner socket must be a direct child of private socket root",
            ));
        }
        // symlink_metadata, never metadata: sockets cannot be symlink aliases.
        let metadata = fs::symlink_metadata(socket)?;
        if !metadata.file_type().is_socket() || metadata.mode() & 0o022 != 0 {
            return Err(CellSplitUnixPortErrorV1::Invalid(
                "owner endpoint is not a protected Unix socket",
            ));
        }
        Ok(metadata)
    }

    fn rpc(
        &self,
        intent: &CellSplitExecutionIntentV1,
        operation: RpcOperationV1,
    ) -> Result<Option<CellSplitExecutionReceiptV1>, CellSplitUnixPortErrorV1> {
        let endpoint = self
            .endpoints
            .get(intent.step.index())
            .ok_or(CellSplitUnixPortErrorV1::Invalid("unknown split step"))?;
        if endpoint.owner_id != intent.owner_id || intent.plan_digest != self.plan_digest {
            return Err(CellSplitUnixPortErrorV1::Invalid("effect owner or plan mismatch"));
        }
        let before = Self::check_socket(&self.root, &endpoint.socket_path)?;
        let mut stream = UnixStream::connect(&endpoint.socket_path)?;
        let after = Self::check_socket(&self.root, &endpoint.socket_path)?;
        if before.dev() != after.dev() || before.ino() != after.ino() {
            return Err(CellSplitUnixPortErrorV1::Invalid(
                "owner socket replaced while connecting",
            ));
        }
        stream.set_read_timeout(Some(RPC_TIMEOUT))?;
        stream.set_write_timeout(Some(RPC_TIMEOUT))?;
        let request = RpcRequestV1 {
            schema: RPC_SCHEMA.to_owned(),
            operation,
            intent: intent.clone(),
            plan: self.plan.clone(),
        };
        let payload = canonical_json(&request)?;
        if payload.is_empty() || payload.len() > RPC_LIMIT {
            return Err(CellSplitUnixPortErrorV1::Invalid("request exceeds RPC bound"));
        }
        stream.write_all(&u32::try_from(payload.len()).map_err(|_| {
            CellSplitUnixPortErrorV1::Invalid("invalid RPC request length")
        })?.to_be_bytes())?;
        stream.write_all(&payload)?;
        stream.flush()?;

        let mut header = [0u8; 4];
        stream.read_exact(&mut header)?;
        let len = usize::try_from(u32::from_be_bytes(header))
            .map_err(|_| CellSplitUnixPortErrorV1::Invalid("invalid response length"))?;
        if len == 0 || len > RPC_LIMIT {
            return Err(CellSplitUnixPortErrorV1::Invalid("response exceeds RPC bound"));
        }
        let mut response_bytes = vec![0; len];
        stream.read_exact(&mut response_bytes)?;
        let response: RpcResponseV1 = serde_json::from_slice(&response_bytes)?;
        if canonical_json(&response)? != response_bytes
            || response.schema != RPC_SCHEMA
            || response.operation != operation
            || response.owner_id != endpoint.owner_id
            || response.intent != *intent
        {
            return Err(CellSplitUnixPortErrorV1::Invalid(
                "external owner reply changed its exact binding",
            ));
        }
        match (response.failure, response.receipt) {
            (Some(failure), None) if !failure.is_empty() && failure.len() <= 1024 => {
                Err(CellSplitUnixPortErrorV1::Remote(failure))
            }
            (None, receipt) if operation == RpcOperationV1::ReadCommitted => Ok(receipt),
            (None, Some(receipt)) if operation == RpcOperationV1::Execute => Ok(Some(receipt)),
            _ => Err(CellSplitUnixPortErrorV1::Invalid("inconsistent effect-owner reply")),
        }
    }
}

impl CellSplitExecutionPortV1 for CellSplitUnixPortV1 {
    type Error = CellSplitUnixPortErrorV1;

    fn execute(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<CellSplitExecutionReceiptV1, Self::Error> {
        self.rpc(intent, RpcOperationV1::Execute)?
            .ok_or(CellSplitUnixPortErrorV1::Invalid("execute omitted committed receipt"))
    }

    fn reconcile(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<Option<CellSplitExecutionReceiptV1>, Self::Error> {
        self.rpc(intent, RpcOperationV1::ReadCommitted)
    }

    fn verify_committed(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
        receipt: &CellSplitExecutionReceiptV1,
    ) -> Result<(), Self::Error> {
        // Read-only, from the SAME pinned owner. No receipt generation here.
        if self.reconcile(intent)?.as_ref() != Some(receipt) {
            return Err(CellSplitUnixPortErrorV1::Invalid(
                "external committed effect absent or changed",
            ));
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "cell_split_unix_port_tests.rs"]
mod tests;
