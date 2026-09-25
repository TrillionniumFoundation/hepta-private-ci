use serde::Deserialize;

use crate::QualificationError;
use crate::verification_primitives::canonical_json;
use crate::verification_primitives::sha256;

const ORACLE_BYTES: usize = 5_194;
const TRACKED_ORACLE_BYTES: usize = ORACLE_BYTES + 1;
const TRACKED_ORACLE_SHA256: &str =
    "faa924acbdca3df64ffacf272d3367a8be26e6d5ed9ec384b71a2d744ccce0e9";
const ORACLE_SHA256: &str = "dfe4f04d26895a6fabfb8435b77d7e807f57379fbb8d2a96c85af747e996cda7";
const ORACLE_COMMIT: &str = "2f704dc7c1172cefca908852456beccf4d02a5d1";
const ORACLE_TREE: &str = "7be9a382b2610790838eef874cb4d381b5025490";
const ORACLE_MANIFEST_SHA256: &str =
    "2c82d45303e912b92a7b9ac31da4661197e59a5ca415d3c70375b49169691377";
const ORACLE_GENERATOR_SHA256: &str =
    "0778717e2ef2a9adfc7eb3c6980a8c2e7433e4ffbbbc6f124fb9e4098b4d1ab9";
const RAW_ARGUMENTS: &str =
    r#"{"command":"/usr/bin/printf hepta-shadow-probe","login":false,"timeout_ms":5000}"#;
const RAW_ARGUMENTS_SHA256: &str =
    "28543d724c56a81d59ccb9c183300ff568b158cb33bc8330a581a3aa32ab239d";
const PAYLOAD_SHA256: &str = "0918708543060974ab1e37c2b08d0ea688838f4ec54477eb9945d62478e07cbf";
const NORMALIZED_RECEIPT_SHA256: &str =
    "8904f0cc74e8a1b465eb75c7cd0c3f6ebef916c414dc9f5b6610d5822e9f68c0";
const SAMPLE_ID_SHA256: &str = "426468e3c420e5557f2edbbb0adfc845b611c00416112c1ed95d99219fa9c5ef";
const PROJECTION_SHA256: &str = "c55cdf2948b15f37bba96d3a2ef53c63c001b4eadeb0173e2f0b9310884ec8ae";

const TRACKED_ORACLE: &[u8] = include_bytes!("../fixtures/live_product_oracle_v2_2f704.json");

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FrozenOracle {
    expected_normalized_receipt: Vec<u8>,
}

impl FrozenOracle {
    pub fn load_embedded() -> Result<Self, QualificationError> {
        if TRACKED_ORACLE.len() != TRACKED_ORACLE_BYTES
            || TRACKED_ORACLE.last() != Some(&b'\n')
            || sha256(TRACKED_ORACLE) != TRACKED_ORACLE_SHA256
        {
            return Err(invalid(
                "tracked oracle representation differs from its pin",
            ));
        }
        Self::load(&TRACKED_ORACLE[..ORACLE_BYTES])
    }

    pub fn load(bytes: &[u8]) -> Result<Self, QualificationError> {
        if bytes.len() != ORACLE_BYTES || sha256(bytes) != ORACLE_SHA256 {
            return Err(invalid("oracle bytes differ from the frozen 2f704 corpus"));
        }
        let value: serde_json::Value = serde_json::from_slice(bytes)
            .map_err(|error| invalid(format!("invalid oracle JSON: {error}")))?;
        if canonical_json(&value)? != bytes {
            return Err(invalid("oracle is not compact canonical JSON"));
        }
        let document: OracleDocument = serde_json::from_value(value)
            .map_err(|error| invalid(format!("invalid strict oracle schema: {error}")))?;
        validate_header(&document)?;
        let case = document
            .cases
            .first()
            .ok_or_else(|| invalid("oracle case is missing"))?;
        validate_case(case)?;
        Ok(Self {
            expected_normalized_receipt: case
                .expected_normalized_receipt_canonical_json
                .as_bytes()
                .to_vec(),
        })
    }

    pub fn corpus_sha256(&self) -> &'static str {
        ORACLE_SHA256
    }

    pub fn expected_normalized_receipt(&self) -> &[u8] {
        &self.expected_normalized_receipt
    }

    pub fn expected_normalized_receipt_sha256(&self) -> &'static str {
        NORMALIZED_RECEIPT_SHA256
    }

    pub fn oracle_commit(&self) -> &'static str {
        ORACLE_COMMIT
    }

    pub fn oracle_tree(&self) -> &'static str {
        ORACLE_TREE
    }

    pub fn payload_sha256(&self) -> &'static str {
        PAYLOAD_SHA256
    }

    pub fn raw_function_arguments(&self) -> &'static str {
        RAW_ARGUMENTS
    }

    pub fn sample_id_sha256(&self) -> &'static str {
        SAMPLE_ID_SHA256
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct OracleDocument {
    authority: OracleAuthority,
    canonical_encoding: String,
    canonical_object: String,
    case_count: u64,
    cases: Vec<OracleCase>,
    generator: OracleGenerator,
    normalization: OracleNormalization,
    oracle_commit: String,
    oracle_manifest_sha256: String,
    oracle_profile: String,
    oracle_tree: String,
    qualification_only: bool,
    reachability: OracleReachability,
    schema: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct OracleAuthority {
    enforce: bool,
    operator_acceptance: bool,
    outbound: bool,
    promotion: bool,
    retirement: bool,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct OracleCase {
    expected_normalized_receipt_canonical_json: String,
    expected_normalized_receipt_sha256: String,
    expected_output_sha256: String,
    expected_projection: serde_json::Value,
    function_arguments_raw: String,
    function_arguments_raw_sha256: String,
    ordinal: u64,
    payload_kind: String,
    payload_sha256: String,
    receipt_phase: String,
    sample_id_sha256: String,
    source_kind: String,
    terminal_kind: String,
    tool_name: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct OracleGenerator {
    entrypoint: String,
    schema: String,
    source_sha256: String,
    version: u32,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct OracleNormalization {
    fixed_identity: OracleFixedIdentity,
    formula: String,
    output: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct OracleFixedIdentity {
    call_id: String,
    thread_id: String,
    turn_id: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct OracleReachability {
    actual_live_product_reachability: String,
    actual_live_product_trial_closure_required: bool,
    parser_reachable_semantics: bool,
    parser_type: String,
    statement: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ShellCommandArgs {
    command: String,
    login: bool,
    timeout_ms: u64,
}

fn validate_header(document: &OracleDocument) -> Result<(), QualificationError> {
    let authority_disabled = !document.authority.enforce
        && !document.authority.operator_acceptance
        && !document.authority.outbound
        && !document.authority.promotion
        && !document.authority.retirement;
    let valid = document.schema == "hepta_live_product_shadow_oracle_corpus_v2"
        && document.canonical_encoding == "compact_utf8_json_recursive_lexicographic_object_keys"
        && document.canonical_object == "codex_hepta_contracts::GovernanceReceipt"
        && document.case_count == 1
        && document.cases.len() == 1
        && document.oracle_commit == ORACLE_COMMIT
        && document.oracle_tree == ORACLE_TREE
        && document.oracle_manifest_sha256 == ORACLE_MANIFEST_SHA256
        && document.oracle_profile == "live_product_parser_reachable_semantics_v2"
        && document.qualification_only
        && authority_disabled
        && document.generator.schema == "hepta_live_product_oracle_generator_v2"
        && document.generator.version == 2
        && document.generator.source_sha256 == ORACLE_GENERATOR_SHA256
        && document.generator.entrypoint
            == "live_product_oracle_v2_generator::emit_frozen_live_product_oracle_v2_one_reachable_case"
        && document.normalization.fixed_identity.call_id == "call-oracle-v2"
        && document.normalization.fixed_identity.thread_id == "thread-oracle-v2"
        && document.normalization.fixed_identity.turn_id == "turn-oracle-v2"
        && document.normalization.formula
            == "replace dynamic thread/turn/call identity with fixed v2 identity; recompute action, decision, and receipt ids; preserve tool, source, payload, policy, decisions, host acceptance, and outcome"
        && document.normalization.output
            == "compact canonical JSON of the normalized GovernanceReceipt"
        && document.reachability.actual_live_product_reachability == "not_proven"
        && document
            .reachability
            .actual_live_product_trial_closure_required
        && document.reachability.parser_reachable_semantics
        && document.reachability.parser_type
            == "codex_protocol::models::ShellCommandToolCallParams"
        && document.reachability.statement
            == "This corpus proves only that the exact Function arguments deserialize through the frozen public shell-command parser and that frozen governance maps the semantic record. Actual live reachability requires a later exact frozen-product trial closure.";
    if !valid {
        return Err(invalid("oracle header differs from the frozen 2f704 pins"));
    }
    Ok(())
}

fn validate_case(case: &OracleCase) -> Result<(), QualificationError> {
    let args_value: serde_json::Value = serde_json::from_str(&case.function_arguments_raw)
        .map_err(|error| invalid(format!("invalid oracle Function arguments: {error}")))?;
    let args: ShellCommandArgs = serde_json::from_value(args_value.clone())
        .map_err(|error| invalid(format!("invalid oracle shell-command arguments: {error}")))?;
    let receipt_value: serde_json::Value =
        serde_json::from_str(&case.expected_normalized_receipt_canonical_json)
            .map_err(|error| invalid(format!("invalid oracle receipt JSON: {error}")))?;
    let valid = case.ordinal == 1
        && case.payload_kind == "function"
        && case.receipt_phase == "admission_and_authorization"
        && case.source_kind == "direct"
        && case.terminal_kind == "handler_completed"
        && case.tool_name == "shell_command"
        && case.function_arguments_raw == RAW_ARGUMENTS
        && case.function_arguments_raw_sha256 == RAW_ARGUMENTS_SHA256
        && sha256(case.function_arguments_raw.as_bytes()) == RAW_ARGUMENTS_SHA256
        && canonical_json(&args_value)? == RAW_ARGUMENTS.as_bytes()
        && args.command == "/usr/bin/printf hepta-shadow-probe"
        && !args.login
        && args.timeout_ms == 5_000
        && case.payload_sha256 == PAYLOAD_SHA256
        && case.sample_id_sha256 == SAMPLE_ID_SHA256
        && case.expected_normalized_receipt_sha256 == NORMALIZED_RECEIPT_SHA256
        && case.expected_output_sha256 == NORMALIZED_RECEIPT_SHA256
        && canonical_json(&receipt_value)?
            == case.expected_normalized_receipt_canonical_json.as_bytes()
        && sha256(case.expected_normalized_receipt_canonical_json.as_bytes())
            == NORMALIZED_RECEIPT_SHA256
        && sha256(&canonical_json(&case.expected_projection)?) == PROJECTION_SHA256;
    if !valid {
        return Err(invalid(
            "oracle case differs from the frozen reachable sample",
        ));
    }
    Ok(())
}

fn invalid(message: impl Into<String>) -> QualificationError {
    QualificationError::Invalid(message.into())
}
