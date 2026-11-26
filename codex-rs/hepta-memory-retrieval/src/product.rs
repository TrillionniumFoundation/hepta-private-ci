//! Product-only retrieval admission.
//!
//! Compatibility functions remain available for historical callers, but a
//! production caller should cross this boundary exactly once. The boundary
//! owns an immutable, validated candidate set, requires an explicit source
//! completeness policy, and requires host-supplied bounded work control.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use crate::EngramDynamicsPolicyV1;
use crate::EngramSnapshotV1;
use crate::GeneratedCandidateInputV1;
use crate::GeneratedRecallV1;
use crate::GeneratorErrorV1;
use crate::MemoryCueV1;
use crate::RecallWorkControlV1;
use crate::RetrievalGeneratorOwnerV1;
use crate::RetrievalPolicyV1;
use crate::RetrievalSourceCompletenessV1;
use crate::recall_generated_with_engram_controlled;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum IncompleteSourceActionV1 {
    Degrade,
    Abstain,
    FailClosed,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct RetrievalCompletenessPolicyRowV1 {
    pub generator: RetrievalGeneratorOwnerV1,
    pub on_limit_reached: IncompleteSourceActionV1,
    pub on_unavailable: IncompleteSourceActionV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalCompletenessPolicyV1 {
    rows: Vec<RetrievalCompletenessPolicyRowV1>,
}

impl RetrievalCompletenessPolicyV1 {
    /// Build the complete expected owner inventory for one product profile.
    ///
    /// Every row names an owner that must be represented in the input. A
    /// missing batch is equivalent to an explicit `Unavailable` batch and is
    /// evaluated with `on_unavailable`; omitting an authority-critical owner
    /// therefore cannot turn a partial observation into `Complete`.
    ///
    /// `Unavailable -> Degrade` is deliberately rejected. The strict generated
    /// recall receipt requires every enabled owner and cannot bind an absent
    /// owner generation. A future degraded policy may enable that transition
    /// only after the unavailable-owner evidence and effective policy are
    /// cryptographically bound into the recall receipt.
    pub fn new(
        mut rows: Vec<RetrievalCompletenessPolicyRowV1>,
    ) -> Result<Self, ProductRecallErrorV1> {
        rows.sort_by_key(|row| row.generator);
        if rows.is_empty()
            || rows
                .windows(2)
                .any(|window| window[0].generator == window[1].generator)
        {
            return Err(ProductRecallErrorV1::InvalidCompletenessPolicy);
        }
        if let Some(row) = rows
            .iter()
            .find(|row| row.on_unavailable == IncompleteSourceActionV1::Degrade)
        {
            return Err(
                ProductRecallErrorV1::UnavailableDegradationRequiresBoundPolicy(row.generator),
            );
        }
        Ok(Self { rows })
    }

    #[must_use]
    pub fn rows(&self) -> &[RetrievalCompletenessPolicyRowV1] {
        &self.rows
    }

    pub fn evaluate(
        &self,
        input: &GeneratedCandidateInputV1,
    ) -> Result<RetrievalCompletenessDecisionV1, ProductRecallErrorV1> {
        input.validate().map_err(ProductRecallErrorV1::Generator)?;
        let policy = self
            .rows
            .iter()
            .map(|row| (row.generator, row))
            .collect::<BTreeMap<_, _>>();
        let batches = input
            .batches
            .iter()
            .map(|batch| (batch.receipt.generator, batch))
            .collect::<BTreeMap<_, _>>();

        // Reject caller-supplied owners outside the selected product profile.
        for batch in &input.batches {
            if !policy.contains_key(&batch.receipt.generator) {
                return Err(ProductRecallErrorV1::MissingCompletenessPolicy(
                    batch.receipt.generator,
                ));
            }
        }

        let mut incomplete_sources = Vec::new();
        let mut decision: Option<IncompleteSourceActionV1> = None;
        // Iterate the policy, not the supplied batches. The policy is the
        // expected owner inventory, so an omitted batch is unavailable rather
        // than invisible.
        for row in &self.rows {
            let completeness = batches
                .get(&row.generator)
                .map_or(RetrievalSourceCompletenessV1::Unavailable, |batch| {
                    batch.receipt.completeness
                });
            let action = match completeness {
                RetrievalSourceCompletenessV1::Exhausted => continue,
                RetrievalSourceCompletenessV1::LimitReached => row.on_limit_reached,
                RetrievalSourceCompletenessV1::Unavailable => row.on_unavailable,
            };
            incomplete_sources.push(IncompleteRetrievalSourceV1 {
                generator: row.generator,
                completeness,
                action,
            });
            decision = Some(decision.map_or(action, |current| current.max(action)));
        }
        if incomplete_sources.is_empty() {
            return Ok(RetrievalCompletenessDecisionV1::Complete);
        }
        let decision = decision.ok_or(ProductRecallErrorV1::InvalidCompletenessPolicy)?;
        Ok(match decision {
            IncompleteSourceActionV1::Degrade => {
                RetrievalCompletenessDecisionV1::Degraded { incomplete_sources }
            }
            IncompleteSourceActionV1::Abstain => {
                RetrievalCompletenessDecisionV1::Abstain { incomplete_sources }
            }
            IncompleteSourceActionV1::FailClosed => {
                RetrievalCompletenessDecisionV1::FailClosed { incomplete_sources }
            }
        })
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct IncompleteRetrievalSourceV1 {
    pub generator: RetrievalGeneratorOwnerV1,
    pub completeness: RetrievalSourceCompletenessV1,
    pub action: IncompleteSourceActionV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RetrievalCompletenessDecisionV1 {
    Complete,
    Degraded {
        incomplete_sources: Vec<IncompleteRetrievalSourceV1>,
    },
    Abstain {
        incomplete_sources: Vec<IncompleteRetrievalSourceV1>,
    },
    FailClosed {
        incomplete_sources: Vec<IncompleteRetrievalSourceV1>,
    },
}

impl RetrievalCompletenessDecisionV1 {
    #[must_use]
    pub fn permits_recall(&self) -> bool {
        matches!(self, Self::Complete | Self::Degraded { .. })
    }
}

/// An immutable candidate set that has passed owner, generation, rank,
/// identity, receipt, global capacity, and source-completeness admission.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ValidatedCandidateSetV1 {
    input: GeneratedCandidateInputV1,
    completeness: RetrievalCompletenessDecisionV1,
}

impl ValidatedCandidateSetV1 {
    pub fn new(
        input: GeneratedCandidateInputV1,
        policy: &RetrievalCompletenessPolicyV1,
    ) -> Result<Self, ProductRecallErrorV1> {
        input.validate().map_err(ProductRecallErrorV1::Generator)?;
        let completeness = policy.evaluate(&input)?;
        Ok(Self {
            input,
            completeness,
        })
    }

    #[must_use]
    pub fn input(&self) -> &GeneratedCandidateInputV1 {
        &self.input
    }

    #[must_use]
    pub fn completeness(&self) -> &RetrievalCompletenessDecisionV1 {
        &self.completeness
    }

    #[must_use]
    pub fn generators(&self) -> BTreeSet<RetrievalGeneratorOwnerV1> {
        self.input
            .batches
            .iter()
            .map(|batch| batch.receipt.generator)
            .collect()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductGeneratedRecallV1 {
    pub recall: Option<GeneratedRecallV1>,
    pub completeness: RetrievalCompletenessDecisionV1,
}

/// The only product facade in this crate. It has no compatibility work-control
/// fallback. Abstention due to incomplete required sources is represented as a
/// typed successful decision with no recall packet; authority-critical
/// incompleteness is an error and cannot be downgraded by the caller.
pub fn recall_product_with_engram_v1(
    cue: &MemoryCueV1,
    retrieval_policy: &RetrievalPolicyV1,
    candidates: &ValidatedCandidateSetV1,
    engram_snapshot: &EngramSnapshotV1,
    dynamics_policy: &EngramDynamicsPolicyV1,
    work: &RecallWorkControlV1,
) -> Result<ProductGeneratedRecallV1, ProductRecallErrorV1> {
    match candidates.completeness() {
        RetrievalCompletenessDecisionV1::FailClosed { incomplete_sources } => {
            return Err(ProductRecallErrorV1::FailClosed(incomplete_sources.clone()));
        }
        RetrievalCompletenessDecisionV1::Abstain { .. } => {
            work.checkpoint().map_err(|error| {
                ProductRecallErrorV1::Generator(GeneratorErrorV1::Recall(error))
            })?;
            return Ok(ProductGeneratedRecallV1 {
                recall: None,
                completeness: candidates.completeness().clone(),
            });
        }
        RetrievalCompletenessDecisionV1::Complete
        | RetrievalCompletenessDecisionV1::Degraded { .. } => {}
    }
    let recall = recall_generated_with_engram_controlled(
        cue,
        retrieval_policy,
        candidates.input(),
        engram_snapshot,
        dynamics_policy,
        work,
    )
    .map_err(ProductRecallErrorV1::Generator)?;
    Ok(ProductGeneratedRecallV1 {
        recall: Some(recall),
        completeness: candidates.completeness().clone(),
    })
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProductRecallErrorV1 {
    Generator(GeneratorErrorV1),
    InvalidCompletenessPolicy,
    MissingCompletenessPolicy(RetrievalGeneratorOwnerV1),
    UnavailableDegradationRequiresBoundPolicy(RetrievalGeneratorOwnerV1),
    FailClosed(Vec<IncompleteRetrievalSourceV1>),
}

impl fmt::Display for ProductRecallErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ProductRecallErrorV1 {}

#[cfg(test)]
#[path = "product_tests.rs"]
mod tests;
