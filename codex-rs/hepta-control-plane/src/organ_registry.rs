//! Bounded registry of reviewed, compiled-in read-only organ capabilities.
//!
//! A registry may contain more drivers than a graph selects. Construction
//! validates the complete graph and binding set before invoking any factory,
//! then creates exactly one handler for each graph organ. In-process factories
//! are trusted product code: this registry does not load code, sandbox callbacks,
//! start handlers, or grant authority.
//!
//! Driver identity names an implementation, while organ identity names one
//! concrete graph instance. A single reviewed stateless implementation may be
//! bound to multiple organ instances in the same graph; each factory call still
//! receives and must return the exact organ instance identity.
//!
//! The capability descriptor is also the single execution-class source. An
//! isolated-process capability is catalogued without fabricating an in-process
//! factory; callers route that descriptor to the supervisor-owned killable
//! execution boundary instead of teaching the synchronous host another branch.

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
pub const ORGAN_DRIVER_ABI_V1: u16 = 1;

/// Execution boundary declared once by the reviewed capability descriptor.
///
/// Only `TrustedShortReadOnly` is admissible to the synchronous in-process
/// `OrganHostV1`. Anything that may block, hang, invoke external code, or be
/// generated at runtime must use the supervisor-owned killable process path.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OrganExecutionClassV1 {
    TrustedShortReadOnly,
    IsolatedProcessReadOnly,
}

/// Authority class declared once alongside the implementation identity.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OrganAuthorityClassV1 {
    ReadOnlyNoEffects,
}

/// Canonical reviewed capability metadata for one driver implementation.
///
/// Registration, digest admission, execution-boundary selection, ABI version,
/// and authority posture all derive from this value instead of parallel string
/// tables or scheduler branches.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OrganCapabilityDescriptorV1 {
    pub driver: StableId,
    pub driver_version: u32,
    pub abi_version: u16,
    pub implementation_digest: Digest32,
    pub execution_class: OrganExecutionClassV1,
    pub authority: OrganAuthorityClassV1,
}

impl OrganCapabilityDescriptorV1 {
    pub fn trusted_short_read_only(
        driver: StableId,
        driver_version: u32,
        implementation_digest: Digest32,
    ) -> Self {
        Self {
            driver,
            driver_version,
            abi_version: ORGAN_DRIVER_ABI_V1,
            implementation_digest,
            execution_class: OrganExecutionClassV1::TrustedShortReadOnly,
            authority: OrganAuthorityClassV1::ReadOnlyNoEffects,
        }
    }

    pub fn isolated_process_read_only(
        driver: StableId,
        driver_version: u32,
        implementation_digest: Digest32,
    ) -> Self {
        Self {
            driver,
            driver_version,
            abi_version: ORGAN_DRIVER_ABI_V1,
            implementation_digest,
            execution_class: OrganExecutionClassV1::IsolatedProcessReadOnly,
            authority: OrganAuthorityClassV1::ReadOnlyNoEffects,
        }
    }

    fn validate(&self) -> Result<(), OrganHandlerRegistryError> {
        if self.driver_version == 0 {
            return Err(OrganHandlerRegistryError::ZeroDriverVersion(
                self.driver.clone(),
            ));
        }
        if self.abi_version != ORGAN_DRIVER_ABI_V1 {
            return Err(OrganHandlerRegistryError::UnsupportedAbiVersion {
                driver: self.driver.clone(),
                abi_version: self.abi_version,
            });
        }
        if self.implementation_digest.is_zero() {
            return Err(OrganHandlerRegistryError::EmptyImplementationDigest(
                self.driver.clone(),
            ));
        }
        Ok(())
    }
}

/// A reviewed, compiled-in constructor for one organ driver implementation.
///
/// The host passes the selected organ identity so one factory can construct
/// multiple stateless instances. Implementations must remain trusted,
/// read-only handlers and must not perform I/O, spawn work, invoke a model or
/// cross an effect boundary.
pub type OrganHandlerFactoryV1 =
    fn(&StableId) -> Result<Box<dyn TrustedReadOnlyOrganV1>, OrganHandlerFaultV1>;

#[derive(Clone, Debug)]
struct RegisteredCapabilityV1 {
    descriptor: OrganCapabilityDescriptorV1,
    in_process_factory: Option<OrganHandlerFactoryV1>,
}

/// A bounded host-owned catalog of reviewed organ capabilities.
#[derive(Debug, Default)]
pub struct OrganHandlerRegistryV1 {
    capabilities: BTreeMap<StableId, RegisteredCapabilityV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum OrganHandlerRegistryError {
    Capacity,
    DuplicateDriver(StableId),
    EmptyImplementationDigest(StableId),
    ZeroDriverVersion(StableId),
    UnsupportedAbiVersion {
        driver: StableId,
        abi_version: u16,
    },
    InProcessExecutionClassRequired(StableId),
    IsolatedExecutionClassRequired(StableId),
    InProcessFactoryMissing(StableId),
    Runtime(OrganRuntimeError),
    BindingCount {
        expected: usize,
        actual: usize,
    },
    DuplicateOrgan(StableId),
    UnknownOrgan(StableId),
    MissingBinding(StableId),
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
        self.capabilities.len()
    }

    pub fn is_empty(&self) -> bool {
        self.capabilities.is_empty()
    }

    /// Backward-compatible registration for a V1 trusted short read-only driver.
    /// New code should prefer `register_descriptor` so metadata has one owner.
    pub fn register(
        &mut self,
        driver: StableId,
        implementation_digest: Digest32,
        factory: OrganHandlerFactoryV1,
    ) -> Result<(), OrganHandlerRegistryError> {
        self.register_descriptor(
            OrganCapabilityDescriptorV1::trusted_short_read_only(driver, 1, implementation_digest),
            factory,
        )
    }

    /// Registers one reviewed in-process implementation from its canonical descriptor.
    pub fn register_descriptor(
        &mut self,
        descriptor: OrganCapabilityDescriptorV1,
        factory: OrganHandlerFactoryV1,
    ) -> Result<(), OrganHandlerRegistryError> {
        descriptor.validate()?;
        if descriptor.execution_class != OrganExecutionClassV1::TrustedShortReadOnly {
            return Err(OrganHandlerRegistryError::InProcessExecutionClassRequired(
                descriptor.driver.clone(),
            ));
        }
        self.insert_capability(descriptor, Some(factory))
    }

    /// Catalogs an isolated implementation without inventing an in-process handler.
    ///
    /// The descriptor remains available to composition/routing code, but
    /// `create_host` will fail closed if a caller attempts to place it on the
    /// synchronous in-process path.
    pub fn register_isolated_descriptor(
        &mut self,
        descriptor: OrganCapabilityDescriptorV1,
    ) -> Result<(), OrganHandlerRegistryError> {
        descriptor.validate()?;
        if descriptor.execution_class != OrganExecutionClassV1::IsolatedProcessReadOnly {
            return Err(OrganHandlerRegistryError::IsolatedExecutionClassRequired(
                descriptor.driver.clone(),
            ));
        }
        self.insert_capability(descriptor, None)
    }

    fn insert_capability(
        &mut self,
        descriptor: OrganCapabilityDescriptorV1,
        in_process_factory: Option<OrganHandlerFactoryV1>,
    ) -> Result<(), OrganHandlerRegistryError> {
        if self.capabilities.len() >= MAX_REGISTERED_FACTORIES {
            return Err(OrganHandlerRegistryError::Capacity);
        }
        if self.capabilities.contains_key(&descriptor.driver) {
            return Err(OrganHandlerRegistryError::DuplicateDriver(
                descriptor.driver.clone(),
            ));
        }
        self.capabilities.insert(
            descriptor.driver.clone(),
            RegisteredCapabilityV1 {
                descriptor,
                in_process_factory,
            },
        );
        Ok(())
    }

    #[must_use]
    pub fn descriptor(&self, driver: &StableId) -> Option<&OrganCapabilityDescriptorV1> {
        self.capabilities.get(driver).map(|entry| &entry.descriptor)
    }

    /// Builds a read-only host for exactly the organ instances in `graph`.
    ///
    /// Every graph organ must have one binding, while unselected registered
    /// drivers are ignored and their factories are never called. Multiple organ
    /// instances may bind the same driver implementation. All graph, binding,
    /// driver and digest checks complete before the first factory is invoked.
    /// The returned host is registered but not started.
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
            let Some(registered) = self.capabilities.get(&binding.driver) else {
                return Err(OrganHandlerRegistryError::UnknownDriver(
                    binding.driver.clone(),
                ));
            };
            if registered.descriptor.implementation_digest != binding.implementation_digest {
                return Err(OrganHandlerRegistryError::DriverDigestMismatch {
                    driver: binding.driver.clone(),
                });
            }
            if registered.descriptor.execution_class != OrganExecutionClassV1::TrustedShortReadOnly
            {
                return Err(OrganHandlerRegistryError::InProcessExecutionClassRequired(
                    binding.driver.clone(),
                ));
            }
            if registered.in_process_factory.is_none() {
                return Err(OrganHandlerRegistryError::InProcessFactoryMissing(
                    binding.driver.clone(),
                ));
            }
        }

        let mut handlers = Vec::with_capacity(graph.organs.len());
        for organ in &graph.organs {
            let binding = by_organ
                .remove(&organ.id)
                .ok_or_else(|| OrganHandlerRegistryError::MissingBinding(organ.id.clone()))?;
            let registered = self
                .capabilities
                .get(&binding.driver)
                .ok_or_else(|| OrganHandlerRegistryError::UnknownDriver(binding.driver.clone()))?;
            let factory = registered.in_process_factory.ok_or_else(|| {
                OrganHandlerRegistryError::InProcessFactoryMissing(binding.driver.clone())
            })?;
            let handler = factory(&organ.id).map_err(|fault| OrganHandlerRegistryError::Factory {
                driver: binding.driver.clone(),
                fault,
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
