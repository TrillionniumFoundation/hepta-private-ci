//! Runtime-consumed projection of the canonical Hepta module registry.
//!
//! The catalog validates the reviewed static module graph once for a host. It
//! grants no runtime, writer, selection, promotion, merge, or release authority.
//! Lifecycle and candidate promotion remain owned by the runtime control plane.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use serde::Deserialize;
use serde::Serialize;
use sha2::Digest as _;
use sha2::Sha256;

const CANONICAL_MODULES_JSON: &str = include_str!("../../../docs/modules/MODULES.json");
const MAX_MODULES: usize = 128;
const MAX_DEPENDENCIES: usize = 64;
const MAX_DOMAINS: usize = 64;
const MAX_ID_BYTES: usize = 128;
const MAX_CATALOG_BYTES: usize = 4 * 1024 * 1024;

#[derive(Clone, Debug, Deserialize)]
struct SourceCatalogV1 {
    modules: Vec<SourceModuleV1>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
struct SourceModuleV1 {
    id: String,
    owner: String,
    state: String,
    #[serde(default)]
    uses: Vec<String>,
    #[serde(default)]
    writes: Vec<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeModuleDefinitionV1 {
    pub id: String,
    pub owner: String,
    pub state: String,
    pub dependencies: Vec<String>,
    pub authoritative_domains: Vec<String>,
    /// Digest of the canonical registry row. This is a manifest identity, not
    /// executable build provenance and must never be presented as such.
    pub manifest_digest: String,
}

#[derive(Clone, Debug)]
pub struct RuntimeModuleCatalogV1 {
    digest: String,
    modules: BTreeMap<String, RuntimeModuleDefinitionV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RuntimeModuleCatalogErrorV1 {
    Decode,
    Bounds,
    InvalidId,
    DuplicateModule(String),
    DuplicateDependency(String),
    DuplicateDomain(String),
    UnknownDependency { module: String, dependency: String },
    DependencyCycle,
}

impl std::fmt::Display for RuntimeModuleCatalogErrorV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for RuntimeModuleCatalogErrorV1 {}

impl RuntimeModuleCatalogV1 {
    pub fn canonical() -> Result<Self, RuntimeModuleCatalogErrorV1> {
        Self::from_reviewed_json(CANONICAL_MODULES_JSON)
    }

    /// Validate a host-supplied reviewed manifest using the canonical parser.
    /// A successfully decoded catalog is data, not approval to load code or
    /// activate its modules. Selection and writer handoff remain separate.
    pub fn from_reviewed_json(json: &str) -> Result<Self, RuntimeModuleCatalogErrorV1> {
        if json.len() > MAX_CATALOG_BYTES {
            return Err(RuntimeModuleCatalogErrorV1::Bounds);
        }
        let source: SourceCatalogV1 =
            serde_json::from_str(json).map_err(|_| RuntimeModuleCatalogErrorV1::Decode)?;
        if source.modules.is_empty() || source.modules.len() > MAX_MODULES {
            return Err(RuntimeModuleCatalogErrorV1::Bounds);
        }

        let mut modules = BTreeMap::new();
        for row in source.modules {
            validate_id(&row.id)?;
            validate_id(&row.owner)?;
            if row.uses.len() > MAX_DEPENDENCIES || row.writes.len() > MAX_DOMAINS {
                return Err(RuntimeModuleCatalogErrorV1::Bounds);
            }
            let encoded =
                serde_json::to_vec(&row).map_err(|_| RuntimeModuleCatalogErrorV1::Decode)?;
            let dependencies = canonical_ids(&row.id, row.uses, true)?;
            let authoritative_domains = canonical_ids(&row.id, row.writes, false)?;
            let definition = RuntimeModuleDefinitionV1 {
                id: row.id.clone(),
                owner: row.owner,
                state: row.state,
                dependencies,
                authoritative_domains,
                manifest_digest: sha256_hex(&encoded),
            };
            if modules.insert(row.id.clone(), definition).is_some() {
                return Err(RuntimeModuleCatalogErrorV1::DuplicateModule(row.id));
            }
        }

        for module in modules.values() {
            for dependency in &module.dependencies {
                if !modules.contains_key(dependency) {
                    return Err(RuntimeModuleCatalogErrorV1::UnknownDependency {
                        module: module.id.clone(),
                        dependency: dependency.clone(),
                    });
                }
            }
        }
        validate_dag(&modules)?;

        Ok(Self {
            digest: sha256_hex(json.as_bytes()),
            modules,
        })
    }

    pub fn digest(&self) -> &str {
        &self.digest
    }

    pub fn len(&self) -> usize {
        self.modules.len()
    }

    pub fn is_empty(&self) -> bool {
        self.modules.is_empty()
    }

    pub fn module(&self, id: &str) -> Option<&RuntimeModuleDefinitionV1> {
        self.modules.get(id)
    }

    pub fn module_ids(&self) -> impl Iterator<Item = &str> {
        self.modules.keys().map(String::as_str)
    }
}

fn canonical_ids(
    module: &str,
    values: Vec<String>,
    dependencies: bool,
) -> Result<Vec<String>, RuntimeModuleCatalogErrorV1> {
    let mut seen = BTreeSet::new();
    let mut result = Vec::with_capacity(values.len());
    for value in values {
        validate_id(&value)?;
        if dependencies && value == module {
            return Err(RuntimeModuleCatalogErrorV1::DependencyCycle);
        }
        if !seen.insert(value.clone()) {
            return Err(if dependencies {
                RuntimeModuleCatalogErrorV1::DuplicateDependency(module.to_string())
            } else {
                RuntimeModuleCatalogErrorV1::DuplicateDomain(module.to_string())
            });
        }
        result.push(value);
    }
    Ok(result)
}

fn validate_id(value: &str) -> Result<(), RuntimeModuleCatalogErrorV1> {
    if value.is_empty()
        || value.len() > MAX_ID_BYTES
        || value
            .bytes()
            .any(|byte| byte == 0 || byte.is_ascii_whitespace())
    {
        return Err(RuntimeModuleCatalogErrorV1::InvalidId);
    }
    Ok(())
}

fn validate_dag(
    modules: &BTreeMap<String, RuntimeModuleDefinitionV1>,
) -> Result<(), RuntimeModuleCatalogErrorV1> {
    fn visit(
        id: &str,
        modules: &BTreeMap<String, RuntimeModuleDefinitionV1>,
        visiting: &mut BTreeSet<String>,
        complete: &mut BTreeSet<String>,
    ) -> Result<(), RuntimeModuleCatalogErrorV1> {
        if complete.contains(id) {
            return Ok(());
        }
        if !visiting.insert(id.to_string()) {
            return Err(RuntimeModuleCatalogErrorV1::DependencyCycle);
        }
        let module = modules.get(id).ok_or(RuntimeModuleCatalogErrorV1::Decode)?;
        for dependency in &module.dependencies {
            visit(dependency, modules, visiting, complete)?;
        }
        visiting.remove(id);
        complete.insert(id.to_string());
        Ok(())
    }

    let mut complete = BTreeSet::new();
    for id in modules.keys() {
        visit(id, modules, &mut BTreeSet::new(), &mut complete)?;
    }
    Ok(())
}

fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    let mut output = String::with_capacity(64);
    for byte in digest {
        use std::fmt::Write as _;
        let _ = write!(&mut output, "{byte:02x}");
    }
    output
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn canonical_catalog_is_bounded_and_acyclic() {
        let catalog = RuntimeModuleCatalogV1::canonical().expect("canonical module catalog");
        let source: SourceCatalogV1 =
            serde_json::from_str(CANONICAL_MODULES_JSON).expect("canonical source");
        assert_eq!(catalog.len(), source.modules.len());
        assert_eq!(
            catalog.module_ids().collect::<BTreeSet<_>>(),
            source.modules.iter().map(|row| row.id.as_str()).collect::<BTreeSet<_>>()
        );
        assert!(!catalog.digest().is_empty());
        assert!(catalog.module("runtime.agentd").is_some());
        assert!(catalog.module("kernel.authority").is_some());
    }

    fn fixture(count: usize) -> serde_json::Value {
        let modules = (0..count)
            .map(|index| {
                serde_json::json!({
                    "id": format!("module-{index}"),
                    "owner": "owner",
                    "state": "stateless",
                    "uses": [],
                    "writes": []
                })
            })
            .collect::<Vec<_>>();
        serde_json::json!({"modules": modules})
    }

    #[test]
    fn forty_first_optional_module_can_be_added_and_removed() {
        let mut value = fixture(41);
        let added = RuntimeModuleCatalogV1::from_reviewed_json(&value.to_string())
            .expect("extension inside the resource bound");
        assert_eq!(added.len(), 41);
        assert!(added.module("module-40").is_some());
        value["modules"].as_array_mut().expect("modules").pop();
        let removed = RuntimeModuleCatalogV1::from_reviewed_json(&value.to_string())
            .expect("removal of an unreferenced optional module");
        assert_eq!(removed.len(), 40);
        assert!(removed.module("module-40").is_none());
        assert_ne!(added.digest(), removed.digest());
    }

    #[test]
    fn removing_a_dependency_is_not_mistaken_for_safe_optional_removal() {
        let mut value = fixture(2);
        value["modules"][0]["uses"] = serde_json::json!(["module-1"]);
        RuntimeModuleCatalogV1::from_reviewed_json(&value.to_string()).expect("valid dependency");
        value["modules"].as_array_mut().expect("modules").pop();
        assert!(matches!(
            RuntimeModuleCatalogV1::from_reviewed_json(&value.to_string()),
            Err(RuntimeModuleCatalogErrorV1::UnknownDependency { .. })
        ));
    }

    #[test]
    fn dynamic_manifests_keep_cycle_duplicate_and_resource_checks() {
        let mut cycle = fixture(2);
        cycle["modules"][0]["uses"] = serde_json::json!(["module-1"]);
        cycle["modules"][1]["uses"] = serde_json::json!(["module-0"]);
        assert!(matches!(
            RuntimeModuleCatalogV1::from_reviewed_json(&cycle.to_string()),
            Err(RuntimeModuleCatalogErrorV1::DependencyCycle)
        ));
        let mut duplicate = fixture(2);
        duplicate["modules"][1]["id"] = serde_json::json!("module-0");
        assert!(matches!(
            RuntimeModuleCatalogV1::from_reviewed_json(&duplicate.to_string()),
            Err(RuntimeModuleCatalogErrorV1::DuplicateModule(_))
        ));
        for count in [0, MAX_MODULES + 1] {
            assert!(matches!(
                RuntimeModuleCatalogV1::from_reviewed_json(&fixture(count).to_string()),
                Err(RuntimeModuleCatalogErrorV1::Bounds)
            ));
        }
        assert!(matches!(
            RuntimeModuleCatalogV1::from_reviewed_json(&" ".repeat(MAX_CATALOG_BYTES + 1)),
            Err(RuntimeModuleCatalogErrorV1::Bounds)
        ));
    }
}
