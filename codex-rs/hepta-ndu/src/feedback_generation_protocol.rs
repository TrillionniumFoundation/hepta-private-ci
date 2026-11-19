//! Bounded TSV transport for the experiment's persistent native owner.

use std::io;
use std::io::BufRead;
use std::io::Read;
use std::io::Write;
use std::str::FromStr;

use crate::FeedbackActionV1;
use crate::FeedbackActionValueV1;
use crate::FeedbackGenerationConfigV1;
use crate::FeedbackGenerationError;
use crate::FeedbackGenerationSessionV1;
use crate::FeedbackPhaseV1;
use crate::FeedbackSnapshotV1;

fn parse<T: FromStr>(value: &str) -> Result<T, FeedbackGenerationError> {
    value
        .parse()
        .map_err(|_| FeedbackGenerationError::InvalidProtocol)
}

fn snapshot(fields: &[&str]) -> Result<FeedbackSnapshotV1, FeedbackGenerationError> {
    Ok(FeedbackSnapshotV1 {
        session_id: parse(fields[1])?,
        version: parse(fields[2])?,
        depth: parse(fields[3])?,
        portfolio_index: parse(fields[4])?,
        latent_digest: parse(fields[5])?,
    })
}

fn command(
    current: &mut Option<FeedbackGenerationSessionV1>,
    fields: &[&str],
) -> Result<String, FeedbackGenerationError> {
    if fields[0] == "INIT" && fields.len() == 8 {
        let config = FeedbackGenerationConfigV1 {
            session_id: parse(fields[1])?,
            budget_macs: parse(fields[2])?,
            emit_macs: parse(fields[3])?,
            refine_macs: parse(fields[4])?,
            max_refinements: parse(fields[5])?,
            portfolio_index: parse(fields[6])?,
            latent_digest: parse(fields[7])?,
        };
        if let Some(previous) = current {
            if previous.phase() != FeedbackPhaseV1::Sealed {
                return Err(FeedbackGenerationError::PendingExecution);
            }
            if config.session_id <= previous.snapshot().session_id {
                return Err(FeedbackGenerationError::SessionSequence);
            }
        }
        let next = FeedbackGenerationSessionV1::new(config)?;
        let result = format!(
            "OK\tINIT\t{}\t0\t{}\t0\tready",
            config.session_id, config.budget_macs
        );
        *current = Some(next);
        return Ok(result);
    }
    let owner = current
        .as_mut()
        .ok_or(FeedbackGenerationError::InvalidProtocol)?;
    match (fields[0], fields.len()) {
        ("CHOOSE", 9 | 12) => {
            let state = snapshot(fields)?;
            let actions = fields[6..]
                .chunks_exact(3)
                .map(|entry| {
                    Ok(FeedbackActionValueV1 {
                        action: match entry[0] {
                            "emit" => FeedbackActionV1::Emit,
                            "refine" => FeedbackActionV1::Refine,
                            _ => return Err(FeedbackGenerationError::InvalidProtocol),
                        },
                        value: parse(entry[1])?,
                        cost_macs: parse(entry[2])?,
                    })
                })
                .collect::<Result<Vec<_>, FeedbackGenerationError>>()?;
            let decision = owner.choose(state, &actions)?;
            let name = match decision.action {
                FeedbackActionV1::Emit => "emit",
                FeedbackActionV1::Refine => "refine",
            };
            Ok(format!(
                "OK\tCHOOSE\t{}\t{}\t{}\t{}\t{name}\t{:.17e}",
                state.session_id,
                decision.version,
                decision.remaining_macs,
                decision.depth,
                decision.value
            ))
        }
        ("REFINED", 6) => {
            let state = snapshot(fields)?;
            owner.confirm_refinement(state)?;
            Ok(format!(
                "OK\tREFINED\t{}\t{}\t{}\t{}\tready",
                state.session_id,
                state.version,
                owner.remaining_macs(),
                state.depth
            ))
        }
        ("EMITTED", 7) => {
            let session_id = parse(fields[1])?;
            let version = parse(fields[2])?;
            owner.confirm_emission(
                session_id,
                version,
                [
                    parse(fields[3])?,
                    parse(fields[4])?,
                    parse(fields[5])?,
                    parse(fields[6])?,
                ],
            )?;
            Ok(format!(
                "OK\tEMITTED\t{session_id}\t{version}\t{}\t{}\tsealed",
                owner.remaining_macs(),
                owner.snapshot().depth
            ))
        }
        _ => Err(FeedbackGenerationError::InvalidProtocol),
    }
}

/// Run a persistent, one-session-at-a-time local control protocol.
///
/// Each line is at most 4096 bytes and consists of tab-separated fields. INIT
/// opens a session; subsequent commands are CHOOSE, REFINED and EMITTED. Every
/// request yields one OK or ERR line. EOF with an unfinished session fails.
/// No command performs a model dispatch or an external operation.
pub fn run_feedback_generation_protocol(
    mut input: impl BufRead,
    mut output: impl Write,
) -> io::Result<()> {
    let mut current = None;
    loop {
        let mut line = String::new();
        let count = input.by_ref().take(4097).read_line(&mut line)?;
        if count == 0 {
            break;
        }
        if count > 4096 {
            writeln!(output, "ERR\tLineLimit")?;
            output.flush()?;
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "feedback line limit",
            ));
        }
        let fields = line
            .trim_end_matches(['\r', '\n'])
            .split('\t')
            .collect::<Vec<_>>();
        let response = match command(&mut current, &fields) {
            Ok(response) => response,
            Err(error) => format!("ERR\t{error}"),
        };
        writeln!(output, "{response}")?;
        output.flush()?;
    }
    if current.is_some_and(|owner| owner.phase() != FeedbackPhaseV1::Sealed) {
        return Err(io::Error::new(
            io::ErrorKind::UnexpectedEof,
            "unfinished feedback session",
        ));
    }
    Ok(())
}
