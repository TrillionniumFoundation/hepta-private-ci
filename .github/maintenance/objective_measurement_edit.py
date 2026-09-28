#!/usr/bin/env python3
"""Apply the remaining objective.compiler source changes.

Development-only edit. This script creates ordinary source changes and never
asserts qualification, target-host acceptance, activation, or release.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace(path: str, old: str, new: str, count: int = 1) -> None:
    text = read(path)
    actual = text.count(old)
    if actual != count:
        raise RuntimeError(
            f"{path}: expected {count} occurrences, found {actual}: {old[:120]!r}"
        )
    write(path, text.replace(old, new))


def replace_after(
    path: str, marker: str, old: str, new: str, count: int = 1
) -> None:
    text = read(path)
    offset = text.find(marker)
    if offset < 0:
        raise RuntimeError(f"{path}: marker not found: {marker!r}")
    prefix, suffix = text[:offset], text[offset:]
    actual = suffix.count(old)
    if actual != count:
        raise RuntimeError(
            f"{path}: expected {count} occurrences after marker, found {actual}: {old[:120]!r}"
        )
    write(path, prefix + suffix.replace(old, new))


def append(path: str, content: str, sentinel: str) -> None:
    text = read(path)
    if sentinel in text:
        raise RuntimeError(f"{path}: sentinel already present: {sentinel}")
    write(path, text.rstrip() + "\n\n" + content.strip() + "\n")


# ---------------------------------------------------------------------------
# 2. Stage-level named-host measurements without weakening validation.
# ---------------------------------------------------------------------------

p = "codex-rs/hepta-objective/src/objective_admission_tests.rs"
replace(
    p,
    "use crate::encode_objective_function_v1;\n",
    '''use crate::ValidatedAdmissionProfileV1;
use crate::admit_validated_objective_v1;
use crate::compile_validated_objective_v1;
use crate::decode_objective_function_v1;
use crate::encode_objective_function_v1;
use crate::encode_proof_bearing_objective_function_v1;
''',
)
text = read(p)
start = text.index(
    '#[test]\n#[ignore = "run only on a named target host through hepta-objective-target-measure.py"]\nfn measurement_ordinary_admission_compile_v1()'
)
prefix = text[:start]
measurement_tail = r'''#[test]
#[ignore = "run only on a named target host through hepta-objective-target-measure.py"]
fn measurement_ordinary_admission_compile_v1() {
    let raw_profile = profile();
    let envelope = envelope();
    let context = context(&raw_profile, &envelope);
    let frozen =
        ValidatedAdmissionProfileV1::from_profile(&raw_profile).expect("frozen measurement profile");
    let samples = measurement_sample_count(1_000, 100_000);

    let mut cold_profile = Vec::with_capacity(samples);
    let mut warm_admission = Vec::with_capacity(samples);
    let mut native_compile = Vec::with_capacity(samples);
    let mut protocol_encode = Vec::with_capacity(samples);
    let mut protocol_decode = Vec::with_capacity(samples);
    let mut warm_total = Vec::with_capacity(samples);

    for _ in 0..samples {
        let started = Instant::now();
        let cold = ValidatedAdmissionProfileV1::from_profile(&raw_profile)
            .expect("cold profile validation");
        cold_profile.push(started.elapsed().as_nanos());
        black_box(cold.reuse_key());

        let total_started = Instant::now();

        let started = Instant::now();
        let admitted = admit_validated_objective_v1(&envelope, &frozen, &context)
            .expect("warm authenticated admission");
        warm_admission.push(started.elapsed().as_nanos());

        let started = Instant::now();
        let proof_bearing =
            compile_validated_objective_v1(admitted).expect("native deterministic compile");
        native_compile.push(started.elapsed().as_nanos());

        let started = Instant::now();
        let protocol =
            encode_proof_bearing_objective_function_v1(&proof_bearing, &envelope, &frozen)
                .expect("proof-bound canonical protocol encoding");
        protocol_encode.push(started.elapsed().as_nanos());

        let started = Instant::now();
        let decoded = decode_objective_function_v1(protocol.canonical_bytes())
            .expect("strict canonical protocol decode");
        protocol_decode.push(started.elapsed().as_nanos());

        warm_total.push(total_started.elapsed().as_nanos());
        black_box(decoded);
        black_box(protocol);
        black_box(proof_bearing);
    }

    let distribution = |values: Vec<u128>| {
        let (p50, p95, p99) = measured_percentiles(values);
        serde_json::json!({"p50": p50, "p95": p95, "p99": p99})
    };
    let key = frozen.reuse_key();
    println!(
        "OBJECTIVE_MEASUREMENT={}",
        serde_json::json!({
            "schema": "hepta.objective-target-measurement.v1",
            "path": "ordinary_authenticated_admission_compile",
            "samples": samples,
            "latencyNanoseconds": distribution(warm_total),
            "phaseLatencyNanoseconds": {
                "coldProfileValidation": distribution(cold_profile),
                "warmAuthenticatedAdmission": distribution(warm_admission),
                "nativeCompile": distribution(native_compile),
                "protocolEncode": distribution(protocol_encode),
                "protocolDecode": distribution(protocol_decode)
            },
            "staticProfileReuseKey": {
                "profileDigest": key.profile_digest.to_string(),
                "profileRevision": key.profile_revision,
                "compilerContractDigest": key.compiler_contract_digest.to_string()
            },
            "dynamicAuthorizationCached": false
        })
    );
}
'''
write(p, prefix + measurement_tail)

# Add observable product-boundary phases without pretending that the atomic
# append/checkpoint/handoff path can be split from outside its owner.
p = "codex-rs/hepta-agentd/tests/objective_product_e2e.rs"
marker = "async fn measurement_signed_objective_daemon_round_trip()"
replace_after(
    p,
    marker,
    '''    let mut execution_timings = Vec::with_capacity(execution_samples);
    let mut last_execution = None;''',
    '''    let mut execution_timings = Vec::with_capacity(execution_samples);
    let mut compiled_publication_timings = Vec::with_capacity(execution_samples);
    let mut context_attachment_timings = Vec::with_capacity(execution_samples);
    let mut final_use_terminal_timings = Vec::with_capacity(execution_samples);
    let mut last_execution = None;''',
)
replace_after(
    p,
    marker,
    '''        let started = Instant::now();
        let receipt = admitted(control.objective_start(request).await?)?;
        ensure!(receipt.disposition == "compiled");''',
    '''        let started = Instant::now();
        let publication_started = Instant::now();
        let receipt = admitted(control.objective_start(request).await?)?;
        compiled_publication_timings.push(publication_started.elapsed().as_nanos());
        ensure!(receipt.disposition == "compiled");''',
)
replace_after(
    p,
    marker,
    '''        let attached = control
            .run_attach_context(''',
    '''        let context_attachment_started = Instant::now();
        let attached = control
            .run_attach_context(''',
)
replace_after(
    p,
    marker,
    '''            )
            .await?;
        let binding = NativeIntelligenceRunBinding {''',
    '''            )
            .await?;
        context_attachment_timings.push(context_attachment_started.elapsed().as_nanos());
        let binding = NativeIntelligenceRunBinding {''',
)
replace_after(
    p,
    marker,
    '''        let output = driver
            .run_intelligence(''',
    '''        let final_use_terminal_started = Instant::now();
        let output = driver
            .run_intelligence(''',
)
replace_after(
    p,
    marker,
    '''        ensure!(terminal.phase == AgentRunPhase::Succeeded && terminal.terminal_observed);
        execution_timings.push(started.elapsed().as_nanos());''',
    '''        ensure!(terminal.phase == AgentRunPhase::Succeeded && terminal.terminal_observed);
        final_use_terminal_timings.push(final_use_terminal_started.elapsed().as_nanos());
        execution_timings.push(started.elapsed().as_nanos());''',
)
replace_after(
    p,
    marker,
    '''    let (p50, p95, p99) = measured_percentiles(timings)?;
    let (execution_p50, execution_p95, execution_p99) = measured_percentiles(execution_timings)?;
    println!(''',
    '''    let (p50, p95, p99) = measured_percentiles(timings)?;
    let (execution_p50, execution_p95, execution_p99) = measured_percentiles(execution_timings)?;
    let (compiled_publication_p50, compiled_publication_p95, compiled_publication_p99) =
        measured_percentiles(compiled_publication_timings)?;
    let (context_attachment_p50, context_attachment_p95, context_attachment_p99) =
        measured_percentiles(context_attachment_timings)?;
    let (final_use_terminal_p50, final_use_terminal_p95, final_use_terminal_p99) =
        measured_percentiles(final_use_terminal_timings)?;
    println!(''',
)
replace_after(
    p,
    marker,
    '''            "executionLatencyNanoseconds": {
                "p50": execution_p50,
                "p95": execution_p95,
                "p99": execution_p99
            },
            "executionExactReplayNanoseconds": execution_replay_ns,''',
    '''            "executionLatencyNanoseconds": {
                "p50": execution_p50,
                "p95": execution_p95,
                "p99": execution_p99
            },
            "phaseLatencyNanoseconds": {
                "signedIngressCompileDurableAppendCheckpointAndAgentdHandoff": {
                    "p50": p50,
                    "p95": p95,
                    "p99": p99
                },
                "compiledPublicationAndAgentdHandoff": {
                    "p50": compiled_publication_p50,
                    "p95": compiled_publication_p95,
                    "p99": compiled_publication_p99
                },
                "contextAttachment": {
                    "p50": context_attachment_p50,
                    "p95": context_attachment_p95,
                    "p99": context_attachment_p99
                },
                "currentFinalUseProviderAndTerminalObservation": {
                    "p50": final_use_terminal_p50,
                    "p95": final_use_terminal_p95,
                    "p99": final_use_terminal_p99
                }
            },
            "atomicOwnerBoundaryNotSplit": true,
            "executionExactReplayNanoseconds": execution_replay_ns,''',
)

# Target recorder: validate the new phases and report observed process-tree peak
# memory without claiming per-phase isolation.
p = "scripts/hepta-objective-target-measure.py"
replace(p, "import platform\n", "import platform\nimport resource\n")
replace(
    p,
    '''def parse_measurement(output: str, expected_path: str) -> dict[str, Any]:''',
    '''def latency_distribution(value: Any, field: str) -> dict[str, int]:
    if not isinstance(value, dict):
        fail(f"missing latency distribution for {field}")
    ordered = [value.get(key) for key in ("p50", "p95", "p99")]
    if not all(type(item) is int and item >= 0 for item in ordered):
        fail(f"invalid latency percentiles for {field}")
    if ordered != sorted(ordered):
        fail(f"non-monotone latency percentiles for {field}")
    return value


def observed_children_peak_resident_set_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    # Darwin reports bytes; Linux and BSD-compatible CI images report KiB.
    scale = 1 if platform.system() == "Darwin" else 1024
    return max(0, int(value) * scale)


def parse_measurement(output: str, expected_path: str) -> dict[str, Any]:''',
)
replace(
    p,
    '''    latency = value.get("latencyNanoseconds")
    if not isinstance(latency, dict):
        fail(f"missing latency distribution for {expected_path}")
    ordered = [latency.get(key) for key in ("p50", "p95", "p99")]
    if not all(type(item) is int and item >= 0 for item in ordered):
        fail(f"invalid latency percentiles for {expected_path}")
    if ordered != sorted(ordered):
        fail(f"non-monotone latency percentiles for {expected_path}")
    return value''',
    '''    latency_distribution(value.get("latencyNanoseconds"), expected_path)
    if expected_path == "ordinary_authenticated_admission_compile":
        phases = value.get("phaseLatencyNanoseconds")
        expected_phases = {
            "coldProfileValidation",
            "warmAuthenticatedAdmission",
            "nativeCompile",
            "protocolEncode",
            "protocolDecode",
        }
        if not isinstance(phases, dict) or set(phases) != expected_phases:
            fail("ordinary measurement phase set is incomplete")
        for name, distribution in phases.items():
            latency_distribution(distribution, f"ordinary.{name}")
        if value.get("dynamicAuthorizationCached") is not False:
            fail("ordinary measurement must state that dynamic authorization is not cached")
    return value''',
)
replace(
    p,
    '''    latency = value.get("latencyNanoseconds")
    if not isinstance(latency, dict):
        fail("missing product latency distribution")
    ordered = [latency.get(key) for key in ("p50", "p95", "p99")]
    if not all(type(item) is int and item >= 0 for item in ordered):
        fail("invalid product latency percentiles")
    if ordered != sorted(ordered):
        fail("non-monotone product latency percentiles")''',
    '''    latency_distribution(value.get("latencyNanoseconds"), "product")
    phases = value.get("phaseLatencyNanoseconds")
    expected_phases = {
        "signedIngressCompileDurableAppendCheckpointAndAgentdHandoff",
        "compiledPublicationAndAgentdHandoff",
        "contextAttachment",
        "currentFinalUseProviderAndTerminalObservation",
    }
    if not isinstance(phases, dict) or set(phases) != expected_phases:
        fail("product measurement phase set is incomplete")
    for name, distribution in phases.items():
        latency_distribution(distribution, f"product.{name}")
    if value.get("atomicOwnerBoundaryNotSplit") is not True:
        fail("product measurement must preserve the atomic owner boundary")''',
)
replace(
    p,
    '''    execution_latency = value.get("executionLatencyNanoseconds")
    if not isinstance(execution_latency, dict):
        fail("missing product execution latency distribution")
    execution_ordered = [execution_latency.get(key) for key in ("p50", "p95", "p99")]
    if not all(type(item) is int and item >= 0 for item in execution_ordered):
        fail("invalid product execution latency percentiles")
    if execution_ordered != sorted(execution_ordered):
        fail("non-monotone product execution latency percentiles")''',
    '''    latency_distribution(value.get("executionLatencyNanoseconds"), "product execution")''',
)
replace(
    p,
    '''    measurement["harnessWallNanoseconds"] = harness_ns
    return measurement''',
    '''    measurement["harnessWallNanoseconds"] = harness_ns
    measurement["observedChildrenPeakResidentSetBytes"] = (
        observed_children_peak_resident_set_bytes()
    )
    measurement["memoryObservationScope"] = (
        "cumulative process-tree peak through this fixture; not per-phase isolation"
    )
    return measurement''',
    count=2,
)
replace(
    p,
    '''        '"path":"ordinary_authenticated_admission_compile","samples":3,'
        '"latencyNanoseconds":{"p50":10,"p95":20,"p99":30}}'
    )''',
    '''        '"path":"ordinary_authenticated_admission_compile","samples":3,'
        '"latencyNanoseconds":{"p50":10,"p95":20,"p99":30},'
        '"phaseLatencyNanoseconds":{'
        '"coldProfileValidation":{"p50":1,"p95":2,"p99":3},'
        '"warmAuthenticatedAdmission":{"p50":1,"p95":2,"p99":3},'
        '"nativeCompile":{"p50":1,"p95":2,"p99":3},'
        '"protocolEncode":{"p50":1,"p95":2,"p99":3},'
        '"protocolDecode":{"p50":1,"p95":2,"p99":3}},'
        '"dynamicAuthorizationCached":false}'
    )''',
)
replace(
    p,
    '''        '"latencyNanoseconds":{"p50":100,"p95":200,"p99":300},'
        '"exactReplayNanoseconds":80,"executionSamples":2,''',
    '''        '"latencyNanoseconds":{"p50":100,"p95":200,"p99":300},'
        '"phaseLatencyNanoseconds":{'
        '"signedIngressCompileDurableAppendCheckpointAndAgentdHandoff":'
        '{"p50":100,"p95":200,"p99":300},'
        '"compiledPublicationAndAgentdHandoff":{"p50":10,"p95":20,"p99":30},'
        '"contextAttachment":{"p50":10,"p95":20,"p99":30},'
        '"currentFinalUseProviderAndTerminalObservation":'
        '{"p50":100,"p95":200,"p99":300}},'
        '"atomicOwnerBoundaryNotSplit":true,'
        '"exactReplayNanoseconds":80,"executionSamples":2,''',
)
replace(
    p,
    '''            "storageQualificationProved": False,
            "activationGranted": False,''',
    '''            "storageQualificationProved": False,
            "staticProfileReuseMeasuredSeparately": True,
            "dynamicAuthorizationCachingAllowed": False,
            "memoryIsObservedProcessTreePeakNotPhaseIsolation": True,
            "atomicAppendCheckpointHandoffBoundaryPreserved": True,
            "activationGranted": False,''',
)


print("objective_measurement_edit.py: applied")
