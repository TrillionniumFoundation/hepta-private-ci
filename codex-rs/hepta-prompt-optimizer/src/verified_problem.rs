#[derive(Clone, Copy, Debug, Default, Eq, Ord, PartialEq, PartialOrd)]
struct FactorMask([u64; 2]);

impl FactorMask {
    fn insert(&mut self, index: usize) {
        self.0[index / 64] |= 1_u64 << (index % 64);
    }

    fn remove(&mut self, index: usize) {
        self.0[index / 64] &= !(1_u64 << (index % 64));
    }

    fn contains(self, index: usize) -> bool {
        self.0[index / 64] & (1_u64 << (index % 64)) != 0
    }

    fn union(self, other: Self) -> Self {
        Self([self.0[0] | other.0[0], self.0[1] | other.0[1]])
    }

    fn intersects(self, other: Self) -> bool {
        self.0[0] & other.0[0] != 0 || self.0[1] & other.0[1] != 0
    }

    fn is_subset(self, other: Self) -> bool {
        self.0[0] & !other.0[0] == 0 && self.0[1] & !other.0[1] == 0
    }

    fn count(self) -> usize {
        usize::try_from(self.0[0].count_ones())
            .unwrap_or(usize::MAX)
            .saturating_add(
                usize::try_from(self.0[1].count_ones()).unwrap_or(usize::MAX),
            )
    }

    fn indices(self, limit: usize) -> impl Iterator<Item = usize> {
        (0..limit).filter(move |index| self.contains(*index))
    }
}

struct DensePromptProblem<'a> {
    rows: Vec<&'a v1::PricedPromptCandidateV1>,
    id_to_index: BTreeMap<StableId, usize>,
    requires: Vec<FactorMask>,
    closures: Vec<FactorMask>,
    conflicts: Vec<FactorMask>,
    dominated: FactorMask,
    pair_values: BTreeMap<(usize, usize), FixedQ32>,
    token_budget: u64,
    maximum_selected: usize,
}

impl<'a> DensePromptProblem<'a> {
    fn new(
        priced: &'a VerifiedPricedPromptCandidatesV2,
        token_budget: u64,
        maximum_selected: usize,
    ) -> Result<Self, VerifiedPromptError> {
        if priced.rows.len() > MAX_CANONICAL_PROMPT_FACTORS {
            return Err(VerifiedPromptError::CandidateLimit);
        }
        let mut rows = priced.rows.iter().collect::<Vec<_>>();
        rows.sort_by(|left, right| left.binding.factor_id.cmp(&right.binding.factor_id));
        let mut id_to_index = BTreeMap::new();
        for (index, row) in rows.iter().enumerate() {
            if id_to_index
                .insert(row.binding.factor_id.clone(), index)
                .is_some()
            {
                return Err(VerifiedPromptError::CandidateBinding(
                    row.binding.factor_id.to_string(),
                ));
            }
        }
        let count = rows.len();
        Ok(Self {
            rows,
            id_to_index,
            requires: vec![FactorMask::default(); count],
            closures: vec![FactorMask::default(); count],
            conflicts: vec![FactorMask::default(); count],
            dominated: FactorMask::default(),
            pair_values: BTreeMap::new(),
            token_budget,
            maximum_selected,
        })
    }

    fn finish_constraints(&mut self) -> Result<(), VerifiedPromptError> {
        let count = self.rows.len();
        let mut visiting = vec![false; count];
        let mut complete = vec![false; count];
        for index in 0..count {
            self.closures[index] = self.compute_closure(index, &mut visiting, &mut complete)?;
            if self.closures[index]
                .indices(count)
                .any(|member| self.conflicts[member].intersects(self.closures[index]))
            {
                return Err(VerifiedPromptError::UnsatisfiableGraph(
                    self.rows[index].binding.factor_id.to_string(),
                ));
            }
        }
        Ok(())
    }

    fn compute_closure(
        &mut self,
        index: usize,
        visiting: &mut [bool],
        complete: &mut [bool],
    ) -> Result<FactorMask, VerifiedPromptError> {
        if complete[index] {
            return Ok(self.closures[index]);
        }
        if visiting[index] {
            return Err(VerifiedPromptError::PrerequisiteCycle(
                self.rows[index].binding.factor_id.to_string(),
            ));
        }
        visiting[index] = true;
        let mut closure = FactorMask::default();
        closure.insert(index);
        let prerequisites = self.requires[index]
            .indices(self.rows.len())
            .collect::<Vec<_>>();
        for prerequisite in prerequisites {
            closure = closure.union(self.compute_closure(prerequisite, visiting, complete)?);
        }
        visiting[index] = false;
        complete[index] = true;
        self.closures[index] = closure;
        Ok(closure)
    }

    fn repair_after_removal(&self, mut mask: FactorMask) -> FactorMask {
        loop {
            let invalid = mask
                .indices(self.rows.len())
                .find(|index| !self.closures[*index].is_subset(mask));
            let Some(index) = invalid else {
                break;
            };
            mask.remove(index);
        }
        mask
    }

    fn tokens(&self, mask: FactorMask) -> Result<u64, VerifiedPromptError> {
        mask.indices(self.rows.len())
            .try_fold(0_u64, |total, index| {
                total
                    .checked_add(u64::from(self.rows[index].pricing.token_cost))
                    .ok_or(VerifiedPromptError::Arithmetic)
            })
    }

    fn utility(&self, mask: FactorMask) -> Result<FixedQ32, VerifiedPromptError> {
        let mut total = FixedQ32::ZERO;
        for index in mask.indices(self.rows.len()) {
            total = total
                .checked_add(self.rows[index].net_utility_q32)
                .map_err(|_| VerifiedPromptError::Arithmetic)?;
        }
        for ((left, right), marginal) in &self.pair_values {
            if mask.contains(*left) && mask.contains(*right) {
                total = total
                    .checked_add(*marginal)
                    .map_err(|_| VerifiedPromptError::Arithmetic)?;
            }
        }
        Ok(total)
    }

    fn relaxed_upper_bound(&self) -> Result<FixedQ32, VerifiedPromptError> {
        self.relaxed_upper_bound_from(FactorMask::default(), FactorMask::default(), 0)
    }

    fn relaxed_upper_bound_from(
        &self,
        selected: FactorMask,
        excluded: FactorMask,
        start_index: usize,
    ) -> Result<FixedQ32, VerifiedPromptError> {
        let mut bound = self.utility(selected)?;
        for index in start_index..self.rows.len() {
            if selected.contains(index)
                || excluded.contains(index)
                || self.dominated.contains(index)
            {
                continue;
            }
            let utility = self.rows[index].net_utility_q32;
            if utility > FixedQ32::ZERO {
                bound = bound
                    .checked_add(utility)
                    .map_err(|_| VerifiedPromptError::Arithmetic)?;
            }
        }
        for ((left, right), marginal) in &self.pair_values {
            if *marginal <= FixedQ32::ZERO
                || excluded.contains(*left)
                || excluded.contains(*right)
                || (selected.contains(*left) && selected.contains(*right))
            {
                continue;
            }
            bound = bound
                .checked_add(*marginal)
                .map_err(|_| VerifiedPromptError::Arithmetic)?;
        }
        Ok(bound)
    }
}
