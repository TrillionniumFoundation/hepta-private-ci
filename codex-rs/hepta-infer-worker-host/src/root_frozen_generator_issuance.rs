//! Bound whole-material work globally and serialize each original Agent owner.
//! A queued same-Agent request does not consume another Agent's global slot.
use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_hepta_contracts::AgentId;
use std::collections::BTreeMap;
use tokio::sync::Semaphore;
use tokio::sync::SemaphorePermit;

pub(super) struct IssuanceGates {
    global: Semaphore,
    agents: BTreeMap<AgentId, Semaphore>,
}

pub(super) struct IssuancePermit<'a> {
    _global: SemaphorePermit<'a>,
    _agent: SemaphorePermit<'a>,
}

impl IssuanceGates {
    pub(super) fn new(agents: impl Iterator<Item = AgentId>, capacity: usize) -> Result<Self> {
        ensure!(
            (1..=4).contains(&capacity),
            "bounded original issuance capacity"
        );
        Ok(Self {
            global: Semaphore::new(capacity),
            agents: agents
                .map(|agent| (agent, Semaphore::new(/*permits*/ 1)))
                .collect(),
        })
    }

    pub(super) async fn acquire(&self, agent: &AgentId) -> Result<IssuancePermit<'_>> {
        let gate = self
            .agents
            .get(agent)
            .context("original issuance Agent absent")?;
        let per_agent = gate.acquire().await?;
        let global = self.global.acquire().await?;
        Ok(IssuancePermit {
            _global: global,
            _agent: per_agent,
        })
    }
}

#[cfg(test)]
#[path = "root_frozen_generator_issuance_tests.rs"]
mod tests;
