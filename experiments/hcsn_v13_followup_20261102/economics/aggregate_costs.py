"""Recompute disjoint V13 waited-worker CPU from retained receipt triplets.

Temporal overlap is not process ancestry. Only the two recorded fit launchers'
explicit --receipts destinations establish the 72 nested fit envelopes.
"""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import itertools
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
BASE = Path(__file__).resolve().parents[1]
UNIT = Decimal("0.000001")
COMPONENTS = ("frontend", "joint_core", "review", "control", "emotion_encoder")
LAUNCHERS = {
    "experiments.hcsn_v13_followup_20261102.joint_core.operations.run_roster":
        "experiments.hcsn_v13_followup_20261102.joint_core.campaign",
    "experiments/hcsn_v13_followup_20261102/control/orchestration/fit_batch.py":
        "experiments.hcsn_v13_followup_20261102.control.value_fit",
}


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cpu(value):
    number = Decimal(str(value))
    if not number.is_finite() or number < 0:
        raise ValueError("CPU must be finite and nonnegative")
    rounded = number.quantize(UNIT)
    if abs(number-rounded) > Decimal("0.000000001"):
        raise ValueError("Unexpected CPU counter precision")
    return rounded


def option(command, name):
    return command[command.index(name)+1]


def load(path, host):
    receipt, supervision, config = read(path), read(path.with_name("SUPERVISION.json")), read(path.with_name("CONFIG.json"))
    assert receipt["schema"] == "hcsn-v8-enclosing-worker-cost.v1"
    assert receipt["command"] == supervision["command"] == config["command"]
    assert receipt["supervision_sha256"] == sha(path.with_name("SUPERVISION.json"))
    complete = (receipt["complete_task_cpu_coverage"] and supervision["complete_task_cpu_coverage"]
                and supervision["all_waitable_children_collected"])
    if host == "local-v13-executor":
        assert complete
    assert receipt["source_unchanged_through_collection"] is True
    waited = receipt["complete_supervisor_wait4"]
    amount = cpu(waited["cpu_seconds"])
    assert amount == cpu(waited["user_cpu_seconds"])+cpu(waited["system_cpu_seconds"])
    begin, end = receipt["monotonic_begin_ns"], receipt["monotonic_end_ns"]
    assert end >= begin
    assert abs((end-begin)/1e9-receipt["cold_supervisor_to_exit_seconds"]) < 1e-8
    return {"receipt": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
            "host_scope": host, "cpu_seconds": str(amount), "command": receipt["command"],
            "task_success": receipt["task_success"], "complete_task_cpu_coverage": complete,
            "diagnostic_largest_single_process_highwater_bytes": waited["largest_single_process_highwater_bytes"],
            "diagnostic_memory_scope": "Largest individual process highwater, not simultaneous complete process-family RSS.",
            "monotonic_begin_ns": begin, "monotonic_end_ns": end,
            "wall_seconds": receipt["cold_supervisor_to_exit_seconds"],
            "receipt_sha256": sha(path), "supervision_sha256": receipt["supervision_sha256"],
            "config_sha256": sha(path.with_name("CONFIG.json")),
            "meter_source_sha256_at_start": receipt["source_sha256_at_start"],
            "measurement_boundary": receipt["measurement_boundary"],
            "outside_boundary": receipt["outside_boundary"]}


def local_inventory():
    paths = []
    for component in COMPONENTS:
        for path in (BASE/component).rglob("RECEIPT.json"):
            # Downloaded remote artifacts and source snapshots are not local reruns.
            if not any(part in ("artifact", "snapshots", "__pycache__") for part in path.relative_to(BASE).parts):
                paths.append(path)
    return sorted(paths)


def nested_batches(rows):
    nested, batches = {}, []
    for parent_path, parent in rows.items():
        launchers = [name for name in LAUNCHERS if name in parent["command"]]
        if not launchers:
            continue
        assert len(launchers) == 1
        command = parent["command"]
        destination = Path(option(command, "--receipts"))
        destination = destination if destination.is_absolute() else ROOT/destination
        run = Path(option(command, "--run"))
        run = run if run.is_absolute() else ROOT/run
        protocol = read(run/"PLAN.json")["protocol"]
        expected = set(itertools.product(protocol["tasks"], protocol["families"], protocol["seeds"]))
        children = [path for path in rows if path.parent.parent == destination]
        assert len(children) == len(expected) == 36
        identities = set()
        for path in children:
            child = rows[path]; args = child["command"]
            assert LAUNCHERS[launchers[0]] in args and "fit" in args
            identity = (option(args, "--task"), option(args, "--family"), int(option(args, "--seed")))
            assert identity not in identities
            identities.add(identity)
            assert parent["monotonic_begin_ns"] <= child["monotonic_begin_ns"] <= child["monotonic_end_ns"] <= parent["monotonic_end_ns"]
            assert path not in nested
            nested[path] = parent_path
        assert identities == expected
        child_cpu = sum((Decimal(rows[path]["cpu_seconds"]) for path in children), Decimal(0))
        assert child_cpu <= Decimal(parent["cpu_seconds"])
        batches.append({"parent": parent["receipt"], "launcher": launchers[0], "child_destination": str(destination.relative_to(ROOT)),
                        "children": len(children), "child_cpu_seconds_already_in_parent": str(child_cpu),
                        "parent_cpu_seconds": parent["cpu_seconds"],
                        "parent_minus_children_cpu_seconds": str(Decimal(parent["cpu_seconds"])-child_cpu),
                        "all_command_roster_and_time_containment_checks_passed": True})
    assert len(batches) == 2 and len(nested) == 72
    return nested, batches


def summarize(ci_artifact, ci_run, ci_status):
    began = datetime.now(timezone.utc).isoformat()
    paths = local_inventory()
    rows = {path: load(path, "local-v13-executor") for path in paths}
    nested, batches = nested_batches(rows)
    top = [row for path, row in rows.items() if path not in nested]
    subtotals = defaultdict(Decimal)
    for path, row in rows.items():
        if path not in nested:
            subtotals[path.relative_to(BASE).parts[0]] += Decimal(row["cpu_seconds"])
    total = sum((Decimal(row["cpu_seconds"]) for row in top), Decimal(0))
    failed = [row for row in top if not row["task_success"]]
    inventory = []
    for path in paths:
        inventory += [(str(path.with_name(name).relative_to(ROOT)), sha(path.with_name(name)))
                      for name in ("CONFIG.json", "RECEIPT.json", "SUPERVISION.json")]
    fingerprint = hashlib.sha256("\n".join(name+":"+digest for name,digest in sorted(inventory)).encode()).hexdigest()
    remote = []
    if ci_artifact is not None:
        remote = [load(path, "github-run-"+str(ci_run)) for path in sorted(ci_artifact.rglob("RECEIPT.json"))
                  if read(path).get("schema") == "hcsn-v8-enclosing-worker-cost.v1"]
    remote_complete = [row for row in remote if row["complete_task_cpu_coverage"]]
    remote_cpu = sum((Decimal(row["cpu_seconds"]) for row in remote_complete), Decimal(0))
    historical = BASE/"frontend/reused_train001/extract_train001.receipt.json"
    earlier = read(historical)
    exploration = read(BASE/"review/EXPLORATORY_SCOPE.json")
    return {"schema": "hcsn-v13-disjoint-cpu-scope.v1", "snapshot_begin_utc": began,
        "snapshot_end_utc": datetime.now(timezone.utc).isoformat(), "aggregator_source_sha256": sha(Path(__file__)),
        "local_receipts": len(rows), "proven_nested_receipts_excluded": len(nested),
        "local_disjoint_top_level_envelopes": len(top), "local_receipt_triplet_inventory_sha256": fingerprint,
        "local_recorded_disjoint_full_worker_cpu_seconds": str(total),
        "local_plus_remote_recorded_disjoint_complete_worker_cpu_seconds": str(total+remote_cpu) if remote_complete else None,
        "local_component_cpu_seconds": {key:str(value) for key,value in sorted(subtotals.items())},
        "failed_top_level_workers": len(failed), "failed_cpu_seconds_included": str(sum((Decimal(row["cpu_seconds"]) for row in failed), Decimal(0))),
        "top_level_workers": top, "batches": batches,
        "nested_receipts": [{"child":rows[path]["receipt"], "parent":rows[parent]["receipt"], "cpu_seconds_already_in_parent":rows[path]["cpu_seconds"]} for path,parent in nested.items()],
        "remote_ci": {"run_id": ci_run, "observed_state":ci_status, "materialized_receipts":remote,
            "recorded_disjoint_complete_worker_cpu_seconds": str(remote_cpu) if remote_complete else None,
            "incomplete_worker_cpu_lower_bound_seconds": str(sum((Decimal(row["cpu_seconds"]) for row in remote if not row["complete_task_cpu_coverage"]), Decimal(0))) if remote else None,
            "complete_workflow_cpu_seconds": None, "setup_and_unwrapped_identity_cpu_seconds":None,
            "scope":"Remote monotonic clocks are not compared with local clocks. No runner/receipt implies unknown CPU, never zero."},
        "separate_existing_preparation": {"receipt":str(historical.relative_to(ROOT)),"sha256":sha(historical),
            "known_direct_child_cpu_seconds":earlier["total_cpu_seconds"],
            "included_in_new_local_total":False,"reason":"Existing adjacent ASR feature preparation, retained for attribution; not a new execution and no allocation across projects inferred.",
            "reported_peak_rss_bytes":earlier["peak_rss_bytes"],"rss_scope":earlier["rss_scope"]},
        "separate_partial_exploration_cpu_seconds_lower_bound": exploration["self_cpu_seconds_lower_bound"],
        "economics_review_and_ledger_generation_complete_cpu_seconds":None,
        "complete_project_cpu_seconds":None,"complete_historical_preparation_cpu_seconds":None,
        "complete_process_family_rss_peak_bytes":None,"attributable_device_energy_joules":None,
        "complete_H20_economics":None,"complete_H10000_economics":None,
        "limits":["Complete refers to the declared waited-worker boundary, not every project operation. Outer launcher bootstrap/CONFIG/final receipt serialization are outside it.",
            "Only command-derived descendants are removed. Independent workers overlapping or even temporally contained in a batch remain additive CPU scopes.",
            "Do not sum worker wall durations into elapsed time. Concurrent fits intentionally overlap.",
            "The receipt source-unchanged map seals the three meter files; scientific entry-source/candidate identity is separately checked by its own manifests.",
            "RUSAGE largest-single-process highwater is not simultaneous family RSS. The V12 singleton qualification applies to its old 16 NumPy models, not V13 Torch/HX or the speech encoders.",
            "Development, orchestration, filesystem/network/API work, pretraining and incomplete historical preparation are not assigned zero cost. Physical energy is unmeasured."]}


def report(data):
    lines = ["# V13 执行经济性：真实非重叠 CPU 范围", "",
        "本账按回执的命令、监督哈希和进程包络重算，不以目录名或时间包含代替父子关系。它是已计量工作下界，不是完整项目或部署经济性。", "",
        "| 本地完整 waited-worker 范围 | CPU 秒 |", "| --- | ---: |"]
    lines += ["| "+name+" | "+value+" |" for name,value in data["local_component_cpu_seconds"].items()]
    lines += ["| 不重复合计 | **"+data["local_recorded_disjoint_full_worker_cpu_seconds"]+"** |", "",
        f"本次快照有 {data['local_receipts']} 份完整回执，移除 {data['proven_nested_receipts_excluded']} 个已含子 fit，保留 {data['local_disjoint_top_level_envelopes']} 个顶层包络。失败 {data['failed_top_level_workers']} 轮的 {data['failed_cpu_seconds_included']} CPU 秒已经计入，不再次追加。", "",
        "| 已含嵌套范围 | 子 fit 数 | 子 CPU（不加） | 父 CPU（已加） |", "| --- | ---: | ---: | ---: |"]
    lines += ["| "+b["launcher"]+" | "+str(b["children"])+" | "+b["child_cpu_seconds_already_in_parent"]+" | "+b["parent_cpu_seconds"]+" |" for b in data["batches"]]
    lines += ["", "独立审阅／前端 worker 即使落在训练 batch 时间内部，也不是其已等待子进程，仍须计入。并发 worker 的 wall 秒不相加冒称等待时间。", ""]
    remote = data["remote_ci"]
    if remote["materialized_receipts"]:
        lines += ["| 远端独立主机的完整 worker 范围 | CPU 秒 |", "| --- | ---: |"]
        lines += ["| "+row["command"][row["command"].index("-m")+1]+" | "+row["cpu_seconds"]+" |"
                  for row in remote["materialized_receipts"] if row["complete_task_cpu_coverage"]]
        lines += ["| 远端已记录完整包络小计 | **"+remote["recorded_disjoint_complete_worker_cpu_seconds"]+"** |",
                  "| 本地＋远端已记录完整包络下界 | **"+data["local_plus_remote_recorded_disjoint_complete_worker_cpu_seconds"]+"** |", "",
                  "远端 acquisition／model worker 各自只计一次，内部 process-body、逐前缀与 OOF 计时已包含，不再相加。远端 monotonic 与本地属于不同主机，不用于互相判断包含或重叠。", ""]
    lines += [
        "既有相邻 ASR 缓存准备的 107.396369 CPU 秒另列，不能当作本轮新执行，也不能把共享准备成本填零。未完整包络的早期数学探针另有 0.379491 self CPU 秒下界。", "",
        "情绪 CI 状态：`"+remote["observed_state"]+"`。未物化回执时 CPU 为 null；已获得 acquisition/model worker 回执后，依赖安装、source identity 和传输重组等 workflow 外部阶段仍须单列未知，不可声称整轮完整 CPU。", "",
        "V13 的完整项目 CPU、历史准备、进程族 RSS、可归因设备焦耳和 H=20／10,000 完整摊销继续为 null。V12 的 70–74 MiB 只属于旧 16 个 NumPy 模型的可信单任务 profile，不能借给新 Torch/HX 模型或 377／661 MB 预训练编码器。", "",
        "可用 `python -m experiments.hcsn_v13_followup_20261102.economics.aggregate_costs` 重算；未来新增 TEST／独审回执会自动纳入，CI 原包物化后显式传 `--ci-artifact`。完整明细、sha 与包络边界见 `COST_SCOPE.json`。", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ci-artifact", type=Path)
    parser.add_argument("--ci-run-id", type=int, default=41379044650)
    parser.add_argument("--ci-status", default="NOT_MATERIALIZED")
    args = parser.parse_args()
    result = summarize(args.ci_artifact, args.ci_run_id, args.ci_status)
    output = BASE/"economics"; output.mkdir(exist_ok=True)
    (output/"COST_SCOPE.json").write_text(json.dumps(result,indent=2)+"\n")
    (output/"REPORT_ZH.md").write_text(report(result))
    print(json.dumps({key:result[key] for key in ("local_receipts","proven_nested_receipts_excluded","local_disjoint_top_level_envelopes","local_recorded_disjoint_full_worker_cpu_seconds","failed_top_level_workers","failed_cpu_seconds_included")}))
