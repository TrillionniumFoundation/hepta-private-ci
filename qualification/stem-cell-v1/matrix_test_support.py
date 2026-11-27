"""Only synthetic integration fixtures; never retained as pretrained evidence."""
import torch

from matrix_materials import freeze_config
from next_round_matrix import build_plan
from paired_execution import PHASES, freeze_contract


def setup(arm="shared_421m_sparse_fixed16_no_ndu"):
    plan = build_plan(reader_id="test-reader", task_set_id="test-only-workload", seed=123)
    contract = freeze_contract(plan, source_sha="a" * 40, workload_sha256="b" * 64,
                               task_ids=["e0", "e1"], device_id="test-cpu", observer_id="independent-test",
                               train_cutoff_ns=10, eval_start_ns=20, eval_end_ns=100,
                               flops_caps=dict.fromkeys(PHASES, 10**9))
    config = freeze_config(plan, contract, arm_id=arm, snapshot_sha256="c" * 64,
                            upstream_revision="d" * 40, material_approval_sha256="e" * 64,
                            train_steps=4, batch_size=2, width_units=3)
    def row(sid, state, when):
        return dict(sample_id=sid, source_group=sid, scope="one-test-principal", state=state,
                    question="select a side", options=["left", "right"], available_at_ns=when)
    workload = dict(schema="hepta.stem.blind-workload.v1",
                    train=[dict(**row("t0", "-1", 2), label=0, label_observed_at_ns=4),
                           dict(**row("t1", "1", 3), label=1, label_observed_at_ns=5)],
                    eval=[row("e0", "-2", 21 - 2), row("e1", "2", 21 - 2)])
    return plan, contract, config, workload


class FixtureEncoder:
    dimension = 4
    weight_bytes = 16
    receipt = {"schema": "explicitly-test-only-encoder", "pretrained": False}

    def __init__(self, *, fail_task=None):
        self.calls = 0
        self.seen = []
        self.fail_task = fail_task
        self.reverified = False

    def encode(self, row):
        self.calls += 1
        self.seen.append(row.copy())
        if row["sample_id"] == self.fail_task:
            raise RuntimeError("test-only failed inference")
        x = float(row["state"])
        return torch.tensor([x, 1., x * x, -x]), 8

    def reverify(self):
        self.reverified = True
