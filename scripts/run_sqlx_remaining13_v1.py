"""A proposed separate engineering admission for the unissued SQLx native work.

This alternative is never selected or authorized by the strict V1 inputs.
Only an explicit new Root policy receipt may consume the actual parser
semantic pass while permanently preserving its thirteen-second bounded FAIL.

The original 7160 scope stays failed. Its full 442-second debit and original
phase records remain in the ledger. This scope never repeats its metadata,
consumer check, scalar check, negative check, or dependency graph generation.
A fresh native executable build is required: no old target cache was retained.
"""

from contextlib import contextmanager
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import resource
import signal
import stat
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
SPEC = "scripts/hepta_sqlx_remaining13_inputs_v1.json"
BRANCH = "fix/hepta-sqlx-remaining13-20261127-7c9e"
BASE_BRANCH = "fix/hepta-sdk-oauth-schema-generation-20261126-7c9e"
PARENT = "3ab4e1dc379be6f1a19a35c7ba17200eb93b8b48"
PARENT_TREE = "9fd93745d55aa89b9a40f61c530fe9291bdced72"
ORIGINAL_HEAD = "df1a177bdc4f3b18466604cd6dcfb704e72acae9"
ORIGINAL_WORKSPACE = "/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs"
ORIGINAL_NATIVE = "scripts/run_sqlx_native12_plus3_v2.py"
ORIGINAL_NATIVE_SHA256 = (
    "c17d0439d614d2fd28e8a3e0f5fc05cc51ba5557904a79aa29f4b6cc9ebc1fba"
)
PROTOCOL = "scripts/hepta_sqlx_native_protocol_v2.py"
PROTOCOL_SHA256 = "8321e6e0c0bcaa2833832a5fdcf7ad0f44cb06e07801d0f582ebd258ba7a42d4"
LEGACY = "scripts/run_sqlx_temporal_contract_v1.py"
LEGACY_SHA256 = "a8636cd8490a011ac1c39a603e637bf0d1bdb56c38b34843a676193efddae4ab"
TOOLS = "scripts/hepta_sqlx_native_tools_v2.py"
TOOLS_SHA256 = "2171a16ac465ce827ca8926504236d1c5810c4a67f0bb75d56c25487da6b38a8"
GENERATION = "qualification/sqlx_native_generation_acceptance_v2.json"
ADMISSION = "qualification/sqlx_native_remaining_v1/admission_v1.json"
PRIOR = "qualification/sqlx_native_remaining_v1/prior7160_observations_v1.json"
PARTS = [
    "qualification/sqlx_native_remaining_v1/original-consumer-metadata.part1.utf8",
    "qualification/sqlx_native_remaining_v1/original-consumer-metadata.part2.utf8",
]
RECEIPTS = {
    GENERATION: "generation_acceptance_pin",
    ADMISSION: "remaining_admission_pin",
    PRIOR: "prior_observations_pin",
}
DELTA_PATHS = sorted(
    [
        LEGACY,
        "scripts/run_sqlx_remaining13_v1.py",
        SPEC,
        ".github/workflows/hepta-sqlx-remaining13-v1.yml",
        ADMISSION,
        PRIOR,
        *PARTS,
    ]
)
NEW_SOURCE_NAMES = {
    "scripts/run_sqlx_remaining13_v1.py",
    ".github/workflows/hepta-sqlx-remaining13-v1.yml",
    *PARTS,
}
ORIGINAL_PHASES = {
    "official_cargo": 1.8315954860000119,
    "metadata": 7.438256973999998,
    "compile": 407.71834971800007,
    "native": 0,
    "verification": 0.4603559159999264,
}
ORIGINAL_BUDGET = {
    "whole_job_seconds": 3600,
    "checkout_seconds": 120,
    "tool_install_seconds": 360,
    "owner_seconds": 2880,
    "retention_seconds": 240,
    "phases": {
        "official_cargo": 120,
        "metadata": 120,
        "compile": 2040,
        "native": 480,
        "verification": 120,
    },
}
ALLOCATION = {
    "Root_parser_controls": 10,
    "checkout": 45,
    "tool_install": 300,
    "official_cargo": 90,
    "metadata_including_Root_binding": 20,
    "explicit_chrono_positive": 210,
    "cold_native_executable_build": 1420,
    "native": 480,
    "verification": 90,
    "retention": 200,
}
ORIGINAL_CHECKOUT_SECONDS = 93.150292035 - 84.486834203
# A conservative budget charge, not a claim that all old overhead was
# verification. It covers even the old terminal tail not present in RESULT.
ORIGINAL_VERIFICATION_CEILING = (
    442
    - ORIGINAL_CHECKOUT_SECONDS
    - sum(value for name, value in ORIGINAL_PHASES.items() if name != "verification")
)
METADATA_PIN = {
    "bytes": 940148,
    "sha256": "9401c64a0132b148fab36acf0d5332c49639fd055014edf8e5a1cab0c563937b",
}
CONTROL_ROOT_OBSERVATION_PIN = {
    "bytes": 14700,
    "sha256": "946f86d38acb3678cf28c79d40350884f9c77db9a5938bef4c6d4c26e45a00ca",
}
CONTROL_ACTUAL_DEBIT_SECONDS = 13
CONTINUATION_CI_CEILING_SECONDS = 2852
CONSUMER_TARGETS_SHA256 = (
    "8d096c7eb2baf7aa6f076da8ae95876adf72f88f9dfd7ab7b98d08aafe404253"
)


def read_regular(path, maximum):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 <= before.st_size <= maximum:
            raise ValueError("source is not a bounded regular file")
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if (
        len(raw) != before.st_size
        or len(raw) > maximum
        or any(getattr(before, key) != getattr(after, key) for key in fields)
    ):
        raise ValueError("source changed while reading")
    return raw


def retain_bytes(path, raw):
    with path.open("xb") as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())


def load_checked(path, expected, name):
    raw = read_regular(path, 1024 * 1024)
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("unbound or changed module source: " + str(path))
    description = importlib.util.spec_from_file_location(name, path)
    if description is None or description.loader is None:
        raise ValueError("module specification is unavailable")
    loaded = importlib.util.module_from_spec(description)
    # Preserve the former module metadata and lack of sys.modules registration.
    # Execute this checked buffer, without loader.get_code/exec_module or pyc.
    exec(compile(raw, str(path), "exec", dont_inherit=True), loaded.__dict__)
    return loaded


def require(condition, message):
    if not condition:
        raise ValueError(message)


class Cancellation:
    """Latch signals; raise only inside the original command cleanup region."""

    def __init__(self):
        self.signals = []
        self.signal_count = 0
        self.retaining = False
        self.previous = {}

    def install(self):
        for number in (signal.SIGINT, signal.SIGTERM):
            self.previous[number] = signal.getsignal(number)
            signal.signal(number, self.observe)

    def observe(self, number, _frame):
        self.signal_count += 1
        if len(self.signals) < 16:
            self.signals.append(
                {
                    "number": number,
                    "name": signal.Signals(number).name,
                    "monotonic_seconds": time.monotonic(),
                    "during_retention": self.retaining,
                }
            )

    def check(self):
        if self.signal_count and not self.retaining:
            raise KeyboardInterrupt("original scope cancellation requested")

    def restore(self):
        for number, previous in self.previous.items():
            signal.signal(number, previous)

    def receipt(self):
        return {
            "requested": self.signal_count > 0,
            "signal_count": self.signal_count,
            "signals": list(self.signals),
            "signals_omitted": self.signal_count - len(self.signals),
            "hard_kill_or_runner_loss_observable": False,
            "escaped_sessions_termination_claimed": False,
        }


def finite_seconds(value, maximum, label):
    require(
        type(value) in (int, float) and math.isfinite(value) and 0 <= value <= maximum,
        label + " is absent, nonfinite, negative, or over budget",
    )
    return float(value)


def original_history():
    return {
        "head": ORIGINAL_HEAD,
        "run_id": 45920364435,
        "run_attempt": 1,
        "job_id": 140249367364,
        "status": "FAIL",
        "whole_job_debit_seconds": 442,
        "phase_elapsed_seconds": ORIGINAL_PHASES,
        "owner_seconds_after_result_io": 417.46794637899995,
        "native_cases_executed": 0,
        "explicit_chrono_positive_issued": False,
        "prior_generation_debit_seconds": 334,
    }


def evidence_pin(value, label):
    require(
        isinstance(value, dict)
        and type(value.get("bytes")) is int
        and 0 < value["bytes"] <= 64 * 1024 * 1024
        and re.fullmatch(r"[0-9a-f]{64}", value.get("sha256", "")),
        label + " receipt pin is absent",
    )


def admit(spec, old, original_protocol, owner, before, evidence, input_raw):
    require(
        sys.platform == "linux"
        and os.uname().machine == "aarch64"
        and str(ROOT / "codex-rs") == ORIGINAL_WORKSPACE,
        "the admitted original Linux ARM checkout layout is required",
    )
    require(
        spec.get("schema") == "hepta-sqlx-remaining13-semantic-dependency-inputs-v2"
        and spec.get("activated") is True
        and spec.get("activation_blockers") == [],
        "remaining scope is inactive",
    )
    require(
        old.read_regular(ROOT / SPEC, 1024 * 1024) == input_raw,
        "inputs changed during admission",
    )
    require(
        spec["budget"] == ORIGINAL_BUDGET
        and spec["allocation"] == ALLOCATION
        and sum(ALLOCATION.values()) == 2865
        and spec["history"] == original_history()
        and spec["branch"] == BRANCH
        and spec["base_branch"] == BASE_BRANCH
        and spec["accepted_source"]
        == {"parent_head": PARENT, "parent_tree": PARENT_TREE}
        and spec["exact_changed_paths"] == DELTA_PATHS
        and spec["unallocated_seconds"] == 293
        and spec["effective_CI_whole_ceiling_seconds"]
        == CONTINUATION_CI_CEILING_SECONDS,
        "parent, history, exact scope, branch, or frozen budget differs",
    )
    require(
        spec["consumer_packages"] == list(old.PACKAGES)
        and spec["native_cases"] == [list(row) for row in old.NATIVE_CASES]
        and spec["target"] == old.TARGET
        and spec["toolchain"] == "1.96.0"
        and spec["nextest_version"] == old.NEXTEST_VERSION == "0.9.103"
        and spec["just_version"] == "1.51.0"
        and spec["compile_capability_cases"] == ["explicit_chrono_positive"]
        and spec["accepted_consumer_targets_sha256"] == CONSUMER_TARGETS_SHA256
        and spec["metadata_parts"] == PARTS
        and spec["original_metadata_pin"] == METADATA_PIN,
        "the exact original selectors, tools, or metadata binding differ",
    )
    require(
        spec["qualification"] is False
        and spec["chrono_removed"] is False
        and spec["E1_E6_added"] == 0
        and spec["E1_E6_frozen"] == "16/16"
        and spec["E6_remaining_seconds"] == 1.9960488015785813
        and spec["old_generation_replays"] == 0
        and spec["successful_compile_replays"] == 0,
        "engineering cannot grant qualification or reset old work",
    )
    required = original_protocol.REQUIRED_PINS | NEW_SOURCE_NAMES
    require(
        set(spec["source_pins"]) == required
        and not set(RECEIPTS).intersection(required)
        and SPEC not in required,
        "the exact source roster or acyclic receipt binding differs",
    )
    for path, pin in spec["source_pins"].items():
        old.check_pin(path, pin)
    require(
        spec["source_pins"][ORIGINAL_NATIVE]["sha256"] == ORIGINAL_NATIVE_SHA256
        and spec["source_pins"][PROTOCOL]["sha256"] == PROTOCOL_SHA256
        and spec["source_pins"][LEGACY]["sha256"] == LEGACY_SHA256
        and spec["source_pins"][TOOLS]["sha256"] == TOOLS_SHA256,
        "a verified original helper or the one-line parser candidate differs",
    )
    generation_raw = old.check_pin(GENERATION, spec["generation_acceptance_pin"])
    generation = old.strict_json(generation_raw)
    require(
        generation["schema"] == "root-hepta7147-four-lock-and-two-graph-acceptance-v1"
        and generation["accepted"] is True
        and generation["execution_authorization"] is False
        and generation["origin"] == spec["generation_origin"]
        and generation["cost"]["cumulative_conservative_full_job_debit_seconds"] == 334
        and generation["E1_E6_training_spent_unchanged"] == "16/16"
        and generation["E6_remaining_seconds_unchanged"] == 1.9960488015785813,
        "original accepted generation or its historical debit changed",
    )
    locks = {
        path: {key: row[key] for key in ("bytes", "sha256")}
        for path, row in generation["lock_set"].items()
    }
    graphs = {
        label: row["normalized_graph_sha256"]
        for label, row in generation["fixture_graphs"].items()
    }
    require(
        spec["accepted_locks"] == locks
        and spec["expected_fixture_graph_sha256"] == graphs,
        "the original accepted four locks or two graph observations differ",
    )
    for path, pin in locks.items():
        old.check_pin(path, pin)
    old.check_fixture_declarations()

    prior_raw = old.check_pin(PRIOR, spec["prior_observations_pin"])
    prior = old.strict_json(prior_raw)
    require(
        prior["schema"] == "root-sqlx7160-prior-observation-reuse-v1"
        and prior["accepted_for_observation_reuse"] is True
        and prior["reviewer"] == "root"
        and prior["execution_authorization"] is False
        and prior["original"] == original_history()
        and prior["whole_original_archive_authenticated"] is False
        and prior["original_targets_retained"] is False
        and prior["source_continuity_parent"] == {"head": PARENT, "tree": PARENT_TREE}
        and prior["original_metadata_pin"] == METADATA_PIN,
        "actual Root acceptance of the original limited observations is absent",
    )
    require(
        prior["original_result_pin"]
        == {
            "bytes": 92446,
            "sha256": "ff9bdb51d28de3a78895e621f5a757474b435264cc2a3dd5c1b1650e37bc96bf",
        }
        and prior["original_terminal_pin"]
        == {
            "bytes": 473,
            "sha256": "c0816227884ba90f194f7d7307448496a40b8f0ef0fc275ac9e2b8085a1f473c",
        }
        and prior["original_negative_command_pin"]
        == {
            "bytes": 1827,
            "sha256": "095782cb0dbe73df061eff9c25b0da55e362d6e29ff406baac89d80dae7af537",
        }
        and prior["original_negative_raw_pin"]
        == {
            "bytes": 720730,
            "sha256": "a05e7eb2c5e7e260b7875fc387ce359ce1dca827fd8b57d1c47f6951fe6c3795",
        },
        "original failed evidence identity differs",
    )
    evidence_pin(prior["root_review_receipt"], "prior Root review")
    controls_raw = prior["controls_root_observation_raw_utf8"].encode("utf-8")
    require(
        len(controls_raw) == CONTROL_ROOT_OBSERVATION_PIN["bytes"]
        and old.digest(controls_raw) == CONTROL_ROOT_OBSERVATION_PIN["sha256"],
        "the exact original Root control observation was not preserved",
    )
    controls_observation = old.strict_json(controls_raw)
    require(
        controls_observation["semantic_controls_pass"] is True
        and controls_observation["bounded_scope_pass"] is False
        and controls_observation["qualification"] is False
        and controls_observation["original_compiler_run_status"] == "FAIL"
        and controls_observation["original_compiler_exit"] == 101
        and controls_observation["accounting"]["observed_supervisor_wall_seconds"] == 13
        and controls_observation["expected_controls"]
        == controls_observation["observed_controls"],
        "original semantic pass, bounded failure, or full thirteen-second debit changed",
    )
    controls = prior["pre_dispatch"]["parser_controls"]
    binding = prior["pre_dispatch"]["metadata_binding"]
    require(
        controls["semantic_status"] == "PASS"
        and controls["bounded_scope_status"] == "FAIL"
        and controls["whole_actual_seconds"] == CONTROL_ACTUAL_DEBIT_SECONDS
        and controls["budget_debit_seconds"] == CONTROL_ACTUAL_DEBIT_SECONDS,
        "the original control overrun must remain a failed bounded scope",
    )
    for name, row, cap in (
        (
            "parser controls semantic evidence with preserved budget failure",
            controls,
            13,
        ),
        ("metadata binding", binding, 20),
    ):
        require(
            row["executed"] is True
            and row["accepted"] is True
            and row["original_process_count"] == 1
            and row["terminal_exit_code"] == 0
            and row["terminal_confirmed"] is True
            and row["dual_EOF"] is True
            and row["retries"] == 0,
            "the one first Root " + name + " result is not terminal and accepted",
        )
        finite_seconds(row["whole_actual_seconds"], cap, name)
        evidence_pin(row["result"], name)
        evidence_pin(row["terminal"], name)
        evidence_pin(row["root_review_receipt"], name + " Root acceptance")
    require(
        controls["control_source_pin"]
        == {
            "bytes": 7754,
            "sha256": "b0fc511b782f8c32d686806db4941b108ccf4952ff14d0e1db2d4d66c29b32bb",
        }
        and controls["candidate_pin"] == {"bytes": 39977, "sha256": LEGACY_SHA256}
        and controls["passed"] == 8
        and controls["failed"] == 0
        and controls["skipped"] == 0
        and controls["original_record_status"] == "failed"
        and controls["original_record_exit_code"] == 101
        and controls["qualification"] is False
        and binding["metadata_commands"] == 0
        and binding["native_commands"] == 0
        and binding["source_parent"] == PARENT
        and binding["source_tree"] == PARENT_TREE,
        "pre-dispatch work was broadened or the failed negative was rewritten",
    )
    require(
        controls["budget_debit_seconds"] == CONTROL_ACTUAL_DEBIT_SECONDS,
        "the full actual Root control scope must remain debited",
    )
    binding_debit = finite_seconds(
        binding["budget_debit_seconds"], 20, "Root metadata debit"
    )
    require(
        binding["whole_actual_seconds"] <= binding_debit < 20,
        "metadata binding must leave a positive part of the shared twenty seconds for CI reuse",
    )
    pre = {
        "parser_controls_seconds": CONTROL_ACTUAL_DEBIT_SECONDS,
        "metadata_binding_seconds": binding_debit,
    }
    require(spec["pre_dispatch_debits"] == pre, "pre-dispatch costs differ")

    admission_raw = old.check_pin(ADMISSION, spec["remaining_admission_pin"])
    admission = old.strict_json(admission_raw)
    require(
        admission["schema"] == "root-sqlx-remaining13-separate-engineering-admission-v2"
        and admission["execution_authorization"] is True
        and admission["budget_admitted"] is True
        and admission["reviewer"] == "root"
        and admission["old_scope_replays"] == 0
        and admission["manual_CI_reruns"] == 0,
        "separate Root continuation admission is absent",
    )
    mirrored = (
        "budget",
        "allocation",
        "history",
        "branch",
        "base_branch",
        "accepted_source",
        "exact_changed_paths",
        "unallocated_seconds",
        "source_pins",
        "generation_acceptance_pin",
        "prior_observations_pin",
        "accepted_consumer_targets_sha256",
        "pre_dispatch_debits",
        "consumer_packages",
        "native_cases",
        "original_metadata_pin",
        "metadata_parts",
    )
    require(
        all(admission[key] == spec[key] for key in mirrored)
        and "inputs_sha256" not in admission
        and "input_sha256" not in admission,
        "Root admission fields differ or introduce a self-referential input hash",
    )
    policy = admission["control_dependency_policy"]
    require(
        spec["control_dependency_policy"] == policy
        and policy["schema"]
        == "root-sqlx-separate-engineering-control-dependency-policy-v1"
        and policy["approved"] is True
        and policy["reviewer"] == "root"
        and policy["controls_root_observation_pin"] == CONTROL_ROOT_OBSERVATION_PIN
        and policy["original_control_whole_limit_seconds"] == 10
        and policy["original_control_actual_debit_seconds"] == 13
        and policy["original_control_semantic_status"] == "PASS"
        and policy["original_control_bounded_scope_status"] == "FAIL"
        and policy["old_failed_scope_reclassified_as_pass"] is False
        and policy["old_scope_retry_or_refund"] is False
        and policy["native_correctness_may_consume_semantics_separately"] is True
        and policy["new_total_allocation_ceiling_seconds"] == 2865
        and policy["effective_CI_whole_ceiling_seconds"] == 2852
        and policy["unallocated_balance_unchanged"] == 293
        and policy["original_verification_phase_ceiling_seconds"] == 120
        and policy["prior_failure_still_blocks_bounded_controls_qualification"] is True,
        "a separate explicit Root engineering dependency contract is absent",
    )
    evidence_pin(policy["root_decision_receipt"], "separate dependency Root decision")
    evidence_pin(admission["root_review_receipt"], "continuation Root review")
    require(
        os.environ.get("GITHUB_EVENT_NAME") == "pull_request"
        and os.environ.get("GITHUB_REPOSITORY") == old.REPOSITORY
        and os.environ.get("GITHUB_RUN_ATTEMPT") == "1"
        and os.environ.get("HEPTA_CI_LANE") == "source-head",
        "not a first owned source-head PR attempt",
    )
    event = old.strict_json(
        old.read_regular(Path(os.environ["GITHUB_EVENT_PATH"]), 4 * 1024 * 1024)
    )
    pull = event["pull_request"]
    require(
        event["action"] == "opened"
        and pull["draft"] is True
        and pull["state"] == "open"
        and pull["user"]["login"] == "ProfHepta"
        and pull["head"]["repo"]["full_name"] == old.REPOSITORY
        and pull["base"]["repo"]["full_name"] == old.REPOSITORY
        and pull["head"]["ref"] == BRANCH
        and pull["base"]["ref"] == BASE_BRANCH
        and pull["head"]["sha"] == os.environ.get("SOURCE_SHA")
        and os.environ.get("SOURCE_SHA") == os.environ.get("TESTED_SHA"),
        "the exact first-open Draft identity differs",
    )
    require(
        before["dirty"] is False
        and before["commit"] == pull["head"]["sha"]
        and before["parents"] == [PARENT]
        and owner.git("rev-parse", PARENT + "^{tree}") == PARENT_TREE
        and sorted(owner.git("diff", "--name-only", PARENT, "HEAD", "--").splitlines())
        == DELTA_PATHS,
        "candidate is not the exact clean source-only child of actual7161",
    )
    job = old.strict_json(old.read_regular(evidence / "job-start.json", 16384))
    prepared = old.strict_json(old.read_regular(evidence / "checkout-end.json", 16384))
    now = time.monotonic()
    require(
        job["head"] == pull["head"]["sha"]
        and job["run_id"] == os.environ["GITHUB_RUN_ID"]
        and job["run_attempt"] == "1"
        and job["boot_id"]
        == Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        and prepared["run_id"] == job["run_id"]
        and 0 <= prepared["monotonic_seconds"] - job["monotonic_seconds"] <= 45
        and 0 <= now - prepared["monotonic_seconds"] <= 300,
        "fresh pre-checkout clock, checkout, or aggregate tool deadline differs",
    )
    steps = old.strict_json(os.environ["SQLX_ALL_STEPS"])
    require(
        all(
            steps[key]["outcome"] == "success"
            for key in (
                "job_scope",
                "checkout",
                "checkout_clock",
                "rust",
                "tools",
                "v8",
            )
        ),
        "a fresh preparation step did not succeed",
    )
    return {
        "source_sha": pull["head"]["sha"],
        "run_id": job["run_id"],
        "run_attempt": "1",
        "job_started_monotonic": job["monotonic_seconds"],
        "source_pins_rechecked": len(required),
        "original_history": original_history(),
        "original_verification_conservative_ceiling_seconds": ORIGINAL_VERIFICATION_CEILING,
        "conservative_ceiling_is_not_an_actual_phase_measurement": True,
        "pre_dispatch_debits": pre,
        "generation_acceptance_sha256": old.digest(generation_raw),
        "remaining_admission_sha256": old.digest(admission_raw),
        "prior_observations_sha256": old.digest(prior_raw),
    }


def make_scope(original):
    class RemainingScope(original.Scope):
        """Use the original owned invoke path with cumulative, non-borrowing caps."""

        def __init__(
            self, old, spec, result, directory, started, admission, cancellation
        ):
            self.old, self.spec, self.result, self.directory = (
                old,
                spec,
                result,
                directory,
            )
            self.started, self.cancellation = started, cancellation
            pre = admission["pre_dispatch_debits"]
            controls = pre["parser_controls_seconds"]
            binding = pre["metadata_binding_seconds"]
            self.deadline = min(
                started + 2310 - binding,
                # Use the whole old job as a conservative old-owner upper bound.
                started + 2880 - 442 - controls - binding,
                admission["job_started_monotonic"]
                + CONTINUATION_CI_CEILING_SECONDS
                - 200
                - binding,
            )
            self.new_caps = {
                "official_cargo": 90,
                "metadata": 20 - binding,
                "compile": 1630,
                "native": 480,
                "verification": 90,
            }
            self.spent = dict(ORIGINAL_PHASES)
            self.spent["verification"] = ORIGINAL_VERIFICATION_CEILING + controls
            self.spent["metadata"] += binding
            self.local_spent = {key: 0.0 for key in self.spent}
            self.active = self.command_deadline = None
            self.before = self.owner = None
            self.target_root = directory.parent.parent / "targets"
            self.target_root.mkdir(mode=0o700, exist_ok=False)
            self.charge("verification", time.monotonic() - started)

        def charge(self, name, elapsed):
            self.spent[name] += elapsed
            self.local_spent[name] += elapsed
            self.result["phase_elapsed_seconds_current_owner"] = dict(self.local_spent)
            self.result["phase_cumulative_budget_charges_seconds"] = dict(self.spent)
            self.result["original_phase_elapsed_seconds"] = dict(ORIGINAL_PHASES)
            self.result["old_verification_conservative_overhead_reserve_seconds"] = (
                ORIGINAL_VERIFICATION_CEILING - ORIGINAL_PHASES["verification"]
            )

        @contextmanager
        def phase(self, name):
            require(
                self.active is None and name in self.new_caps, "invalid phase overlap"
            )
            self.active, self.phase_start = name, time.monotonic()
            try:
                self.check_time()
                yield
                self.check_time()
            finally:
                self.charge(name, time.monotonic() - self.phase_start)
                self.active = None

        def check_time(self):
            self.cancellation.check()
            require(self.active in self.new_caps, "a command needs an active phase")
            now = time.monotonic()
            elapsed = now - self.phase_start
            reserve = (
                0
                if self.active == "verification"
                else max(
                    0, self.new_caps["verification"] - self.local_spent["verification"]
                )
            )
            remaining = min(
                self.deadline - now - reserve,
                ORIGINAL_BUDGET["phases"][self.active]
                - self.spent[self.active]
                - elapsed,
                self.new_caps[self.active] - self.local_spent[self.active] - elapsed,
                self.command_deadline - now
                if self.command_deadline is not None
                else math.inf,
            )
            require(
                remaining > 0, "original cumulative or remaining phase budget exhausted"
            )
            return remaining

        @contextmanager
        def command_window(self, name, cap):
            require(self.command_deadline is None, "command windows must not overlap")
            began = time.monotonic()
            self.command_deadline = began + cap
            row = {"name": name, "cap_seconds": cap, "started_monotonic": began}
            self.result.setdefault("command_windows", []).append(row)
            try:
                self.check_time()
                yield
                self.check_time()
            finally:
                row["elapsed_seconds"] = time.monotonic() - began
                row["completed_within_cap"] = row["elapsed_seconds"] <= cap
                self.command_deadline = None

        def verification_deadline(self):
            return min(
                self.deadline,
                time.monotonic()
                + max(
                    0,
                    min(
                        120 - self.spent["verification"],
                        90 - self.local_spent["verification"],
                    ),
                ),
            )

    return RemainingScope


def expression(old):
    return " | ".join(
        "(binary_id(=" + binary + ") & test(=" + name + "))"
        for binary, name in old.NATIVE_CASES
    )


def metadata_reuse(scope, old):
    originals = [old.check_pin(path, scope.spec["source_pins"][path]) for path in PARTS]
    raw = b"".join(originals)
    require(
        len(raw) == METADATA_PIN["bytes"] and old.digest(raw) == METADATA_PIN["sha256"],
        "the complete original metadata bytes were not reconstructed exactly",
    )
    metadata = old.strict_json(raw)
    require(
        metadata["version"] == 1
        and metadata["resolve"] is None
        and metadata["workspace_root"] == ORIGINAL_WORKSPACE
        and len(metadata["packages"]) == len(metadata["workspace_members"]) == 193
        and {p["id"] for p in metadata["packages"]}
        == set(metadata["workspace_members"])
        and all(p["source"] is None for p in metadata["packages"]),
        "the original complete no-deps workspace metadata differs",
    )
    found = [row for row in metadata["packages"] if row["name"] in old.PACKAGES]
    require(
        len(found) == 12 and {row["name"] for row in found} == set(old.PACKAGES),
        "the complete original twelve-consumer roster differs",
    )
    targets = {}
    for package in found:
        rows = []
        for declared in package["targets"]:
            target = dict(declared)
            target["src_path"] = Path(target["src_path"]).relative_to(ROOT).as_posix()
            rows.append(target)
        targets[package["name"]] = sorted(rows, key=old.canonical)
    require(
        old.digest(old.canonical(targets)) == CONSUMER_TARGETS_SHA256
        and sum(map(len, targets.values())) == 88,
        "the complete original target declarations changed",
    )
    rebound = dict(metadata)
    target_directory = str(scope.target_root / "main")
    rebound["target_directory"] = rebound["build_directory"] = target_directory
    require(
        {
            key: value
            for key, value in rebound.items()
            if key not in ("target_directory", "build_directory")
        }
        == {
            key: value
            for key, value in metadata.items()
            if key not in ("target_directory", "build_directory")
        },
        "metadata reuse altered a package, ID, dependency, target, or source path",
    )
    retained = scope.directory / "rebound-consumer-metadata.json"
    derivative = old.canonical(rebound) + b"\n"
    retain_bytes(retained, derivative)
    pin = {
        "path": str(retained),
        "bytes": len(derivative),
        "sha256": old.digest(derivative),
    }
    scope.result["metadata_reuse"] = {
        "original": METADATA_PIN,
        "parts": PARTS,
        "packages": 193,
        "workspace_members": 193,
        "consumers": 12,
        "declared_targets": 88,
        "consumer_targets_sha256": CONSUMER_TARGETS_SHA256,
        "only_rebound_top_level_fields": ["target_directory", "build_directory"],
        "original_target_directory": metadata["target_directory"],
        "original_build_directory": metadata["build_directory"],
        "fresh_target_directory": target_directory,
        "derivative": pin,
        "metadata_commands": 0,
        "old_target_artifacts_reused": False,
    }
    scope.result["declared_targets"] = targets
    scope.result["required_feature_declarations_not_claimed_compiled"] = [
        {"package": name, "target": row["name"], "features": row["required-features"]}
        for name, rows in targets.items()
        for row in rows
        if row.get("required-features")
    ]
    return retained, pin, metadata


def recheck_retained(old, pin):
    raw = old.read_regular(Path(pin["path"]), 64 * 1024 * 1024)
    require(
        len(raw) == pin["bytes"] and old.digest(raw) == pin["sha256"],
        "a bound metadata file changed",
    )
    return raw


def binary_pin(path, target_root, check_time):
    actual = Path(path)
    require(
        actual.is_absolute()
        and actual == actual.resolve(strict=True)
        and actual.is_relative_to(target_root.resolve(strict=True)),
        "a binary is not an exact regular path inside the fresh target tree",
    )
    descriptor = os.open(actual, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(
            stat.S_ISREG(before.st_mode)
            and 64 <= before.st_size <= 1024 * 1024 * 1024
            and os.access(actual, os.X_OK),
            "a fresh native binary is absent, too large, or not executable",
        )
        digest, size, header = hashlib.sha256(), 0, b""
        while True:
            check_time()
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            if not header:
                header = chunk[:64]
            size += len(chunk)
            require(size <= before.st_size, "binary grew while reading")
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    fields = ("st_dev", "st_ino", "st_size", "st_mode", "st_mtime_ns", "st_ctime_ns")
    require(
        size == before.st_size
        and all(getattr(before, key) == getattr(after, key) for key in fields)
        and header[:6] == b"\x7fELF\x02\x01"
        and int.from_bytes(header[18:20], "little") == 183,
        "the exact binary changed or is not ELF64 AArch64",
    )
    check_time()
    return {
        "path": str(actual),
        "bytes": size,
        "sha256": digest.hexdigest(),
        "mode": stat.S_IMODE(before.st_mode),
        "ELF_machine": 183,
    }


def binary_metadata(scope, old, command, metadata):
    _record, raw, record_path = command
    marker = b'{"rust-build-meta":'
    require(
        raw.count(marker) == 1,
        "binary metadata is absent or ambiguous in the full raw log",
    )
    offset = raw.index(marker)
    suffix = raw[offset:]
    # The pinned nextest Json writer emits one compact object without a newline.
    # Preserve that exact suffix; do not drop arbitrary trailing diagnostics.
    parsed = old.strict_json(suffix)
    require(
        isinstance(parsed, dict)
        and set(parsed) == {"rust-build-meta", "rust-binaries"},
        "the exact nextest binary-list schema differs",
    )
    expected = {
        "codex-state": ("codex_state", "codex-state", "lib"),
        "codex-hepta-operations": (
            "codex_hepta_operations",
            "codex-hepta-operations",
            "lib",
        ),
        "codex-hepta-operations::destination_recovery_binding": (
            "destination_recovery_binding",
            "codex-hepta-operations",
            "test",
        ),
        "codex-thread-store": ("codex_thread_store", "codex-thread-store", "lib"),
    }
    binaries = parsed["rust-binaries"]
    build = parsed["rust-build-meta"]
    require(
        isinstance(binaries, dict)
        and set(binaries) == set(expected)
        and build["target-directory"] == str(scope.target_root / "main")
        and isinstance(build["platforms"], dict)
        and len(build["platforms"]["targets"]) == 1,
        "the first native build did not yield exactly the four selected target binaries",
    )
    packages = {row["name"]: row["id"] for row in metadata["packages"]}
    retained = scope.directory / "native-binaries.json"
    retain_bytes(retained, suffix)
    pin = {"path": str(retained), "bytes": len(suffix), "sha256": old.digest(suffix)}
    pins, findings = {}, {}
    observation = scope.result["native_binary_manifest"] = {
        "status": "verifying",
        "file": pin,
        "source_command_record": record_path.name,
        "source_command_record_sha256": old.digest(
            old.read_regular(record_path, 1024 * 1024)
        ),
        "complete_raw_log_sha256": old.digest(raw),
        "complete_raw_log_bytes": len(raw),
        "json_offset_in_original_combined_log": offset,
        "json_ends_at_original_log_EOF": True,
        "cold_build": True,
        "old_artifacts_reused": False,
        "native_test_bodies_executed_by_build": 0,
        "binaries": pins,
        "findings": findings,
    }
    for name, (binary_name, package_name, kind) in expected.items():
        row = binaries[name]
        finding = findings[name] = {"status": "failed"}
        try:
            require(
                set(row)
                == {
                    "binary-id",
                    "binary-name",
                    "package-id",
                    "kind",
                    "binary-path",
                    "build-platform",
                }
                and row["binary-id"] == name
                and row["binary-name"] == binary_name
                and row["package-id"] == packages[package_name]
                and row["kind"] == kind
                and row["build-platform"] == "target",
                "native binary ID, package, target kind, or build platform differs",
            )
            pins[name] = binary_pin(
                row["binary-path"], scope.target_root / "main", scope.check_time
            )
            finding["status"] = "passed"
        except Exception as error:
            finding["error"] = f"{type(error).__name__}: {error}"
    require(
        all(row["status"] == "passed" for row in findings.values())
        and len(pins) == 4
        and len({pin["path"] for pin in pins.values()}) == 4,
        "not all four selected binaries are unique, bound ELF64 AArch64 executables",
    )
    observation["status"] = "verified"
    return retained, pin, pins


def recheck_binaries(scope, pins):
    rows = scope.result.setdefault("binary_rechecks", [])
    for name, expected in pins.items():
        row = {"binary": name, "expected": expected, "status": "failed"}
        rows.append(row)
        try:
            row["observed"] = binary_pin(
                expected["path"], scope.target_root / "main", scope.check_time
            )
            require(row["observed"] == expected, "a selected native executable changed")
            row["status"] = "passed"
        except Exception as error:
            row["error"] = f"{type(error).__name__}: {error}"
    require(
        all(row["status"] == "passed" for row in rows),
        "one or more selected native executables failed re-verification",
    )


def explicit_positive(scope, old, tools):
    with scope.command_window("explicit-chrono-positive", 210):
        scope.invoke(
            "explicit-chrono-positive",
            [
                tools["fixture_cargo"]["path"],
                "check",
                "--locked",
                "--target",
                old.TARGET,
                "--manifest-path",
                str(ROOT / old.COMPATIBILITY / "Cargo.toml"),
                "--bin",
                "chrono_explicit",
                "--message-format=json",
            ],
            target="compatibility",
            fixture_rustc=tools["rustc"]["path"],
        )
        scope.result["explicit_chrono_positive"] = {
            "status": "passed",
            "first_issue": True,
            "original7160_observation": False,
        }


def cold_build(scope, old, rebound, metadata):
    with scope.command_window("cold-native-executable-build", 1420):
        record = scope.invoke(
            "cold-native-executable-build",
            [
                "cargo",
                "+1.96.0",
                "nextest",
                "list",
                "--cargo-metadata",
                str(rebound),
                "--locked",
                "--target",
                old.TARGET,
                "--target-dir",
                str(scope.target_root / "main"),
                "-p",
                "codex-state",
                "-p",
                "codex-hepta-operations",
                "-p",
                "codex-thread-store",
                "--lib",
                "--test",
                "destination_recovery_binding",
                "--list-type",
                "binaries-only",
                "--message-format",
                "json",
                "-E",
                expression(old),
            ],
        )
        return binary_metadata(scope, old, record, metadata)


def native_command(old, rebound, binaries):
    # Cargo selection flags were applied to the one first build. They conflict
    # with --binaries-metadata in the pinned nextest version and are not repeated.
    return [
        "just",
        "test",
        "--cargo-metadata",
        str(rebound),
        "--binaries-metadata",
        str(binaries),
        "--retries",
        "0",
        "--test-threads",
        "1",
        "--status-level",
        "pass",
        "--final-status-level",
        "fail",
        "-E",
        expression(old),
    ]


def final_source_checks(
    result, spec, input_raw, protocol, scope, directory, started, owner, before
):
    began = time.monotonic()
    deadline = scope.verification_deadline() if scope is not None else started + 90
    findings = result["final_source_verification"] = {}
    rows = []
    supplied = spec if isinstance(spec, dict) else {}
    required = (
        protocol.REQUIRED_PINS | NEW_SOURCE_NAMES
        if protocol is not None
        else NEW_SOURCE_NAMES
    )
    for label, names in (
        ("source_pins", required),
        (
            "accepted_locks",
            {
                "MODULE.bazel.lock",
                "codex-rs/Cargo.lock",
                "qualification/sqlx_temporal_default_v1/Cargo.lock",
                "qualification/sqlx_temporal_explicit_chrono_v1/Cargo.lock",
            },
        ),
    ):
        pins = supplied.get(label)
        if not isinstance(pins, dict) or not 0 < len(pins) <= 256:
            findings[label] = {
                "status": "unavailable",
                "error": "bounded pin roster unavailable",
            }
            pins = {}
        rows.extend(
            (label + ":" + name, name, pins.get(name), False)
            for name in sorted(set(pins) | names)
        )
    input_pin = (
        None
        if input_raw is None
        else {"bytes": len(input_raw), "sha256": hashlib.sha256(input_raw).hexdigest()}
    )
    rows.append(("inputs", SPEC, input_pin, True))
    rows.extend(
        ("receipt:" + path, path, supplied.get(key), True)
        for path, key in RECEIPTS.items()
    )
    rows.append(
        (
            "bootstrap_protocol",
            "scripts/hepta_sqlx_native_protocol_v2.py",
            {"sha256": PROTOCOL_SHA256},
            False,
        )
    )
    for label, relative, pin, retain in rows:
        row = findings[label] = {"path": relative, "expected": pin, "status": "failed"}
        try:
            if time.monotonic() >= deadline:
                raise TimeoutError("final source verification budget exhausted")
            path = Path(relative)
            if (
                path.is_absolute()
                or ".." in path.parts
                or path.as_posix() != relative
                or not (ROOT / path).resolve().is_relative_to(ROOT)
            ):
                raise ValueError("source path escapes the checkout")
            raw = read_regular(ROOT / path, 64 * 1024 * 1024)
            row["observed"] = {
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
            if retain:
                if directory is None:
                    raise ValueError("original evidence directory was not created")
                retained = directory / path.name
                if not retained.exists():
                    retain_bytes(retained, raw)
                retained_raw = read_regular(retained, 64 * 1024 * 1024)
                row["retained_sha256"] = hashlib.sha256(retained_raw).hexdigest()
                if retained_raw != raw:
                    raise ValueError("retained input and final source differ")
            if (
                not isinstance(pin, dict)
                or not isinstance(pin.get("sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", pin["sha256"]) is None
            ):
                raise ValueError("actual expected pin is unavailable")
            if label != "bootstrap_protocol" and (
                type(pin.get("bytes")) is not int
                or not 0 <= pin["bytes"] <= 64 * 1024 * 1024
                or pin["bytes"] != len(raw)
            ):
                raise ValueError("source byte count differs or is unbound")
            if row["observed"]["sha256"] != pin["sha256"]:
                raise ValueError("source SHA256 differs")
            if (
                "git_blob_sha1" in pin
                and hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
                != pin["git_blob_sha1"]
            ):
                raise ValueError("source Git blob differs")
            if time.monotonic() >= deadline:
                raise TimeoutError("source observation exceeded verification deadline")
            row["status"] = "passed"
        except Exception as error:
            row["error"] = f"{type(error).__name__}: {error}"
    identity = findings["identity"] = {"status": "unavailable", "before": before}
    try:
        if time.monotonic() >= deadline:
            raise TimeoutError("identity verification budget exhausted")
        if owner is None:
            raise ValueError("verified original identity owner was not loaded")
        after = owner.identity()
        result["after"] = identity["after"] = after
        expected = supplied.get("accepted_source", {})
        parent = expected.get("parent_head") if isinstance(expected, dict) else None
        tree = expected.get("parent_tree") if isinstance(expected, dict) else None
        identity["expected_parent"] = parent
        identity["expected_parent_tree"] = tree
        if not isinstance(parent, str) or re.fullmatch(r"[0-9a-f]{40}", parent) is None:
            raise ValueError("actual expected parent is unavailable")
        identity["observed_parent_tree"] = owner.git("rev-parse", parent + "^{tree}")
        identity["checks"] = {
            "before_after_equal": before is not None and after == before,
            "clean": after["dirty"] is False,
            "source_head": after["commit"]
            == os.environ.get("SOURCE_SHA")
            == os.environ.get("TESTED_SHA"),
            "sole_parent": after["parents"] == [parent],
            "parent_tree": identity["observed_parent_tree"] == tree,
        }
        if not all(identity["checks"].values()):
            raise ValueError("original source identity or admitted parent differs")
        if time.monotonic() >= deadline:
            raise TimeoutError("identity observation exceeded verification deadline")
        identity["status"] = "passed"
    except Exception as error:
        identity["error"] = f"{type(error).__name__}: {error}"
    result["source_postcheck_errors"] = {
        name: row.get("error", "unverified")
        for name, row in findings.items()
        if row["status"] != "passed"
    }
    if scope is not None:
        scope.charge("verification", time.monotonic() - began)
    else:
        result["unscoped_bootstrap_and_retention_seconds"] = time.monotonic() - started
    return not result["source_postcheck_errors"]


def main():
    started = time.monotonic()
    cpu = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = {
        "schema": "hepta-sqlx-remaining13-observation-v1",
        "status": "rejected",
        "commands": [],
        "qualification": False,
        "chrono_removed": False,
        "E1_E6_added": 0,
        "old_generation_replays": 0,
        "successful_compile_replays": 0,
        "original_scope_status": "FAIL",
        "original_whole_job_debit_seconds": 442,
        "remaining_allocation_ceiling_seconds": 2865,
        "effective_CI_whole_ceiling_seconds": 2852,
        "Root_parser_controls_actual_debit_seconds": 13,
        "Root_parser_controls_bounded_scope_status": "FAIL",
        "unallocated_seconds_not_borrowable": 293,
        "cold_native_build_required": True,
        "original_targets_retained": False,
        "historical_observations_are_not_new_results": True,
    }
    protocol = spec = old = scope = tools = tool_module = collector = native = None
    base_owner = rebound = rebound_pin = binaries = binary_data_pin = None
    binary_pins = {}
    directory = input_raw = owner = before = None
    code = 2
    original_cwd = Path.cwd()
    overrides = {
        "RUSTUP_TOOLCHAIN": "1.96.0",
        "CARGO_NET_RETRY": "0",
        "RUSTC_WRAPPER": "",
        "RUSTC_WORKSPACE_WRAPPER": "",
        "PYTHONDONTWRITEBYTECODE": "1",
        "NEXTEST_PROFILE": "local",
        "RUST_MIN_STACK": "8388608",
    }
    previous = {key: os.environ.get(key) for key in overrides}
    cancellation = Cancellation()
    owned_commands = result["owned_command_observations"] = []
    try:
        cancellation.install()
        cancellation.check()
        stage = Path(os.environ["SQLX_REMAINING_STAGE"])
        proposed = stage / "evidence/native"
        proposed.mkdir(mode=0o700, parents=False, exist_ok=False)
        directory = proposed
        input_raw = read_regular(ROOT / SPEC, 1024 * 1024)
        result["inputs_sha256"] = hashlib.sha256(input_raw).hexdigest()
        spec = json.loads(input_raw)
        retain_bytes(directory / Path(SPEC).name, input_raw)
        require(
            spec.get("activated") is True and spec.get("activation_blockers") == [],
            "remaining scope is inactive",
        )
        old = load_checked(ROOT / LEGACY, LEGACY_SHA256, "sqlx_remaining_contract")
        spec = old.strict_json(input_raw)
        base_owner = load_checked(
            ROOT / ORIGINAL_NATIVE,
            ORIGINAL_NATIVE_SHA256,
            "sqlx_remaining_original_owner",
        )
        protocol = load_checked(
            ROOT / PROTOCOL, PROTOCOL_SHA256, "sqlx_remaining_protocol"
        )
        cancellation.check()
        owner = load_checked(
            ROOT / "scripts/hepta_ci_exec.py", old.OWNER_SHA256, "sqlx_remaining_exec"
        )
        owner = base_owner.cancellable_executor(owner, cancellation, owned_commands)
        cancellation.check()
        os.chdir(ROOT / "codex-rs")
        before = owner.identity()
        result["before"] = before
        admission = admit(
            spec, old, protocol, owner, before, stage / "evidence", input_raw
        )
        result["admission"] = admission
        cancellation.check()
        scope = make_scope(base_owner)(
            old, spec, result, directory, started, admission, cancellation
        )
        scope.owner, scope.before = owner, before
        with scope.phase("verification"):
            for source, key in RECEIPTS.items():
                retain_bytes(
                    directory / Path(source).name, old.check_pin(source, spec[key])
                )
            collector = load_checked(
                ROOT / "scripts/hepta_ci_junit.py",
                old.COLLECTOR_SHA256,
                "sqlx_remaining_junit",
            )
            tool_module = load_checked(
                ROOT / TOOLS, TOOLS_SHA256, "sqlx_remaining_tools"
            )
            os.environ.update(overrides)
            require(
                not (ROOT / "codex-rs/target/nextest/local/junit.xml").exists(),
                "the fresh scope already contains an original native JUnit file",
            )
        with scope.phase("official_cargo"):
            tools = tool_module.prepare(scope, old)
        with scope.phase("metadata"):
            tool_module.check_versions(scope, old, tools)
            rebound, rebound_pin, original_metadata = metadata_reuse(scope, old)
        with scope.phase("compile"):
            explicit_positive(scope, old, tools)
            recheck_retained(old, rebound_pin)
            binaries, binary_data_pin, binary_pins = cold_build(
                scope, old, rebound, original_metadata
            )
        with scope.phase("verification"):
            recheck_retained(old, rebound_pin)
            recheck_retained(old, binary_data_pin)
            recheck_binaries(scope, binary_pins)
            require(
                not (ROOT / "codex-rs/target/nextest/local/junit.xml").exists(),
                "the first executable build unexpectedly produced native JUnit",
            )
        with scope.phase("native"):
            native = scope.invoke(
                "native-twelve",
                native_command(old, rebound, binaries),
                minimum=12,
                allow_failed=True,
            )
        code = 0
    except KeyboardInterrupt as error:
        result.update(status="interrupted", error=str(error))
        code = 130
    except Exception as error:
        result.update(status="failed", error=f"{type(error).__name__}: {error}")
    finally:
        cancellation.retaining = True
        boundary_started = time.monotonic()
        boundary_deadline = (
            scope.verification_deadline() if scope is not None else started + 90
        )
        try:
            if time.monotonic() >= boundary_deadline:
                raise TimeoutError("owned-boundary retention budget exhausted")
            if directory is None:
                raise ValueError("original evidence directory was not created")
            boundary_raw = (
                json.dumps(
                    {
                        "schema": "hepta-sqlx-remaining-owned-command-boundaries-v1",
                        "commands": owned_commands,
                        "cancellation": cancellation.receipt(),
                        "captured_monotonic_seconds": time.monotonic(),
                        "qualification": False,
                        "observation_only": True,
                        "requires_final_result_and_actual_original_exit": True,
                    },
                    indent=2,
                    sort_keys=True,
                ).encode()
                + b"\n"
            )
            retain_bytes(directory / "OWNED_COMMAND_BOUNDARIES.json", boundary_raw)
            result["owned_command_boundaries"] = {
                "file": "OWNED_COMMAND_BOUNDARIES.json",
                "bytes": len(boundary_raw),
                "sha256": hashlib.sha256(boundary_raw).hexdigest(),
                "observation_only": True,
            }
            if time.monotonic() >= boundary_deadline:
                raise TimeoutError(
                    "owned-boundary retention exceeded verification deadline"
                )
        except Exception as error:
            result["owned_boundary_retention_error"] = (
                f"{type(error).__name__}: {error}"
            )
            code = code or 2
        finally:
            if scope is not None:
                scope.charge("verification", time.monotonic() - boundary_started)
        if scope is not None:
            try:
                with scope.phase("verification"):
                    issued = any(
                        row["name"] == "native-twelve" for row in result["commands"]
                    )
                    original_xml = ROOT / "codex-rs/target/nextest/local/junit.xml"
                    if issued and original_xml.exists():
                        try:
                            raw_xml = old.read_regular(original_xml, 64 * 1024 * 1024)
                            retain_bytes(
                                directory / "original-junit-unverified.xml", raw_xml
                            )
                            result["unverified_xml_retained"] = {
                                "bytes": len(raw_xml),
                                "sha256": old.digest(raw_xml),
                                "not_a_passing_observation": True,
                            }
                        except Exception as error:
                            result["unverified_xml_retention_error"] = (
                                f"{type(error).__name__}: {error}"
                            )
                            code = code or 2
                    if native is not None:
                        try:
                            base_owner.collect_native(scope, old, collector, native)
                        except Exception as error:
                            result["native_collection_error"] = (
                                f"{type(error).__name__}: {error}"
                            )
                            code = code or 2
                    if rebound_pin is not None:
                        try:
                            recheck_retained(old, rebound_pin)
                            result["metadata_postcheck"] = "passed"
                        except Exception as error:
                            result["metadata_postcheck_error"] = (
                                f"{type(error).__name__}: {error}"
                            )
                            code = code or 2
                    captured = result.get("native_binary_manifest", {})
                    captured_pin = binary_data_pin or captured.get("file")
                    captured_binaries = binary_pins or captured.get("binaries", {})
                    if captured_pin is not None:
                        try:
                            recheck_retained(old, captured_pin)
                            result["binary_manifest_postcheck"] = "passed"
                        except Exception as error:
                            result["binary_manifest_postcheck_error"] = (
                                f"{type(error).__name__}: {error}"
                            )
                            code = code or 2
                    if captured_binaries:
                        try:
                            recheck_binaries(scope, captured_binaries)
                        except Exception as error:
                            result["binary_postcheck_error"] = (
                                f"{type(error).__name__}: {error}"
                            )
                            code = code or 2
                    if tools is not None:
                        try:
                            tool_module.recheck(
                                old,
                                tools,
                                directory,
                                result.get("verified_v8_pair", {}),
                            )
                        except Exception as error:
                            result["tool_postcheck_error"] = (
                                f"{type(error).__name__}: {error}"
                            )
                            code = code or 2
            except Exception as error:
                result["postcheck_error"] = f"{type(error).__name__}: {error}"
                code = code or 2
        if not final_source_checks(
            result, spec, input_raw, protocol, scope, directory, started, owner, before
        ):
            code = code or 2
        if cancellation.signal_count:
            code = code or 130
        result["cancellation_observed_before_final_io"] = cancellation.signal_count > 0
        result["cancellation"] = cancellation.receipt()
        result["all_observed_owned_commands_reaped"] = bool(owned_commands) and all(
            row["owned_group_signal_and_direct_child_reap_observed"]
            for row in owned_commands
        )
        if not result["all_observed_owned_commands_reaped"]:
            code = code or 2
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        try:
            os.chdir(original_cwd)
        except OSError as error:
            result["cwd_restore_error"] = f"{type(error).__name__}: {error}"
            code = code or 2
        now_cpu, now_children = (
            resource.getrusage(kind)
            for kind in (resource.RUSAGE_SELF, resource.RUSAGE_CHILDREN)
        )
        result.update(
            elapsed_seconds_before_final_io=time.monotonic() - started,
            self_cpu_seconds=now_cpu.ru_utime
            + now_cpu.ru_stime
            - cpu.ru_utime
            - cpu.ru_stime,
            reaped_children_cpu_seconds=now_children.ru_utime
            + now_children.ru_stime
            - children.ru_utime
            - children.ru_stime,
            whole_job_CPU_seconds=None,
            phase_intervals_are_nested=True,
            original_GitHub_job_and_queue_still_required=True,
        )
        write_deadline = (
            scope.verification_deadline() if scope is not None else started + 90
        )
        if time.monotonic() >= write_deadline:
            code = 124
        result["status"] = "passed_pending_terminal" if code == 0 else "failed"
        result["exit_code_before_final_io"] = code
        final_io_started = time.monotonic()
        raw = json.dumps(result, indent=2, sort_keys=True).encode() + b"\n"
        result_retained, retention_errors = False, {}
        try:
            if directory is None:
                raise ValueError("original evidence directory was not created")
            retain_bytes(directory / "RESULT.json", raw)
            result_retained = True
        except Exception as error:
            retention_errors["RESULT.json"] = f"{type(error).__name__}: {error}"
            code = code or 2
        if scope is not None:
            scope.charge("verification", time.monotonic() - final_io_started)
        if time.monotonic() >= write_deadline:
            code = 124
        if cancellation.signal_count:
            code = code or 130
        terminal_io_started = time.monotonic()
        terminal = {
            "status": "passed" if code == 0 else "failed",
            "exit_code": code,
            "result_sha256": hashlib.sha256(raw).hexdigest(),
            "result_retained": result_retained,
            "retention_errors": dict(retention_errors),
            "elapsed_seconds_after_result_io": time.monotonic() - started,
            "original_whole_job_debit_seconds": 442,
            "pre_dispatch_debits": spec.get("pre_dispatch_debits")
            if isinstance(spec, dict)
            else None,
            "current_owner_phase_seconds_before_terminal_io": dict(scope.local_spent)
            if scope
            else None,
            "cumulative_phase_budget_charges_before_terminal_io": dict(scope.spent)
            if scope
            else None,
            "requires_actual_original_CI_exit_and_full_job_cost": True,
            "cancellation": cancellation.receipt(),
        }
        try:
            if directory is None:
                raise ValueError("original evidence directory was not created")
            retain_bytes(
                directory / "TERMINAL.json",
                json.dumps(terminal, sort_keys=True).encode() + b"\n",
            )
        except Exception as error:
            retention_errors["TERMINAL.json"] = f"{type(error).__name__}: {error}"
            code = code or 2
            terminal.update(
                status="failed", exit_code=code, retention_errors=dict(retention_errors)
            )
        if scope is not None:
            scope.charge("verification", time.monotonic() - terminal_io_started)
        if time.monotonic() >= write_deadline:
            code = 124
        stdout_started = time.monotonic()
        print(
            json.dumps(
                {
                    "elapsed_before_stdout_flush": time.monotonic() - started,
                    "return_code_before_stdout_flush": code,
                    "qualification": False,
                    "cumulative_phase_budget_charges_after_result_io": scope.spent
                    if scope
                    else {"verification": time.monotonic() - started},
                    "retention_errors": retention_errors,
                    "cancellation": cancellation.receipt(),
                    "unretained_result": result if not result_retained else None,
                    "unretained_terminal": terminal
                    if "TERMINAL.json" in retention_errors
                    else None,
                }
            ),
            flush=True,
        )
        if scope is not None:
            scope.charge("verification", time.monotonic() - stdout_started)
        if time.monotonic() >= write_deadline:
            code = 124
        cancellation.restore()
        if cancellation.signal_count:
            code = code or 130
    return code


if __name__ == "__main__":
    raise SystemExit(main())
