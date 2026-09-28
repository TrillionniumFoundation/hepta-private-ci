//! Bounded role assignment. A frame only removes identities it inserted.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

pub(crate) const DEFAULT_ASSIGNMENT_BUDGET: usize = 100_000;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct AssignmentBudgetExceeded;

pub(crate) fn distinct_identity_assignment<R: Copy + Ord>(
    roles: &[R],
    identities: &BTreeMap<R, BTreeSet<(String, String)>>,
    mut budget: usize,
) -> Result<bool, AssignmentBudgetExceeded> {
    if roles.is_empty() || roles.iter().collect::<BTreeSet<_>>().len() != roles.len() {
        return Ok(false);
    }
    let mut ordered = roles.to_vec();
    ordered.sort_by_key(|role| identities.get(role).map_or(0, BTreeSet::len));
    if ordered
        .iter()
        .any(|role| identities.get(role).is_none_or(BTreeSet::is_empty))
    {
        return Ok(false);
    }
    let mut principals = BTreeSet::new();
    let mut keys = BTreeSet::new();
    for (principal, key) in ordered
        .iter()
        .filter_map(|role| identities.get(role))
        .flatten()
    {
        principals.insert(principal.as_str());
        keys.insert(key.as_str());
    }
    if principals.len() < roles.len() || keys.len() < roles.len() {
        return Ok(false);
    }
    search(
        0,
        &ordered,
        identities,
        &mut BTreeSet::new(),
        &mut BTreeSet::new(),
        &mut budget,
    )
}

fn search<'a, R: Copy + Ord>(
    index: usize,
    roles: &[R],
    identities: &'a BTreeMap<R, BTreeSet<(String, String)>>,
    principals: &mut BTreeSet<&'a str>,
    keys: &mut BTreeSet<&'a str>,
    budget: &mut usize,
) -> Result<bool, AssignmentBudgetExceeded> {
    if index == roles.len() {
        return Ok(true);
    }
    let Some(options) = identities.get(&roles[index]) else {
        return Ok(false);
    };
    for (principal, key) in options {
        *budget = budget.checked_sub(1).ok_or(AssignmentBudgetExceeded)?;
        if principals.contains(principal.as_str()) || keys.contains(key.as_str()) {
            continue;
        }
        principals.insert(principal.as_str());
        keys.insert(key.as_str());
        let result = search(index + 1, roles, identities, principals, keys, budget);
        principals.remove(principal.as_str());
        keys.remove(key.as_str());
        if result? {
            return Ok(true);
        }
    }
    Ok(false)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn options(values: &[(&str, &str)]) -> BTreeSet<(String, String)> {
        values
            .iter()
            .map(|(principal, key)| ((*principal).to_string(), (*key).to_string()))
            .collect()
    }

    #[test]
    fn three_roles_cannot_reuse_the_outer_principal() {
        let identities = BTreeMap::from([
            (0, options(&[("alice", "key-1")])),
            (1, options(&[("alice", "key-1"), ("bob", "key-2")])),
            (2, options(&[("alice", "key-3")])),
        ]);
        assert_eq!(
            distinct_identity_assignment(&[0, 1, 2], &identities, DEFAULT_ASSIGNMENT_BUDGET),
            Ok(false)
        );
    }

    #[test]
    fn empty_duplicate_and_shared_key_roles_are_not_independent() {
        let identities = BTreeMap::from([
            (0, options(&[("alice", "key-1")])),
            (1, options(&[("bob", "key-1")])),
        ]);
        for roles in [vec![], vec![0, 0], vec![0, 1]] {
            assert_eq!(
                distinct_identity_assignment(&roles, &identities, DEFAULT_ASSIGNMENT_BUDGET),
                Ok(false)
            );
        }
    }

    #[test]
    fn budget_exhaustion_is_not_acceptance() {
        let identities = BTreeMap::from([(0, options(&[("alice", "key-1")]))]);
        assert_eq!(
            distinct_identity_assignment(&[0], &identities, 0),
            Err(AssignmentBudgetExceeded)
        );
    }

    #[test]
    fn all_three_role_subsets_and_orders_match_cartesian_product_oracle() {
        // Independent oracle: Cartesian product, not another DFS implementation.
        let universe = [("a", "1"), ("a", "2"), ("b", "2"), ("c", "3")];
        let orders = [
            [0, 1, 2],
            [0, 2, 1],
            [1, 0, 2],
            [1, 2, 0],
            [2, 0, 1],
            [2, 1, 0],
        ];
        for a in 0_u8..16 {
            for b in 0_u8..16 {
                for c in 0_u8..16 {
                    let mut identities = BTreeMap::new();
                    for (role, mask) in [(0, a), (1, b), (2, c)] {
                        let selected: Vec<_> = universe
                            .iter()
                            .enumerate()
                            .filter(|(i, _)| mask & (1 << i) != 0)
                            .map(|(_, pair)| *pair)
                            .collect();
                        identities.insert(role, options(&selected));
                    }
                    let expected = identities[&0].iter().any(|x| {
                        identities[&1].iter().any(|y| {
                            identities[&2].iter().any(|z| {
                                x.0 != y.0
                                    && x.0 != z.0
                                    && y.0 != z.0
                                    && x.1 != y.1
                                    && x.1 != z.1
                                    && y.1 != z.1
                            })
                        })
                    });
                    for roles in orders {
                        assert_eq!(
                            distinct_identity_assignment(
                                &roles,
                                &identities,
                                DEFAULT_ASSIGNMENT_BUDGET
                            ),
                            Ok(expected),
                            "masks={a}/{b}/{c}, roles={roles:?}"
                        );
                    }
                }
            }
        }
    }
}
