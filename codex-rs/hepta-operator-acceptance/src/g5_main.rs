use std::env;
use std::path::PathBuf;

use codex_hepta_operator_acceptance::G5AssessRequest;
use codex_hepta_operator_acceptance::G5EvidenceBinding;
use codex_hepta_operator_acceptance::G5HeadBinding;
use codex_hepta_operator_acceptance::G5PrepareRequest;
use codex_hepta_operator_acceptance::G5SignatureInput;
use codex_hepta_operator_acceptance::G5TrustInputs;
use codex_hepta_operator_acceptance::assess_g5_challenge;
use codex_hepta_operator_acceptance::prepare_g5_challenge;

const USAGE: &str = "usage:\n  hepta-g5-trust-assessor prepare-g5 <challenge> <policy> <policy-sha256> <allowed-signers> <revocations> <base> <head> <parent-head> <parent-tree> <tree> <aggregate-sha256> <manifest-sha256> <sha256sums-sha256> <now-unix-seconds> <lifetime-seconds>\n  hepta-g5-trust-assessor assess-g5  <challenge> <policy> <policy-sha256> <allowed-signers> <revocations> <base> <head> <parent-head> <parent-tree> <tree> <aggregate-sha256> <manifest-sha256> <sha256sums-sha256> <now-unix-seconds> <assessment-output-or-> [detached-signature]";

fn main() {
    if let Err(error) = run(env::args().collect()) {
        eprintln!("{error}");
        std::process::exit(1);
    }
}

fn run(arguments: Vec<String>) -> Result<(), String> {
    require_g5_environment()?;
    let command = arguments.get(1).ok_or_else(|| USAGE.to_string())?;
    match command.as_str() {
        "prepare-g5" if arguments.len() == 17 => {
            let parsed = parse_common(&arguments, /*start*/ 2)?;
            let lifetime = parse_u64(&arguments[16], "lifetime-seconds")?;
            let candidate = parsed.candidate.clone();
            let evidence = parsed.evidence.clone();
            let prepared = prepare_g5_challenge(G5PrepareRequest {
                challenge_path: &parsed.challenge,
                candidate,
                evidence,
                lifetime_seconds: lifetime,
                now_unix_seconds: parsed.now,
                trust: parsed.trust(),
            })
            .map_err(|error| error.to_string())?;
            println!(
                "{}",
                serde_json::to_string(&prepared).map_err(|error| error.to_string())?
            );
            Ok(())
        }
        "assess-g5" if arguments.len() == 17 || arguments.len() == 18 => {
            let parsed = parse_common(&arguments, /*start*/ 2)?;
            let expected_candidate = parsed.candidate.clone();
            let expected_evidence = parsed.evidence.clone();
            let assessment_path = if arguments[16] == "-" {
                None
            } else {
                Some(PathBuf::from(&arguments[16]))
            };
            // Keep the optional path alive through the assessment call.  A
            // detached signature is never written by this process.
            let signature_holder = arguments
                .get(17)
                .and_then(|value| (value != "-").then(|| PathBuf::from(value)));
            let signature = signature_holder
                .as_deref()
                .map(G5SignatureInput::Detached)
                .unwrap_or(G5SignatureInput::Absent);
            let assessed = assess_g5_challenge(G5AssessRequest {
                assessment_path: assessment_path.as_deref(),
                challenge_path: &parsed.challenge,
                expected_candidate,
                expected_evidence,
                now_unix_seconds: parsed.now,
                signature,
                trust: parsed.trust(),
            })
            .map_err(|error| error.to_string())?;
            println!(
                "{}",
                serde_json::to_string(&assessed).map_err(|error| error.to_string())?
            );
            Ok(())
        }
        _ => Err(USAGE.to_string()),
    }
}

struct ParsedCommon {
    allowed_signers: PathBuf,
    challenge: PathBuf,
    evidence: G5EvidenceBinding,
    candidate: G5HeadBinding,
    now: u64,
    policy: PathBuf,
    policy_sha256: String,
    revocations: PathBuf,
}

impl ParsedCommon {
    fn trust(&self) -> G5TrustInputs<'_> {
        G5TrustInputs {
            allowed_signers_path: &self.allowed_signers,
            externally_pinned_policy_sha256: &self.policy_sha256,
            revocation_path: &self.revocations,
            trust_policy_path: &self.policy,
        }
    }
}

fn parse_common(arguments: &[String], start: usize) -> Result<ParsedCommon, String> {
    let challenge = PathBuf::from(&arguments[start]);
    let policy = PathBuf::from(&arguments[start + 1]);
    let policy_sha256 = arguments[start + 2].clone();
    let allowed_signers = PathBuf::from(&arguments[start + 3]);
    let revocations = PathBuf::from(&arguments[start + 4]);
    let candidate = G5HeadBinding {
        base: arguments[start + 5].clone(),
        head: arguments[start + 6].clone(),
        parent_head: arguments[start + 7].clone(),
        parent_tree: arguments[start + 8].clone(),
        tree: arguments[start + 9].clone(),
    };
    let evidence = G5EvidenceBinding {
        aggregate_sha256: arguments[start + 10].clone(),
        evidence_manifest_sha256: arguments[start + 11].clone(),
        sha256sums_sha256: arguments[start + 12].clone(),
    };
    let now = parse_u64(&arguments[start + 13], "now-unix-seconds")?;
    Ok(ParsedCommon {
        challenge,
        evidence,
        candidate,
        now,
        allowed_signers,
        policy,
        policy_sha256,
        revocations,
    })
}

fn parse_u64(value: &str, label: &str) -> Result<u64, String> {
    value
        .parse::<u64>()
        .map_err(|error| format!("{label} must be an unsigned integer: {error}"))
}

fn require_g5_environment() -> Result<(), String> {
    let expected = [
        ("HEPTA_SSD_ROOT", "/Volumes/T5/hepta-vnext"),
        (
            "HEPTA_SSD_VOLUME_UUID",
            "FB804D1B-24CB-4D6E-AEA7-A9E180807758",
        ),
        ("HEPTA_LANE", "r2-g5-operator-trust-20260823"),
        (
            "HEPTA_WORKTREE",
            "/Volumes/T5/hepta-vnext/worktrees/r2-g5-operator-trust-20260823",
        ),
        ("HEPTA_ARTIFACTS_DIR", "/Volumes/T5/hepta-vnext/artifacts"),
    ];
    for (name, value) in expected {
        if env::var(name).ok().as_deref() != Some(value) {
            return Err(format!(
                "G5 trust assessor requires exact {name} from hepta-ssd-run"
            ));
        }
    }
    Ok(())
}
