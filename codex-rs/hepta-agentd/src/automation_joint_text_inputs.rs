//! Fixed-root custody, owned by the original registered Joint provider. This
//! module stages data only; it has no process launch, lease, signer or receipt.

use std::io;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_automation::JOINT_TEXT_MAX_COMMAND_BYTES;
use codex_hepta_automation::JOINT_TEXT_MAX_PACKET_BYTES;
use codex_hepta_automation::JOINT_TEXT_MAX_REQUEST_BYTES;
use codex_hepta_automation::JointTextInputRefV1;
use codex_hepta_automation::JointTextRootIdentityV1;
use codex_hepta_contracts::Sha256Digest;

use crate::PreparedJointTextTrainingRequestV1;

#[path = "automation_joint_text_input_files.rs"]
mod files;

#[path = "automation_joint_text_completion.rs"]
mod completion;
#[path = "automation_joint_text_retained.rs"]
mod retained;

pub(crate) use completion::JointTextCompletedOutputV1;
pub(crate) use completion::JointTextRecordedSourceV1;
pub(crate) use completion::JointTextReservationV1;
pub(crate) use retained::JointTextJobBindingV1;

const ROOT_LAYOUT: &[u8] =
    b"{\"schema_version\":1,\"layout\":\"hepta.joint.text.linux-supervisor.v1\"}";

pub(crate) struct JointTextInputCustodyV1 {
    root_path: PathBuf,
    root: files::Directory,
}

/// Owned readback bytes; their custody does not authenticate a current learning
/// snapshot or replace the original Memory/Ledger owners at completion.
pub(crate) struct JointTextInputBytesV1 {
    pub(crate) request: Vec<u8>,
    pub(crate) predecessor: Vec<u8>,
}

impl JointTextInputCustodyV1 {
    /// Open only an existing root. HC6 must admit its signed deployment and
    /// retain this concrete handle; a caller cannot provision authority here.
    pub(crate) fn open_existing(
        root: &Path,
        expected: &JointTextRootIdentityV1,
    ) -> io::Result<Self> {
        let custody = Self {
            root_path: root.to_path_buf(),
            root: files::Directory::open_root(root, expected)?,
        };
        custody.verify_root()?;
        Ok(custody)
    }

    /// Used by the real provider's mandatory contact guard. The deployment
    /// owner must already have provisioned this exact marker; never create it.
    pub(crate) fn verify_root(&self) -> io::Result<()> {
        self.root.verify_root(&self.root_path)?;
        let marker = self.root.read("layout.json", ROOT_LAYOUT.len())?;
        if marker.bytes != ROOT_LAYOUT {
            return files::invalid("Joint root layout marker changed");
        }
        marker.verify(&self.root, "layout.json")?;
        self.root.verify_root(&self.root_path)
    }

    pub(crate) fn stage(
        &self,
        prepared: &PreparedJointTextTrainingRequestV1,
        predecessor: &[u8],
    ) -> io::Result<JointTextInputRefV1> {
        let reference = prepared
            .input_reference(predecessor)
            .map_err(io::Error::other)?;
        self.stage_bound(&reference, prepared.request_bytes(), predecessor)?;
        Ok(reference)
    }

    fn stage_bound(
        &self,
        reference: &JointTextInputRefV1,
        request: &[u8],
        predecessor: &[u8],
    ) -> io::Result<()> {
        reference.validate().map_err(io::Error::other)?;
        if request.len() as u64 != reference.manifest.request_bytes
            || Sha256Digest::for_bytes(request) != reference.manifest.request_sha256
            || predecessor.len() as u64 != reference.manifest.predecessor_bytes
            || Sha256Digest::for_bytes(predecessor) != reference.manifest.predecessor_sha256
        {
            return files::invalid("Joint staging bytes do not match the prepared binding");
        }
        self.verify_root()?;
        let (inputs, _) = self.root.create("inputs")?;
        let (entry, creation) = inputs.create(reference.input_id.as_str())?;
        if let files::Creation::Created = creation {
            entry.write_new("request.json", request)?;
            entry.write_new("predecessor.heptapk", predecessor)?;
            // Last durable file: a crash before it leaves an unusable partial
            // entry, not a reason to overwrite it or retry a worker launch.
            entry.write_new(
                "manifest.json",
                &reference.manifest.encode().map_err(io::Error::other)?,
            )?;
        }
        self.root.verify_child("inputs", &inputs)?;
        inputs.verify_child(reference.input_id.as_str(), &entry)?;
        let readback = self.read(reference)?;
        if readback.request != request || readback.predecessor != predecessor {
            return files::invalid("Joint staging readback differs from its original bytes");
        }
        Ok(())
    }

    pub(crate) fn read(
        &self,
        reference: &JointTextInputRefV1,
    ) -> io::Result<JointTextInputBytesV1> {
        reference.validate().map_err(io::Error::other)?;
        self.verify_root()?;
        let inputs = self.root.open("inputs")?;
        let entry = inputs.open(reference.input_id.as_str())?;
        let names = ["request.json", "predecessor.heptapk", "manifest.json"];
        entry.exact_files(&names)?;
        let manifest = entry.read("manifest.json", JOINT_TEXT_MAX_COMMAND_BYTES)?;
        let request = entry.read("request.json", JOINT_TEXT_MAX_REQUEST_BYTES)?;
        let predecessor = entry.read("predecessor.heptapk", JOINT_TEXT_MAX_PACKET_BYTES)?;
        if manifest.bytes != reference.manifest.encode().map_err(io::Error::other)?
            || Sha256Digest::for_bytes(&manifest.bytes) != reference.manifest_sha256
            || request.bytes.len() as u64 != reference.manifest.request_bytes
            || Sha256Digest::for_bytes(&request.bytes) != reference.manifest.request_sha256
            || predecessor.bytes.len() as u64 != reference.manifest.predecessor_bytes
            || Sha256Digest::for_bytes(&predecessor.bytes) != reference.manifest.predecessor_sha256
        {
            return files::invalid("Joint input closure does not match the original descriptor");
        }
        manifest.verify(&entry, "manifest.json")?;
        request.verify(&entry, "request.json")?;
        predecessor.verify(&entry, "predecessor.heptapk")?;
        entry.exact_files(&names)?;
        inputs.verify_child(reference.input_id.as_str(), &entry)?;
        self.root.verify_child("inputs", &inputs)?;
        self.verify_root()?;
        Ok(JointTextInputBytesV1 {
            request: request.bytes,
            predecessor: predecessor.bytes,
        })
    }
}

#[cfg(test)]
#[path = "automation_joint_text_inputs_tests.rs"]
mod tests;
