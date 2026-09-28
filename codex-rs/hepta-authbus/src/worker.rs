use std::future::Future;
use std::sync::Arc;
use std::time::Duration;

use tokio::sync::watch;
use tokio::time::MissedTickBehavior;

use crate::AuthBusAuthorityError;
use crate::AuthBusAuthorityHost;
use crate::AuthBusMaintenanceReport;
use crate::AuthBusSloPolicy;
use crate::TrustedTimeSample;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AuthBusAuthorityWorkerConfig {
    pub interval: Duration,
    pub batch_limit: u32,
    pub slo: AuthBusSloPolicy,
}

impl Default for AuthBusAuthorityWorkerConfig {
    fn default() -> Self {
        Self {
            interval: Duration::from_secs(30),
            batch_limit: 256,
            slo: AuthBusSloPolicy::PRODUCTION,
        }
    }
}

pub struct AuthBusAuthorityWorker {
    host: Arc<AuthBusAuthorityHost>,
    config: AuthBusAuthorityWorkerConfig,
}

impl AuthBusAuthorityWorker {
    pub fn new(
        host: Arc<AuthBusAuthorityHost>,
        config: AuthBusAuthorityWorkerConfig,
    ) -> Result<Self, AuthBusAuthorityError> {
        if config.interval < Duration::from_secs(1)
            || config.interval > Duration::from_secs(3_600)
            || config.batch_limit == 0
            || config.batch_limit > 1024
        {
            return Err(AuthBusAuthorityError::InvalidInput(
                "authority worker interval or batch is outside supported bounds",
            ));
        }
        config.slo.validate()?;
        Ok(Self { host, config })
    }

    pub async fn run_once(
        &self,
        time: TrustedTimeSample,
    ) -> Result<AuthBusMaintenanceReport, AuthBusAuthorityError> {
        self.host
            .maintenance_tick(time, self.config.batch_limit, self.config.slo)
            .await
    }

    /// Run periodic maintenance with shutdown observable during time acquisition
    /// AND database maintenance, not just while waiting for the next tick.
    /// Each awaited phase has an interval-sized deadline. Cancellation never
    /// acknowledges a maintenance result; begin_mutation reconciles any durable
    /// transition left by a cancelled database operation before further writes.
    ///
    /// The time callback must return a freshly verified sample. The synchronous
    /// observer must be nonblocking (for example, try_send to a supervised
    /// exporter). Failure is returned, never discarded. A blocking callback
    /// cannot be preempted by an async deadline and is not supported here.
    pub async fn run_until_shutdown<TimeFn, TimeFuture, ObserveFn>(
        &self,
        mut trusted_time: TimeFn,
        mut observe: ObserveFn,
        mut shutdown: watch::Receiver<bool>,
    ) -> Result<(), AuthBusAuthorityError>
    where
        TimeFn: FnMut() -> TimeFuture,
        TimeFuture: Future<Output = Result<TrustedTimeSample, AuthBusAuthorityError>>,
        ObserveFn: FnMut(&AuthBusMaintenanceReport) -> Result<(), AuthBusAuthorityError>,
    {
        let mut ticker = tokio::time::interval(self.config.interval);
        ticker.set_missed_tick_behavior(MissedTickBehavior::Skip);
        loop {
            // Keep ALL awaits inside the selected future. Awaiting them in the
            // ticker branch body would stop polling shutdown indefinitely.
            let iteration = async {
                ticker.tick().await;
                let time = tokio::time::timeout(self.config.interval, trusted_time())
                    .await
                    .map_err(|_| {
                        AuthBusAuthorityError::Storage("trusted-time provider deadline exceeded".into())
                    })??;
                tokio::time::timeout(self.config.interval, self.run_once(time))
                    .await
                    .map_err(|_| {
                        AuthBusAuthorityError::Storage("authority maintenance deadline exceeded".into())
                    })?
            };
            tokio::select! {
                biased;
                () = shutdown_requested(&mut shutdown) => return Ok(()),
                result = iteration => observe(&result?)?,
            }
        }
    }
}

async fn shutdown_requested(shutdown: &mut watch::Receiver<bool>) {
    loop {
        if *shutdown.borrow_and_update() || shutdown.changed().await.is_err() {
            return;
        }
    }
}

#[cfg(all(test, unix))]
mod tests {
    use std::os::unix::fs::PermissionsExt;

    use super::*;

    async fn fixture() -> (tempfile::TempDir, AuthBusAuthorityWorker) {
        let root = tempfile::tempdir().expect("private root");
        let database = root.path().join("database");
        let witness = root.path().join("witness");
        for path in [&database, &witness] {
            std::fs::create_dir(path).expect("private directory");
            std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700))
                .expect("private permissions");
        }
        let host = AuthBusAuthorityHost::bootstrap(
            &database.join("authority.sqlite"),
            witness.join("checkpoint.json"),
            "worker-test",
        )
        .await
        .expect("bootstrap");
        let worker = AuthBusAuthorityWorker::new(
            Arc::new(host),
            AuthBusAuthorityWorkerConfig {
                interval: Duration::from_secs(1),
                ..AuthBusAuthorityWorkerConfig::default()
            },
        )
        .expect("worker");
        (root, worker)
    }

    #[tokio::test]
    async fn shutdown_interrupts_a_stalled_trusted_time_provider() {
        let (_root, worker) = fixture().await;
        let (sender, receiver) = watch::channel(false);
        let task = tokio::spawn(async move {
            worker
                .run_until_shutdown(std::future::pending, |_| Ok(()), receiver)
                .await
        });
        tokio::time::sleep(Duration::from_millis(20)).await;
        sender.send(true).expect("request shutdown");
        tokio::time::timeout(Duration::from_millis(500), task)
            .await
            .expect("shutdown must not wait for provider")
            .expect("worker task")
            .expect("clean shutdown");
    }

    #[tokio::test]
    async fn dropped_supervisor_stops_a_stalled_provider() {
        let (_root, worker) = fixture().await;
        let (sender, receiver) = watch::channel(false);
        drop(sender);
        tokio::time::timeout(
            Duration::from_millis(500),
            worker.run_until_shutdown(std::future::pending, |_| Ok(()), receiver),
        )
        .await
        .expect("closed supervisor channel must stop worker")
        .expect("clean shutdown");
    }

    #[tokio::test]
    async fn provider_deadline_is_an_error_not_a_successful_tick() {
        let (_root, worker) = fixture().await;
        let (_sender, receiver) = watch::channel(false);
        let result = tokio::time::timeout(
            Duration::from_secs(3),
            worker.run_until_shutdown(std::future::pending, |_| panic!("no report exists"), receiver),
        )
        .await
        .expect("bounded provider deadline");
        assert!(matches!(result, Err(AuthBusAuthorityError::Storage(_))));
    }
}
