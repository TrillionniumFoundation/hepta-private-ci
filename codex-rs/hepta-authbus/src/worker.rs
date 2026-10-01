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

    /// Run the sole periodic maintenance loop. The time callback must return a
    /// freshly verified trusted-time sample. The observer must durably hand the
    /// report to the module metrics/alert exporter; observer failure stops the
    /// worker rather than silently dropping safety signals.
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
        if *shutdown.borrow() {
            return Ok(());
        }
        let mut ticker = tokio::time::interval(self.config.interval);
        ticker.set_missed_tick_behavior(MissedTickBehavior::Skip);
        loop {
            tokio::select! {
                _ = ticker.tick() => {
                    let report = self.run_once(trusted_time().await?).await?;
                    observe(&report)?;
                }
                changed = shutdown.changed() => {
                    if changed.is_err() || *shutdown.borrow_and_update() {
                        return Ok(());
                    }
                }
            }
        }
    }
}
