//! Actual dedicated issuer, protected time and external frontier RPC service.

use std::future::Future;
use std::sync::Arc;

use crate::ConsumerPortError;
use crate::authority_role_config::SecretsAuthorityServiceConfig;
use crate::authority_role_owner::AuthorityRoleOwner;
use crate::local_endpoint::BoundSocket;
use crate::local_service::LocalServiceOwner;
use crate::role_storage::unavailable;
use crate::role_wire::AuthorityRequest;
use crate::role_wire::AuthorityResponse;
use crate::role_wire::TimeAttestation;

pub async fn serve_secrets_authority(
    config: SecretsAuthorityServiceConfig,
    shutdown: impl Future<Output = ()>,
) -> Result<(), ConsumerPortError> {
    let endpoint = BoundSocket::bind(&config.service.socket_path, config.service.ipc_group_gid)?;
    let service = config.service.clone();
    let owner = Arc::new(AuthorityRoleOwner::open(config).await?);
    crate::local_service::serve(service, owner, endpoint, shutdown).await
}

impl LocalServiceOwner for AuthorityRoleOwner {
    async fn handle(&self, peer_uid: u32, request: &[u8]) -> Result<Vec<u8>, ConsumerPortError> {
        let request: AuthorityRequest = serde_json::from_slice(request).map_err(unavailable)?;
        if peer_uid != self.config.runtime_uid
            && !matches!(
                request,
                AuthorityRequest::Time | AuthorityRequest::Frontier { .. }
            )
        {
            return Err(ConsumerPortError::Rejected);
        }
        let result = async {
            match request {
                AuthorityRequest::Time => Ok(AuthorityResponse::Time {
                    attestation: TimeAttestation::from_signed(self.time().await?),
                }),
                AuthorityRequest::Frontier { owner_id } => {
                    if owner_id != self.config.issuer_id {
                        return Err(ConsumerPortError::Rejected);
                    }
                    let (frontier, revocations) = self.frontier().await?;
                    Ok(AuthorityResponse::Frontier {
                        frontier,
                        revocations,
                    })
                }
                AuthorityRequest::CompareAndSet {
                    owner_id,
                    expected,
                    next,
                } => {
                    if owner_id != self.config.issuer_id {
                        return Err(ConsumerPortError::Rejected);
                    }
                    self.compare_and_set(expected, next).await?;
                    let (frontier, revocations) = self.frontier().await?;
                    if frontier != next {
                        return Err(ConsumerPortError::Conflict);
                    }
                    Ok(AuthorityResponse::Frontier {
                        frontier,
                        revocations,
                    })
                }
                AuthorityRequest::ApplyRevocations { update } => {
                    self.apply_revocations(&update).await?;
                    let (frontier, revocations) = self.frontier().await?;
                    Ok(AuthorityResponse::Frontier {
                        frontier,
                        revocations,
                    })
                }
                AuthorityRequest::Issue {
                    original_operation_id,
                } => Ok(AuthorityResponse::Grant {
                    grant: self.issue(&original_operation_id).await?,
                }),
                AuthorityRequest::BeginOriginal {
                    original_operation_id,
                    approval,
                } => {
                    let (grant_sha256, approval_sha256) = self
                        .begin_original(&original_operation_id, &approval)
                        .await?;
                    Ok(AuthorityResponse::OriginalAdmitted {
                        grant_sha256,
                        approval_sha256,
                    })
                }
                AuthorityRequest::OriginalStatus {
                    original_operation_id,
                } => match self.original_status(&original_operation_id).await? {
                    Some((grant_sha256, approval_sha256)) => {
                        Ok(AuthorityResponse::OriginalStarted {
                            grant_sha256,
                            approval_sha256,
                        })
                    }
                    None => Ok(AuthorityResponse::Unknown),
                },
            }
        }
        .await;
        let response = match result {
            Ok(response) => response,
            Err(ConsumerPortError::Conflict) => AuthorityResponse::Conflict,
            Err(ConsumerPortError::Rejected | ConsumerPortError::Invalid) => {
                AuthorityResponse::Rejected
            }
            Err(ConsumerPortError::Unavailable | ConsumerPortError::Capacity) => {
                AuthorityResponse::Unknown
            }
        };
        serde_json::to_vec(&response).map_err(unavailable)
    }
    fn fence_unknown(&self) {
        self.fence();
    }
    async fn close(&self) {
        AuthorityRoleOwner::close(self).await;
    }
}
