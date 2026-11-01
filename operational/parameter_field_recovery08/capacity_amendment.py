"""The sole explicitly registered execution08 storage-capacity difference.

Original scientific and resource source bytes remain immutable. The original
loader still validates its original 2 GiB profile. This module separately admits
the new 6 GiB profile, and replaces only the operational registration aliases for
the lifetime of a new execution08 process scope. No scientific result is read.
"""

from contextlib import contextmanager
import importlib
from pathlib import Path

from . import common as c

GIB = 1024**3
RAW_CAP = 6 * GIB
INITIAL_DISK = 48 * GIB
MODULE_NAMES = (
    "resource_v2", "run_v2", "architecture_run_v2", "endpoint_v2",
    "launch_v2", "analysis_launch_v2", "finalize_v2",
    "register_followups_v2", "register_summary_v2", "controller_envelope_v2",
)
PACKAGE = "experiments.parameter_field_fullstudy_20261029."
RESOURCE = importlib.import_module(PACKAGE + "resource_v2")
ORIGINAL_LOADER = RESOURCE.load_registration


def load_registration(path, expected_sha256):
    """Validate the declared capacity revision without claiming the old cap passed."""
    contract = c.read(c.OWN / "INPUT_CONTRACT.json")
    item = c.descriptor(path)
    c.need(item == c.descriptor(c.OWN / "OPS_EXECUTION08.json")
           and item["sha256"] == expected_sha256,
           "Only the exact committed execution08 capacity profile is admitted")
    original_item = contract["original_resource_amendment"]
    original_path = c.SOURCE / original_item["path"]
    c.need(c.descriptor(original_path) == {**original_item, "path": str(original_path)},
           "Original resource profile bytes changed")
    original = ORIGINAL_LOADER(original_path, original_item["sha256"])
    value = c.bound(item)
    capacity_item = c.descriptor(c.OWN / "CAPACITY_AMENDMENT.json")
    capacity = c.bound(capacity_item)
    c.need(value.get("schema") == original["schema"]
           and value.get("status") == "REGISTERED_PRE_ENDPOINT"
           and value.get("execution_ready") is True
           and value.get("attempt_id") == "attempt02"
           and value.get("execution_episode") == c.EPISODE
           and value.get("raw_root") == contract["raw_root"]
           and value.get("content_addressed_store") == contract["cas_root"]
           and value.get("concurrency") == original["concurrency"],
           "New registration identity, roots or unchanged concurrency differ")
    declared_capacity = {**capacity_item, "path": "operational/parameter_field_recovery08/CAPACITY_AMENDMENT.json"}
    c.need(value.get("capacity_amendment") == declared_capacity
           and capacity.get("schema") == "hepta.execution08.capacity-amendment.1"
           and capacity.get("execution_episode") == c.EPISODE
           and capacity.get("scientific_outcomes_used") is False
           and capacity.get("original_scientific_source_files_unchanged") == 167
           and capacity.get("old_raw_cap_bytes") == 2 * GIB
           and capacity.get("new_raw_cap_bytes") == RAW_CAP
           and capacity.get("new_initial_disk_headroom_bytes") == INITIAL_DISK
           and capacity.get("original_two_gib_cap_completed") is False,
           "Capacity amendment is absent, changed or claims the failed cap passed")
    declared = value["proposed_resource_contract"]
    for key, old in original["proposed_resource_contract"].items():
        if type(old) in (int, float, bool):
            expected = RAW_CAP if key == "global_raw_logical_bytes" else old
            c.need(type(declared.get(key)) is type(expected)
                   and declared.get(key) == expected,
                   "Undeclared numerical resource change: " + key)
    plan = value["durable_execution"]
    c.need(plan["execution_episode"] == c.EPISODE
           and plan["canonical_job_order"] == list(c.ORDER)
           and plan["imported_jobs"] == []
           and plan["automatic_scientific_retry"] is False
           and plan["unknown_upload_outcome_retry"] is False
           and plan["unchanged_numeric_resource_contract"] is False
           and plan["initial_disk_headroom_bytes"] == INITIAL_DISK
           and plan["original_initial_disk_headroom_bytes"] == 2415919104
           and plan["initial_ram_headroom_bytes"] == 1879048192
           and plan["initial_gate_samples"] == 3
           and plan["initial_gate_interval_seconds"] == 10,
           "Fresh population, admission or retry rules changed")
    value.update(_path=str(Path(path).resolve()), _sha256=expected_sha256)
    return value


def require_disk_sample(sample):
    c.need(sample.get("original_joint_pass") is True
           and type(sample.get("disk_available")) is int
           and sample["disk_available"] >= INITIAL_DISK,
           "New execution08 48 GiB physical headroom gate failed")


@contextmanager
def installed(config):
    """Only validated loader aliases change; all budget and science code is original."""
    pin = config["descriptors"]["amendment"]
    load_registration(pin["path"], pin["sha256"])
    modules = []
    for name in MODULE_NAMES:
        module = importlib.import_module(PACKAGE + name)
        relative = c.PREFIX + name + ".py"
        c.need(Path(module.__file__).resolve() == c.SOURCE / relative
               and c.descriptor(c.SOURCE / relative)["sha256"] == config["source_files"][relative],
               "Original resource alias source differs: " + name)
        if hasattr(module, "load_registration"):
            c.need(module.load_registration is ORIGINAL_LOADER,
                   "Nested or unknown operational loader alias: " + name)
            modules.append(module)
    try:
        for module in modules:
            module.load_registration = load_registration
        yield
    finally:
        for module in reversed(modules):
            module.load_registration = ORIGINAL_LOADER
