//! Per-round references over original complete role configurations. These pure
//! projections preserve key paths, controller/trust, data custody and denials.
use crate::PairedReviewSourcePlanV1;
use crate::ParameterRoleSourceV3;
use std::path::PathBuf;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
pub enum OriginalPairedParameterConfigurationV1<'a> {
    Generator {
        inputs: &'a ParameterRoleSourceV3,
    },
    Execution {
        generator: &'a ParameterRoleSourceV3,
        work_directory: &'a PathBuf,
        deadline_ms: u64,
    },
    Review {
        publication: &'a ParameterRoleSourceV3,
        parameter: &'a ParameterRoleSourceV3,
    },
    Finish {
        publication: &'a ParameterRoleSourceV3,
        evaluation: &'a ParameterRoleSourceV3,
        parameter: &'a ParameterRoleSourceV3,
        evidence_path: &'a PathBuf,
        acknowledgement_path: &'a PathBuf,
    },
}
/// Decode both complete configurations with the original purpose owner. Only
/// these explicitly typed references change; no arbitrary field map is accepted.
pub fn project_original_paired_parameter_configuration_v1(
    bytes: &[u8],
    references: OriginalPairedParameterConfigurationV1<'_>,
) -> Result<Vec<u8>> {
    if bytes.len() > 32 * 1024 {
        return Err("original complete role configuration bound".into());
    }
    let mut value: serde_json::Value = serde_json::from_slice(bytes)?;
    match &references {
        OriginalPairedParameterConfigurationV1::Generator { .. } => {
            crate::fixed_paired_generator_host::validate_paired_parameter_generator_config(bytes)?
        }
        OriginalPairedParameterConfigurationV1::Execution { .. } => {
            crate::fixed_paired_custody_host::validate_paired_parameter_execution_config(bytes)?
        }
        OriginalPairedParameterConfigurationV1::Review { .. } => {
            crate::fixed_paired_review_host::validate_paired_parameter_review_config(bytes)?
        }
        OriginalPairedParameterConfigurationV1::Finish { .. } => {
            crate::fixed_paired_finish_host::validate_paired_parameter_finish_config(bytes)?
        }
    }
    match references {
        OriginalPairedParameterConfigurationV1::Generator { inputs } => {
            value["source"] = serde_json::to_value(inputs)?
        }
        OriginalPairedParameterConfigurationV1::Execution {
            generator,
            work_directory,
            deadline_ms,
        } => {
            if deadline_ms == 0 {
                return Err("original Round deadline".into());
            }
            value["generator"] = serde_json::to_value(generator)?;
            value["work_directory"] = serde_json::to_value(work_directory)?;
            value["operation_expires_at_ms"] = deadline_ms.into();
        }
        OriginalPairedParameterConfigurationV1::Review {
            publication,
            parameter,
        } => {
            value["publication_path"] = serde_json::to_value(&publication.path)?;
            value["publication_digest"] = publication.digest.clone().into();
            value["parameter_evaluation"] = serde_json::to_value(parameter)?;
        }
        OriginalPairedParameterConfigurationV1::Finish {
            publication,
            evaluation,
            parameter,
            evidence_path,
            acknowledgement_path,
        } => {
            value["execution"] = serde_json::to_value(publication)?;
            value["evaluator_result"] = serde_json::to_value(evaluation)?;
            value["parameter_evaluation"] = serde_json::to_value(parameter)?;
            value["evidence_path"] = serde_json::to_value(evidence_path)?;
            value["ack_path"] = serde_json::to_value(acknowledgement_path)?;
        }
    }
    let output = serde_json::to_vec(&value)?;
    if output.len() > 32 * 1024 {
        return Err("projected complete original configuration bound".into());
    }
    // The same original decoder rejects missing/extra fields after projection.
    match value["schema"].as_str().ok_or("original role schema")? {
        "hepta.fixed-paired-generator-config.v1" => {
            crate::fixed_paired_generator_host::validate_paired_parameter_generator_config(&output)?
        }
        "hepta.fixed-paired-review-config.v1" => {
            crate::fixed_paired_review_host::validate_paired_parameter_review_config(&output)?
        }
        "hepta.fixed-paired-custody-finish-config.v1" => {
            crate::fixed_paired_finish_host::validate_paired_parameter_finish_config(&output)?
        }
        schema if schema.starts_with("hepta.fixed-paired-custody-execution-config.v") => {
            crate::fixed_paired_custody_host::validate_paired_parameter_execution_config(&output)?
        }
        _ => return Err("unknown original finite purpose".into()),
    }
    Ok(output)
}
/// Keep original encoder, full batch membership, physical width and budgets.
/// G measures the fresh request bytes itself before signing the original plan.
pub fn project_original_paired_parameter_generator_inputs_v1(
    bytes: &[u8],
    plan: &PairedReviewSourcePlanV1,
) -> Result<Vec<u8>> {
    crate::fixed_paired_generator_host::replace_paired_parameter_generator_plan(bytes, plan)
}

#[cfg(test)]
#[path = "paired_parameter_configuration_tests.rs"]
mod tests;
