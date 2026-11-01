"""Recompute R12 historical quality/cost using raw records, without model imports."""

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

import numpy as np

from .sensors import probe


REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
MODULE = "experiments.hcsn_validation_r13_20261031.cost.audit"
DEFAULT_STUDY = "experiments/hcsn_validation_r12_20261031/content/results/formal001"
REQUESTS = (1, 3, 10, 30, 100, 300, 1000, 3000, 10000, 30000, 100000, 300000, 1000000)
FAMILIES = ("ordinary_dual", "probit", "analytic", "lif_snn", "continuous_rnn",
            "cfc", "mamba1", "transformer")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def table(path, rows):
    with Path(path).open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def relative(path):
    return str(Path(path).resolve().relative_to(REPO))


def inventory(study):
    source = study.parent.parent
    files = {study / name for name in ("PROTOCOL.json", "SOURCE_FREEZE.json", "CANDIDATE_FREEZE.json")}
    files.update(source / name for name in read(study / "SOURCE_FREEZE.json")["files"])
    files.update(source.parent / name for name in ("process_meter.py", "schedule_content.py"))
    for pattern in ("jobs/*/attempt*/summary.json", "process_receipts/*/*.json",
                    "process_receipts/*/*.log", "profiles/*.json", "heldout/*/summary.json",
                    "heldout/*/*.npz", "schedules/*/START.json", "schedules/*/END.json"):
        files.update(study.glob(pattern))
    return {relative(p): dict(sha256=sha(p), bytes=p.stat().st_size) for p in sorted(files)}


def freeze(study, output):
    output.mkdir(parents=True, exist_ok=False)
    contract = dict(kind="historical_reanalysis_not_new_confirmation",
        created_at_utc=datetime.now(timezone.utc).isoformat(), study=relative(study),
        selection="No models, checkpoints or protocols changed; all historical domains retained",
        quality="Independent stable-softmax scores from retained raw prediction NPZ, no R12 imports",
        timing="Original per-process wait4 receipts; median of 12 warm profiles per fit, then fit mean",
        pareto="IID accuracy versus validation-IID-shape CPU only; descriptive mean frontier, no significance test",
        amortization="(full shared-encoder donor training + candidate fit/selection)/N + warm batch-1 CPU",
        research_allocation="Donor counted once in total; optional 1/16 per-fit share is accounting, not deployment cost",
        excluded="Joules, CPU prices, economic total utility, unmeasured service startup, stress-domain latency",
        independent_unit="Three fitting seeds conditional on shared fixed synthetic datasets; repeats are not fits",
        checkpoint_identity="Recorded candidate SHA links only; no weight loading or weight hash recheck",
        source_identity="Hashes of supplied copied bytes; no assertion that all R12 results were already published",
        model_identity="Content expected-renewal gate only; numerical HX and value-policy tracks are separate",
        requests=list(REQUESTS))
    write(output / "PROTOCOL.json", contract)
    inputs = inventory(study)
    write(output / "INPUT_MANIFEST.json", dict(files=inputs, file_count=len(inputs),
        total_bytes=sum(r["bytes"] for r in inputs.values()), root="repository root",
        origin="Retained local R12 evidence copied into this checkout; current hashes, not proof of remote publication"))
    sources = list(HERE.glob("*.py")) + list(HERE.glob("README.md")) + [HERE.parent / "__init__.py"]
    write(output / "SOURCE_MANIFEST.json", dict(files={relative(p): dict(sha256=sha(p),
        bytes=p.stat().st_size) for p in sorted(sources)}, protocol_sha256=sha(output / "PROTOCOL.json"),
        input_manifest_sha256=sha(output / "INPUT_MANIFEST.json")))
    return dict(source_files=len(sources), input_files=len(inputs),
                input_bytes=sum(r["bytes"] for r in inputs.values()))


def verify_frozen(output):
    inputs, sources = read(output / "INPUT_MANIFEST.json"), read(output / "SOURCE_MANIFEST.json")
    require(sha(output / "PROTOCOL.json") == sources["protocol_sha256"], "Analysis protocol changed")
    require(sha(output / "INPUT_MANIFEST.json") == sources["input_manifest_sha256"], "Input manifest changed")
    for manifest in (inputs, sources):
        for name, row in manifest["files"].items():
            path = REPO / name
            require(path.stat().st_size == row["bytes"] and sha(path) == row["sha256"],
                    f"Frozen input/source mismatch: {name}")
    study = REPO / read(output / "PROTOCOL.json")["study"]
    freeze_record = read(study / "SOURCE_FREEZE.json")
    require(sha(study / "PROTOCOL.json") == freeze_record["protocol_sha256"], "R12 protocol hash")
    for name, digest in freeze_record["files"].items():
        require(sha(study.parent.parent / name) == digest, f"R12 source freeze: {name}")
    return study, read(study / "PROTOCOL.json"), read(study / "CANDIDATE_FREEZE.json")


def receipts(study, protocol):
    ledger, indexed = [], defaultdict(list)
    expected_jobs = {j["id"]: j for j in protocol["jobs"]}
    for path in sorted((study / "process_receipts").glob("*/*.json")):
        record = read(path)
        argv, stage = record["command"], path.parent.name
        if stage == "audit":
            require("--job" not in argv, "Unexpected job in historical audit")
            job = "__historical_audit__"
        else:
            job = argv[argv.index("--job") + 1]
            require(job in expected_jobs and stage in ("worker", "evaluate", "profile"), "Unknown receipt")
        for key in ("cpu_seconds", "wall_seconds", "peak_rss_bytes"):
            require(math.isfinite(record[key]) and record[key] >= 0, f"Invalid {key}: {path}")
        require(sha(path.with_suffix(".log")) == record["log_sha256"], f"Receipt log hash: {path}")
        row = dict(stage=stage, job=job, attempt=path.stem.rsplit("_", 1)[-1],
            returncode=record["returncode"], cpu_seconds=record["cpu_seconds"],
            wall_seconds=record["wall_seconds"], peak_rss_bytes=record["peak_rss_bytes"],
            device_energy_joules=record["device_energy_joules"], receipt_path=relative(path),
            receipt_sha256=sha(path), log_sha256=record["log_sha256"])
        ledger.append(row)
        indexed[(stage, job)].append(row)
    for job in protocol["jobs"]:
        stages = ("worker",) if job["kind"] == "donor" else ("worker", "evaluate", "profile")
        for stage in stages:
            require((stage, job["id"]) in indexed, f"Missing {stage} receipt for {job['id']}")
    return ledger, indexed


def profile(study, job, candidate, training):
    path = study / "profiles" / (job + ".json")
    record = read(path)
    require(record["job"] == job and record["checkpoint"] == candidate, "Profile candidate mismatch")
    require(record["threads"] == 1 and record["warmups"] == 3, "Unexpected profiling configuration")
    require(record["input_sha256"] == training["selected_validation"]["input_sha256"],
            "Profile was not the recorded validation input")
    result = dict(profile_sha256=sha(path), energy_joules=record["energy_joules"])
    for batch in (1, 32):
        rows = record["measurements"][str(batch)]
        require(len(rows) == 12, "Incomplete profile repeats")
        for key in ("cpu_seconds", "wall_seconds"):
            values = [row[key] for row in rows]
            require(all(math.isfinite(v) and v > 0 for v in values), "Invalid profile timing")
            stem = "cpu" if key == "cpu_seconds" else "wall"
            result[f"profile_{stem}_s_b{batch}"] = float(np.median(values)) / batch
            result[f"profile_{stem}_s_b{batch}_min"] = min(values) / batch
            result[f"profile_{stem}_s_b{batch}_max"] = max(values) / batch
    return result


def scores(path):
    with np.load(path, allow_pickle=False) as data:
        logits, labels = data["logits"].astype(np.float64), data["labels"]
        require(logits.ndim == 2 and labels.shape == logits.shape[:1], "Prediction shape")
        require(np.isfinite(logits).all() and ((labels >= 0) & (labels < logits.shape[1])).all(),
                "Invalid prediction values")
        shifted = logits - logits.max(1, keepdims=True)
        normalizer = np.log(np.exp(shifted).sum(1))
        probability = np.exp(shifted - normalizer[:, None])
        result = dict(n=len(labels), accuracy=float((logits.argmax(1) == labels).mean()),
            ce=float((normalizer - shifted[np.arange(len(labels)), labels]).mean()),
            brier=float(((probability - np.eye(logits.shape[1])[labels]) ** 2).sum(1).mean()),
            input_sha256=str(data["input_sha256"]), prediction_sha256=sha(path))
        same_observations = hashlib.sha256(labels.tobytes() + data["ids"].tobytes()
                                           + data["groups"].tobytes()).hexdigest()
    return result, same_observations


def recompute(study, protocol, candidates, indexed):
    require(candidates["protocol_sha256"] == sha(study / "PROTOCOL.json"), "Candidate protocol identity")
    require(candidates["source_freeze_sha256"] == sha(study / "SOURCE_FREEZE.json"), "Candidate source identity")
    costs, qualities, shared = [], [], {}
    donor_users = Counter(j.get("donor") for j in protocol["jobs"] if j["kind"] == "fit")
    for job in protocol["jobs"]:
        entry = candidates["candidates"][job["id"]]
        summary = read(study / entry["path"] / "summary.json")
        require(summary["job"] == job and summary["completed"], "Incomplete or misidentified fit")
        require(summary["selected_checkpoint_sha256"] == entry["sha256"], "Recorded checkpoint identity")
        best = min(summary["validations"], key=lambda r: r["loss"])["step"]
        require(best == summary["selected_step"] == entry["step"], "Validation selection mismatch")
        require(any(r["returncode"] == 0 and r["attempt"] == Path(entry["path"]).name
                    for r in indexed[("worker", job["id"])]), "Selected attempt did not succeed")
        if job["kind"] == "donor":
            continue
        donor = candidates["candidates"][job["donor"]]
        require(summary["donor_sha256"] == donor["sha256"], "Recorded donor identity")
        worker = indexed[("worker", job["id"])]
        fit_cpu = sum(r["cpu_seconds"] for r in worker)
        donor_cpu = sum(r["cpu_seconds"] for r in indexed[("worker", job["donor"])])
        row = dict(job=job["id"], task=job["task"], mode=job["mode"], family=job["family"],
            seed=job["seed"], selected_step=entry["step"], parameters=summary["parameters"],
            trainable_parameters=summary["trainable_parameters"],
            core_parameters=protocol["core_configs"][job["family"]]["n_parameters"],
            core_parameter_gap=protocol["core_configs"][job["family"]]["relative_gap"],
            fit_updates=protocol["fit_updates"], learning_rate=protocol["learning_rate"],
            fit_process_cpu_s=fit_cpu, donor_process_cpu_s=donor_cpu,
            standalone_training_cpu_s=fit_cpu + donor_cpu,
            allocated_research_training_cpu_s=fit_cpu + donor_cpu / donor_users[job["donor"]],
            nested_training_cpu_s=summary["training_including_validation_cpu_seconds"],
            training_peak_rss_bytes=max(r["peak_rss_bytes"] for r in worker),
            evaluation_process_cpu_s=sum(r["cpu_seconds"] for r in indexed[("evaluate", job["id"])]),
            evaluation_peak_rss_bytes=max(r["peak_rss_bytes"] for r in indexed[("evaluate", job["id"])]),
            profiling_process_cpu_s=sum(r["cpu_seconds"] for r in indexed[("profile", job["id"])]),
            profiling_peak_rss_bytes=max(r["peak_rss_bytes"] for r in indexed[("profile", job["id"])]),
            selected_checkpoint_recorded_sha256=entry["sha256"], **profile(study, job["id"], entry, summary))
        heldout = read(study / "heldout" / job["id"] / "summary.json")
        require(heldout["checkpoint"] == entry and heldout["candidate_freeze_sha256"]
                == sha(study / "CANDIDATE_FREEZE.json"), "Heldout candidate identity")
        for domain in protocol["domains"][job["task"]]:
            value, observation_digest = scores(study / "heldout" / job["id"] / (domain + ".npz"))
            recorded = heldout["results"][domain]
            for metric in ("accuracy", "ce", "brier"):
                require(abs(recorded[metric] - value[metric]) < 3e-6, f"Raw score mismatch: {job['id']}/{domain}")
            require(value["input_sha256"] == recorded["input_sha256"], "Input identity mismatch")
            key = (job["task"], domain)
            identity = (value["input_sha256"], observation_digest)
            require(key not in shared or shared[key] == identity, "Methods did not share heldout observations")
            shared[key] = identity
            qualities.append(dict(**row, domain=domain, **value,
                domain_cpu_s_per_request=row["profile_cpu_s_b1"] if domain == "iid" else None,
                cost_scope="validation IID shape; cached raw tensor" if domain == "iid" else
                           "domain inference unmeasured; profile columns are IID references only"))
            if domain == "iid":
                costs.append(dict(**row, **value))
    total_training = sum(sum(r["cpu_seconds"] for r in v) for (stage, _), v in indexed.items() if stage == "worker")
    require(math.isclose(sum(r["allocated_research_training_cpu_s"] for r in costs),
                         total_training, abs_tol=1e-8), "Donor allocation double-counts training")
    return costs, qualities


def aggregate_rows(costs):
    grouped = defaultdict(list)
    for row in costs:
        grouped[(row["task"], row["mode"], row["family"])].append(row)
    result = []
    for (task, mode, family), rows in grouped.items():
        rows.sort(key=lambda r: r["seed"])
        result.append(dict(task=task, mode=mode, family=family, seeds=[r["seed"] for r in rows],
            accuracy_mean=float(np.mean([r["accuracy"] for r in rows])),
            accuracy_seeds=[r["accuracy"] for r in rows],
            cpu_ms_b1_mean=float(np.mean([r["profile_cpu_s_b1"] for r in rows])) * 1000,
            cpu_ms_b32_mean=float(np.mean([r["profile_cpu_s_b32"] for r in rows])) * 1000,
            training_cpu_s_mean=float(np.mean([r["standalone_training_cpu_s"] for r in rows])),
            fit_cpu_s_mean=float(np.mean([r["fit_process_cpu_s"] for r in rows])),
            parameters=rows[0]["parameters"], peak_rss_bytes=max(r["training_peak_rss_bytes"] for r in rows),
            selected_step_zero=sum(r["selected_step"] == 0 for r in rows)))
    for row in result:
        peers = [r for r in result if (r["task"], r["mode"]) == (row["task"], row["mode"])]
        for batch in (1, 32):
            axis = f"cpu_ms_b{batch}_mean"
            row[f"pareto_batch{batch}"] = not any(r[axis] <= row[axis] and r["accuracy_mean"] >= row["accuracy_mean"]
                and (r[axis] < row[axis] or r["accuracy_mean"] > row["accuracy_mean"]) for r in peers)
    return result


def report(output, summary, aggregate):
    lines = ["# R13：R12 原始记录的独立质量与成本重算", "",
        "**这是已公开结果后的历史重分析，未重训、未选择新候选，也不是新的留出确认。**",
        "720 份原始预测独立重算；96 个模型的质量、102 个训练任务和 294 份模型流程成本按身份配对；另计1份原始审计收据。"
        "本报告只分析固定期望 renewal 门的内容模型；数值 HX 核和真实动作价值线不因此合为一个模型。", "",
        "## 输入身份与核验范围", "",
        "INPUT_MANIFEST.json 列出本轮实际读取的每个文件、字节数和 SHA-256。SOURCE_MANIFEST.json "
        "冻结本次分析代码及协议。原 R12 已记录的源码冻结与本地副本字节匹配；这不证明全部原始结果此前已经上传远端。"
        "候选只核对清单、训练摘要和评估摘要中的 SHA 链，不读取或重新执行权重。"
        "本程序不导入 R12 的模型、数据生成器或 audit_results.py。", "",
        "## 进程总账", "", "| 阶段 | 收据数 | CPU 秒 | 失败 | 峰值 RSS MiB |",
        "|---|---:|---:|---:|---:|"]
    for stage, row in summary["process_totals"].items():
        lines.append(f"| {stage} | {row['receipts']} | {row['cpu_seconds']:.6f} | {row['failures']} | {row['peak_rss_bytes']/2**20:.3f} |")
    lines += ["", "训练总账包含6个共同 donor，各计一次。独立部署单个候选的训练成本包含该 donor 全额与该候选 fit/选择。"
        "allocated_research_training_cpu_s 将 donor 按16个使用者均摊，只用于核对研究总账。"
        "内层训练/验证 CPU 已包含在完整进程 CPU 中，不能再相加。并行 worker wall 不能相加解释为研究耗时。", "",
        "## IID 质量与实际 profile 成本", "",
        "每个 latency 先取该 fit 的12次 CPU 计时中位数，再对3个 fit 求均值；batch32 按32个样本摊分。"
        "这些是缓存原始张量经完整 encoder/core/readout 到输出拷贝的 warm CPU 测量。"
        "不是请求网络时延，也没有把启动、训练和 profile 内的重复调用再次计入单次请求。", "",
        "| 任务 | 模式 | 模型 | IID 准确率 | batch1 ms | batch32 ms/样本 | fit CPU s | donor+fit CPU s | batch1 Pareto |",
        "|---|---|---|---:|---:|---:|---:|---:|---|"]
    for r in aggregate:
        lines.append(f"| {r['task']} | {r['mode']} | {r['family']} | {r['accuracy_mean']:.6f} | "
            f"{r['cpu_ms_b1_mean']:.6f} | {r['cpu_ms_b32_mean']:.6f} | {r['fit_cpu_s_mean']:.6f} | "
            f"{r['training_cpu_s_mean']:.6f} | {'是' if r['pareto_batch1'] else '否'} |")
    lines += ["", "逐 seed 及全部 stress 域在 per_seed_quality_cost.csv；三个 seed 的质量和计时均保留，"
        "Pareto 是种子均值的描述性前沿，不是显著性结论。96个完整模型在 IID 与验证集具有同一输入形状；"
        "stress 域缺少对应 profile，因此 domain_cpu_s_per_request 留空，不用 IID 计时冒充长度外推或 clock4x 成本。", "",
        "## 训练摊销", "",
        r"对单个候选复用 N 次，绘制 CPU/request = (T_donor + T_fit)/N + t_warm_request。",
        "N 从1到1,000,000，原始逐 seed 情景在 training_amortization.csv。该数值是测得训练成本与 warm "
        "请求成本的会计组合；未测生产服务加载/编译、部署基础设施、外部数据获取，不能冒称完整生产成本。"
        "不赋予 CPU 价格，不把质量换成货币，不把 CPU 秒乘假定功率生成 Joule。", "",
        "## 八族基线及调参预算", "",
        "普通双头、匹配中心斜率 probit 与 renewal 三者均为1,584个动态核心参数，初始化严格配对。"
        "真实 LIF+替代梯度、continuous RNN、官方 ncps CfC、Mamba-1 CPU serial scan、SDPA Transformer"
        "使用最近实际宽度匹配，误差分别为3.03%、3.09%、2.02%、0%、5.81%。"
        "每 fit 固定128步、batch32、lr=0.003，允许step zero；并未逐族调参。"
        "LIF/Mamba有chance附近或step-zero结果，当前范围是固定预算对照，不能称最强充分优化基线已被击败。"
        "Mamba未使用融合GPU scan，Transformer调用真实SDPA；这些CPU结果不推断GPU排名。", "",
        "frozen_frontend 仅冻结共同的当前/前一帧编码器，动态核心与任务readout仍训练。joint训练三者。"
        "内容 analytic 是固定漂移、噪声、reset和不应期的有限完整 E[N] 门，加普通write头；"
        "它不持有完整存活条件密度，也没有求解任务最优自由边界。特殊函数成本已包含在模型profile内；"
        "完整分布存储和自由边界求解没有在这个模型里发生，不能借数值线的验证补齐。", "",
        "## 能耗与成本缺口", "",
        f"本轮只读探测到可见遥测：{summary['energy_probe']['visible_telemetry']}。详情在 ENERGY_VISIBILITY.json。"
        "这是当前容器可见性，既不声称物理宿主没有传感器，也不替代原运行的能耗记录。"
        "即使存在共享host计数器，也不能自动归因到本任务。R12历史能耗维持null；"
        "原meter的energy_sensor_available字段是固定值，不将其当作实际探测结果。", "",
        "进程RSS含解释器/库/模型，不是分布状态专项内存。当前还未测在线外部查询、流式cache、"
        "stress域推理时延、优化GPU实现、物理能耗与生产服务初始化。"
        "在这些缺口关闭前，不能用局部核速度或抽象任务tariff声称完整计算净优势。", "",
        "## 文件", "",
        "- process_ledger.csv：294份模型流程与1份原审计进程收据及hash。",
        "- per_seed_iid.csv：96候选逐seed的IID质量、CPU、训练、RSS、身份。",
        "- per_seed_quality_cost.csv：720个逐seed×域记录；未测域时延为空。",
        "- aggregate_iid.json：均值及batch1/batch32描述性Pareto。",
        "- training_amortization.csv：1,248个逐seed×请求数情景。",
        "- quality_cpu.png / .svg：IID质量与CPU。",
        "- training_amortization.png / .svg：训练复用成本。",
        "- ANALYSIS_PROCESS_RECEIPT.json：本次重分析自身成本，与R12总账分开。",
        "- INPUT_MANIFEST.json / SOURCE_MANIFEST.json：复跑所需字节身份。", ""]
    (output / "REPORT_ZH.md").write_text("\n".join(lines), encoding="utf-8")


def worker(output):
    study, protocol, candidates = verify_frozen(output)
    require(set(protocol["core_configs"]) == set(FAMILIES), "Unexpected model family set")
    ledger, indexed = receipts(study, protocol)
    costs, qualities = recompute(study, protocol, candidates, indexed)
    aggregate = aggregate_rows(costs)
    amortized = [dict(job=r["job"], task=r["task"], mode=r["mode"], family=r["family"],
        seed=r["seed"], requests=n, training_cpu_s=r["standalone_training_cpu_s"],
        warm_request_cpu_s=r["profile_cpu_s_b1"],
        cpu_s_per_request=r["standalone_training_cpu_s"] / n + r["profile_cpu_s_b1"])
        for r in costs for n in REQUESTS]
    totals = {}
    for stage in ("worker", "evaluate", "profile", "audit"):
        rows = [r for r in ledger if r["stage"] == stage]
        totals[stage] = dict(receipts=len(rows), cpu_seconds=sum(r["cpu_seconds"] for r in rows),
            failures=sum(r["returncode"] != 0 for r in rows),
            peak_rss_bytes=max(r["peak_rss_bytes"] for r in rows))
    schedule = read(study / "schedules" / "profile_attempt001" / "START.json")
    require(schedule["workers"] == 1, "Original profiles were not serial")
    energy = probe()
    summary = dict(passed=True, analysis_kind="historical_reanalysis", fit_jobs=len(costs),
        prediction_tables=len(qualities), prediction_rows=sum(r["n"] for r in qualities),
        profile_records=len(costs), amortization_rows=len(amortized), process_totals=totals,
        energy_probe=energy, source_manifest_sha256=sha(output / "SOURCE_MANIFEST.json"),
        input_manifest_sha256=sha(output / "INPUT_MANIFEST.json"),
        checks="Frozen bytes; source/protocol/candidate links; log hashes; actual receipt costs; selected step; raw scores; shared inputs; donor allocation; serial profiles",
        limitations="No new fitting, model execution, weight payload validation, fresh confirmation, population inference or remote-publication claim")
    table(output / "process_ledger.csv", ledger)
    table(output / "per_seed_iid.csv", costs)
    table(output / "per_seed_quality_cost.csv", qualities)
    table(output / "training_amortization.csv", amortized)
    write(output / "aggregate_iid.json", aggregate)
    write(output / "ENERGY_VISIBILITY.json", energy)
    from .figures import make_figures
    make_figures(output, FAMILIES, costs, aggregate, amortized)
    write(output / "SUMMARY.json", summary)
    report(output, summary, aggregate)
    print(json.dumps({key: summary[key] for key in ("passed", "fit_jobs", "prediction_tables", "prediction_rows")}))


def run(output):
    started = time.perf_counter()
    argv = [sys.executable, "-B", "-m", MODULE, "worker", "--output", str(output)]
    env = os.environ.copy()
    env.update(OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    with (output / "ANALYSIS_PROCESS.log").open("xb") as log:
        child = subprocess.Popen(argv, cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT)
        _, status, usage = os.wait4(child.pid, 0)
        child.returncode = os.waitstatus_to_exitcode(status)
    write(output / "ANALYSIS_PROCESS_RECEIPT.json", dict(command=argv, returncode=child.returncode,
        cpu_seconds=usage.ru_utime + usage.ru_stime, wall_seconds=time.perf_counter() - started,
        peak_rss_bytes=usage.ru_maxrss * 1024, python=platform.python_version(),
        energy_joules=None, scope="This fresh historical reanalysis process including imports, hash checks, raw scores and figures; excluded from R12 totals",
        log_sha256=sha(output / "ANALYSIS_PROCESS.log"),
        source_manifest_sha256=sha(output / "SOURCE_MANIFEST.json")))
    if child.returncode:
        raise SystemExit(child.returncode)
    print((output / "ANALYSIS_PROCESS.log").read_text())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("freeze", "run", "worker"))
    parser.add_argument("--study", type=Path, default=REPO / DEFAULT_STUDY)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if args.command == "freeze":
        print(json.dumps(freeze(args.study.resolve(), output)))
    elif args.command == "run":
        run(output)
    else:
        worker(output)


if __name__ == "__main__":
    main()
