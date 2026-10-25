//! Bounded kernel readback policy; a value here is not a launch credential.
use anyhow::Result;

#[derive(Debug, PartialEq, Eq)]
pub(crate) struct ManagedTokenSnapshot {
    pub(crate) version: [u32; 6], // TokenId, AuthenticationId, ModifiedId (low, high).
    pub(crate) user: Vec<u8>,
    pub(crate) groups: Vec<(Vec<u8>, u32)>,
    pub(crate) privileges: Vec<(String, u32)>,
    pub(crate) default_dacl: Option<Vec<u8>>,
    pub(crate) primary: u32,
    pub(crate) filtered: u8,
    pub(crate) app_container: u32,
    pub(crate) elevated: u32,
    pub(crate) elevation_type: u32,
    pub(crate) restricting_count: usize,
}

impl ManagedTokenSnapshot {
    pub(crate) fn validate_continuity(
        &self,
        original: &Self,
        user: &[u8],
        managed_group: &[u8],
    ) -> Result<()> {
        self.validate(user, managed_group)?;
        anyhow::ensure!(
            self == original,
            "managed token instance or security state changed"
        );
        Ok(())
    }

    pub(crate) fn validate(&self, user: &[u8], managed_group: &[u8]) -> Result<()> {
        anyhow::ensure!(
            self.user == user && user != managed_group,
            "managed TokenUser differs"
        );
        anyhow::ensure!(
            self.primary == 1
                && self.filtered == 0
                && self.app_container == 0
                && self.elevated == 0
                && self.elevation_type == 1
                && self.restricting_count == 0,
            "managed base is not an ordinary unfiltered primary token"
        );
        anyhow::ensure!(
            self.default_dacl
                .as_ref()
                .is_some_and(|acl| (8..=65_536).contains(&acl.len())),
            "managed base lacks a bounded original default DACL"
        );
        anyhow::ensure!(!self.groups.is_empty() && self.groups.len() <= 128);
        let logon = sid(/*authority*/ 5, &[5, self.version[3], self.version[2]]);
        let users = sid(/*authority*/ 5, &[32, 545]);
        let ordinary = [
            sid(/*authority*/ 1, &[0]),
            sid(/*authority*/ 2, &[0]),
            sid(/*authority*/ 2, &[1]),
            sid(/*authority*/ 5, &[4]),
            sid(/*authority*/ 5, &[11]),
            sid(/*authority*/ 5, &[15]),
            sid(/*authority*/ 5, &[113]),
            sid(/*authority*/ 5, &[64, 10]),
            sid(/*authority*/ 16, &[8192]),
            sid(/*authority*/ 18, &[1]),
            users.clone(),
            logon.clone(),
        ];
        let mut seen = Vec::new();
        for (group, attributes) in &self.groups {
            anyhow::ensure!(
                !seen.contains(&group) && attributes & !0xC000_0067 == 0,
                "duplicate or nonordinary group attributes"
            );
            anyhow::ensure!(
                group == managed_group || ordinary.contains(group),
                "managed base contains a foreign or privileged group"
            );
            let logon_attributes = attributes & 0xC000_0000;
            anyhow::ensure!(
                if *group == logon {
                    logon_attributes == 0xC000_0000
                } else {
                    logon_attributes == 0
                },
                "wrong logon group"
            );
            seen.push(group);
        }
        anyhow::ensure!(
            [managed_group, users.as_slice(), logon.as_slice()]
                .iter()
                .all(|required| self
                    .groups
                    .iter()
                    .any(|(group, attributes)| group == required && attributes & 4 != 0)),
            "managed base lacks its enabled original account cohorts"
        );
        anyhow::ensure!(self.privileges.len() <= 5);
        let mut seen_privileges = Vec::new();
        for (name, attributes) in &self.privileges {
            anyhow::ensure!(!seen_privileges.contains(&name) && attributes & !0x8000_0003 == 0);
            anyhow::ensure!(
                matches!(
                    name.as_str(),
                    "SeChangeNotifyPrivilege"
                        | "SeShutdownPrivilege"
                        | "SeUndockPrivilege"
                        | "SeIncreaseWorkingSetPrivilege"
                        | "SeTimeZonePrivilege"
                ),
                "managed base contains a privileged user right"
            );
            anyhow::ensure!(
                attributes & 2 == 0 || name == "SeChangeNotifyPrivilege",
                "managed base has a nonordinary enabled privilege"
            );
            seen_privileges.push(name);
        }
        Ok(())
    }
}

fn sid(authority: u8, subauthorities: &[u32]) -> Vec<u8> {
    let mut bytes = vec![1, subauthorities.len() as u8, 0, 0, 0, 0, 0, authority];
    for value in subauthorities {
        bytes.extend(value.to_le_bytes());
    }
    bytes
}

#[cfg(test)]
#[path = "managed_token_policy_tests.rs"]
mod tests;
