//! Bounded startup reconciliation without random-prefix cache eviction.

use std::collections::BTreeMap;

use super::RetirementStore;
use super::index_prefix;
use super::load_bucket_from_manifest;
use crate::error::ShellError;
use crate::journal::OperationRecord;

const MAX_MEMBERSHIP_QUERIES: usize = 4096;

#[derive(Debug, PartialEq, Eq)]
pub(crate) enum RetirementMembership {
    Absent,
    Legacy,
    Archived(Box<OperationRecord>),
}

impl RetirementStore {
    /// Resolve one bounded active journal against the published index. Each
    /// queried bucket is read and fully validated once, then released. Returned
    /// archives have also passed their content hash, identity and phase checks;
    /// neither the ordinary lookup cache nor an uncommitted segment is authority.
    pub(crate) fn memberships(
        &self,
        identities: &[String],
    ) -> Result<Vec<RetirementMembership>, ShellError> {
        self.root.verify()?;
        if identities.len() > MAX_MEMBERSHIP_QUERIES {
            return Err(ShellError::State(format!(
                "retirement membership batch exceeds {MAX_MEMBERSHIP_QUERIES} identities"
            )));
        }
        let mut groups: BTreeMap<String, Vec<(usize, &str)>> = BTreeMap::new();
        for (position, identity) in identities.iter().enumerate() {
            groups
                .entry(index_prefix(identity)?)
                .or_default()
                .push((position, identity));
        }
        let mut results: Vec<_> = identities
            .iter()
            .map(|_| RetirementMembership::Absent)
            .collect();
        for (prefix, queries) in groups {
            let bucket = load_bucket_from_manifest(&self.root, &self.buckets, &prefix)?;
            for (position, identity) in queries {
                results[position] = match bucket.entries.get(identity) {
                    None => RetirementMembership::Absent,
                    Some(None) => RetirementMembership::Legacy,
                    Some(Some(digest)) => RetirementMembership::Archived(Box::new(
                        self.read_archived_record(identity, digest)?,
                    )),
                };
            }
        }
        self.root.verify()?;
        Ok(results)
    }
}

#[cfg(test)]
#[path = "retirement_membership_tests.rs"]
mod tests;
