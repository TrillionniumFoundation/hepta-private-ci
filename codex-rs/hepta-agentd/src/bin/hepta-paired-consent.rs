//! Private one-shot verification for an already attached Linux owner.

#[cfg(not(target_os = "linux"))]
fn main() -> anyhow::Result<()> {
    anyhow::bail!("paired consent requires the original Linux Root and human UI")
}

#[cfg(target_os = "linux")]
fn main() -> anyhow::Result<()> {
    linux::run()
}

#[cfg(target_os = "linux")]
mod linux {
    use std::io::Read;
    use std::os::fd::FromRawFd;
    use std::os::fd::OwnedFd;
    use std::os::fd::RawFd;
    use std::os::unix::net::UnixStream;
    use std::sync::Arc;
    use std::time::Duration;

    use anyhow::Context;
    use codex_hepta_agentd::AgentdUnixFinalUseGrantProvider;
    use codex_hepta_agentd::PairedLearningDataUse;
    use codex_hepta_agentd::text_session::AgentdTextSessionConfig;
    use codex_hepta_evidence::HeptaEvidenceStore;
    use codex_hepta_types::Digest32;
    use codex_state::SqliteConfig;
    use codex_utils_absolute_path::AbsolutePathBuf;
    use serde::Deserialize;

    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Request {
        study_sha256: String,
        delivery_id: String,
        scope: Scope,
    }

    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Statement {
        study_sha256: String,
        scope: Scope,
    }

    #[derive(Deserialize)]
    #[serde(rename_all = "snake_case")]
    enum Outcome {
        Accepted,
        Rejected,
    }

    #[derive(Deserialize)]
    #[serde(tag = "use", rename_all = "snake_case", deny_unknown_fields)]
    enum Scope {
        Train {
            failure: String,
            correction: String,
        },
        EvaluateOnly {
            freeze: String,
            task: String,
        },
        RequestConsumerRun {
            operation: String,
            pair: String,
            candidate: String,
            task: String,
        },
        ReportConsumerOutcome {
            operation: String,
            pair: String,
            candidate: String,
            task: String,
            run_receipt: String,
            output: String,
            effect: String,
            outcome: Outcome,
        },
    }

    impl Scope {
        fn parse(self) -> anyhow::Result<PairedLearningDataUse> {
            Ok(match self {
                Scope::Train {
                    failure,
                    correction,
                } => PairedLearningDataUse::TrainOnFailureAndCorrection {
                    failure: failure.parse()?,
                    correction: correction.parse()?,
                },
                Scope::EvaluateOnly { freeze, task } => {
                    PairedLearningDataUse::EvaluateOnlyAfterFreeze {
                        freeze: freeze.parse()?,
                        task: task.parse()?,
                    }
                }
                Scope::RequestConsumerRun {
                    operation,
                    pair,
                    candidate,
                    task,
                } => PairedLearningDataUse::RequestConsumerRun {
                    operation: operation.parse()?,
                    pair: pair.parse()?,
                    candidate: candidate.parse()?,
                    task: task.parse()?,
                },
                Scope::ReportConsumerOutcome {
                    operation,
                    pair,
                    candidate,
                    task,
                    run_receipt,
                    output,
                    effect,
                    outcome,
                } => PairedLearningDataUse::ReportConsumerOutcome {
                    operation: operation.parse()?,
                    pair: pair.parse()?,
                    candidate: candidate.parse()?,
                    task: task.parse()?,
                    run_receipt: run_receipt.parse()?,
                    output: output.parse()?,
                    effect: effect.parse()?,
                    accepted: matches!(outcome, Outcome::Accepted),
                },
            })
        }
    }

    fn inherited(fd: RawFd) -> std::io::Result<OwnedFd> {
        // fcntl checks that the inherited descriptor exists. Duplicate above
        // both fixed slots so a missing pidfd cannot alias a new duplicate.
        let owned = unsafe { libc::fcntl(fd, libc::F_DUPFD_CLOEXEC, 5) };
        if owned < 0 {
            return Err(std::io::Error::last_os_error());
        }
        // SAFETY: a successful F_DUPFD_CLOEXEC returns a new descriptor we own.
        Ok(unsafe { OwnedFd::from_raw_fd(owned) })
    }

    fn bounded_json(reader: impl Read) -> anyhow::Result<Vec<u8>> {
        let mut bytes = Vec::new();
        reader.take(32769).read_to_end(&mut bytes)?;
        anyhow::ensure!(bytes.len() <= 32768, "private JSON exceeds 32 KiB");
        Ok(bytes)
    }

    pub(super) fn run() -> anyhow::Result<()> {
        let usage = "hepta-paired-consent --print-statement < scope.json\nhepta-paired-consent ROOT_PID SQLITE_HOME ROUTE_JSON < private-refs.json\nThe existing protected Linux owner passes the Root issuer socket on fd 3 and its held pidfd on fd 4.";
        let args: Vec<_> = std::env::args_os().skip(1).collect();
        if matches!(args.as_slice(), [flag] if flag == "--help") {
            println!("{usage}");
            return Ok(());
        }
        if matches!(args.as_slice(), [flag] if flag == "--print-statement") {
            let statement: Statement = serde_json::from_slice(&bounded_json(std::io::stdin())?)?;
            let study = statement.study_sha256.parse()?;
            let scope = statement.scope.parse()?;
            print!("{}", scope.consent_text(study));
            return Ok(());
        }
        let [pid, sqlite_home, route_file] = args.as_slice() else {
            anyhow::bail!("{usage}");
        };
        let root_pid: u32 = pid.to_str().context("invalid Root PID")?.parse()?;
        // Verify inherited capabilities before opening a route or reading stdin.
        let issuer = Arc::new(AgentdUnixFinalUseGrantProvider::from_root_stream(
            UnixStream::from(
                inherited(3).context("missing inherited private Root socket on fd 3")?,
            ),
            root_pid,
            inherited(4).context("missing inherited original Root pidfd on fd 4")?,
            Duration::from_secs(3),
            Duration::from_secs(15),
        )?);
        let route: AgentdTextSessionConfig =
            serde_json::from_slice(&bounded_json(std::fs::File::open(route_file)?)?)?;
        let bytes = bounded_json(std::io::stdin())?;
        let request: Request = serde_json::from_slice(&bytes)?;
        let study: Digest32 = request.study_sha256.parse()?;
        let delivery: Digest32 = request.delivery_id.parse()?;
        let allowed = request.scope.parse()?;
        let sqlite =
            SqliteConfig::from_sqlite_home(AbsolutePathBuf::from_absolute_path(sqlite_home)?);
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()?;
        let owner = runtime.block_on(async {
            let evidence = HeptaEvidenceStore::open_existing_read_only(&sqlite).await?;
            let result = issuer
                .verify_retained_paired_learning_consent(
                    &evidence, &route, delivery, study, allowed,
                )
                .await;
            evidence.close().await;
            Ok::<_, anyhow::Error>(result?)
        })?;
        let consent = Digest32::of_bytes(allowed.consent_text(study).as_bytes());
        let principal = Digest32::of_bytes(&serde_json::to_vec(&(
            "hepta.paired-learning.principal.v1",
            study.to_string(),
            &owner.principal_id,
        ))?);
        let (scope, receipt_schema, hash_field) = match allowed {
            PairedLearningDataUse::TrainOnFailureAndCorrection { .. } => (
                "train",
                "hepta.paired-learning.consent-readback.v1",
                "consent_text_sha256",
            ),
            PairedLearningDataUse::EvaluateOnlyAfterFreeze { .. } => (
                "evaluate_only",
                "hepta.paired-learning.consent-readback.v1",
                "consent_text_sha256",
            ),
            PairedLearningDataUse::RequestConsumerRun { .. } => (
                "request_consumer_run",
                "hepta.paired-learning.consumer-statement-readback.v1",
                "statement_sha256",
            ),
            PairedLearningDataUse::ReportConsumerOutcome { .. } => (
                "report_consumer_outcome",
                "hepta.paired-learning.consumer-statement-readback.v1",
                "statement_sha256",
            ),
        };
        let receipt = serde_json::json!({
            "schema": receipt_schema, "study_sha256": study.to_string(), "delivery_id": delivery.to_string(),
            "use": scope, (hash_field): consent.to_string(), "study_principal_sha256": principal.to_string()
        });
        println!("{receipt}");
        Ok(())
    }
}
