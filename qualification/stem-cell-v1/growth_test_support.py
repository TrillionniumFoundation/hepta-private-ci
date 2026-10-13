"""Synthetic-only setup for bound growth integration tests, not model evidence."""
from execution_meter import WorkLedger
from matrix_growth import GROWTH_SCHEMA
from matrix_materials import freeze_config
from matrix_runtime import execute
from matrix_test_support import FixtureEncoder, setup
from paired_execution import freeze_contract
from test_execution_meter import policy


def growth_setup(arm="shared_421m_sparse_split_no_ndu", *, threshold=0., cap=10_000, groups=2, mode="strict"):
    plan, old, config, workload = setup("shared_421m_sparse_direct32_no_ndu")
    names = ("source_sha", "workload_sha256", "task_ids", "device_id", "observer_id",
             "train_cutoff_ns", "eval_start_ns", "eval_end_ns", "flops_caps", "tolerance_ppm")
    contract = freeze_contract(plan, **{k: old[k] for k in names}, max_peak_trainable_params=cap)
    fields = {k: v for k, v in config.items() if k not in ("schema", "contract_id", "config_id")}
    fields.update(arm_id=arm, width_units=4, train_steps=6)
    growth = dict(schema=GROWTH_SCHEMA, decision_step=2, loss_threshold=threshold,
                  minimum_source_groups=groups, gate_noise_scale=.001)
    config = freeze_config(plan, contract, **fields, measurement_policy=policy(mode), growth_policy=growth)
    return plan, contract, config, workload


def run_growth(parts, backend=None):
    p, c, cfg, w = parts
    meter = WorkLedger(cfg["measurement_policy"], c["flops_caps"])
    return execute(p, c, cfg, w, backend or FixtureEncoder(), clock=lambda: 25, meter=meter)
