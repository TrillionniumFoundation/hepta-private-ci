//! Retain the actual old pidfds while waiting for their original lease expiry.
//! Persisted phase descriptions are audit data, never reconstructed exit proof.

use std::path::PathBuf;
use std::time::Duration;
use std::time::Instant;

use serde_json::json;

use super::cold_administration::OriginalColdRetirement;
use super::cold_deployment::OriginalColdPlan;
use super::post_a_retained::RetainedOrdinaryQ24Fixture;
use crate::ordinary_q24_cold_snapshot_tests::OriginalBusinessSnapshot;
use crate::ordinary_q24_process_child_tests::ExitedOriginalProcess;

pub(super) struct OriginalColdPhase<'a> {
    original: &'a RetainedOrdinaryQ24Fixture,
    retirement: OriginalColdRetirement,
    evidence: OriginalColdEvidence,
    end: Instant,
}

pub(super) struct OriginalColdEvidence {
    pub(super) directory: PathBuf,
    files: Vec<PathBuf>,
    business: OriginalBusinessSnapshot,
}

impl<'a> OriginalColdPhase<'a> {
    pub(super) fn observe_original_completion(
        original: &'a RetainedOrdinaryQ24Fixture,
        end: Instant,
    ) -> anyhow::Result<Self> {
        anyhow::ensure!(Instant::now() < end, "whole cold parent deadline");
        let retirement = OriginalColdRetirement::observe(original)?;
        let directory = original
            .plan
            .resources
            .original
            .plan
            .protected
            .path()
            .join("ordinary-cold-phase");
        std::fs::create_dir(&directory)?;
        super::super::owned_mode(&directory, 0, 0, 0o700)?;
        let first = &original.plan.resources.original;
        for (name, process) in [
            ("a-daemon", &first.daemon),
            ("a-root", &first.root),
            ("a-observer", &first.observer),
            ("post-a-daemon", &original.daemon),
            ("post-a-root", &original.root),
            ("independent-source", &original.source),
        ] {
            process.require_dead()?;
            let destination = directory.join(name);
            std::fs::create_dir(&destination)?;
            super::super::owned_mode(&destination, 0, 0, 0o700)?;
            process.archive_original_logs(&destination)?;
            super::root::write_json(
                &destination.join("actual-exited-process-data.json"),
                &process_data(process),
            )?;
        }
        let files = original.business_files();
        let business = OriginalBusinessSnapshot::capture(&files)?;
        super::root::write_bytes(
            &directory.join("before-cold-business-images.txt"),
            format!("{business:#?}\n").as_bytes(),
        )?;
        let terminal = original
            .terminal
            .snapshot
            .as_ref()
            .ok_or_else(|| anyhow::anyhow!("actual original terminal absent"))?;
        super::root::write_json(
            &directory.join("original-completed-phase.json"),
            &json!({
                "schema":1,
                "source_commit":std::env::var("HEPTA_ORDINARY_SOURCE_COMMIT")?,
                "source_tree":std::env::var("HEPTA_ORDINARY_SOURCE_TREE")?,
                "observed_unix_ms":crate::authbus_ingress::now_ms()?,
                "not_before_unix_ms":retirement.not_before_unix_ms(),
                "terminal_head":terminal.head_digest.to_string(),
                "c_publication":original.completed.source.publication_digest().to_string(),
                "c_checkpoint":original.completed.source.checkpoint_digest().to_string(),
                "c_cell_revision":original.completed.cell.snapshot.revision,
                "business_files":files,
                "cold_recovery_completed":false
            }),
        )?;
        business.require_unchanged(&files)?;
        anyhow::ensure!(Instant::now() < end, "whole cold observation deadline");
        eprintln!("ORDINARY_Q24_COLD_PHASE_EVIDENCE={}", directory.display());
        Ok(Self {
            original,
            retirement,
            evidence: OriginalColdEvidence {
                directory,
                files,
                business,
            },
            end,
        })
    }

    pub(super) fn wait_for_actual_expiry(
        self,
    ) -> anyhow::Result<(OriginalColdPlan<'a>, OriginalColdEvidence)> {
        let started = crate::authbus_ingress::now_ms()?;
        let not_before = self.retirement.not_before_unix_ms();
        let mut previous = started;
        loop {
            anyhow::ensure!(Instant::now() < self.end, "whole cold wait deadline");
            self.original.daemon.require_dead()?;
            self.original.root.require_dead()?;
            self.original.source.require_dead()?;
            let now = crate::authbus_ingress::now_ms()?;
            anyhow::ensure!(now >= previous, "actual retirement clock regressed");
            previous = now;
            if now >= not_before {
                break;
            }
            let remaining = self.end.saturating_duration_since(Instant::now());
            std::thread::sleep(
                Duration::from_millis(not_before - now)
                    .min(Duration::from_millis(250).min(remaining)),
            );
        }
        self.evidence.require_unchanged(self.original)?;
        let observed = crate::authbus_ingress::now_ms()?;
        anyhow::ensure!(observed >= not_before, "actual original expiry required");
        // This is only the new read-only fixture phase's outer deadline. It
        // changes neither an old product deadline nor an old signed lifetime.
        let end = self.end.min(
            Instant::now()
                .checked_add(Duration::from_secs(120))
                .ok_or_else(|| anyhow::anyhow!("cold read-only deadline overflow"))?,
        );
        super::root::write_json(
            &self.evidence.directory.join("actual-retirement-wait.json"),
            &json!({
                "schema":1,"started_unix_ms":started,"not_before_unix_ms":not_before,
                "observed_expired_unix_ms":observed,
                "read_only_remaining_ms":end.saturating_duration_since(Instant::now()).as_millis(),
                "old_daemon":process_data(&self.original.daemon),
                "old_root":process_data(&self.original.root)
            }),
        )?;
        let administration = self
            .retirement
            .prepare_after_actual_expiry(self.original, end)?;
        let plan = OriginalColdPlan::prepare(self.original, administration)?;
        self.evidence.require_unchanged(self.original)?;
        Ok((plan, self.evidence))
    }
}

impl OriginalColdEvidence {
    pub(super) fn require_unchanged(
        &self,
        original: &RetainedOrdinaryQ24Fixture,
    ) -> anyhow::Result<()> {
        original.daemon.require_dead()?;
        original.root.require_dead()?;
        original.source.require_dead()?;
        anyhow::ensure!(
            original.business_files() == self.files,
            "business set changed"
        );
        self.business.require_unchanged(&self.files)
    }
}

fn process_data(process: &ExitedOriginalProcess) -> serde_json::Value {
    let actual = process.lifetime();
    json!({"pid":actual.pid,"start_ticks":actual.start_ticks,"boot_id":actual.boot_id})
}
