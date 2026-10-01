//! One read source per gateway; Fleet mode never opens a legacy database.

use std::sync::Arc;

use anyhow::Result;
use codex_hepta_paths::HeptaStateRoot;
use codex_hepta_runtime::HeptaRuntime;
use tokio::net::TcpStream;

use crate::GatewayAuth;
use crate::source_launch::ControllerOptions;
use crate::source_launch::ObserverOptions;

#[cfg(unix)]
mod fleet;

pub(super) enum RuntimeSource {
    Legacy(Arc<HeptaRuntime>),
    #[cfg(unix)]
    Fleet(fleet::FleetSource),
}

impl RuntimeSource {
    pub async fn open(root: HeptaStateRoot, observer: Option<ObserverOptions>) -> Result<Self> {
        match observer {
            #[cfg(unix)]
            Some(observer) => Ok(Self::Fleet(fleet::FleetSource::new(observer)?)),
            #[cfg(not(unix))]
            Some(_) => anyhow::bail!("Fleet observation requires Unix peer credentials"),
            None => Ok(Self::Legacy(Arc::new(
                HeptaRuntime::open_existing(root).await?,
            ))),
        }
    }

    pub async fn serve(&self, stream: TcpStream, auth: Arc<GatewayAuth>) -> Result<()> {
        match self {
            Self::Legacy(runtime) => {
                crate::serve_connection(stream, Arc::clone(runtime), auth).await
            }
            #[cfg(unix)]
            Self::Fleet(source) => source.serve(stream, &auth).await,
        }
    }

    pub(super) fn with_controller(
        self,
        options: Option<ControllerOptions>,
        auth: &GatewayAuth,
    ) -> Result<Self> {
        match options {
            None => Ok(self),
            #[cfg(unix)]
            Some(options) => match self {
                Self::Fleet(mut source) => {
                    source.controller = Some(crate::lifecycle_source::LifecycleSource::new(
                        options, auth,
                    )?);
                    Ok(Self::Fleet(source))
                }
                Self::Legacy(_) => {
                    anyhow::bail!("lifecycle control requires the actual Fleet source")
                }
            },
            #[cfg(not(unix))]
            Some(_) => {
                let _ = auth;
                anyhow::bail!("lifecycle control requires Unix peer credentials");
            }
        }
    }
}
