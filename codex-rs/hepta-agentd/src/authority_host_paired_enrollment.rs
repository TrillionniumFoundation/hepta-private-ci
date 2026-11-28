//! Explicit Root intent for one original pre-enrollment; no data-use consent.

use super::*;
use crate::HostAuthorityPairedTrainingProfileV1;
use crate::authority_host_admin::deadline::require_before;
use crate::authority_host_config::HostAuthorityRegistration;
use crate::authority_host_config::HostAuthorityServiceConfig;
use crate::authority_host_config::read_root_json;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;

#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct RootPairedEnrollmentIntentV1 {
    schema_version: u32,
    operation: String,
    profile: HostAuthorityPairedTrainingProfileV1,
    enrollment_lifetime_ms: u64,
}

impl HostAuthorityService {
    pub(crate) fn register_original_paired_enrollment_intent(
        &self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        paired: &RegisteredPairedTrainingPlan,
        intent_file: &Path,
    ) -> io::Result<()> {
        // SAFETY: observe the original process credentials without changing them.
        if unsafe { libc::getuid() } != 0
            || unsafe { libc::geteuid() } != 0
            || !(1..=500).contains(&config.timeout_ms)
        {
            return Err(io::Error::other("original Root enrollment owner required"));
        }
        let end = Instant::now() + Duration::from_millis(config.timeout_ms);
        let intent: RootPairedEnrollmentIntentV1 = read_root_json(intent_file)?;
        if intent.schema_version != 1
            || intent.operation != "hepta.root.paired-enrollment.register.v1"
            || intent.enrollment_lifetime_ms == 0
            || intent.enrollment_lifetime_ms > config.lifetime_ms
        {
            return Err(io::Error::other("invalid explicit Root enrollment intent"));
        }
        let check = || {
            require_before(end)?;
            self.with_original_paired_profile(
                config,
                registration,
                owner,
                &intent.profile,
                |plan, proof| {
                    if plan != paired.plan || plan.enrollment_revision != 1 {
                        return Err(io::Error::other(
                            "enrollment differs from original fixed plan",
                        ));
                    }
                    Ok(proof)
                },
            )
        };
        let proof = check()?;
        require_before(end)?;
        let writer = self
            .writer
            .as_ref()
            .ok_or_else(|| io::Error::other("original writer missing"))?;
        let registry = self
            .root_registry
            .as_ref()
            .ok_or_else(|| io::Error::other("original registry missing"))?;
        // The read-only profile closure has returned and released its registry
        // dispatch lock. Never nest the new CAS inside that closure.
        self.issuer.register_original_paired_enrollment_once(
            &paired.plan,
            registry,
            &writer.registration,
            &writer.proof,
            intent.enrollment_lifetime_ms,
            end,
        )?;
        if check().map_err(|error| {
            io::Error::other(format!(
                "enrollment outcome uncertain after CAS; observe original registry: {error}"
            ))
        })? != proof
        {
            return Err(io::Error::other(
                "enrollment outcome uncertain: original proof changed",
            ));
        }
        require_before(end).map_err(|error| {
            io::Error::other(format!("enrollment outcome uncertain after CAS: {error}"))
        })
    }
}
