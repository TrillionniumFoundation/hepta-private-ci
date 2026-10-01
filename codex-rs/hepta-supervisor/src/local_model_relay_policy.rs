//! Optional credential-owning route; neither its DTO nor its URL grants access.

use std::collections::BTreeSet;
use std::path::PathBuf;

use serde::Deserialize;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ModelRelayPolicy {
    pub socket: PathBuf,
    pub credential_profile_home: PathBuf,
    pub credential_uid: u32,
    pub credential_gid: u32,
    pub allowed_models: BTreeSet<String>,
    pub max_concurrent_calls: usize,
    pub ingress_timeout_ms: u64,
    pub credential_timeout_ms: u64,
    pub call_timeout_ms: u64,
}

#[cfg(all(test, feature = "local-model-relay"))]
mod tests {
    use super::*;

    fn configuration() -> serde_json::Value {
        serde_json::json!({
            "socket": "/run/hepta-private-ci-model/responses.sock",
            "credential_profile_home": "/home/operator/.codex",
            "credential_uid": 1000, "credential_gid": 1000,
            "allowed_models": ["gpt-5.6-sol"], "max_concurrent_calls": 1,
            "ingress_timeout_ms": 2000, "credential_timeout_ms": 10000,
            "call_timeout_ms": 120000
        })
    }

    #[test]
    fn workload_cannot_be_enrolled_as_its_credential_owner() {
        let policy: ModelRelayPolicy = serde_json::from_value(configuration()).unwrap();
        assert!(policy.validate(1000).is_err());
        assert!(policy.validate(991).is_ok());
        let mut value = configuration();
        value["credential_uid"] = 0.into();
        let policy: ModelRelayPolicy = serde_json::from_value(value).unwrap();
        assert!(policy.validate(991).is_err());
    }

    #[test]
    fn enrollment_rejects_unbounded_work_and_untrusted_route_fields() {
        for (field, invalid) in [
            ("socket", serde_json::json!("/run/../tmp/model.sock")),
            (
                "credential_profile_home",
                serde_json::json!("relative/profile"),
            ),
            ("max_concurrent_calls", serde_json::json!(9)),
            ("ingress_timeout_ms", serde_json::json!(0)),
            ("credential_timeout_ms", serde_json::json!(60001)),
            ("call_timeout_ms", serde_json::json!(600001)),
            ("allowed_models", serde_json::json!(["model\r\nheader"])),
        ] {
            let mut value = configuration();
            value[field] = invalid;
            let policy: ModelRelayPolicy = serde_json::from_value(value).unwrap();
            assert!(policy.validate(991).is_err(), "accepted {field}");
        }
        let mut value = configuration();
        value["upstream_url"] = serde_json::json!("https://untrusted.invalid");
        assert!(serde_json::from_value::<ModelRelayPolicy>(value).is_err());
    }
}

impl ModelRelayPolicy {
    pub(super) fn validate(&self, workload_uid: u32) -> anyhow::Result<()> {
        anyhow::ensure!(
            cfg!(feature = "local-model-relay"),
            "model relay requires the explicitly compiled local-model-relay feature"
        );
        for path in [&self.socket, &self.credential_profile_home] {
            anyhow::ensure!(
                path.is_absolute()
                    && !path
                        .components()
                        .any(|part| { matches!(part, std::path::Component::ParentDir) }),
                "model relay paths must be absolute and normalized"
            );
        }
        anyhow::ensure!(
            self.credential_uid != 0
                && self.credential_gid != 0
                && self.credential_uid != workload_uid,
            "model credentials and workloads require separate nonroot identities"
        );
        anyhow::ensure!(
            (1..=8).contains(&self.max_concurrent_calls)
                && (1..=30_000).contains(&self.ingress_timeout_ms)
                && (1..=60_000).contains(&self.credential_timeout_ms)
                && (1..=600_000).contains(&self.call_timeout_ms),
            "model relay concurrency or time bounds are invalid"
        );
        anyhow::ensure!(
            (1..=8).contains(&self.allowed_models.len())
                && self.allowed_models.iter().all(|model| {
                    !model.is_empty()
                        && model.len() <= 128
                        && model.bytes().all(|byte| {
                            byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'.' | b'_')
                        })
                }),
            "model relay model enrollment is invalid"
        );
        Ok(())
    }
}
