"""Independent task, causal-access, recovery and intervention audits.

This module does not import the task executor, model inference or transition
helpers. Native subprocesses choose their own actions; an audit never supplies
an action override. Deliberately constructed policies are labelled interventions.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import resource
import shutil
import struct
import subprocess
import time

import numpy as np
from scipy.linalg import expm
from scipy.special import expit


ACTIONS = ("STOP", "SKIP", "READ", "FIRE")


def require(condition, reason):
    if not condition:
        raise AssertionError(reason)


def close(actual, expected, reason, atol=2e-9):
    require(np.shape(actual) == np.shape(expected)
            and np.allclose(actual, expected, atol=atol, rtol=2e-10), reason)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def legal(meta, state):
    active = not state["terminal"] and state["job"] < 2 and state["tick"] < meta["deadline"]
    later = active and state["tick"] + 1 < meta["deadline"]
    return [not state["terminal"], bool(later), bool(later and state["budget"] > 0), bool(active)]


def public_features(meta, state, policy):
    """Rebuild the 62 contractual coordinates without the feature encoder."""
    n = meta["deadline"]
    reliability, prices, durations = np.zeros((2, 10)), np.zeros((2, 10)), np.zeros(10)
    reliability[:, :n], prices[:, :n] = meta["reliability"], meta["price"]
    durations[:n] = meta["duration"]
    return np.r_[[state["job"], state["tick"], state["budget"], state["posterior"],
                  n, meta["budget"], policy["multiplier"], policy["latency_price"]],
                 reliability.ravel(), prices.ravel(), durations, np.asarray(policy["confusion"]).ravel()]


def physical(theta, driver):
    """Independent scalar construction of the declared five-state model."""
    v = expit(theta)
    mu = .1 + .8 * expit(theta[0] + theta[1] * driver)
    sigma, boundary = .25 + .25 * v[2], .8 + .4 * v[3]
    reset, refractory = -.3 + .2 * v[4], .3 + .5 * v[5]
    width = (boundary + 1) / 3
    location = (reset + 1) / width - .5
    require(0 <= location <= 1, "reset left the declared interpolation cell")
    origin = np.array([1-location, location, 0., 0., 0.])
    down, up = sigma**2/(2*width**2), sigma**2/(2*width**2) + mu/width
    rate = 2/refractory
    matrix = np.zeros((5, 5))
    for source, target, weight in ((0, 1, up), (1, 0, down), (1, 2, up),
                                    (2, 1, down), (2, 4, up), (4, 3, rate),
                                    (3, 0, rate*(1-location)), (3, 1, rate*location)):
        matrix[source, target] += weight
        matrix[source, source] -= weight
    return matrix, origin, up


def independent_state(policy, history):
    """Unconditional finite state and cumulative events, including task resets."""
    theta = np.asarray(policy["parameters"], float)
    ordinary = policy["family"] == "ordinary"
    state = np.array([.5, .5]) if ordinary else physical(theta, 0.)[1]
    events = 0.
    for interval in history:
        d, duration = interval["driver"], interval["duration"]
        if ordinary:
            rate = np.logaddexp(0., theta[:6].reshape(2, 3) @ [1., d, d*d])
            retention = np.exp(-rate*duration)
            state = retention*state + (1-retention)*np.array([expit(2*d), d*d])
        else:
            matrix, _, rate = physical(theta, d)
            integral = np.zeros((6, 6))
            integral[:5, :5], integral[2, 5] = matrix, rate
            transition = expm(duration*integral)
            events += float(state @ transition[:5, 5])
            state = state @ transition[:5, :5]
        if interval["reset"]:
            state = np.array([.5, .5]) if ordinary else physical(theta, 0.)[1]
    return state, events


def independent_features(policy, history, driver, horizon):
    """Replay earlier public intervals; query cannot consume the next packet."""
    theta = np.asarray(policy["parameters"], float)
    ordinary = policy["family"] == "ordinary"
    state, _ = independent_state(policy, history)
    if ordinary:
        rate = np.logaddexp(0., theta[:6].reshape(2, 3) @ [1., driver, driver*driver])
        raw = np.r_[state, -np.expm1(-rate*horizon)]
    else:
        matrix, _, event_rate = physical(theta, driver)
        integral = np.zeros((6, 6))
        integral[:5, :5], integral[2, 5] = matrix, event_rate
        count = float(state @ expm(horizon*integral)[:5, 5])
        killed = matrix.copy()
        killed[2, 4] = 0.
        hit = float(1-state @ expm(horizon*killed) @ np.ones(5))
        raw = np.array([state[:3] @ [1/6, .5, 5/6], state[3:].sum(), count/(1+count), hit])
    return np.r_[raw, expit(raw @ theta[6:10] + theta[10])]


def independent_choice(meta, state, policy, history):
    allowed = legal(meta, state)
    features = public_features(meta, state, policy)
    driver = .8*(2*state["posterior"]-1) + .2*(2*meta["reliability"][state["job"]][state["tick"]]-1)
    horizon = meta["duration"][state["tick"]]
    if policy["controller"] == "fixed":
        action = (3 if allowed[3] and (max(state["posterior"], 1-state["posterior"])
                  >= policy["fixed_boundary"] or not allowed[2]) else 2 if allowed[2] else 0)
        return ACTIONS[action], features, None, None, driver, horizon
    cell = independent_features(policy, history, driver, horizon)
    x = (np.r_[features, cell] - policy["norm"]["mean"]) / policy["norm"]["scale"]
    weights = {k: np.asarray(v) for k, v in policy["weights"].items()}
    q = np.tanh(x @ weights["w"] + weights["b"]) @ weights["v"] + weights["c"]
    action = int(np.argmax(np.where(allowed, q, -np.inf)))
    return ACTIONS[action], features, cell, q, driver, horizon


def expected_transition(meta, before, policy, action, observation=None, failed=False):
    """Scalar independent task transition; no content/model/executor calls."""
    require(action in ACTIONS and legal(meta, before)[ACTIONS.index(action)], "illegal native action")
    state = copy.deepcopy(before)
    job, tick = before["job"], before["tick"]
    slots = 0 if action == "STOP" else 2 if action == "FIRE" else 1
    duration = sum(meta["duration"][tick:min(tick+slots, meta["deadline"])])
    state["task_elapsed"] += duration
    state["latency_cost"] += policy["latency_price"] * duration
    if action == "STOP":
        state["terminal"] = True
    elif action == "SKIP":
        state["tick"] += 1
    elif action == "READ":
        state["query_cost"] += policy["multiplier"] * meta["price"][job][tick]
        if failed:
            state["terminal"] = True
        else:
            require(observation in (0, 1), "successful READ needs one decoded observation")
            c = np.asarray(policy["confusion"])
            r, p = meta["reliability"][job][tick], before["posterior"]
            negative = r*c[0, observation] + (1-r)*c[1, observation]
            positive = r*c[1, observation] + (1-r)*c[0, observation]
            state["posterior"] = p*positive / (p*positive + (1-p)*negative)
            state["tick"] += 1
            state["budget"] -= 1
            state["reads_in_job"] += 1
    else:
        state["answers"].append(dict(job=job, prediction=int(before["posterior"] >= .5),
            posterior=before["posterior"], tick=tick, reads=before["reads_in_job"]))
        state["job"], state["tick"] = job+1, tick+2
        state["posterior"], state["reads_in_job"] = .5, 0
    state["charged_cost"] = state["query_cost"] + state["latency_cost"]
    state["terminal"] = state["terminal"] or state["job"] >= 2 or state["tick"] >= meta["deadline"]
    return state, duration


def intervention_gate(left, right):
    """A latent-only change cannot establish a task/content-control effect.

    These inputs are audit summaries, not user-supplied policy observations.
    A positive causal witness is not a statistical utility/quality certificate.
    """
    latent_changed = not np.allclose(left["cell_features"], right["cell_features"], atol=1e-10, rtol=1e-10)
    flow_changed = left["read_trace"] != right["read_trace"]
    successor_changed = left["task_trace"] != right["task_trace"]
    return dict(latent_changed=bool(latent_changed), actual_read_flow_changed=flow_changed,
                task_successor_changed=successor_changed,
                causal_content_gate=bool(latent_changed and flow_changed and successor_changed),
                utility_gain_proved=False,
                reason="Latent changes without changed real READ flow fail the content gate.")


class NativeRunner:
    """Launch a fresh process for every request and retain its complete output."""
    def __init__(self, binary, content, public, policy, snapshot, evidence):
        self.binary, self.content = Path(binary).resolve(), Path(content).resolve()
        self.public, self.policy = Path(public).resolve(), Path(policy).resolve()
        self.snapshot, self.evidence = Path(snapshot).resolve(), Path(evidence).resolve()
        self.invocations = []

    def run(self, steps, ack=None, expect_rejection=False):
        model = json.loads(self.policy.read_text())
        command = [str(self.binary), "--public", str(self.public), "--content-model", str(self.content),
                   "--policy", str(self.policy), "--family", model["family"],
                   "--controller", model["controller"], "--steps", str(steps),
                   "--snapshot", str(self.snapshot)]
        if ack is not None:
            command += ["--ack", ack]
        prior_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        started = time.perf_counter()
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate(timeout=120)
        process_wall = time.perf_counter()-started
        after_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        process_cpu = after_usage.ru_utime+after_usage.ru_stime-prior_usage.ru_utime-prior_usage.ru_stime
        native_output = json.loads(stdout) if stdout.strip() else {}
        receipt = dict(argv=command, pid=process.pid, exit_code=process.returncode,
                       stdout=stdout, stderr=stderr, requested_steps=steps,
                       process_cpu_seconds=process_cpu, process_wall_seconds=process_wall,
                       native_owner_load_nanos=native_output.get("load_nanos"),
                       native_artifact_load_nanos=native_output.get("artifact_load_nanos"),
                       native_action_stage_costs=[r["stage_costs"] for r in native_output.get("receipts", [])],
                       cost_scope="CPU is child-process user+system, including startup/loading/I/O/commit/exit; wall includes process launch and IPC; audit parsing/hashing is outside timing.",
                       policy_file_sha256=digest(self.policy), public_file_sha256=digest(self.public),
                       content_model_file_sha256=digest(self.content))
        path = self.evidence / f"process_{len(self.invocations):03d}.json"
        write(path, receipt)
        self.invocations.append(receipt)
        if expect_rejection:
            require(process.returncode != 0, "changed identity must be rejected")
            rejection = json.loads(stdout)
            reason = rejection.get("error", "")
            require("identity" in reason or "acknowledged" in reason,
                    "rejection was not caused by the challenged identity: " + reason)
            return receipt
        require(process.returncode == 0, "native execution failed: " + (stderr or stdout)[-1000:])
        return json.loads(stdout)


def constant_policy(policy, action):
    """Explicit model intervention; never an owner-action command."""
    result = copy.deepcopy(policy)
    result["controller"] = "value"
    result["weights"] = {key: np.zeros_like(value, dtype=float).tolist()
                         for key, value in result["weights"].items()}
    result["weights"]["c"][ACTIONS.index(action)] = 10.
    return result


def semantic_state(state):
    keys = ("job", "tick", "budget", "posterior", "terminal", "reads_in_job", "charged_cost",
            "query_cost", "latency_cost", "task_elapsed", "answers")
    return {key: state[key] for key in keys}


def process_costs(runner):
    rows = runner.invocations
    artifact = [row["native_artifact_load_nanos"] for row in rows]
    owner = [row["native_owner_load_nanos"] for row in rows]
    return dict(processes=len(rows), cpu_seconds=sum(row["process_cpu_seconds"] for row in rows),
                wall_seconds=sum(row["process_wall_seconds"] for row in rows),
                owner_load_seconds=(sum(owner)/1e9 if all(x is not None for x in owner) else None),
                artifact_load_seconds=(sum(artifact)/1e9 if all(x is not None for x in artifact) else None),
                energy_joules=None)


def compare_state(actual, expected):
    for key, value in semantic_state(expected).items():
        if isinstance(value, (float, int)) and not isinstance(value, bool):
            close(actual[key], value, "task successor mismatch: " + key)
        else:
            require(actual[key] == value, "task successor mismatch: " + key)


def task_state(value):
    return value["task"] if "task" in value else value


def causal_history(meta, state):
    return [dict(driver=.8*(2*event["posterior_before"]-1)
                        + .2*(2*meta["reliability"][event["job"]][event["tick"]]-1),
                 duration=event["duration"], reset=event["action"] == "FIRE")
            for event in state["history"]]


def audit_result(result, meta, policy):
    """Recompute each choice and successor solely from its public prefix."""
    require(result["production_activation"] is False and result["authority"] == "DENY_ALL",
            "research owner must retain its authority boundary")
    require(result["native_neuron_runtime"] is True, "owner did not execute the native neuron runtime")
    previous = task_state(result["start"])
    checks = []
    for receipt in result["receipts"]:
        before, after = task_state(receipt["before"]), task_state(receipt["after"])
        compare_state(before, previous)
        require(before["counts"] == previous["counts"] and before["history"] == previous["history"],
                "receipt prefix is not the previous acknowledged state")
        action, public, cell, q, driver, horizon = independent_choice(meta, before, policy, causal_history(meta, before))
        require(receipt["action"] == action and receipt["legal"] == legal(meta, before),
                "native action must equal independent legal frozen-policy choice")
        close(receipt["public_features"], public, "public decision features differ")
        close(receipt["driver"], driver, "driver must precede the current observation")
        close(receipt["horizon_micros"], horizon*1e6, "forecast clock differs", atol=1e-6)
        if policy["controller"] == "fixed":
            require(receipt["q"] is None and receipt["cell_features"] is None,
                    "fixed control must not evaluate an unused critic or forecast")
        else:
            close(receipt["cell_features"], cell, "independent cell forecast differs")
            close(receipt["q"], q, "independent critic differs")
        event = receipt["event"]
        require(event["action"] == action and event["job"] == before["job"]
                and event["tick"] == before["tick"] and event["budget_before"] == before["budget"],
                "read receipt is not bound to the pre-decision task")
        close(event["posterior_before"], before["posterior"], "event posterior is not pre-action")
        failed = event["error"] is not None
        require(not failed or action == "READ", "only READ can have a content failure")
        expected, duration = expected_transition(meta, before, policy, action, event["observation"], failed)
        compare_state(after, expected)
        close(event["duration"], duration, "action duration differs")
        close(event["query_charge"], expected["query_cost"]-before["query_cost"], "query charge differs")
        close(event["latency_charge"], expected["latency_cost"]-before["latency_cost"], "latency charge differs")
        counts = copy.deepcopy(before["counts"])
        counts[action] += 1
        if action == "READ" and not failed:
            counts["content_invocations"] += 1
            counts["packet_file_reads"] += 1
            counts["payload_bytes"] += event["payload_bytes"]
            require(event["payload_sha256"] == meta["packet_sha256"][before["job"]][before["tick"]],
                    "successful READ must bind the actual declared packet")
        else:
            require(event["observation"] is None and event["payload_sha256"] is None
                    and event["payload_bytes"] == 0, "non-completed READ cannot reveal content")
            if failed:
                counts["failed_read_attempts"] += 1
        require(after["counts"] == counts, "completed/failed access counts differ")
        require(after["history"] == before["history"]+[event], "acknowledged history must append exactly once")
        require(after["elapsed_micros"] == before["elapsed_micros"]+round(duration*1e6), "physical task clock differs")
        require(after["in_flight"] is None and after["pending_observation"] is None
                and after["recovery_ticks_remaining"] == 0, "acknowledged action is incomplete")
        previous = after
        checks.append(dict(action=action, failed_read=failed, before_tick=before["tick"],
                           after_tick=after["tick"], real_decodes=after["counts"]["content_invocations"]))
    compare_state(task_state(result["end"]), previous)
    require(task_state(result["end"])["counts"] == previous["counts"], "final counts differ")
    cell_snapshot = result["end"]["cell"]
    state, events = independent_state(policy, causal_history(meta, previous))
    bit_key = "gates_bits" if policy["family"] == "ordinary" else "probability_bits"
    unpack = lambda bits: struct.unpack(">d", int(bits, 16).to_bytes(8, "big"))[0]
    close([unpack(bits) for bits in cell_snapshot[bit_key]], state, "acknowledged cell state differs")
    close(unpack(cell_snapshot["event_count_bits"]), events, "cumulative latent events differ")
    require(cell_snapshot["elapsed_micros"] == previous["elapsed_micros"]
            and cell_snapshot["sequence"] == len(previous["history"]), "cell/task clocks or sequences differ")
    require(result["end"]["content"]["completed_reads"] == previous["counts"]["content_invocations"],
            "content checkpoint and task counters differ")
    return checks


def intervention_summary(result):
    require(len(result["receipts"]) == 1, "boundary witness compares exactly one common prefix")
    receipt = result["receipts"][0]
    event = receipt["event"]
    reads = ([dict(job=event["job"], tick=event["tick"], payload_sha256=event["payload_sha256"])]
             if event["action"] == "READ" and event["error"] is None else [])
    return dict(cell_features=receipt["cell_features"], read_trace=reads,
                task_trace=[semantic_state(task_state(receipt["after"]))])


def audit_suite(binary, content, public, policy_path, output):
    """Real native witnesses on a development fixture, not an efficacy trial."""
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    public, policy_path, content = Path(public).resolve(), Path(policy_path).resolve(), Path(content).resolve()
    meta, policy = json.loads(public.read_text()), json.loads(policy_path.read_text())
    require(meta["deadline"] >= 2 and meta["budget"] > 0, "audit fixture must permit all four initial actions")
    inputs = dict(binary_sha256=digest(binary), content_sha256=digest(content), public_sha256=digest(public),
                  policy_sha256=digest(policy_path), audit_source_sha256=digest(__file__))
    write(output/"INPUTS.json", inputs)
    with (output/"AUDIT_SOURCE.py").open("xb") as stream:
        stream.write(Path(__file__).read_bytes())
    findings, all_processes = {}, []

    def case(name, model, mutation=None):
        folder = output/name
        session = folder/"session"
        session.mkdir(parents=True)
        shutil.copyfile(public, session/"public.json")
        for row in meta["packets"]:
            for name in row:
                source = public.parent/name
                if source.exists():
                    shutil.copyfile(source, session/name)
        # Invalid labels deliberately cannot be used by native execution.
        (session/"evaluator_labels.json").write_text("audit: labels are not native inputs\n")
        if mutation:
            mutation(session)
        model_path = folder/"policy.json"
        write(model_path, model)
        write(folder/"INTERVENTION.json", dict(source_policy_sha256=inputs["policy_sha256"],
            intervention_policy_sha256=digest(model_path), fresh_initial_prefix=True,
            checkpoint_policy_rebound=False, efficacy_evidence=False))
        runner = NativeRunner(binary, content, session/"public.json", model_path, folder/"state.json", folder/"processes")
        all_processes.append(runner)
        return runner

    def checked(runner, steps, model, ack=None):
        result = runner.run(steps, ack)
        require(result["policy_sha256"] == digest(runner.policy)
                and result["public_sha256"] == digest(runner.public)
                and result["content_model_sha256"] == digest(runner.content),
                "native output identities do not bind exact input bytes")
        require(result["external_ack_verified"] == (ack is not None),
                "external acknowledgement claim differs from the actual request")
        audit_result(result, meta, model)
        if runner.snapshot.exists():
            require(digest(runner.snapshot) == result["acknowledged_sha256"], "snapshot bytes differ from native acknowledgement")
        return result

    def missing(session):
        for name in session.glob("job*_tick*.json"):
            name.unlink()
        (session/"evaluator_labels.json").unlink()

    for family in ("ordinary", "distribution"):
        family_policy = dict(policy, family=family)
        actions = {}
        for action in ACTIONS:
            model = constant_policy(family_policy, action)
            runner = case(f"actions_{family}_{action}", model)
            inspect = checked(runner, 0, model)
            require(not inspect["receipts"] and task_state(inspect["end"])["counts"]["content_invocations"] == 0,
                    "inspection must neither act nor decode")
            result = checked(runner, 1, model, inspect.get("acknowledged_sha256"))
            require(result["receipts"][0]["action"] == action, "constant-critic native witness took the wrong action")
            actions[action] = semantic_state(task_state(result["end"]))
        findings["four_actions_"+family] = actions

    for action in ("SKIP", "STOP"):
        model = constant_policy(policy, action)
        ordinary = checked(case("present_"+action, model), 1, model)
        absent = checked(case("missing_"+action, model, missing), 1, model)
        compare_state(task_state(absent["end"]), task_state(ordinary["end"]))
        close(absent["receipts"][0]["q"], ordinary["receipts"][0]["q"], "unread files changed a pre-read decision")
        findings["missing_unread_"+action] = True

    model = constant_policy(policy, "READ")
    failed_runner = case("failed_read", model, missing)
    failure = checked(failed_runner, 1, model)
    require(failure["receipts"][0]["event"]["error"] is not None, "missing actual READ must fail")
    recovered = checked(failed_runner, 0, model, failure["acknowledged_sha256"])
    compare_state(task_state(recovered["end"]), task_state(failure["end"]))
    findings["failed_read_cost_persisted"] = semantic_state(task_state(recovered["end"]))
    findings["failed_read_process_costs"] = [
        {key: row[key] for key in ("pid", "process_cpu_seconds", "process_wall_seconds",
         "native_owner_load_nanos", "native_artifact_load_nanos", "native_action_stage_costs")}
        for row in failed_runner.invocations]

    # A nonconstant frozen critic, unlike the forced action witnesses, also has
    # to produce the same pre-read values when hidden payloads are changed.
    probe = dict(policy, controller="value")
    original = checked(case("causal_original", probe), 1, probe)

    def replace_unread(session):
        (session/meta["packets"][0][0]).write_text("a changed, undeclared unread packet\n")
        (session/"evaluator_labels.json").unlink()

    altered = checked(case("causal_altered", probe, replace_unread), 1, probe)
    for key in ("action", "legal", "public_features", "cell_features", "q", "driver", "horizon_micros"):
        left, right = original["receipts"][0][key], altered["receipts"][0][key]
        if isinstance(left, (list, float, int)):
            close(left, right, "hidden packet changed decision field " + key)
        else:
            require(left == right, "hidden packet changed decision field " + key)
    findings["nonconstant_pre_read_causality"] = True

    for family in ("ordinary", "distribution"):
        model = dict(policy, family=family, controller="fixed")
        continuous_runner = case("continuous_"+family, model)
        complete = checked(continuous_runner, 32, model)
        runner = case("restarted_"+family, model)
        ack, results = None, []
        for _ in range(32):
            result = checked(runner, 1, model, ack)
            ack = result["acknowledged_sha256"]
            results.append(result)
            if task_state(result["end"])["terminal"]:
                break
        require(len(results) >= 2 and len({r["pid"] for r in runner.invocations}) == len(results),
                "recovery requires distinct real process invocations")
        require(task_state(results[-1]["end"])["terminal"], "restarted run did not terminate")
        compare_state(task_state(results[-1]["end"]), task_state(complete["end"]))
        require(task_state(results[-1]["end"])["counts"] == task_state(complete["end"])["counts"],
                "restart duplicated or omitted completed I/O")
        require(task_state(results[-1]["end"])["history"] == task_state(complete["end"])["history"],
                "restart changed observations, actions or sunk costs")
        require(results[-1]["end"]["cell"] == complete["end"]["cell"]
                and results[-1]["end"]["content"] == complete["end"]["content"],
                "restart changed exact cell/content checkpoint bits")
        continuous_cost, recovery_cost = process_costs(continuous_runner), process_costs(runner)
        findings["true_process_restore_"+family] = dict(processes=len(results),
            pids=[r["pid"] for r in runner.invocations], final=semantic_state(task_state(results[-1]["end"])),
            continuous_cost=continuous_cost, recovery_cost=recovery_cost,
            overhead_cpu_seconds=recovery_cost["cpu_seconds"]-continuous_cost["cpu_seconds"],
            overhead_wall_seconds=recovery_cost["wall_seconds"]-continuous_cost["wall_seconds"],
            scope="One paired development fixture, not a performance confidence interval; includes all process startup and recovery work.")

        checkpoint_files = lambda: {str(p): digest(p) for p in runner.snapshot.parent.glob(runner.snapshot.name+"*") if p.is_file()}
        bound = checkpoint_files()
        original_policy, original_public, original_content = runner.policy, runner.public, runner.content
        changed_policy = copy.deepcopy(model)
        changed_policy["weights"]["c"][0] += .123
        alternate = runner.snapshot.parent/"changed_policy.json"
        write(alternate, changed_policy)
        runner.policy = alternate
        runner.run(0, ack, expect_rejection=True)
        runner.policy = original_policy
        alternate = runner.snapshot.parent/"changed_public.json"
        changed_public = copy.deepcopy(meta)
        changed_public["price"][0][0] += .001
        write(alternate, changed_public)
        runner.public = alternate
        runner.run(0, ack, expect_rejection=True)
        runner.public = original_public
        alternate = runner.snapshot.parent/"changed_content.json"
        alternate.write_bytes(content.read_bytes()+b"\n")
        runner.content = alternate
        runner.run(0, ack, expect_rejection=True)
        runner.content = original_content
        runner.run(0, "0"*64, expect_rejection=True)
        require(checkpoint_files() == bound, "identity rejection must not mutate the acknowledged checkpoint")
        findings["identity_rejections_"+family] = ["policy", "public", "content", "external_ack"]

    # Explicit positive and negative mechanism controls: neither is a learned
    # efficacy result, and neither changes a policy hidden inside a checkpoint.
    boundaries = []
    for value in (-3., 3.):
        model = constant_policy(dict(policy, family="distribution"), "READ")
        model["parameters"][3] = value
        boundaries.append(model)
    negative = [checked(case(f"latent_only_{i}", model), 1, model) for i, model in enumerate(boundaries)]
    gate = intervention_gate(*(intervention_summary(result) for result in negative))
    require(gate["latent_changed"] and not gate["causal_content_gate"], "latent-only intervention was misclassified")
    findings["latent_only_negative_control"] = gate
    hits = [result["receipts"][0]["cell_features"][3] for result in negative]
    require(abs(hits[0]-hits[1]) > 1e-10, "development boundary fixture has no resolvable first-hit contrast")
    coefficient, center = 2/abs(hits[0]-hits[1]), sum(hits)/2
    positive = []
    for i, model in enumerate(boundaries):
        model["norm"] = dict(mean=[0.]*67, scale=[1.]*67)
        model["weights"]["w"][65][0] = coefficient
        model["weights"]["b"][0] = -coefficient*center
        model["weights"]["v"][0][2] = 1.
        model["weights"]["c"] = [-2., 0., 0., -2.]
        positive.append(checked(case(f"constructed_boundary_sensitive_{i}", model), 1, model))
    gate = intervention_gate(*(intervention_summary(result) for result in positive))
    require(gate["causal_content_gate"], "constructed boundary-sensitive policy failed to gate actual content")
    findings["constructed_sensitivity_witness"] = dict(gate, trained_policy=False, development_fixture_only=True)
    report = dict(schema="hcsn.native-loop.independent-audit.v1", audit_integrity_passed=True,
        inputs=inputs, findings=findings, native_invocations=sum(len(r.invocations) for r in all_processes),
        scientific_efficacy_proved=False, continuous_diffusion_qualified=False,
        complete_audit_process_costs=dict(cpu_seconds=sum(process_costs(r)["cpu_seconds"] for r in all_processes),
            wall_seconds=sum(process_costs(r)["wall_seconds"] for r in all_processes), energy_joules=None,
            scope="All native invocations, including inspection, failure and rejection probes; audit Python/setup and independent solver CPU are additional research costs."),
        recovery_scope="Acknowledged complete actions, distinct processes, externally supplied acknowledgement",
        source_scope="Independent task/feature/CTMC/critic arithmetic; actual content is executed by native owner")
    write(output/"REPORT.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "content_model", "public", "policy", "output"):
        parser.add_argument("--"+name.replace("_", "-"), type=Path, required=True)
    args = parser.parse_args()
    try:
        report = audit_suite(args.binary, args.content_model, args.public, args.policy, args.output)
    except Exception as error:
        if args.output.is_dir() and not (args.output/"FAILURE.json").exists():
            write(args.output/"FAILURE.json", dict(audit_integrity_passed=False,
                error_type=type(error).__name__, error=str(error),
                scope="Original native stdout/stderr and process identities remain in each case directory."))
        raise
    print(json.dumps(dict(audit_integrity_passed=report["audit_integrity_passed"],
                         native_invocations=report["native_invocations"], report=str(args.output/"REPORT.json"))))


if __name__ == "__main__":
    main()
