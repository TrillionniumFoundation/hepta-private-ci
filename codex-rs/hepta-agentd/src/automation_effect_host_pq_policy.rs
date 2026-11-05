//! Exact immutable owner policy and bounded, explicitly authorized recovery.
use super::*;

impl HostV4 {
    /// The signed scope includes the complete immutable owner policy. The
    /// mutable head is authenticated separately by the original signed feed.
    pub(super) fn scope(&self) -> Result<Sha256Digest, AgentdError> {
        let a = &self.authority;
        let value = serde_json::json!({
            "schema":"hepta-agentd-effect-owner-policy-pq-v4",
            "authentication_profile":self.authentication_profile,
            "agent_id":self.agent_id,"spawn_generation":self.spawn_generation,
            "provider_scope":self.provider_scope,"destination_id":self.destination_id,
            "contract_id":self.contract_id,"contract_authority_epoch":self.contract_authority_epoch,
            "contract_root":self.contract_root,"provider":self.provider,
            "signer_id":a.signer_id,"issuer_keys":a.issuer_keys,
            "revocation_distributor_id":a.revocation_distributor_id,"revocation_keys":a.revocation_keys,
            "signed_revocations_file":a.signed_revocations_file,
            "clock":endpoint_policy(&a.external_clock),"frontier":endpoint_policy(&a.external_frontier),
            "recovery_provider_policies":self.recovery_provider_policies,
        });
        let mut bytes = b"hepta.agentd.effect-owner-policy.pq.v4\0".to_vec();
        bytes.extend(serde_json::to_vec(&value)?);
        Ok(Sha256Digest::for_bytes(&bytes))
    }

    pub(super) fn validate(&self, identity: &AgentdIdentity) -> Result<Sha256Digest, AgentdError> {
        if self.schema_version != 4
            || self.authentication_profile != FinalUseAuthenticationProfile::MlDsa65V2
            || self.agent_id != identity.agent_id.as_str()
            || self.spawn_generation != identity.spawn_generation
            || self.contract_authority_epoch != self.authority.head.authority_epoch
            || self.contract_authority_epoch == 0
        {
            return Err(invalid(
                "explicit current owner, generation and PQ epoch required",
            ));
        }
        for (label, value) in [
            ("provider_scope", &self.provider_scope),
            ("destination_id", &self.destination_id),
            ("signer_id", &self.authority.signer_id),
            ("contract_id", &self.contract_id),
        ] {
            validate_host_identifier(label, value)?;
        }
        if self.recovery_provider_policies.len() > 8 {
            return Err(invalid(
                "at most eight explicit recovery provider policies are allowed",
            ));
        }
        if !(1..=8).contains(&self.authority.issuer_keys.len())
            || !(1..=8).contains(&self.authority.revocation_keys.len())
        {
            return Err(invalid(
                "bounded explicit issuer and revocation key rings required",
            ));
        }
        let mut keys = BTreeSet::new();
        for key in std::iter::once(&self.contract_root)
            .chain(&self.authority.issuer_keys)
            .chain(&self.authority.revocation_keys)
        {
            validate_host_identifier("authority key_id", &key.key_id)?;
            if key.not_before_authority_epoch == 0
                || key.not_after_authority_epoch < key.not_before_authority_epoch
            {
                return Err(invalid("authority key epoch window is invalid"));
            }
            let verified =
                PqNativeVerifier::from_pinned_spki(&key.public_key_spki, key.public_key_id)
                    .map_err(invalid)?;
            if !keys.insert(verified.public_spki().to_vec()) {
                return Err(invalid(
                    "contract, grant, feed, clock and frontier require distinct keys",
                ));
            }
        }
        for endpoint in [
            &self.authority.external_clock,
            &self.authority.external_frontier,
        ] {
            let verified = PqNativeVerifier::from_pinned_spki(
                &endpoint.public_key_spki,
                endpoint.public_key_id,
            )
            .map_err(invalid)?;
            if !keys.insert(verified.public_spki().to_vec()) {
                return Err(invalid(
                    "contract, grant, feed, clock and frontier require distinct keys",
                ));
            }
        }
        let clock = &self.authority.external_clock.socket_path;
        let frontier = &self.authority.external_frontier.socket_path;
        if clock == frontier {
            return Err(invalid("clock and frontier services must be distinct"));
        }
        for path in [clock, frontier, &self.authority.signed_revocations_file] {
            if !path.is_absolute() || path.canonicalize()?.as_os_str() != path.as_os_str() {
                return Err(invalid(
                    "external trust paths must be absolute and canonical",
                ));
            }
            for owned in [
                &identity.fleet_root,
                &identity.home_root,
                &identity.run_root,
                &identity.workspace,
            ] {
                let owned = match owned.canonicalize() {
                    Ok(path) => path,
                    Err(error) if error.kind() == std::io::ErrorKind::NotFound => owned.clone(),
                    Err(error) => return Err(error.into()),
                };
                if path.starts_with(owned) {
                    return Err(invalid("trust must remain outside Agentd-owned roots"));
                }
            }
        }
        let scope = self.scope()?;
        if self.final_use_scope_sha256 != scope.as_str() {
            return Err(invalid(
                "FinalUse scope must bind the exact signed provider and authority policy",
            ));
        }
        Ok(scope)
    }
}

/// Only the current signed contract authorizes these exact historical bytes.
/// Old sockets/feeds are never opened and their references are never followed.
/// Recovery permits lookup only; dispatch continues to require the current scope.
pub(super) fn authenticate_recovery_policies(
    config: &HostV4,
) -> Result<Vec<Sha256Digest>, AgentdError> {
    let mut scopes = Vec::new();
    for reference in &config.recovery_provider_policies {
        if !reference.path.is_absolute() || reference.path.canonicalize()? != reference.path {
            return Err(invalid(
                "recovery policy path must be absolute and canonical",
            ));
        }
        let raw = read_protected_file(
            &reference.path,
            256 * 1024,
            "historical PQ effect provider policy",
        )?;
        if Sha256Digest::for_bytes(&raw) != reference.sha256 {
            return Err(invalid(
                "historical provider policy bytes differ from current signed reference",
            ));
        }
        let old: HostV4 = serde_json::from_slice(&raw)?;
        if old.schema_version != 4
            || old.authentication_profile != FinalUseAuthenticationProfile::MlDsa65V2
        {
            return Err(invalid(
                "historical policy requires the explicit PQ contract version",
            ));
        }
        let scope = old.scope()?;
        if old.final_use_scope_sha256 != scope.as_str() || scopes.contains(&scope) {
            return Err(invalid("historical policy scope is invalid or duplicated"));
        }
        let digest = match &old.provider {
            ProviderV4::Http {
                dispatch_url,
                lookup_url_template,
                headers,
                timeout_ms,
            } => {
                let mut values = HeaderMap::new();
                for (name, value) in headers {
                    values.append(
                        HeaderName::from_bytes(name.as_bytes()).map_err(invalid)?,
                        HeaderValue::from_str(value).map_err(invalid)?,
                    );
                }
                HttpProviderEffectConfig {
                    dispatch_url: dispatch_url.clone(),
                    lookup_url_template: lookup_url_template.clone(),
                    headers: values,
                    timeout: Duration::from_millis(*timeout_ms),
                    contract_id: old.contract_id.clone(),
                    attestation: None,
                }
                .contract_sha256()
                .map_err(invalid)?
            }
            ProviderV4::Pon { .. } => {
                let mut bytes = b"hepta.agentd.pon-provider-contract.pq.v3\0".to_vec();
                bytes.extend(serde_json::to_vec(&old.provider)?);
                Sha256Digest::for_bytes(&bytes)
            }
        };
        attestation(&old, &digest, &scope)?;
        if old.agent_id != config.agent_id
            || old.spawn_generation > config.spawn_generation
            || old.provider_scope != config.provider_scope
            || old.destination_id != config.destination_id
            || old.provider != config.provider
        {
            return Err(invalid(
                "historical policy must select this exact owner and provider target",
            ));
        }
        scopes.push(scope);
    }
    Ok(scopes)
}
