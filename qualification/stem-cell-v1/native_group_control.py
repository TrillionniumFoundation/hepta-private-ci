"""Online research continuation control; no labels, outcomes or production owner.

Forecast scenarios remain empirical claims. Native arithmetic is checked against
an independent integer oracle; neither execution nor hashing certifies support.
"""

import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
import time

from native_ndu_bridge import Q32, _integer, _sha, quantize_q32

SCHEMA = "hepta.ndu.group-control.v1"
RECEIPT_SCHEMA = "hepta.ndu.group-control-receipt.v1"
MAX_INPUT_BYTES = 16_384
BINDINGS = ("objective_sha256", "subject_sha256", "context_sha256", "model_sha256", "critic_sha256",
            "feature_sha256", "workspace_sha256", "policy_sha256", "support_sha256")
CONTEXT = ("generation", "as_of_ns", "critic_cutoff_ns", "observed_through_ns", "expires_at_ns",
           "stop_upper_q32", "minimum_margin_q32", "lower_q32", "upper_q32",
           "remaining_formula_work", "remaining_wall_ns")
SCENARIO = ("probability_q32", "continue_lower_q32", "discount_q32", "compute_cost_q32",
            "time_cost_q32", "formula_work_upper", "duration_upper_ns")


def _quantize_bound(value, direction):
    if type(value) not in (int, float) or (type(value) is float and not math.isfinite(value)):
        raise ValueError("finite bound required")
    numerator, denominator = value.as_integer_ratio()
    scaled = numerator * Q32
    raw = scaled // denominator if direction == "lower" else -((-scaled) // denominator)
    return _integer(raw)


def build_control_request(*, bindings, generation, as_of_ns, critic_cutoff_ns, observed_through_ns,
                          expires_at_ns, stop_upper, minimum_margin, scenarios,
                          remaining_formula_work, remaining_wall_ns, lower=-8, upper=8):
    """Freeze only observable inputs; scenarios contain seven declared fields.

    Scenario fields are probability, continue_lower, discount, compute_cost,
    time_cost, formula_work_upper, duration_upper_ns. Costs are future segment
    upper bounds in normalized utility units; current controller cost is sunk.
    The raw request format additionally supports exact Q32 probabilities.
    """
    if type(bindings) is not dict or set(bindings) != set(BINDINGS):
        raise ValueError("complete observable bindings required")
    if type(scenarios) not in (list, tuple) or not 1 <= len(scenarios) <= 16:
        raise ValueError("bounded scenarios required")
    if type(minimum_margin) not in (int, float) or not math.isfinite(minimum_margin) or minimum_margin < 0:
        raise ValueError("nonnegative finite margin required")
    frozen = []
    for scenario in scenarios:
        expected = {"probability", "continue_lower", "discount", "compute_cost", "time_cost",
                    "formula_work_upper", "duration_upper_ns"}
        if type(scenario) is not dict or set(scenario) != expected:
            raise ValueError("no target/outcome or unknown scenario fields allowed")
        for key in ("probability", "discount", "compute_cost", "time_cost"):
            value = scenario[key]
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError("nonnegative finite probability, discount and costs required")
        if scenario["probability"] > 1 or scenario["discount"] > 1:
            raise ValueError("probability and discount must not exceed one")
        forecast = _quantize_bound(scenario["continue_lower"], "lower")
        frozen.append(dict(probability_q32=quantize_q32(scenario["probability"]),
            continue_lower_q32=forecast,
            discount_q32=_quantize_bound(scenario["discount"], "lower" if forecast >= 0 else "upper"),
            compute_cost_q32=_quantize_bound(scenario["compute_cost"], "upper"),
            time_cost_q32=_quantize_bound(scenario["time_cost"], "upper"),
            formula_work_upper=scenario["formula_work_upper"], duration_upper_ns=scenario["duration_upper_ns"]))
    request = dict(schema=SCHEMA, bindings=dict(bindings), generation=generation, as_of_ns=as_of_ns,
        critic_cutoff_ns=critic_cutoff_ns, observed_through_ns=observed_through_ns, expires_at_ns=expires_at_ns,
        stop_upper_q32=_quantize_bound(stop_upper, "upper"), minimum_margin_q32=_quantize_bound(minimum_margin, "upper"),
        lower_q32=_quantize_bound(lower, "lower"), upper_q32=_quantize_bound(upper, "upper"),
        remaining_formula_work=remaining_formula_work, remaining_wall_ns=remaining_wall_ns, scenarios=frozen)
    validate_request(request)
    return request


def validate_request(request):
    if type(request) is not dict or set(request) != {"schema", "bindings", "scenarios", *CONTEXT} or request["schema"] != SCHEMA:
        raise ValueError("complete versioned observable request required")
    if type(request["bindings"]) is not dict or set(request["bindings"]) != set(BINDINGS):
        raise ValueError("fixed bindings required")
    for value in request["bindings"].values():
        _sha(value)
    for key in ("generation", "as_of_ns", "critic_cutoff_ns", "observed_through_ns", "expires_at_ns"):
        _integer(request[key], minimum=1, maximum=(1 << 64) - 1)
    if (request["critic_cutoff_ns"] >= request["as_of_ns"]
            or not request["critic_cutoff_ns"] <= request["observed_through_ns"] <= request["as_of_ns"] < request["expires_at_ns"]):
        raise ValueError("future or expired critic observations")
    lower, upper = (_integer(request[key]) for key in ("lower_q32", "upper_q32"))
    if not lower < upper or not lower <= 0 <= upper or not lower <= _integer(request["stop_upper_q32"]) <= upper:
        raise ValueError("invalid utility bounds")
    _integer(request["minimum_margin_q32"], minimum=0)
    for key in ("remaining_formula_work", "remaining_wall_ns"):
        _integer(request[key], minimum=0, maximum=(1 << 64) - 1)
    if type(request["scenarios"]) is not list or not 1 <= len(request["scenarios"]) <= 16:
        raise ValueError("bounded scenarios required")
    for scenario in request["scenarios"]:
        if type(scenario) is not dict or set(scenario) != set(SCENARIO):
            raise ValueError("complete scenario required")
        for key in ("probability_q32", "discount_q32"):
            _integer(scenario[key], minimum=0, maximum=Q32)
        if not lower <= _integer(scenario["continue_lower_q32"]) <= upper:
            raise ValueError("forecast outside bounds")
        for key in ("compute_cost_q32", "time_cost_q32"):
            _integer(scenario[key], minimum=0)
        cost = scenario["compute_cost_q32"] + scenario["time_cost_q32"]
        if cost > (1 << 63) - 1 or -cost < lower:
            raise ValueError("cost outside native instant domain")
        _integer(scenario["formula_work_upper"], minimum=0, maximum=(1 << 64) - 1)
        _integer(scenario["duration_upper_ns"], minimum=1, maximum=(1 << 64) - 1)
    if sum(s["probability_q32"] for s in request["scenarios"]) != Q32:
        raise ValueError("complete declared Q32 probability mass required")


def control_wire(request):
    validate_request(request)
    values = [request["bindings"][key] for key in BINDINGS] + [request[key] for key in CONTEXT]
    lines = [SCHEMA, "context " + " ".join(map(str, values))]
    lines += ["scenario " + " ".join(str(s[key]) for key in SCENARIO) for s in request["scenarios"]]
    payload = ("\n".join(lines) + "\n").encode("ascii")
    wire = payload + f"finish {hashlib.sha256(payload).hexdigest()}\n".encode("ascii")
    if len(wire) > MAX_INPUT_BYTES:
        raise ValueError("request byte ceiling exceeded")
    return wire


def reference_control_receipt(request):
    """Independent integer oracle including native evidence and floor guards."""
    wire = control_wire(request)
    input_digest = hashlib.sha256(wire[:wire.rfind(b"finish ")]).digest()
    episode = hashlib.sha256(b"hepta.ndu.group-control.episode.v1" + input_digest).digest()
    binding = request["bindings"]
    scenarios, numerator, projected, feasible = [], 0, False, True
    for index, scenario in enumerate(request["scenarios"]):
        cost = scenario["compute_cost_q32"] + scenario["time_cost_q32"]
        forecast, discount = scenario["continue_lower_q32"], scenario["discount_q32"]
        product = forecast * discount
        quotient, remainder = divmod(abs(product), Q32)
        quotient += remainder > Q32 // 2 or (remainder == Q32 // 2 and quotient % 2 == 1)
        raw = (-quotient if product < 0 else quotient) - cost
        native = min(max(raw, request["lower_q32"]), request["upper_q32"])
        projections = int(raw != native)
        conservative = product // Q32 - cost if projections == 0 else None
        evidence = bytearray(b"hepta.ndu.recursive-utility.scalar.q32.v1")
        identities = (bytes.fromhex(binding["objective_sha256"]), episode, bytes.fromhex(binding["policy_sha256"]),
            hashlib.sha256(b"hepta.ndu.group-control.normalized-utility.q32.v1").digest(),
            hashlib.sha256(b"hepta.ndu.group-control.arithmetic-zero-boundary.v1").digest())
        evidence.extend(b"".join(identities))
        evidence.extend(struct.pack(">qqqQ", 0, request["lower_q32"], request["upper_q32"], 2))
        for position, instant, factor in ((1, -cost, discount), (2, forecast, 0)):
            event = hashlib.sha256(b"hepta.ndu.group-control.event.v1" + input_digest + struct.pack(">QQ", index, position)).digest()
            evidence.extend(struct.pack(">Q", position) + event + bytes.fromhex(binding["support_sha256"]))
            evidence.extend(struct.pack(">qq", instant, factor))
        evidence.extend(struct.pack(">qqqI", native, forecast, 0, projections))
        probability = scenario["probability_q32"]
        if probability:
            projected |= conservative is None
            feasible &= (scenario["formula_work_upper"] <= request["remaining_formula_work"]
                         and scenario["duration_upper_ns"] < request["remaining_wall_ns"])
            numerator += probability * (conservative or 0)
        scenarios.append(dict(probability_q32=probability, native_value_q32=native,
            conservative_value_q32=conservative, projection_count=projections,
            evidence_sha256=hashlib.sha256(evidence).hexdigest()))
    expected = None if projected else numerator // Q32
    continues = not projected and feasible and expected > request["stop_upper_q32"] + request["minimum_margin_q32"]
    reason = ("scenario_projection_unsupported" if projected else "infeasible_continuation" if not feasible
              else "supported_net_gain" if continues else "no_supported_net_gain")
    return dict(schema=RECEIPT_SCHEMA, input_sha256=input_digest.hex(), expected_lower_q32=expected,
        stop_upper_q32=request["stop_upper_q32"], minimum_margin_q32=request["minimum_margin_q32"],
        continue_computation=continues, reason=reason, scenarios=scenarios,
        terminal_reference_role="arithmetic_zero_boundary_not_observed_outcome", support_certified=False,
        production_owner_integrated=False, general_fbsde_solved=False)


def _child_cpu_ns():
    try:
        import resource
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        return int((usage.ru_utime + usage.ru_stime) * 1e9)
    except (ImportError, AttributeError, OSError):
        return None


def run_native_control(request, binary, *, timeout_seconds=5, clock=time.time_ns):
    """Execute before future proposal; errors, stale inputs and overspend stop.

    Child CPU uses process-wide reaped-child counters and may include concurrent
    children; it is not an exclusive per-child attribution or ATen FLOP estimate.
    """
    started, cpu_before = time.perf_counter_ns(), _child_cpu_ns()
    report = dict(schema="hepta.ndu.group-control-execution.v1", continue_computation=False,
        reason="native_control_failed", native_receipt=None, native_binary_sha256=None,
        native_attempted=False, native_executed=False, reference_match=False, support_certified=False,
        production_owner_integrated=False, general_fbsde_solved=False,
        child_cpu_accounting="process_reaped_children_delta_may_include_concurrent_children",
        subprocess_work_in_aten_meter=False, child_wall_ns=0)
    try:
        wire = control_wire(request)
        report["input_sha256"] = hashlib.sha256(wire[:wire.rfind(b"finish ")]).hexdigest()
        before = clock()
        if type(before) is not int or not request["as_of_ns"] <= before < request["expires_at_ns"]:
            raise ValueError("stale control input")
        if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 60:
            raise ValueError("bounded subprocess timeout required")
        path = Path(binary)
        report["native_binary_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        report["native_attempted"] = True
        child_started = time.perf_counter_ns()
        try:
            completed = subprocess.run([str(path)], input=wire, capture_output=True,
                timeout=min(timeout_seconds, request["remaining_wall_ns"] / 1e9), check=True)
        finally:
            report["child_wall_ns"] = time.perf_counter_ns() - child_started
        report["native_executed"] = True
        if len(completed.stdout) > MAX_INPUT_BYTES:
            raise ValueError("native receipt byte ceiling exceeded")
        receipt = json.loads(completed.stdout)
        if json.dumps(receipt, sort_keys=True) != json.dumps(reference_control_receipt(request), sort_keys=True):
            raise ValueError("native receipt differs from bound exact oracle")
        if hashlib.sha256(path.read_bytes()).hexdigest() != report["native_binary_sha256"]:
            raise ValueError("binary changed during control call")
        report.update(native_receipt=receipt, reference_match=True,
                      continue_computation=receipt["continue_computation"], reason=receipt["reason"])
        after = clock()
        if type(after) is not int or not before <= after < request["expires_at_ns"]:
            report.update(continue_computation=False, reason="expired_during_native_control")
        elapsed = time.perf_counter_ns() - started
        remaining = request["remaining_wall_ns"] - elapsed
        if any(s["probability_q32"] and s["duration_upper_ns"] >= remaining for s in request["scenarios"]):
            report.update(continue_computation=False, reason="insufficient_wall_after_native_control")
    except (ValueError, TypeError, OverflowError, OSError, subprocess.SubprocessError) as error:
        report.update(continue_computation=False, reason="native_control_failed", error_type=type(error).__name__)
    finally:
        cpu_after = _child_cpu_ns()
        report["child_cpu_ns"] = None if cpu_before is None or cpu_after is None else max(0, cpu_after - cpu_before)
        report["native_subprocess_elapsed_ns"] = time.perf_counter_ns() - started
    return report
