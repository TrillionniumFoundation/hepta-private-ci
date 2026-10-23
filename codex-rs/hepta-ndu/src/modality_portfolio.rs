//! MP1 research owner: compare supplied utilities, charge registered costs,
//! and require actual-neural acknowledgments. This does not solve Bellman
//! equations, execute kernels, authenticate hashes, or grant dispatch authority.

use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum ModalityV1 {
    Text,
    Audio,
    Image,
    Video,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum ActionV1 {
    Emit,
    Refine(ModalityV1),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) enum PolicyV1 {
    Adaptive,
    Committed(Vec<ModalityV1>),
    Clean,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct ConfigV1 {
    pub session_id: u64,
    pub q_index: u32,
    pub q_digest: Digest32,
    pub budget_macs: u64,
    pub init_macs: u64,
    pub max_refinements: u16,
    pub decoder_macs: [u64; 4],
    pub refine_macs: [u64; 4],
    pub latent_digests: [Digest32; 4],
    pub policy: PolicyV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum PhaseV1 {
    Ready,
    AwaitRefinement(ModalityV1),
    AwaitOutputs,
    Sealed,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct SnapshotV1 {
    pub session_id: u64,
    pub version: u64,
    pub remaining_macs: u64,
    pub counts: [u16; 4],
    pub latent_digests: [Digest32; 4],
    pub phase: PhaseV1,
}

impl SnapshotV1 {
    pub fn joint_digest(self) -> Digest32 {
        bundle_digest(
            b"hepta.modality-portfolio.latents.v1\0",
            &self.latent_digests,
        )
    }

    pub fn total_refinements(self) -> u16 {
        self.counts.into_iter().sum()
    }
}

pub(crate) fn bundle_digest(domain: &[u8], hashes: &[Digest32; 4]) -> Digest32 {
    Digest32::of_parts(&[
        domain,
        hashes[0].as_array(),
        hashes[1].as_array(),
        hashes[2].as_array(),
        hashes[3].as_array(),
    ])
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct ActionValueV1 {
    pub action: ActionV1,
    pub value: f64,
    pub cost_macs: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum PortfolioError {
    InvalidConfiguration,
    InvalidProfile,
    InvalidTable,
    NonFiniteValue,
    CostMismatch,
    NonZeroIneligible,
    SnapshotMismatch,
    PendingExecution,
    Sealed,
    ActionMismatch,
    UnrelatedLatentChanged,
    InvalidOutputs,
}

impl fmt::Display for PortfolioError {
    fn fmt(&self, output: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(output, "{self:?}")
    }
}

impl Error for PortfolioError {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct SessionV1 {
    config: ConfigV1,
    state: SnapshotV1,
    output_digests: Option<[Digest32; 4]>,
}

impl SessionV1 {
    pub fn new(config: ConfigV1) -> Result<Self, PortfolioError> {
        if config.session_id == 0
            || config.q_index >= 8
            || config.q_digest.is_zero()
            || config.latent_digests.into_iter().any(Digest32::is_zero)
            || matches!(&config.policy, PolicyV1::Committed(plan) if plan.len() > 2)
        {
            return Err(PortfolioError::InvalidConfiguration);
        }
        if config.budget_macs != 351_232
            || config.init_macs != 3_584
            || config.max_refinements != 2
            || config.decoder_macs != [6_656, 69_632, 53_248, 200_704]
            || config.refine_macs != [8_704; 4]
        {
            return Err(PortfolioError::InvalidProfile);
        }
        Ok(Self {
            state: SnapshotV1 {
                session_id: config.session_id,
                version: 0,
                remaining_macs: config.budget_macs - config.init_macs,
                counts: [0; 4],
                latent_digests: config.latent_digests,
                phase: PhaseV1::Ready,
            },
            config,
            output_digests: None,
        })
    }

    pub fn snapshot(&self) -> SnapshotV1 {
        self.state
    }

    pub fn output_digests(&self) -> Option<[Digest32; 4]> {
        self.output_digests
    }

    fn check_version(&self, session_id: u64, version: u64) -> Result<(), PortfolioError> {
        if self.state.phase == PhaseV1::Sealed {
            return Err(PortfolioError::Sealed);
        }
        if (session_id, version) != (self.state.session_id, self.state.version) {
            return Err(PortfolioError::SnapshotMismatch);
        }
        Ok(())
    }

    pub fn choose(
        &mut self,
        session_id: u64,
        version: u64,
        joint_digest: Digest32,
        actions: &[ActionValueV1],
    ) -> Result<ActionValueV1, PortfolioError> {
        self.check_version(session_id, version)?;
        if self.state.phase != PhaseV1::Ready {
            return Err(PortfolioError::PendingExecution);
        }
        if joint_digest != self.state.joint_digest() {
            return Err(PortfolioError::SnapshotMismatch);
        }
        if actions.len() != 5 {
            return Err(PortfolioError::InvalidTable);
        }
        let mut ordered = [None; 5];
        for candidate in actions {
            if !candidate.value.is_finite() {
                return Err(PortfolioError::NonFiniteValue);
            }
            let (index, cost) = match candidate.action {
                ActionV1::Emit => (0, 330_240),
                ActionV1::Refine(m) => (1 + m as usize, self.config.refine_macs[m as usize]),
            };
            if candidate.cost_macs != cost {
                return Err(PortfolioError::CostMismatch);
            }
            if ordered[index].replace(*candidate).is_some() {
                return Err(PortfolioError::InvalidTable);
            }
        }
        let depth = self.state.total_refinements();
        let mut selected: Option<ActionValueV1> = None;
        for candidate in ordered.into_iter().flatten() {
            let physically_feasible = match candidate.action {
                ActionV1::Emit => self.state.remaining_macs >= 330_240,
                ActionV1::Refine(_) => {
                    depth < self.config.max_refinements
                        && candidate
                            .cost_macs
                            .checked_add(330_240)
                            .is_some_and(|cost| cost <= self.state.remaining_macs)
                }
            };
            let policy_feasible = match &self.config.policy {
                PolicyV1::Adaptive => true,
                PolicyV1::Clean => candidate.action == ActionV1::Emit,
                PolicyV1::Committed(plan) => {
                    candidate.action
                        == plan
                            .get(usize::from(depth))
                            .copied()
                            .map_or(ActionV1::Emit, ActionV1::Refine)
                }
            };
            if !physically_feasible || !policy_feasible {
                if candidate.value != 0.0 {
                    return Err(PortfolioError::NonZeroIneligible);
                }
            } else if selected.is_none_or(|best| candidate.value > best.value + 1e-12) {
                selected = Some(candidate);
            }
        }
        let selected = selected.ok_or(PortfolioError::InvalidTable)?;
        self.state.remaining_macs -= selected.cost_macs;
        self.state.version += 1;
        self.state.phase = match selected.action {
            ActionV1::Emit => PhaseV1::AwaitOutputs,
            ActionV1::Refine(m) => {
                self.state.counts[m as usize] += 1;
                PhaseV1::AwaitRefinement(m)
            }
        };
        Ok(selected)
    }

    pub fn confirm_refinement(
        &mut self,
        session_id: u64,
        version: u64,
        modality: ModalityV1,
        hashes: [Digest32; 4],
    ) -> Result<(), PortfolioError> {
        self.check_version(session_id, version)?;
        let PhaseV1::AwaitRefinement(expected) = self.state.phase else {
            return Err(PortfolioError::PendingExecution);
        };
        if modality != expected {
            return Err(PortfolioError::ActionMismatch);
        }
        if hashes.into_iter().any(Digest32::is_zero) {
            return Err(PortfolioError::SnapshotMismatch);
        }
        if hashes
            .iter()
            .zip(self.state.latent_digests)
            .enumerate()
            .any(|(i, (next, old))| i != modality as usize && *next != old)
        {
            return Err(PortfolioError::UnrelatedLatentChanged);
        }
        self.state.latent_digests = hashes;
        self.state.phase = PhaseV1::Ready;
        Ok(())
    }

    pub fn confirm_emission(
        &mut self,
        session_id: u64,
        version: u64,
        joint_digest: Digest32,
        outputs: [Digest32; 4],
    ) -> Result<(), PortfolioError> {
        self.check_version(session_id, version)?;
        if self.state.phase != PhaseV1::AwaitOutputs {
            return Err(PortfolioError::PendingExecution);
        }
        if joint_digest != self.state.joint_digest() {
            return Err(PortfolioError::SnapshotMismatch);
        }
        if outputs.into_iter().any(Digest32::is_zero) {
            return Err(PortfolioError::InvalidOutputs);
        }
        self.output_digests = Some(outputs);
        self.state.phase = PhaseV1::Sealed;
        Ok(())
    }
}

#[cfg(test)]
#[path = "modality_portfolio_tests.rs"]
mod tests;
