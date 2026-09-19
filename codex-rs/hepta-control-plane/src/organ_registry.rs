//! Bounded registry of reviewed, compiled-in read-only organ factories.
//!
//! A registry may contain more drivers than a graph selects.  Construction
//! validates the complete graph and binding set before invoking any factory,
//! then creates exactly one handler for each graph organ.  Factories are
//! trusted product code: this registry does not load code, sandbox callbacks,
//! start handlers, or grant authority.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::OrganDriverBindingV1;
use crate::OrganGraphsV1;
use crate::OrganHandlerFaultV1;
use crate::OrganHostV1;
use crate::OrganRuntimeError;
use crate::TrustedReadOnlyOrganV1;

const MAX_REGISTERED_FACTORIES: usize = 256;

/// A reviewed, compiled-in constructor for one organ driver implementation.
///
/// The host passes the selected organ identity so one factory can construct
/// multiple stateless instances. Implementations must remain trusted,
/// read-only handlers and must not perform I/O, spawn work, invoke a model or
/// cross an effect boundary.
pub type OrganHandlerFactoryV1 =
    fn(&StableId) -> Result<Box<dyn TrustedReadOnlyOrganV1>, OrganHandlerFaultV1>;

#[derive(Clone, Copy, Debug)]
struct RegisteredFactoryV1 {
    implementation_digest: Digest32,
    factory: OrganHandlerFactoryV1,
}

/// A bounded host-owned catalog of reviewed compiled-in organ factories.
#[derive(Debug, Default)]
pub struct OrganHandlerRegistryV1 {
    factories: BTreeMap<StableId, RegisteredFactoryV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum OrganHandlerRegistryError {
    Capacity,
    DuplicateDriver(StableId),
    EmptyImplementationDigest(StableId),
    Runtime(OrganRuntimeError),
    BindingCount {
        expected: usize,
        actual: usize,
    },
    DuplicateOrgan(StableId),
    UnknownOrgan(StableId),
    MissingBinding(StableId),
    DuplicateDriverBinding(StableId),
    UnknownDriver(StableId),
    DriverDigestMismatch {
        driver: StableId,
    },
    Factory {
        driver: StableId,
        fault: OrganHandlerFaultV1,
    },
    HandlerIdentityMismatch {
        expected: StableId,
        actual: StableId,
    },
}

impl std::fmt::Display for OrganHandlerRegistryError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for OrganHandlerRegistryError {}

impl From<OrganRuntimeError> for OrganHandlerRegistryError {
    fn from(error: OrganRuntimeError) -> Self {
        Self::Runtime(error)
    }
}

impl OrganHandlerRegistryV1 {
    /// Creates an empty registry. Registration does not instantiate a handler.
    pub fn new() -> Self {
        Self::default()
    }

    pub fn len(&self) -> usize {
        self.factories.len()
    }

    pub fn is_empty(&self) -> bool {
        self.factories.is_empty()
    }

    /// Registers one reviewed factory under an immutable driver identity.
    pub fn register(
        &mut self,
        driver: StableId,
        implementation_digest: Digest32,
        factory: OrganHandlerFactoryV1,
    ) -> Result<(), OrganHandlerRegistryError> {
        if implementation_digest.is_zero() {
            return Err(OrganHandlerRegistryError::EmptyImplementationDigest(driver));
        }
        if self.factories.len() >= MAX_REGISTERED_FACTORIES {
            return Err(OrganHandlerRegistryError::Capacity);
        }
        if self.factories.contains_key(&driver) {
            return Err(OrganHandlerRegistryError::DuplicateDriver(driver));
        }
        self.factories.insert(
            driver,
            RegisteredFactoryV1 {
                implementation_digest,
                factory,
            },
        );
        Ok(())
    }

    /// Builds a read-only host for exactly the organs in `graph`.
    ///
    /// Every graph organ must have one binding, while unselected registered
    /// drivers are ignored and their factories are never called. All graph,
    /// binding, driver and digest checks complete before the first factory is
    /// invoked. The returned host is registered but not started.
    pub fn create_host(
        &self,
        graph: OrganGraphsV1,
        bindings: &[OrganDriverBindingV1],
    ) -> Result<OrganHostV1, OrganHandlerRegistryError> {
        graph.validate().map_err(OrganRuntimeError::Graph)?;
        if let Some(organ) = graph
            .organs
            .iter()
            .find(|organ| !organ.effect_scope.is_empty())
        {
            return Err(OrganRuntimeError::ReadOnlyEffectScope {
                organ: organ.id.clone(),
            }
            .into());
        }
        if bindings.len() != graph.organs.len() {
            return Err(OrganHandlerRegistryError::BindingCount {
                expected: graph.organs.len(),
                actual: bindings.len(),
            });
        }

        let organ_ids = graph
            .organs
            .iter()
            .map(|organ| organ.id.clone())
            .collect::<BTreeSet<_>>();
        let mut by_organ = BTreeMap::new();
        let mut drivers = BTreeSet::new();
        for binding in bindings {
            if !organ_ids.contains(&binding.organ) {
                return Err(OrganHandlerRegistryError::UnknownOrgan(
                    binding.organ.clone(),
                ));
            }
            if by_organ
                .insert(binding.organ.clone(), binding.clone())
                .is_some()
            {
                return Err(OrganHandlerRegistryError::DuplicateOrgan(
                    binding.organ.clone(),
                ));
            }
            if !drivers.insert(binding.driver.clone()) {
                return Err(OrganHandlerRegistryError::DuplicateDriverBinding(
                    binding.driver.clone(),
                ));
            }
            let Some(registered) = self.factories.get(&binding.driver) else {
                return Err(OrganHandlerRegistryError::UnknownDriver(
                    binding.driver.clone(),
                ));
            };
            if registered.implementation_digest != binding.implementation_digest {
                return Err(OrganHandlerRegistryError::DriverDigestMismatch {
                    driver: binding.driver.clone(),
                });
            }
        }

        let mut handlers = Vec::with_capacity(graph.organs.len());
        for organ in &graph.organs {
            let binding = by_organ
                .remove(&organ.id)
                .ok_or_else(|| OrganHandlerRegistryError::MissingBinding(organ.id.clone()))?;
            let Some(registered) = self.factories.get(&binding.driver) else {
                return Err(OrganHandlerRegistryError::UnknownDriver(
                    binding.driver.clone(),
                ));
            };
            let handler = (registered.factory)(&organ.id).map_err(|fault| {
                OrganHandlerRegistryError::Factory {
                    driver: binding.driver.clone(),
                    fault,
                }
            })?;
            let actual = handler.id().clone();
            if actual != organ.id {
                return Err(OrganHandlerRegistryError::HandlerIdentityMismatch {
                    expected: organ.id.clone(),
                    actual,
                });
            }
            handlers.push(handler);
        }
        OrganHostV1::new(graph, handlers).map_err(Into::into)
    }
}

#[cfg(test)]
#[path = "organ_registry_tests.rs"]
mod tests;
