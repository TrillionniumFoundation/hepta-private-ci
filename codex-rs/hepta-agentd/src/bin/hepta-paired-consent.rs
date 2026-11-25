//! Statement rendering; legacy SQLite-only authorization is unavailable.

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

    use codex_hepta_agentd::PairedLearningDataUse;
    use serde::Deserialize;

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

    fn bounded_json(reader: impl Read) -> anyhow::Result<Vec<u8>> {
        let mut bytes = Vec::new();
        reader.take(32769).read_to_end(&mut bytes)?;
        anyhow::ensure!(bytes.len() <= 32768, "private JSON exceeds 32 KiB");
        Ok(bytes)
    }

    pub(super) fn run() -> anyhow::Result<()> {
        let usage = "hepta-paired-consent --print-statement < scope.json\nLegacy ROOT_PID SQLITE_HOME ROUTE_JSON verification is unavailable: ORIGINAL_TURN_VERIFIER_REQUIRED.";
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
        // An acknowledged SQLite row and a live Root signature cannot prove
        // the original Core turn or its current queue/checkpoint state. Refuse
        // before reading caller paths, stdin or inherited capabilities.
        anyhow::bail!(
            "ORIGINAL_TURN_VERIFIER_REQUIRED: paired authorization requires the original protected runtime; SQLite-only verification is disabled"
        )
    }
}
