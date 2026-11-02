"""Seal the independent audit and render descriptive historical TEST tables."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[4]
os.chdir(ROOT)
BASE = Path("experiments/hcsn_v13_followup_20261102/review/content96")
EVAL = Path("experiments/hcsn_v13_followup_20261102/joint_core/results/content_evaluation002")
READ = BASE / "audit002"
read = lambda path: json.loads(path.read_text())
audit, aggregates, means = [read(READ / name) for name in ("AUDIT.json", "AGGREGATES.json", "MEAN_CONTRASTS.json")]
head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
records = []
for path in sorted(EVAL.iterdir()):
    if not path.is_file():
        continue
    blob = subprocess.check_output(["git", "hash-object", "--no-filters", str(path)], text=True).strip()
    recorded = subprocess.check_output(["git", "rev-parse", head + ":" + str(path)], text=True).strip()
    records.append(dict(path=str(path), git_blob=blob, committed_git_blob=recorded,
                        sha256=hashlib.sha256(path.read_bytes()).hexdigest(), match=blob == recorded))
assert len(records) == 199 and all(item["match"] for item in records)
source_paths = [BASE / name for name in ("audit_content96.py", "audit_content96_failed001.py", "inspect_inputs.py", "summarize_review.py")]
output_paths = list(READ.glob("*.json"))
seal = dict(schema="hcsn-v13-content96-review-seal.v1", evidence_local_head=head,
            audit_pass=audit["audit_pass"], evaluation_files=records,
            local_current_head_check_only=True,
            source_and_output_sha256={str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths + output_paths},
            quality_acceptance=False, all_blockers_closed=False, production_activation=False)
(BASE / "SEAL.json").write_text(json.dumps(seal, indent=2) + "\n")
costs = [(name, read(BASE / name / "RECEIPT.json")) for name in ("cost_inspect001", "cost_audit001", "cost_audit002")]
labels = {("hx_full", "hx_full"): "A: full/full", ("hx_full", "hx_margin"): "B: full/margin",
          ("hx_margin", "hx_full"): "C: margin/full", ("hx_margin", "hx_margin"): "D: margin/margin"}
order = list(labels) + [(name, name) for name in ("ordinary_gate", "gru", "ssm", "history")]
lines = ["# V13 静态内容 96 条件独立复核", "", "审计技术结果：PASS。仅复核当前新训练的固定模型在已暴露 VAL/TEST 上的描述性历史重放；不是新的独立确认。quality_acceptance、all_blockers_closed、production_activation 均保持 false。", "",
         "独立脚本仅使用 NumPy/stdlib，不导入作者评估器或聚合器、不训练、不选择模型/seed、不打开额外源数据、不计算置信区间。NLL 从原始 logits 以 stable logsumexp 重算；all 为全部 sequence×6-prefix 等权均值，final 为第6 prefix，先按10个dependent accepted orders汇总object，再与原作者object表逐项核对。", "",
         f"96 个唯一条件、36 个固定最终 checkpoint、全部 seeds 13301/13303/13307、1,728 条 object metrics 均完整。核对96个raw SHA256、136个publication gate文件SHA256/Git blobs、全部weights与TRAIN元数据、CANDIDATES/PLAN及source/protocol seal。当前HEAD `{head}` 下199个评估证据文件逐个验证Git blob，其中96个raw。远端↔本地外部核验由root完成，本脚本只复核现存本地Git对象及记录映射。", "",
         "原source remote `4c2fa0d86b9b09d5b26849b4738458fabc7b2945` 对应本地f77ee树；candidate/dependency remote `f810ee199755d139f5b8c08187efc41cbd7839c9` 对应本地0381树。PLAN的20个source文件在原source树可核，recovered/v3/experiments/hcsn_free_boundary_v1/datasets.py原树未包含，已在candidate/dependency publication中封存为blob `188bb065ad088c41169a2ed69827a3a7b7577e25`。此处没有把后来补依赖表述为原source已完整。", "",
         "首次audit001因脚本假定PLAN全部source已在原source树而退出；失败源码audit_content96_failed001.py及cost_audit001日志保留。修复为区分原source树与补齐后的candidate/dependency树，fresh audit002通过。", "",
         "独立重算相对原作者：row最大绝对误差1.11e-16，prefix/object 4.44e-16，三seed均值1.78e-15，逐seed contrast 1.11e-16，mean contrast 3.82e-17；在5e-12绝对容差内，无实质差异。概率最大误差2.22e-16；预测完全相同。", "",
         "每split的async_av为12 recording objects×10 orders；av_binding为24 pair objects×10 orders，但仅12个底层recordings且每个recording被多个pair复用；每split只有2个历史actor。10 orders逐object核为audio首位、3 audio+3 video的全部10种次序。所有条件的labels/object_index/orders保持同一配对。不得把orders、重叠pairs、不同seed或A/D重复引用当作新的独立样本。", "",
         "## 已暴露历史 TEST：三固定seed算术均值", "", "accuracy列为百分比；NLL为越小越好。A/B/C/D分别为训练×执行full/full、full/margin、margin/full、margin/margin。", "",
         "| task | condition | all accuracy % | final accuracy % | all NLL | final NLL |", "|---|---|---:|---:|---:|---:|"]
for task in ("async_av", "av_binding"):
    for family, mode in order:
        row = next(x for x in aggregates if (x["task"], x["split"], x["training_family"], x["execution_mode"]) == (task, "test", family, mode))
        condition = labels.get((family, mode), family)
        lines.append(f"| {task} | {condition} | {100*row['all_prefix_accuracy']:.6f} | {100*row['final_prefix_accuracy']:.6f} | {row['all_prefix_nll']:.9f} | {row['final_prefix_nll']:.9f} |")
lines += ["", "## TEST：全部预登记contrast的三seed均值", "", "差值方向均为左减右；accuracy差值为百分点，NLL差值为正表示左侧更差。hx_margin对照即D。", "",
          "| task | contrast | Δall accuracy pp | Δfinal accuracy pp | Δall NLL | Δfinal NLL |", "|---|---|---:|---:|---:|---:|"]
for entry in means:
    if entry["split"] != "test":
        continue
    for name, vals in entry["fixed_seed_mean_contrasts"].items():
        lines.append(f"| {entry['task']} | {name} | {100*vals['all_prefix_accuracy']:+.6f} | {100*vals['final_prefix_accuracy']:+.6f} | {vals['all_prefix_nll']:+.9f} | {vals['final_prefix_nll']:+.9f} |")
lines += ["", "async_av上A−B的all accuracy为+2.083333pp、final为+0.833333pp，但all NLL变差+0.027088670，final NLL改善−0.049581087；C−D accuracy均为0，NLL变化很小。A−GRU的all/final accuracy分别为−0.185185/−4.166667pp，不能据该表声称A普遍优于普通模型。", "",
          "av_binding上A−B的all/final accuracy为−0.092593/−0.138889pp，NLL变化约−0.000038/+0.000474；A对普通对照的accuracy有不同程度正差，但三seed均值NLL均更差。训练差异A−C与执行差异A−B须分别解释；这些小量描述性差异不能建立独立确认或机制/经济优越性。", "",
          "## 可复核文件与成本", "", "audit002/ROWS.json保留96条逐seed结果；OBJECT_METRICS.json保留全部object结果；CONTRASTS.json保留12组×10 contrasts×4 metrics；AGGREGATES.json和MEAN_CONTRASTS.json由独立算术重算。AUDIT.json记录逐项检查数量、原始文件与gate hashes、136个Git blob，SEAL.json补当前199个评估文件Git blob关联和审计源码/输出SHA256。", "",
          "| envelope | task success | enclosing CPU seconds |", "|---|---|---:|"]
for name, receipt in costs:
    lines.append(f"| {name} | {str(receipt['task_success']).lower()} | {receipt['complete_supervisor_wait4']['cpu_seconds']:.6f} |")
lines += ["", "所有实质审计通过现存v8 economics.worker_cost外层wait4包络且单线程。上表含失败成本；inner diagnostics不再相加。当前report/seal步骤另由cost_summary001包络，其RECEIPT.json保留该步骤成本。上述CPU是审计成本，不是模型推理时间或经济优势证据。", ""]
(BASE / "REVIEW_ZH.md").write_text("\n".join(lines))
print(json.dumps(dict(evaluation_files=len(records), raw_files=sum(x["path"].endswith(".npz") for x in records),
                      all_git_blobs_match=True, audit_pass=audit["audit_pass"], evidence_local_head=head)))
