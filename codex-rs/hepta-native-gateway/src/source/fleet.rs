//! Authenticated HTTP projection of the existing read-only Fleet observer.

use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use anyhow::Context;
use anyhow::Result;
use codex_hepta_supervisor::MAX_SUPERVISORD_ROSTER;
use codex_hepta_supervisor::RobrixSupervisordMethod;
use codex_hepta_supervisor::RobrixSupervisordPayload;
use codex_hepta_supervisor::SupervisorObserverClient;
use codex_hepta_supervisor::SupervisordHealth;
use tokio::io::AsyncWriteExt;
use tokio::net::TcpStream;
use tokio::sync::Semaphore;

use crate::GatewayAuth;
use crate::RuntimeRepresentation;
use crate::native_mac;
use crate::response;
use crate::source_launch::ObserverOptions;

const MAX_BODY_BYTES: usize = 1024 * 1024 - 4096;

pub(crate) struct FleetSource {
    client: SupervisorObserverClient,
    serial: Semaphore,
    revision: AtomicU64,
    pub(super) controller: Option<crate::lifecycle_source::LifecycleSource>,
}

impl FleetSource {
    pub fn new(options: ObserverOptions) -> Result<Self> {
        Ok(Self {
            client: SupervisorObserverClient::new(options.socket, options.owner_uid)?,
            serial: Semaphore::new(/*permits*/ 1),
            revision: AtomicU64::new(/*v*/ 0),
            controller: None,
        })
    }

    async fn health(&self) -> Result<SupervisordHealth> {
        match self.client.query(RobrixSupervisordMethod::Health).await? {
            RobrixSupervisordPayload::Health(health) => Ok(health),
            _ => anyhow::bail!("Fleet health is unavailable"),
        }
    }

    async fn observe(&self) -> Result<Vec<u8>> {
        // Serialize observations so HTTP completion order cannot regress the
        // gateway's observation identity. This is not a Fleet mutation counter.
        let _permit = self
            .serial
            .acquire()
            .await
            .context("Fleet read admission closed")?;
        let before = self.health().await?;
        if before.registered_agents > MAX_SUPERVISORD_ROSTER {
            anyhow::bail!("Fleet exceeds the complete roster observation bound");
        }
        let agents = match self
            .client
            .query(RobrixSupervisordMethod::Roster {
                limit: MAX_SUPERVISORD_ROSTER,
            })
            .await?
        {
            RobrixSupervisordPayload::Roster { agents } => agents,
            _ => anyhow::bail!("Fleet roster is unavailable"),
        };
        let after = self.health().await?;
        if before.supervisor_epoch != after.supervisor_epoch
            || before.process_id != after.process_id
            || before.registered_agents != after.registered_agents
            || usize::from(after.registered_agents) != agents.len()
            || agents
                .iter()
                .any(|agent| agent.control_fence.supervisor_epoch != after.supervisor_epoch)
        {
            anyhow::bail!("Fleet owner or roster changed during observation; refresh required");
        }
        let next = self
            .revision
            .load(Ordering::Relaxed)
            .checked_add(/*rhs*/ 1)
            .context("Fleet observation revision exhausted")?;
        let body = serde_json::to_vec(&serde_json::json!({
            "schema": "hepta_fleet_observation_v1",
            "observation_revision": next,
            "health": after,
            "agents": agents,
        }))?;
        if body.len() > MAX_BODY_BYTES {
            anyhow::bail!("Fleet observation exceeds the native response bound");
        }
        self.revision.store(next, Ordering::Relaxed);
        Ok(body)
    }

    async fn route(&self, request: &[u8], auth: &GatewayAuth) -> Result<Vec<u8>> {
        let parsed = crate::lifecycle_http::parse(request)?;
        if parsed.method == "POST" {
            return match &self.controller {
                Some(controller) => controller.route(parsed, auth).await,
                None => Ok(crate::unauthorized_response()),
            };
        }
        let request = std::str::from_utf8(request).context("HTTP request is not UTF-8")?;
        // Fleet observations require request/response MACs. The legacy source
        // keeps its separate bearer compatibility route.
        let proof = match native_mac::authenticate(request, auth) {
            Ok(Some(proof)) => proof,
            Ok(None) | Err(_) => return Ok(crate::unauthorized_response()),
        };
        let target = request
            .lines()
            .next()
            .and_then(|line| line.split_ascii_whitespace().nth(1))
            .context("authenticated HTTP target is missing")?;
        let result = match Some(target) {
            Some("/healthz") => response(
                "200 OK",
                "application/json; charset=utf-8",
                &serde_json::to_vec(&serde_json::json!({
                    "product": "hepta", "status": "ok", "native_auth": "keyring_mac_v2",
                    "native_protocol_version": 2,
                    "lifecycle_control": self.controller.is_some(),
                    "native_incarnation": codex_hepta_contracts::native_gateway::native_gateway_incarnation_hex(&auth.server_incarnation),
                }))?,
            ),
            Some("/api/hepta/runtime")
                if crate::runtime_representation(request) == RuntimeRepresentation::Json =>
            {
                match self.observe().await {
                    Ok(body) => response("200 OK", "application/json; charset=utf-8", &body),
                    Err(error) => {
                        eprintln!("Fleet observation unavailable: {error:#}");
                        response(
                            "503 Service Unavailable",
                            "application/json; charset=utf-8",
                            br#"{"error":"Fleet observation unavailable; refresh required"}"#,
                        )
                    }
                }
            }
            Some("/api/hepta/runtime") => response(
                "406 Not Acceptable",
                "application/json; charset=utf-8",
                br#"{"error":"Fleet observations require JSON"}"#,
            ),
            _ => response(
                "404 Not Found",
                "application/json; charset=utf-8",
                br#"{"error":"not found"}"#,
            ),
        };
        native_mac::sign_response(result, &proof, auth)
    }

    pub async fn serve(&self, mut stream: TcpStream, auth: &GatewayAuth) -> Result<()> {
        let request = tokio::time::timeout(
            crate::REQUEST_TIMEOUT,
            crate::lifecycle_http::read(&mut stream),
        )
        .await
        .context("loopback request timed out")??;
        let response = tokio::time::timeout(crate::REQUEST_TIMEOUT, self.route(&request, auth))
            .await
            .context("Fleet observation timed out")??;
        tokio::time::timeout(crate::RESPONSE_TIMEOUT, stream.write_all(&response))
            .await
            .context("loopback response timed out")??;
        tokio::time::timeout(crate::RESPONSE_TIMEOUT, stream.shutdown())
            .await
            .context("loopback shutdown timed out")??;
        Ok(())
    }
}

#[cfg(test)]
#[path = "fleet_tests.rs"]
mod tests;
