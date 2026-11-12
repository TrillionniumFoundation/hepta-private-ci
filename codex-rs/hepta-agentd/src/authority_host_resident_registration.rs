//! Open-only original Root factory for the explicitly registered resident
//! purpose. Cold readback does not require A's old pidfd or writer lease.
//! The new purpose-specific grant and same Registry lease are still mandatory.

use std::io;
use std::path::Path;
use std::sync::Arc;

use super::HostAuthorityServiceConfig;
use super::OriginalHostIssuerCustodyV3;
use super::open_original_issuer_custody;
use super::read_root_json;
use crate::RootResidentLearningProfileV3;
use crate::RootResidentLearningReadbackAuthorizationV3;
use crate::RootResidentLearningRegistrationV3;

/// The caller provides a new explicit Root intent and already registered lease.
/// Existing/partial registration never initializes another operation namespace.
pub fn register_host_resident_learning_v3(
    config_file: &Path,
    profile: RootResidentLearningProfileV3,
) -> io::Result<RootResidentLearningRegistrationV3> {
    let config: HostAuthorityServiceConfig = read_root_json(config_file)?;
    let OriginalHostIssuerCustodyV3 {
        issuer,
        leases,
        root,
        ..
    } = open_original_issuer_custody(&config)?;
    RootResidentLearningRegistrationV3::register_original_root(
        root,
        issuer,
        Arc::new(leases),
        profile,
    )
}

/// A current independently supplied readback intent can observe the exact old
/// operation after A exits. This cannot create an owner or reinstall execution.
pub fn recover_host_resident_learning_v3(
    config_file: &Path,
    profile: RootResidentLearningProfileV3,
    authorization: RootResidentLearningReadbackAuthorizationV3,
) -> io::Result<RootResidentLearningRegistrationV3> {
    let config: HostAuthorityServiceConfig = read_root_json(config_file)?;
    let OriginalHostIssuerCustodyV3 {
        issuer,
        leases,
        root,
        ..
    } = open_original_issuer_custody(&config)?;
    RootResidentLearningRegistrationV3::recover_original_root(
        root,
        issuer,
        Arc::new(leases),
        profile,
        authorization,
    )
}
