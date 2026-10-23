//! Bounded MP1 TSV transport for the separately versioned research owner.

use std::io;
use std::io::BufRead;
use std::io::Read;
use std::io::Write;
use std::str::FromStr;

use crate::modality_portfolio::ActionV1;
use crate::modality_portfolio::ActionValueV1;
use crate::modality_portfolio::ConfigV1;
use crate::modality_portfolio::ModalityV1;
use crate::modality_portfolio::PhaseV1;
use crate::modality_portfolio::PolicyV1;
use crate::modality_portfolio::PortfolioError;
use crate::modality_portfolio::SessionV1;
use crate::modality_portfolio::bundle_digest;

fn parse<T: FromStr>(value: &str) -> Result<T, PortfolioError> {
    value.parse().map_err(|_| PortfolioError::InvalidProtocol)
}

fn four<T: FromStr>(fields: &[&str]) -> Result<[T; 4], PortfolioError> {
    Ok([
        parse(fields[0])?,
        parse(fields[1])?,
        parse(fields[2])?,
        parse(fields[3])?,
    ])
}

fn action(value: &str) -> Result<ActionV1, PortfolioError> {
    match value {
        "EMIT" => Ok(ActionV1::Emit),
        "REFINE_text" => Ok(ActionV1::Refine(ModalityV1::Text)),
        "REFINE_audio" => Ok(ActionV1::Refine(ModalityV1::Audio)),
        "REFINE_image" => Ok(ActionV1::Refine(ModalityV1::Image)),
        "REFINE_video" => Ok(ActionV1::Refine(ModalityV1::Video)),
        _ => Err(PortfolioError::InvalidProtocol),
    }
}

fn response(command: &str, owner: &SessionV1) -> String {
    let state = owner.snapshot();
    let phase = match state.phase {
        PhaseV1::Ready => "ready",
        PhaseV1::AwaitRefinement(_) => "await_refinement",
        PhaseV1::AwaitOutputs => "await_outputs",
        PhaseV1::Sealed => "sealed",
    };
    let [text, audio, image, video] = state.counts;
    let mut result = format!(
        "MP1\tOK\t{command}\t{}\t{}\t{}\t{}\t{text}\t{audio}\t{image}\t{video}\t{phase}\t{}",
        state.session_id,
        state.version,
        state.remaining_macs,
        state.total_refinements(),
        state.joint_digest()
    );
    if let Some(outputs) = owner.output_digests() {
        for (name, hash) in ["text", "audio", "image", "video"].into_iter().zip(outputs) {
            result.push_str(&format!("\t{name}\t{hash}"));
        }
        result.push_str(&format!(
            "\t{}",
            bundle_digest(b"hepta.modality-portfolio.outputs.v1\0", &outputs)
        ));
    }
    result
}

fn command(current: &mut Option<SessionV1>, fields: &[&str]) -> Result<String, PortfolioError> {
    if fields.first() != Some(&"MP1") || fields.len() < 2 {
        return Err(PortfolioError::InvalidProtocol);
    }
    if fields[1] == "INIT" && fields.len() == 22 {
        let policy = match (fields[20], fields[21]) {
            ("ADAPTIVE", "-") => PolicyV1::Adaptive,
            ("CLEAN", "-") => PolicyV1::Clean,
            ("COMMITTED", "-") => PolicyV1::Committed(Vec::new()),
            ("COMMITTED", plan) => PolicyV1::Committed(
                plan.split(',')
                    .map(|token| match action(token)? {
                        ActionV1::Refine(modality) => Ok(modality),
                        ActionV1::Emit => Err(PortfolioError::InvalidProtocol),
                    })
                    .collect::<Result<Vec<_>, _>>()?,
            ),
            _ => return Err(PortfolioError::InvalidProtocol),
        };
        let config = ConfigV1 {
            session_id: parse(fields[2])?,
            q_index: parse(fields[3])?,
            q_digest: parse(fields[4])?,
            budget_macs: parse(fields[5])?,
            init_macs: parse(fields[6])?,
            max_refinements: parse(fields[7])?,
            decoder_macs: four(&fields[8..12])?,
            refine_macs: four(&fields[12..16])?,
            latent_digests: four(&fields[16..20])?,
            policy,
        };
        if let Some(previous) = current {
            if previous.snapshot().phase != PhaseV1::Sealed {
                return Err(PortfolioError::PendingExecution);
            }
            if config.session_id <= previous.snapshot().session_id {
                return Err(PortfolioError::SessionSequence);
            }
        }
        let next = SessionV1::new(config)?;
        let result = response("INIT", &next);
        *current = Some(next);
        return Ok(result);
    }
    let owner = current.as_mut().ok_or(PortfolioError::InvalidProtocol)?;
    match (fields[1], fields.len()) {
        ("CHOOSE", 20) => {
            let entries = fields[5..]
                .chunks_exact(3)
                .map(|row| {
                    Ok(ActionValueV1 {
                        action: action(row[0])?,
                        value: parse(row[1])?,
                        cost_macs: parse(row[2])?,
                    })
                })
                .collect::<Result<Vec<_>, PortfolioError>>()?;
            let selected = owner.choose(
                parse(fields[2])?,
                parse(fields[3])?,
                parse(fields[4])?,
                &entries,
            )?;
            let name = match selected.action {
                ActionV1::Emit => "EMIT",
                ActionV1::Refine(ModalityV1::Text) => "REFINE_text",
                ActionV1::Refine(ModalityV1::Audio) => "REFINE_audio",
                ActionV1::Refine(ModalityV1::Image) => "REFINE_image",
                ActionV1::Refine(ModalityV1::Video) => "REFINE_video",
            };
            Ok(format!(
                "{}\t{name}\t{:.17e}",
                response("CHOOSE", owner),
                selected.value
            ))
        }
        ("REFINED", 9) => {
            let ActionV1::Refine(modality) = action(fields[4])? else {
                return Err(PortfolioError::InvalidProtocol);
            };
            owner.confirm_refinement(
                parse(fields[2])?,
                parse(fields[3])?,
                modality,
                four(&fields[5..9])?,
            )?;
            Ok(response("REFINED", owner))
        }
        ("EMITTED", 13) => {
            if [fields[5], fields[7], fields[9], fields[11]] != ["text", "audio", "image", "video"]
            {
                return Err(PortfolioError::InvalidOutputs);
            }
            let outputs = four(&[fields[6], fields[8], fields[10], fields[12]])?;
            owner.confirm_emission(
                parse(fields[2])?,
                parse(fields[3])?,
                parse(fields[4])?,
                outputs,
            )?;
            Ok(response("EMITTED", owner))
        }
        _ => Err(PortfolioError::InvalidProtocol),
    }
}

/// Every bounded TSV request receives an OK/ERR response. Only complete,
/// acknowledged sessions finish successfully; the bridge never executes kernels.
pub(crate) fn run(mut input: impl BufRead, mut output: impl Write) -> io::Result<()> {
    let mut current = None;
    loop {
        let mut line = String::new();
        let count = input.by_ref().take(4097).read_line(&mut line)?;
        if count == 0 {
            break;
        }
        if count > 4096 {
            writeln!(output, "MP1\tERR\tLineLimit")?;
            output.flush()?;
            return Err(io::Error::new(io::ErrorKind::InvalidData, "MP1 line limit"));
        }
        let fields = line
            .trim_end_matches(['\r', '\n'])
            .split('\t')
            .collect::<Vec<_>>();
        let result = match command(&mut current, &fields) {
            Ok(result) => result,
            Err(error) => format!("MP1\tERR\t{error}"),
        };
        writeln!(output, "{result}")?;
        output.flush()?;
    }
    if current.is_some_and(|owner| owner.snapshot().phase != PhaseV1::Sealed) {
        return Err(io::Error::new(
            io::ErrorKind::UnexpectedEof,
            "unfinished MP1 session",
        ));
    }
    Ok(())
}

#[cfg(test)]
#[path = "modality_portfolio_protocol_tests.rs"]
mod tests;
