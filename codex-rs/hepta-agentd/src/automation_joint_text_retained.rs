//! Fixed effect-request retention under the already admitted input root.
//! These records preserve exact bytes for Status. They grant no restart.

use std::io;

use codex_hepta_automation::JOINT_TEXT_MAX_COMMAND_BYTES;
use codex_hepta_automation::JointTextInputRefV1;
use codex_hepta_automation::JointTextJobIdentityV1;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

use super::JointTextInputCustodyV1;
use super::files;

const MAX_RETAINED_EFFECT_BYTES: usize = 8 * crate::MAX_AUTOMATION_EFFECT_WIRE_BYTES;

/// Written only after the ordinary owner's actual verified FinalUse claim.
/// Reusing an input under a different logical job is refused across restarts.
#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct JointTextJobBindingV1 {
    pub(crate) schema_version: u32,
    pub(crate) provider_scope: String,
    pub(crate) run_id: String,
    pub(crate) step_id: String,
    pub(crate) identity: JointTextJobIdentityV1,
    pub(crate) input: JointTextInputRefV1,
}

impl JointTextJobBindingV1 {
    fn validate(&self) -> io::Result<()> {
        self.input.validate().map_err(io::Error::other)?;
        let payload = self.input.encode().map_err(io::Error::other)?;
        let expected = JointTextJobIdentityV1::for_taskflow(
            &self.provider_scope,
            &self.run_id,
            &self.step_id,
            Sha256Digest::for_bytes(&payload),
        )
        .map_err(io::Error::other)?;
        if self.schema_version != 1 || self.identity != expected {
            return files::invalid("Joint job binding differs from the original logical effect");
        }
        Ok(())
    }
}

impl JointTextInputCustodyV1 {
    pub(crate) fn bind_job(&self, binding: &JointTextJobBindingV1) -> io::Result<()> {
        binding.validate()?;
        let bytes = serde_json::to_vec(binding).map_err(io::Error::other)?;
        if bytes.len() > JOINT_TEXT_MAX_COMMAND_BYTES {
            return files::invalid("Joint original job binding exceeds the effect bound");
        }
        self.read(&binding.input)?;
        self.verify_root()?;
        let (bindings, _) = self.root.create("job-bindings")?;
        let name = format!("{}.json", binding.input.input_id.as_str());
        match bindings.write_new(&name, &bytes) {
            Ok(()) => {}
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {}
            Err(error) => return Err(error),
        }
        let observed = bindings.read(&name, JOINT_TEXT_MAX_COMMAND_BYTES)?;
        if observed.bytes != bytes {
            return files::invalid("Joint input is already bound to another or incomplete job");
        }
        observed.verify(&bindings, &name)?;
        self.root.verify_child("job-bindings", &bindings)?;
        self.verify_root()
    }

    pub(crate) fn read_bound_job(
        &self,
        input: &JointTextInputRefV1,
    ) -> io::Result<JointTextJobBindingV1> {
        input.validate().map_err(io::Error::other)?;
        self.verify_root()?;
        let bindings = self.root.open("job-bindings")?;
        let name = format!("{}.json", input.input_id.as_str());
        let observed = bindings.read(&name, JOINT_TEXT_MAX_COMMAND_BYTES)?;
        let binding: JointTextJobBindingV1 =
            serde_json::from_slice(&observed.bytes).map_err(io::Error::other)?;
        binding.validate()?;
        if binding.input != *input
            || serde_json::to_vec(&binding).map_err(io::Error::other)? != observed.bytes
        {
            return files::invalid("Joint original job record does not match the fixed input");
        }
        observed.verify(&bindings, &name)?;
        self.root.verify_child("job-bindings", &bindings)?;
        self.verify_root()?;
        Ok(binding)
    }

    pub(crate) fn retain_effect(
        &self,
        intent_digest: &Sha256Digest,
        bytes: &[u8],
    ) -> io::Result<()> {
        Sha256Digest::parse(intent_digest.as_str()).map_err(io::Error::other)?;
        if bytes.is_empty() || bytes.len() > MAX_RETAINED_EFFECT_BYTES {
            return files::invalid("retained Joint effect exceeds its bound");
        }
        self.verify_root()?;
        let (requests, _) = self.root.create("taskflow-requests")?;
        let name = format!("{}.json", intent_digest.as_str());
        match requests.write_new(&name, bytes) {
            Ok(()) => {}
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {}
            Err(error) => return Err(error),
        }
        let observed = requests.read(&name, MAX_RETAINED_EFFECT_BYTES)?;
        if observed.bytes != bytes {
            return files::invalid("retained Joint effect has conflicting or partial bytes");
        }
        observed.verify(&requests, &name)?;
        self.root.verify_child("taskflow-requests", &requests)?;
        self.verify_root()
    }

    pub(crate) fn read_retained_effect(&self, intent_digest: &Sha256Digest) -> io::Result<Vec<u8>> {
        Sha256Digest::parse(intent_digest.as_str()).map_err(io::Error::other)?;
        self.verify_root()?;
        let requests = self.root.open("taskflow-requests")?;
        let name = format!("{}.json", intent_digest.as_str());
        let observed = requests.read(&name, MAX_RETAINED_EFFECT_BYTES)?;
        observed.verify(&requests, &name)?;
        self.root.verify_child("taskflow-requests", &requests)?;
        self.verify_root()?;
        Ok(observed.bytes)
    }
}
