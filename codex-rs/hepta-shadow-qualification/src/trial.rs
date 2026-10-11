use std::path::Path;
use std::time::Duration;

use crate::ChildOutcome;
use crate::CompletedPreSend;
use crate::FrozenProductBinary;
use crate::HttpAuditRecord;
use crate::QualificationDriverRun;
use crate::QualificationError;
use crate::QualificationRuntimeLayout;
use crate::durable::verify_private_tree;
use crate::session::run_app_server;
use crate::session::run_mcp;

const MAX_TRIAL_TIMEOUT: Duration = Duration::from_secs(300);

pub struct QualificationTrial;

impl QualificationTrial {
    pub async fn run(
        product_path: impl AsRef<Path>,
        runtime_root: impl AsRef<Path>,
        timeout: Duration,
    ) -> Result<QualificationTrialOutcome, QualificationError> {
        if timeout.is_zero() || timeout > MAX_TRIAL_TIMEOUT {
            return Err(invalid(
                "trial timeout must be within one nanosecond and 300 seconds",
            ));
        }
        let product = FrozenProductBinary::verify(product_path)?;
        let layout = QualificationRuntimeLayout::create(runtime_root)?;
        let mut driver = QualificationDriverRun::create(layout.observer_root(), layout.work())?;
        let app_server =
            run_app_server(&product, layout.app_server(), &mut driver, timeout).await?;
        let mcp = run_mcp(&product, layout.mcp(), &mut driver, timeout).await?;
        layout.harden_known_product_permissions()?;
        verify_private_tree(layout.root())?;
        let completed = driver.finish()?;
        Ok(QualificationTrialOutcome {
            app_server_child: app_server.child,
            app_server_http: app_server.http,
            app_server_thread_id: app_server.thread_id,
            app_server_turn_ids: app_server.turn_ids,
            completed,
            layout,
            mcp_child: mcp.child,
            mcp_http: mcp.http,
            mcp_thread_id: mcp.thread_id,
        })
    }
}

pub struct QualificationTrialOutcome {
    app_server_child: ChildOutcome,
    app_server_http: Vec<HttpAuditRecord>,
    app_server_thread_id: String,
    app_server_turn_ids: Vec<String>,
    completed: CompletedPreSend,
    layout: QualificationRuntimeLayout,
    mcp_child: ChildOutcome,
    mcp_http: Vec<HttpAuditRecord>,
    mcp_thread_id: String,
}

impl QualificationTrialOutcome {
    pub fn app_server_child(&self) -> &ChildOutcome {
        &self.app_server_child
    }

    pub fn app_server_http(&self) -> &[HttpAuditRecord] {
        &self.app_server_http
    }

    pub fn app_server_thread_id(&self) -> &str {
        &self.app_server_thread_id
    }

    pub fn app_server_turn_ids(&self) -> &[String] {
        &self.app_server_turn_ids
    }

    pub fn completed(&self) -> &CompletedPreSend {
        &self.completed
    }

    pub fn layout(&self) -> &QualificationRuntimeLayout {
        &self.layout
    }

    pub fn mcp_child(&self) -> &ChildOutcome {
        &self.mcp_child
    }

    pub fn mcp_http(&self) -> &[HttpAuditRecord] {
        &self.mcp_http
    }

    pub fn mcp_thread_id(&self) -> &str {
        &self.mcp_thread_id
    }
}

fn invalid(message: impl Into<String>) -> QualificationError {
    QualificationError::Invalid(message.into())
}
