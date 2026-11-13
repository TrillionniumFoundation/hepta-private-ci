//! Original Root fixes source descriptors before enabling its one-shot capture.
//! These handles are independent read-only descriptions, never writer duplicates.

use super::*;

pub(crate) struct RetainedRootHistoricalSourceInputsV1 {
    inputs: RootHistoricalSourceInputsV1,
    files: [FilePin; 2],
    identity: Digest32,
    target: CellGenerationOwnerBindingV1,
}

impl RootHistoricalSourceInputsV1 {
    pub(crate) fn retain_original(
        mut self,
        identity: &crate::AgentdIdentity,
        target: &CellGenerationOwnerBindingV1,
        uid: u32,
        gid: u32,
    ) -> io::Result<RetainedRootHistoricalSourceInputsV1> {
        original_root()?;
        require_target(target, &self.definition, &self.source)?;
        if target.scope().agent_id != identity.agent_id.as_str()
            || self.fence.owner_agent_id != identity.agent_id
            || identity.spawn_generation.checked_add(1) != Some(self.fence.generation)
        {
            return Err(io::Error::other(
                "original source configuration differs from A",
            ));
        }
        let (journal, journal_pin) = FilePin::readonly(&self.journal, uid, gid)?;
        let (witness, witness_pin) = FilePin::readonly(&self.witness, uid, gid)?;
        if (journal_pin.device, journal_pin.inode) == (witness_pin.device, witness_pin.inode) {
            return Err(io::Error::other(
                "independent original source witness required",
            ));
        }
        self.journal = journal;
        self.witness = witness;
        Ok(RetainedRootHistoricalSourceInputsV1 {
            inputs: self,
            files: [journal_pin, witness_pin],
            identity: crate::neuron_generation_process_identity_digest_v1(identity)
                .map_err(io::Error::other)?,
            target: target.clone(),
        })
    }
}

impl RetainedRootHistoricalSourceInputsV1 {
    pub(crate) fn into_registered(
        self,
        identity: &crate::AgentdIdentity,
        target: &CellGenerationOwnerBindingV1,
        uid: u32,
        gid: u32,
    ) -> io::Result<RootHistoricalSourceInputsV1> {
        original_root()?;
        if &self.target != target
            || self.identity
                != crate::neuron_generation_process_identity_digest_v1(identity)
                    .map_err(io::Error::other)?
            || self.files
                != [
                    FilePin::read(&self.inputs.journal, uid, gid)?,
                    FilePin::read(&self.inputs.witness, uid, gid)?,
                ]
        {
            return Err(io::Error::other(
                "registered original source custody changed",
            ));
        }
        Ok(self.inputs)
    }
}
