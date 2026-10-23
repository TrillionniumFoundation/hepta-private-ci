//! Bounded capability registry declarations, without sandbox qualification.

use anyhow::Result;
use anyhow::ensure;
use serde::Deserialize;
use serde::Serialize;
use std::collections::HashMap;

pub(crate) const REGISTRY_VERSION: u32 = 2;
pub(crate) const MAX_REGISTERED_ROOTS: usize = 256;
pub(crate) const MAX_PATH_BYTES: usize = 4096;
const MAX_SID_BYTES: usize = 184;

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct CapSids {
    pub(crate) version: u32,
    pub(crate) generation: String,
    pub workspace: String,
    pub readonly: String,
    #[serde(deserialize_with = "bounded_roots")]
    pub workspace_by_cwd: HashMap<String, String>,
    #[serde(deserialize_with = "bounded_roots")]
    pub writable_root_by_path: HashMap<String, String>,
}

pub(crate) fn sid_is_bounded(sid: &str) -> bool {
    let Some(rest) = sid.strip_prefix("S-1-") else {
        return false;
    };
    if sid.len() > MAX_SID_BYTES {
        return false;
    }
    let mut parts = rest.split('-');
    if !parts.next().is_some_and(|part| {
        part.parse::<u64>()
            .is_ok_and(|value| value <= 0xffff_ffff_ffff)
    }) {
        return false;
    }
    let mut count = 0;
    for part in parts {
        if part.parse::<u32>().is_err() {
            return false;
        }
        count += 1;
    }
    (1..=15).contains(&count)
}

fn bounded_roots<'de, D: serde::Deserializer<'de>>(
    deserializer: D,
) -> Result<HashMap<String, String>, D::Error> {
    struct Roots;
    impl<'de> serde::de::Visitor<'de> for Roots {
        type Value = HashMap<String, String>;
        fn expecting(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            formatter.write_str("bounded unique capability roots")
        }
        fn visit_map<A: serde::de::MapAccess<'de>>(
            self,
            mut map: A,
        ) -> Result<Self::Value, A::Error> {
            let mut roots = HashMap::new();
            while let Some((path, sid)) = map.next_entry::<String, String>()? {
                if roots.len() >= MAX_REGISTERED_ROOTS
                    || path.is_empty()
                    || path.len() > MAX_PATH_BYTES
                    || !sid_is_bounded(&sid)
                    || roots.insert(path, sid).is_some()
                {
                    return Err(serde::de::Error::custom(
                        "invalid, duplicate or excessive capability roots",
                    ));
                }
            }
            Ok(roots)
        }
    }
    deserializer.deserialize_map(Roots)
}

impl CapSids {
    pub(crate) fn validate(&self) -> Result<()> {
        ensure!(
            self.version == REGISTRY_VERSION,
            "unsupported capability registry version"
        );
        ensure!(
            self.generation.len() == 32 && self.generation.bytes().all(|b| b.is_ascii_hexdigit()),
            "invalid capability registry generation"
        );
        ensure!(
            self.workspace_by_cwd
                .len()
                .saturating_add(self.writable_root_by_path.len())
                <= MAX_REGISTERED_ROOTS,
            "capability registry capacity exceeded"
        );
        ensure!(
            sid_is_bounded(&self.workspace)
                && sid_is_bounded(&self.readonly)
                && self.workspace != self.readonly,
            "invalid capability registry identities"
        );
        let mut sids =
            std::collections::HashSet::from([self.workspace.as_str(), self.readonly.as_str()]);
        for (path, sid) in self
            .workspace_by_cwd
            .iter()
            .chain(&self.writable_root_by_path)
        {
            ensure!(
                !path.is_empty() && path.len() <= MAX_PATH_BYTES,
                "capability root path exceeds bound"
            );
            ensure!(
                sid_is_bounded(sid) && sids.insert(sid),
                "invalid or reused capability identity"
            );
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "capability_registry_tests.rs"]
mod tests;
