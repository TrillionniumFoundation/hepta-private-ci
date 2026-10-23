//! Bounded filesystem role declarations; deserialization grants no authority.
use crate::capability_registry::CapSids;
use crate::capability_registry::MAX_PATH_BYTES;
use crate::capability_registry::sid_is_bounded;
use anyhow::Result;
use anyhow::ensure;
use serde::Deserialize;
use serde::Serialize;

const PLAN_VERSION: u32 = 1;
const MAX_ACTIVE_ROOTS: usize = 64;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct RootCapability {
    pub(crate) path: String,
    pub(crate) sid: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
enum DesktopRole {
    NotPrepared,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
enum ChildObjectRole {
    PreserveBaseRequired,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct NetworkRouteCapability {
    sid: String,
}

/// Filesystem identity role; network/desktop/child-object roles stay separate.
#[derive(Clone, Copy)]
pub enum FilesystemCapabilityRole {
    Read,
    Write,
}

/// A bounded, versioned declaration passed to setup and runner.
///
/// Validation binds identities to the current registry; it does not produce an
/// opaque prepared-ACL or sandbox-qualified value.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct FilesystemCapabilityPlan {
    version: u32,
    registry_generation: String,
    cwd: String,
    #[serde(deserialize_with = "bounded_active_roots")]
    read: Vec<RootCapability>,
    #[serde(deserialize_with = "bounded_active_roots")]
    write: Vec<RootCapability>,
    desktop: DesktopRole,
    child_objects: ChildObjectRole,
    network_route: Option<NetworkRouteCapability>,
}

fn bounded_active_roots<'de, D: serde::Deserializer<'de>>(
    deserializer: D,
) -> Result<Vec<RootCapability>, D::Error> {
    struct Roots;
    impl<'de> serde::de::Visitor<'de> for Roots {
        type Value = Vec<RootCapability>;
        fn expecting(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            formatter.write_str("at most 64 bounded filesystem roots")
        }
        fn visit_seq<A: serde::de::SeqAccess<'de>>(
            self,
            mut sequence: A,
        ) -> Result<Self::Value, A::Error> {
            let mut roots = Vec::new();
            while let Some(root) = sequence.next_element::<RootCapability>()? {
                if roots.len() >= MAX_ACTIVE_ROOTS
                    || root.path.is_empty()
                    || root.path.len() > MAX_PATH_BYTES
                    || !sid_is_bounded(&root.sid)
                {
                    return Err(serde::de::Error::custom(
                        "invalid or excessive active filesystem roots",
                    ));
                }
                roots.push(root);
            }
            Ok(roots)
        }
    }
    deserializer.deserialize_seq(Roots)
}

impl FilesystemCapabilityPlan {
    pub(crate) fn declare(
        caps: &CapSids,
        cwd: String,
        read: Vec<String>,
        write: Vec<String>,
    ) -> Result<Self> {
        let plan = Self {
            version: PLAN_VERSION,
            registry_generation: caps.generation.clone(),
            cwd: cwd.clone(),
            read: read
                .into_iter()
                .map(|path| RootCapability {
                    path,
                    sid: caps.readonly.clone(),
                })
                .collect(),
            write: write
                .into_iter()
                .map(|path| {
                    let sid = if path == cwd {
                        caps.workspace_by_cwd.get(&path)
                    } else {
                        caps.writable_root_by_path.get(&path)
                    };
                    Ok(RootCapability {
                        path,
                        sid: sid.cloned().ok_or_else(|| {
                            anyhow::anyhow!("write root has no registered capability")
                        })?,
                    })
                })
                .collect::<Result<_>>()?,
            desktop: DesktopRole::NotPrepared,
            child_objects: ChildObjectRole::PreserveBaseRequired,
            network_route: None,
        };
        plan.validate_registry(caps)?;
        Ok(plan)
    }

    /// Adds a separate network-route declaration, never a filesystem identity.
    pub fn with_network_route(mut self, sid: Option<String>) -> Result<Self> {
        ensure!(
            sid.as_deref().is_none_or(sid_is_bounded),
            "invalid network-route SID declaration"
        );
        self.network_route = sid.map(|sid| NetworkRouteCapability { sid });
        Ok(self)
    }

    pub(crate) fn validate_registry(&self, caps: &CapSids) -> Result<()> {
        caps.validate()?;
        ensure!(
            self.version == PLAN_VERSION && self.registry_generation == caps.generation,
            "stale filesystem capability plan"
        );
        ensure!(
            !self.cwd.is_empty() && self.cwd.len() <= MAX_PATH_BYTES,
            "invalid plan cwd"
        );
        ensure!(
            self.read.len() <= MAX_ACTIVE_ROOTS && self.write.len() <= MAX_ACTIVE_ROOTS,
            "active filesystem root capacity exceeded"
        );
        for roots in [&self.read, &self.write] {
            let mut paths = std::collections::HashSet::new();
            for root in roots {
                ensure!(
                    !root.path.is_empty()
                        && root.path.len() <= MAX_PATH_BYTES
                        && paths.insert(&root.path),
                    "invalid or duplicated plan root"
                );
            }
        }
        ensure!(
            self.read.iter().all(|root| root.sid == caps.readonly),
            "read capability role mismatch"
        );
        for root in &self.write {
            let expected = if root.path == self.cwd {
                caps.workspace_by_cwd.get(&root.path)
            } else {
                caps.writable_root_by_path.get(&root.path)
            };
            ensure!(
                expected == Some(&root.sid),
                "write capability role mismatch"
            );
        }
        if let Some(route) = &self.network_route {
            ensure!(
                sid_is_bounded(&route.sid)
                    && route.sid != caps.readonly
                    && route.sid != caps.workspace
                    && !caps
                        .workspace_by_cwd
                        .values()
                        .chain(caps.writable_root_by_path.values())
                        .any(|sid| sid == &route.sid),
                "network-route identity overlaps filesystem role"
            );
        }
        Ok(())
    }

    pub(crate) fn same_filesystem_declaration(&self, other: &Self) -> bool {
        self.version == other.version
            && self.registry_generation == other.registry_generation
            && self.cwd == other.cwd
            && self.read == other.read
            && self.write == other.write
            && self.desktop == other.desktop
            && self.child_objects == other.child_objects
    }

    pub(crate) fn matches_roots(&self, cwd: &str, read: &[String], write: &[String]) -> bool {
        self.cwd == cwd
            && self.read.iter().map(|root| &root.path).eq(read)
            && self.write.iter().map(|root| &root.path).eq(write)
    }

    /// Checks the old transport mirror without interpreting it as authority.
    pub fn validate_transport_mirror(
        &self,
        role: FilesystemCapabilityRole,
        identities: &[String],
        network: Option<&str>,
    ) -> Result<()> {
        let expected = self.capability_sids(role);
        let observed: std::collections::BTreeSet<_> =
            identities.iter().map(String::as_str).collect();
        ensure!(
            expected
                .iter()
                .copied()
                .collect::<std::collections::BTreeSet<_>>()
                == observed
                && observed.len() == identities.len(),
            "untyped transport mirror differs from role plan"
        );
        ensure!(
            self.network_route_sid() == network,
            "network-route transport role mismatch"
        );
        Ok(())
    }

    /// Returns only declared identities for the specified filesystem role.
    pub fn capability_sids(&self, role: FilesystemCapabilityRole) -> Vec<&str> {
        match role {
            FilesystemCapabilityRole::Read => self
                .read_sids()
                .collect::<std::collections::BTreeSet<_>>()
                .into_iter()
                .collect(),
            FilesystemCapabilityRole::Write => self.write_sids().collect(),
        }
    }

    /// Returns the declared capability identities; this cannot authorize a token.
    pub fn read_sids(&self) -> impl Iterator<Item = &str> {
        self.read.iter().map(|root| root.sid.as_str())
    }

    /// Returns the declared write identities; prepared ACLs remain separate.
    pub fn write_sids(&self) -> impl Iterator<Item = &str> {
        self.write.iter().map(|root| root.sid.as_str())
    }

    /// Returns only the separately declared network-route identity.
    pub fn network_route_sid(&self) -> Option<&str> {
        self.network_route.as_ref().map(|role| role.sid.as_str())
    }
}

#[cfg(test)]
#[path = "capability_plan_tests.rs"]
mod tests;
