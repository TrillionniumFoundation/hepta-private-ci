//! Source-owned, multi-proposition evidence; no text-derived polarity.

use codex_hepta_types::Digest32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use std::collections::BTreeMap;
use std::collections::BTreeSet;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum OwnerPolarity {
    Affirmed,
    Denied,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct OwnerProposition {
    pub(crate) record_id: StableId,
    pub(crate) revision: Revision,
    pub(crate) subject: Digest32,
    pub(crate) predicate: Digest32,
    pub(crate) object: Digest32,
    pub(crate) scope: Digest32,
    pub(crate) valid_from: i64,
    pub(crate) valid_to: Option<i64>,
    pub(crate) polarity: OwnerPolarity,
    pub(crate) source_support: Digest32,
}

impl OwnerProposition {
    pub(crate) fn validate(&self) -> Result<(), &'static str> {
        if [
            self.subject,
            self.predicate,
            self.object,
            self.scope,
            self.source_support,
        ]
        .iter()
        .any(|digest| digest.is_zero())
        {
            return Err("proposition has an empty owner identity");
        }
        if self.valid_to.is_some_and(|end| end <= self.valid_from) {
            return Err("proposition has an empty or reversed applicability interval");
        }
        Ok(())
    }

    pub(crate) fn proposition_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.sqlite.owner-proposition.v1".to_vec();
        for digest in [self.subject, self.predicate, self.object, self.scope] {
            bytes.extend_from_slice(digest.as_array());
        }
        Digest32::of_bytes(&bytes)
    }

    pub(crate) fn evidence_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.sqlite.owner-proposition-evidence.v1".to_vec();
        bytes.extend_from_slice(self.proposition_digest().as_array());
        let id = self.record_id.as_str().as_bytes();
        bytes.extend_from_slice(&u64::try_from(id.len()).unwrap_or(u64::MAX).to_be_bytes());
        bytes.extend_from_slice(id);
        bytes.extend_from_slice(&self.revision.get().to_be_bytes());
        bytes.extend_from_slice(&self.valid_from.to_be_bytes());
        match self.valid_to {
            Some(end) => {
                bytes.push(1);
                bytes.extend_from_slice(&end.to_be_bytes());
            }
            None => bytes.push(0),
        }
        bytes.push(match self.polarity {
            OwnerPolarity::Affirmed => 1,
            OwnerPolarity::Denied => 2,
        });
        bytes.extend_from_slice(self.source_support.as_array());
        Digest32::of_bytes(&bytes)
    }
}

/// Evaluate exact admitted revisions at the declared query time. Intervals are
/// half-open eligibility conditions, not proposition identity. Overlapping
/// opposite assertions conflict; disjoint or out-of-scope assertions do not.
/// Legacy ConflictReported evidence never enters this explicit assertion set.
pub(crate) fn admitted_conflicts(
    claims: &[OwnerProposition],
    admitted: &BTreeSet<(StableId, Revision)>,
    now: i64,
) -> Result<BTreeSet<Digest32>, &'static str> {
    if claims.len() > 4096 {
        return Err("owner proposition observation exceeds 4096 claims");
    }
    let mut polarities = BTreeMap::<Digest32, u8>::new();
    let mut evidence = BTreeSet::new();
    for claim in claims {
        claim.validate()?;
        if !evidence.insert(claim.evidence_digest()) {
            return Err("duplicate owner proposition evidence");
        }
        if !admitted.contains(&(claim.record_id.clone(), claim.revision))
            || now < claim.valid_from
            || claim.valid_to.is_some_and(|end| now >= end)
        {
            continue;
        }
        let mask = match claim.polarity {
            OwnerPolarity::Affirmed => 1,
            OwnerPolarity::Denied => 2,
        };
        *polarities.entry(claim.proposition_digest()).or_default() |= mask;
    }
    Ok(polarities
        .into_iter()
        .filter_map(|(digest, mask)| (mask == 3).then_some(digest))
        .collect())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn claim(number: u8, polarity: OwnerPolarity) -> OwnerProposition {
        let digest = Digest32::of_bytes(b"fixture-proposition");
        OwnerProposition {
            record_id: StableId::new(format!("memory:{number}")).expect("id"),
            revision: Revision::new(1).expect("revision"),
            subject: digest,
            predicate: digest,
            object: digest,
            scope: digest,
            valid_from: 10,
            valid_to: Some(20),
            polarity,
            source_support: Digest32::of_bytes(&[number]),
        }
    }
    fn admitted(claims: &[OwnerProposition]) -> BTreeSet<(StableId, Revision)> {
        claims
            .iter()
            .map(|claim| (claim.record_id.clone(), claim.revision))
            .collect()
    }
    #[test]
    fn opposite_claims_conflict_only_inside_shared_interval() {
        let first = claim(1, OwnerPolarity::Affirmed);
        let mut second = claim(2, OwnerPolarity::Denied);
        second.valid_from = 15;
        second.valid_to = Some(25);
        let claims = vec![first, second];
        let legal = admitted(&claims);
        assert!(
            admitted_conflicts(&claims, &legal, 14)
                .expect("before")
                .is_empty()
        );
        assert_eq!(
            admitted_conflicts(&claims, &legal, 15)
                .expect("overlap")
                .len(),
            1
        );
        assert!(
            admitted_conflicts(&claims, &legal, 20)
                .expect("half-open")
                .is_empty()
        );
    }
    #[test]
    fn wrong_revision_and_below_floor_do_not_poison_admission() {
        let claims = vec![
            claim(1, OwnerPolarity::Affirmed),
            claim(2, OwnerPolarity::Denied),
        ];
        assert!(
            admitted_conflicts(&claims, &admitted(&claims[..1]), 15)
                .expect("legal")
                .is_empty()
        );
        let mut legal = admitted(&claims);
        legal.remove(&(claims[1].record_id.clone(), claims[1].revision));
        legal.insert((
            claims[1].record_id.clone(),
            Revision::new(2).expect("revision"),
        ));
        assert!(
            admitted_conflicts(&claims, &legal, 15)
                .expect("revision")
                .is_empty()
        );
    }
    #[test]
    fn scope_and_predicate_are_not_collapsed() {
        let mut claims = vec![
            claim(1, OwnerPolarity::Affirmed),
            claim(2, OwnerPolarity::Denied),
        ];
        claims[1].scope = Digest32::of_bytes(b"other-scope");
        assert!(
            admitted_conflicts(&claims, &admitted(&claims), 15)
                .expect("scope")
                .is_empty()
        );
        claims[1].scope = claims[0].scope;
        claims[1].predicate = Digest32::of_bytes(b"other-predicate");
        assert!(
            admitted_conflicts(&claims, &admitted(&claims), 15)
                .expect("predicate")
                .is_empty()
        );
    }
    #[test]
    fn malformed_and_duplicate_evidence_fail_before_filtering() {
        let mut malformed = claim(1, OwnerPolarity::Affirmed);
        malformed.valid_to = Some(10);
        assert!(admitted_conflicts(&[malformed], &BTreeSet::new(), 15).is_err());
        let first = claim(1, OwnerPolarity::Affirmed);
        assert!(admitted_conflicts(&[first.clone(), first], &BTreeSet::new(), 15).is_err());
    }
}
