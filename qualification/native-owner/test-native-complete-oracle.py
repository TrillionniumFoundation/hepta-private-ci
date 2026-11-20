"""Synthetic complete-path serial regression; imports the actual runner oracle."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
runner_path = Path(__file__).with_name("run-native-owner-qualification.py")
spec = importlib.util.spec_from_file_location("native_complete_oracle", runner_path)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

OWNER_INFO = {"bytes": 100, "entry": 4096}
REPORT = {
    "qualification": "original_root_agentd_sqlite_native_hos2",
    "production_ready": False,
    "original_daemon_initialized": True,
    "original_app_server_ready": True,
    "supervisor_promoted": False,
    "fleet_lifecycle": "starting",
    "native_hos2": True,
    "uid": 60002,
    "foreign_scope_grant_refused": True,
    "refused_scope_effect_entries": 0,
    "initial_native_revision": 2,
    "final_native_revision": 3,
    "dispatch_count": 1,
    "native_observation_count": 1,
    "terminal": "committed",
    "native_retired_through": 1,
    "current_cut": {
        "profile": "hepta:cognitive:exact-current-cut:v1",
        "owner_agent_id": "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12",
        "schema_digest": "1" * 64,
        "state_digest": "2" * 64,
    },
    "loss_injection": "wrapper_withheld_actual_ioctl_reply",
    "physical_power_loss": False,
    "cross_boot_qualified": False,
}
PUBLICATION = []
for role in range(1, 4):
    PUBLICATION += [
        "[hepta-g2] trusted initial image committed: bytes=100 entry=0x1000",
        f"[hepta-g1d] trusted role committed: role={role} pid={role}",
    ]
PUBLICATION += [
    "[hepta-g1d] initial control activated: manager=1 workload=2 recovery=3 cap_ns=50000000 period_ns=100000000 lease_ns=300000000000 hepta_durability=false",
]
PUBLICATION += [
    f"HEPTA_NATIVE_BOOT role={role} pid={role} original_owner=true production_ready=false"
    for role in range(1, 4)
]
PHASES = [
    "HEPTA_NATIVE_GENESIS_BEGIN original_sqlite=true",
    "HEPTA_NATIVE_GENESIS_COMPLETE original_sqlite=true",
    "HEPTA_NATIVE_AGENT_CREDENTIALS uid=60002 capabilities=0 no_new_privs=true same_image=true",
    "HEPTA_NATIVE_ROOT_SERVICE_BEGIN peer_uid=60002 production_ready=false",
    "HEPTA_NATIVE_ORIGINAL_DAEMON_READY original_app_server=true original_sqlite=true",
    "HEPTA_NATIVE_REPLY_WITHHELD actual_kernel_install=true replay=false",
]


def serial(report, root_report=None):
    complete = report if root_report is None else root_report
    return ("\n".join(PUBLICATION + PHASES + [
        "HEPTA_NATIVE_OWNER_REPORT " + json.dumps(report),
        "HEPTA_NATIVE_ROOT_SERVICE_END result=Ok(())",
        "HEPTA_NATIVE_COMPLETE " + json.dumps(complete),
    ]) + "\n").encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    checks = []

    def check(case, raw, expected, code=33, timed_out=False, excessive=False):
        observed = runner.verdict(raw, code, timed_out, excessive, None, OWNER_INFO)
        if observed["passed"] is not expected:
            raise AssertionError(f"{case}: {observed}")
        checks.append({"case": case, "passed": True, "expected_acceptance": expected})

    check("complete original-owner path uses 2 to 3", serial(REPORT), True)
    for initial in (1, 37, 2**64 - 2):
        value = copy.deepcopy(REPORT)
        value.update(initial_native_revision=initial, final_native_revision=initial + 1)
        check(f"dynamic successor {initial}", serial(value), True)
    for field in ("initial_native_revision", "final_native_revision"):
        value = copy.deepcopy(REPORT)
        del value[field]
        check(f"missing {field}", serial(value), False)
        for label, invalid in (
            ("null", None), ("zero", 0), ("negative", -1), ("true", True),
            ("false", False), ("string", str(REPORT[field])),
            ("float", float(REPORT[field])), ("overflow", 2**64),
        ):
            value = copy.deepcopy(REPORT)
            value[field] = invalid
            check(f"{field} rejects {label}", serial(value), False)
    for label, initial in (("zero", 0), ("negative", -1), ("true", True),
                           ("false", False), ("float", 2.0), ("exhausted", 2**64 - 1),
                           ("overflow", 2**64)):
        value = copy.deepcopy(REPORT)
        value.update(initial_native_revision=initial, final_native_revision=initial + 1)
        check(f"matching successor does not admit invalid initial {label}", serial(value), False)
    for final in (2, 4, 2**64 - 1):
        value = copy.deepcopy(REPORT)
        value["final_native_revision"] = final
        check(f"wrong final revision {final}", serial(value), False)
    for field in ("initial_native_revision", "final_native_revision"):
        value = copy.deepcopy(REPORT)
        value[field] += 1
        check(f"Root and Agent disagree on {field}", serial(REPORT, value), False)
        check(f"Agent and Root disagree on {field}", serial(value, REPORT), False)
        value = copy.deepcopy(REPORT)
        value[field] = float(value[field])
        check(f"Root alone has float {field}", serial(REPORT, value), False)
        check(f"Agent alone has float {field}", serial(value, REPORT), False)
    root_value = copy.deepcopy(REPORT)
    root_value.update(initial_native_revision=1, final_native_revision=2)
    agent_value = copy.deepcopy(root_value)
    agent_value["initial_native_revision"] = True
    check("Agent bool is not equal to Root integer revision one", serial(agent_value, root_value), False)
    for key, invalid in (("dispatch_count", 2), ("native_observation_count", 0),
                         ("terminal", "indeterminate"), ("native_retired_through", 0),
                         ("foreign_scope_grant_refused", False), ("refused_scope_effect_entries", 1)):
        value = copy.deepcopy(REPORT)
        value[key] = invalid
        check(f"original complete claim {key} remains enforced", serial(value), False)
    complete_raw = serial(REPORT)
    for marker in PHASES:
        check("missing " + marker.split()[0], complete_raw.replace((marker + "\n").encode(), b""), False)
    for marker in (b"HEPTA_NATIVE_COMPLETE ", b"HEPTA_NATIVE_OWNER_REPORT "):
        retained = complete_raw.splitlines(keepends=True)
        check("missing " + marker.decode().strip(), b"".join(line for line in retained if not line.startswith(marker)), False)
        duplicate = next(line for line in retained if line.startswith(marker))
        check("duplicate " + marker.decode().strip(), complete_raw + duplicate, False)
    check("guest failure cannot qualify", complete_raw + b"HEPTA_NATIVE_FAILURE actual_error\n", False)
    check("kernel panic cannot qualify", complete_raw + b"Kernel panic\n", False)
    check("wrong sealed image cannot qualify", complete_raw.replace(b"bytes=100", b"bytes=101"), False)
    check("wrong QEMU exit cannot qualify", complete_raw, False, code=65)
    check("timeout cannot qualify", complete_raw, False, timed_out=True)
    check("excess output cannot qualify", complete_raw, False, excessive=True)
    result = {
        "schema": "native-complete-oracle-host-check.v1", "passed": True,
        "checks": len(checks), "cases": checks,
        "synthetic_parser_inputs": True, "qemu_executed": False, "native_guest_qualified": False,
        "runner_sha256": runner.file_digest(runner_path), "test_sha256": runner.file_digest(Path(__file__)),
        "fixture_initial_native_revision": 2, "fixture_final_native_revision": 3,
    }
    if args.output:
        with args.output.open("x") as stream:
            stream.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "cases"}))


if __name__ == "__main__":
    main()
