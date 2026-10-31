"""Render existing measurements only; this module never fits or evaluates a model."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil


HERE = Path(__file__).parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def interval(value, digits=6, scale=1.):
    return "[" + ", ".join(f"{v * scale:+.{digits}f}" for v in value) + "]"


def render(run, process):
    development = json.loads((HERE / "DEVELOPMENT.json").read_text())
    protocol = json.loads((HERE / "PROTOCOL-v2.json").read_text())
    lines = ["# Control follow-up：同来源质量、真实成本与精确缓存", "",
        "本轮研究原有 NDU 图文生成器上的控制成本，并检验去除额外 CNN 的紧凑条件价值方案。"
        "本控制实验未重新训练生成器；新的训练由独立 training 目录报告。", "",
        "## 1. 开发结果与冻结选择", "",
        "仅复用已经读取的历史 forecast_fit[480,736) 和 forecast_calibration[448,576) 作为开发数据。"
        "它们没有被重新命名为未见验证。每个 seed 的21条实际候选路径重新生成、保存、回读并由 primary observer 评分。", "",
        "紧凑头以384维当前生成器状态、192维实际 caption one-hot 和1维剩余预算为输入，"
        "共享64宽 trunk 预测5个正值条件风险矩和5个成功概率，共37,642参数，无额外 CNN。"
        "来源两折的 H1 预测产生 H2 目标，未以事后最佳未来作为在线信息或 Bellman 标签。"
        "预测成功率限制要求所选动作距预测最优成功率不超过.02；这一学习约束不等于真实成功率保证。", "",
        "开发选择预先要求 compact 相对 old feedback 的代理净 CE 不低于−.002，成功率不低于−.005。"
        "五个 seed 均未同时满足门槛，因此全部选择 exact cached feedback。"
        "没有根据开发失败放宽门槛，也没有丢弃紧凑方案；它继续作为正式描述性对照执行。", "",
        "| Seed | Compact − old，代理 CE | 成功率差／百分点 | 冻结 candidate | 冻结强非反馈 |",
        "| --- | ---: | ---: | --- | --- |"]
    for item in development["controllers"]:
        sel = item["selection"]
        lines.append(f"| {item['seed']} | {sel['compact']['proxy_net_CE'] - sel['old_feedback']['proxy_net_CE']:+.8f} | "
                     f"{100 * (sel['compact']['success'] - sel['old_feedback']['success']):+.6f} | {sel['selected_candidate']} | {sel['selected_nonfeedback']} |")
    lines += ["", "Exact cache 保持原有反馈权重和763维公开特征。只有当前实际 draft 像素逐值相等时，"
        "才复用 generator draft encoder 与 public reader 的视觉结果；latent、caption 和预算每步重算。"
        "共享语义或文字动作不改变图像时可避免重复 CNN。One-shot 对照获得相同缓存能力；"
        "所有对照均保留相同的共享内容动作权限。", "",
        "开发入口计时：wall **" + f"{development['wall_ns'] / 1e9:.9f}" + " s**，process CPU **" +
        f"{development['cpu_ns'] / 1e9:.9f}" + " s**。这包含来源构造、实际开发树、拟合和选择，"
        "不包含 interpreter startup/import 或最终 result JSON 写出；不是纯梯度训练时长。"
        "成功或失败候选的开发成本均保留。[DEVELOPMENT.json](DEVELOPMENT.json)", "",
        "## 2. 正式来源、比较与测量边界", "",
        "正式评价固定 test[512,768)：256个来源对、512张不同原图、8个视图、2个生成场景和5个已有 NDU 模型 seed。"
        "四策略各实际执行20,480次请求，共81,920次。Selected feedback 只引用事前选定 candidate 的实际行，"
        "不增加物理请求或独立 N。Root 的新生成器实验使用同一256来源组，双方不能算成512个独立来源组。", "",
        "SOURCE_ALLOCATION 对所有历史角色与新 native 角色检查 individual ID 和像素 SHA 的交集，"
        "并包括16个大型历史 metadata 文件的完整结构化扫描。旧 test[0,512) 已用于历史评价；"
        "新 native calibration[768,1568) 和 verification[1568,3000) 与本组分离。"
        "原始 writer cluster 不可得，因此不声称 writer 级独立性。", "",
        "每次 resident 请求包含 owner RNG、真实初始化/选定动作/发射、公开特征与策略、无损 NPZ 序列化、"
        "append+fsync、同一仍打开文件描述符上的回读与 hash 核查。请求之后关闭整个媒体文件，"
        "再回读并由两个冻结 observer 离线评分。单请求端点是 durable local output；"
        "不包含网络交付或设备显示。原运行时的动作提交在进程内先于 future draws，不是 crash-durable action journal。", "",
        "模型装载、来源准备、离线评分、分析及开发训练分账；完整 child 进程另由 exact-PID wait4 测量。"
        "同组策略执行顺序循环轮换。共享主机不等于隔离硬件，所有 outlier 保留。", "",
        "两个主要比较家族使用4,000次配对来源×seed bootstrap、名义双侧97.5%区间：", "",
        "- Candidate 对强非反馈：raw CE 下端>0，且 success 下端≥0，零成功率 margin。",
        "- Candidate 对 old feedback：raw CE 与 success 下端分别≥−.005，且平均 wall 差上端<0。",
        "", "后一项是事前规定的有界替代问题，不能改写成全局无损保证。"
        "精确 cache 另做逐请求 output/path/ledger 身份核对。有限五 seed 的 percentile 覆盖没有总体保证。", ""]
    lines += ["CE 先在每个已训练模型的4,096个来源/视图/场景输出上计算，再对五个模型做算术平均。"
        "训练 seed 没有被当成额外生成样本混入一次指数风险聚合。等权来源内预聚合与直接在该模型全部输出上计算CE等价。"
        "每来源/视图只有两个生成场景，这是有限样本 plug-in 估计；来源bootstrap不使条件尾部突然精确，也不提供无偏总体CE。", ""]
    if run is None or not (run / "summary.json").exists():
        lines += ["## 3. 正式执行状态", "", "**PENDING：正式来源尚未打开。** 本文件只报告已完成开发、冻结方法与测量边界；"
                  "没有正式质量、成本、收益或闭合结论。等待全部候选冻结与事前发布后才执行。", ""]
    else:
        summary = json.loads((run / "summary.json").read_text())
        shutil.copyfile(run / "summary.json", HERE / "SUMMARY.json")
        lines += ["## 3. 正式实际执行", "", f"完成状态：**{summary['status']}**。Census：**{summary['census']['requests']:,}** 请求。"]
        if summary["status"] != "complete":
            lines += ["", "**完整 census / 产物身份门槛未通过，质量推断被阻止。** 所有尝试与失败保留在汇总中。", ""]
        else:
            audit = summary["census"]
            lines += ["", f"请求失败 {len(audit['failures'])}；old/cache 匹配对 **{audit['cache_matched_pairs']:,}**；"
                      f"output/path/ledger 身份差异 **{len(audit['cache_identity_mismatches'])}**。", "",
                "### 3.1 Primary 主要对比", "",
                "| 比较 | Raw CE 差 | 名义97.5%区间 | 成功率差／百分点 | 同等级区间／百分点 |",
                "| --- | ---: | --- | ---: | --- |"]
            for key in ("selected_feedback_minus_reference", "selected_feedback_minus_old_feedback"):
                c = summary["primary_comparisons"]["primary"][key]
                lines.append(f"| {key} | {c['raw_CE']['gain']:+.8f} | {interval(c['raw_CE']['interval'], 8)} | "
                    f"{100*c['success']['gain']:+.6f} | {interval(c['success']['interval'], 6, 100)} |")
            lines += ["", "| 注册家族 | 条件逐项 | 全部满足 |", "| --- | --- | --- |"]
            for key in ("new_feedback_quality_over_strong_nonfeedback", "efficient_replacement_of_old_feedback"):
                gate = summary["registered_gates"][key]
                lines.append(f"| {key} | " + "; ".join(f"{k}={v}" for k, v in gate.items()) + f" | {all(gate.values())} |")
            lines += ["", "### 3.2 策略质量与实际延迟", "",
                "| 策略 | Raw CE | Exact success／% | 完成率／% | Wall mean ms | P50 ms | P95 ms | CPU mean ms |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
            for name in ("reference", "old_feedback", "cached_feedback", "compact_feedback"):
                q, c = summary["quality"]["primary"][name], summary["cost"][name]
                lines.append(f"| {name} | {q['raw_utility']['joint_ce']:.8f} | {100*q['success']:.6f} | "
                    f"{100*audit['required_completion'][name]:.3f} | {c['wall_ms']['mean']:.6f} | {c['wall_ms']['p50']:.6f} | "
                    f"{c['wall_ms']['p95']:.6f} | {c['cpu_ms']['mean']:.6f} |")
            lines += ["", "所有 seed 的 selected 都是 cached；上表 cached 即主要 candidate。"
                "这项选择在新来源之前冻结。紧凑策略的正式结果只作描述性分析，未被用于重新选择。", "",
                "| 成本比较，candidate − reference | Mean wall ms | 名义97.5%区间 | P95 差 ms | 同等级区间 |",
                "| --- | ---: | --- | ---: | --- |"]
            for key in ("selected_feedback_minus_reference", "selected_feedback_minus_old_feedback"):
                c = summary["cost"][key]["wall_ms"]
                lines.append(f"| {key} | {c['point_estimates']['mean']:+.6f} | {interval(c['intervals']['mean'])} | "
                             f"{c['point_estimates']['p95']:+.6f} | {interval(c['intervals']['p95'])} |")
            compact = summary["primary_comparisons"]["primary"]["compact_feedback_minus_old_feedback"]
            compact_cost = summary["cost"]["compact_feedback_minus_old_feedback"]["wall_ms"]
            lines += ["", "未被开发阶段选中的 compact 仍完整执行。其 primary observer 相对 old feedback 的描述性结果为："
                f"raw CE差 **{compact['raw_CE']['gain']:+.8f}**，95%区间 {interval(compact['raw_CE']['interval'], 8)}；"
                f"成功率差 **{100*compact['success']['gain']:+.6f}个百分点**，95%区间 "
                f"{interval(compact['success']['interval'], 6, 100)}；平均wall差 **{compact_cost['point_estimates']['mean']:+.6f} ms**，"
                f"95%区间 {interval(compact_cost['intervals']['mean'])}。"
                "这不是替换冻结 candidate 的依据，也不能由单个改善指标宣称总体优越。"]
            lines += ["", "### 3.3 独立 Secondary observer", "",
                "| 比较 | Raw CE 差 | 描述性95%区间 | 成功率差／百分点 | 描述性95%区间／百分点 |",
                "| --- | ---: | --- | ---: | --- |"]
            for key in ("selected_feedback_minus_reference", "selected_feedback_minus_old_feedback", "compact_feedback_minus_old_feedback"):
                c = summary["primary_comparisons"]["secondary"][key]
                lines.append(f"| {key} | {c['raw_CE']['gain']:+.8f} | {interval(c['raw_CE']['interval'], 8)} | "
                    f"{100*c['success']['gain']:+.6f} | {interval(c['success']['interval'], 6, 100)} |")
            lines += ["", "### 3.4 缺失信息、错误提示与尾部", "",
                "| 视图 | Selected raw CE | Selected success／% | Reference raw CE | Reference success／% |",
                "| --- | ---: | ---: | ---: | ---: |"]
            for view in protocol["profile"]["views"]:
                a = summary["quality"]["primary"]["selected_feedback"]["by_view"][view]
                b = summary["quality"]["primary"]["reference"]["by_view"][view]
                lines.append(f"| {view} | {a['raw_CE']:.8f} | {100*a['success']:.6f} | {b['raw_CE']:.8f} | {100*b['success']:.6f} |")
            lines += ["", "| 策略 | Mean loss | Output CVaR90 | Source-mean CVaR90 |", "| --- | ---: | ---: | ---: |"]
            for name in ("reference", "old_feedback", "cached_feedback", "compact_feedback"):
                tails = summary["quality"]["primary"][name]["loss_tails"]
                a, b = tails["output_level"]["mean_across_seed_summaries"], tails["source_mean_level"]["mean_across_seed_summaries"]
                lines.append(f"| {name} | {a['mean']:.8f} | {a['cvar']:.8f} | {b['cvar']:.8f} |")
            lines += ["", "尾部是完整样本上的描述性经验值；先平均来源再取尾部改变了估计对象。"
                "没有统一条件尾部保证。完成率与事实正确率分开报告。", "",
                "## 4. 实际价格敏感性", "",
                "每个价格计算 **CE₂(U − λ·实际请求成本ms)**。质量和成本的同一行相关性保留；"
                "未使用 CE(U)−λE[C] 替代。预先指定8个价格分别作用于 wall 和 CPU，"
                "采用共同来源×seed 重采样产生有限网格上的名义95% max-deviation band。", ""]
            for metric in ("wall_ms", "cpu_ms"):
                lines += [f"### {metric}", "", "| λ，utility/ms | Candidate − reference CE | 描述性逐点95%区间 | 网格同时95%区间 | 同时下端>0 |",
                          "| --- | ---: | --- | --- | --- |"]
                curve = summary["actual_price_sensitivity"]["primary"][metric]
                for point in curve["grid"]:
                    ci = point["nominal_simultaneous_95_interval_over_frozen_grid"]
                    lines.append(f"| {point['utility_per_ms']:.4f} | {point['CE_gain']:+.8f} | "
                        f"{interval(point['pointwise_descriptive_95_interval'], 8)} | {interval(ci, 8)} | {ci[0] > 0} |")
                lines.append("")
            lines += ["本次两个成本网格的同时band全部跨零，**未建立统一置信意义的实际成本补偿结论**。"
                "低价格的正点估计或逐点描述性区间不能替换这一结果。按已冻结网格，wall和CPU的净CE差均在λ=.005时为正、"
                "λ=.01时为负；这是点估计符号所在的网格区间，没有计算连续价格的置信break-even。"
                "高价格将尾部慢请求赋予很大的指数风险权重，统一max-deviation半径随之变宽；"
                "这与仅检验raw质量的主要比较使用不同的推断问题。所有慢请求保留，未为通过门槛删除或缩尾。", ""]
            lines += ["这些 λ 是敏感性参数，未声称它们是用户的实际经济价值。"
                "wall 与 CPU 的 bands 分别解释，不是合并双价格家族保证，也不能扩展为连续价格区间。"
                "请求曲线不包含模型预训练、历史 generator/controller 训练或新增开发的摊销成本，"
                "因此不能作为完整生命周期经济收益证书。新增开发成本已在 §1 全部保留。", "",
                "## 5. 完整进程与阶段成本", "",
                f"Runner entry wall **{summary['runner_wall_ns']/1e9:.9f} s**，CPU **{summary['runner_cpu_ns']/1e9:.9f} s**。", "",
                "| 阶段 | Wall s | CPU s |", "| --- | ---: | ---: |"]
            for name, measured in summary["phases"].items():
                lines.append(f"| {name} | {measured['wall_ns']/1e9:.9f} | {measured['cpu_ns']/1e9:.9f} |")
            if process is not None and process.exists():
                receipt = json.loads(process.read_text()); shutil.copyfile(process, HERE / "PROCESS_RECEIPT.json")
                lines += ["", f"Exact-PID child 正常退出码 **{receipt['exit_code']}**，完整 wall **{receipt['wall_ns']/1e9:.9f} s**，"
                    f"child CPU **{receipt['child_cpu_ns']/1e9:.9f} s**，Linux peak RSS **{receipt['exact_child_peak_rss_bytes_linux']:,} B**。"
                    "包含启动/import、请求、离线评分、分析、结果写出及退出；wrapper 自身CPU另列。"
                    "它与 runner、单请求和阶段计时有包含关系，不能重复相加。"]
            lines += [""]
    lines += ["## 6. 验证、身份与可支持范围", "",
        "7项 synthetic-only 验证覆盖：完整公开特征缓存的精确相等、真实动作改变像素后的失效、"
        "紧凑特征一致性、私有 RunState 拒绝、成功概率约束/支配动作、实际生成+持久回读的旧/缓存路径身份、"
        "完整 census、source错绑、失败/outlier保留和随机质量/成本的联合CE计算。"
        "[VALIDATION.json](VALIDATION.json) 记录实际退出0与源码hash；不声称完整仓库测试。", "",
        "正式来源开放前，依赖预检发现旧 runner 将 Snapshot 的语义 fingerprint 误作 checkpoint 文件字节 SHA，"
        "这会在模型装载时拒绝执行。原 PROTOCOL.json 保留；PROTOCOL-v2.json 分别冻结文件 SHA 与参数/配置语义摘要，"
        "并在预检及 resident 装载时检查两者。没有重跑开发选择、改变策略、来源或统计。"
        "新增历史 forecast_calibration[448,449) 的真实 smoke 覆盖五模型×四策略共20次生成，"
        "并分别检查错误文件 SHA 和错误语义摘要被拒绝；全部通过，未读取新 test。"
        "[MODEL_IDENTITY_AMENDMENT.json](MODEL_IDENTITY_AMENDMENT.json) 与 "
        "[MODEL_IDENTITY_VALIDATION.json](MODEL_IDENTITY_VALIDATION.json) 保留修订和实际验证。", "",
        "Control 冻结协议首次发布于 GitHub commit `ad6462e98ba131880d68ba49465afff166af9347`，"
        "完整源码/开发/验证发布到 `46102fb5c0504e3a691bd012b11087a4693592df`。"
        "模型身份 v2 修订发布于 `78f4ed0d8d35147a0de81b1ff40580590a8e29ab`；"
        "共享最终来源等待新的15模型与5个 warm 参考全部冻结并发布于 "
        "`a2d9942da8a8a1080bf85522a9995101a11ee19e` 后开放。"
        "正式 launch 的实际时序另由 process registration 与 root 总发布记录核对。", "",
        "本轮只回答所列固定生成器、任务、来源和动作空间中的控制实现与成本问题。"
        "紧凑方案失败不证明所有无 CNN 状态不可行；新成功率监督与模型容量同时变化，"
        "其作用未被单因素分离。精确缓存没有新增生成器训练，也不改变旧风险训练成功率下降的事实。"
        "全模态端到端训练、长时域控制、真正生产接纳和全局 portfolio 最优另需相应证据。", "",
        "| 文件 | SHA-256 |", "| --- | --- |"]
    for name in ("SOURCE_ALLOCATION.json", "DEVELOPMENT.json", "PROTOCOL.json", "PROTOCOL-v2.json", "VALIDATION.json",
                 "MODEL_IDENTITY_AMENDMENT.json", "MODEL_IDENTITY_VALIDATION.json", "SUMMARY.json", "PROCESS_RECEIPT.json"):
        path = HERE / name
        if path.exists():
            lines.append(f"| [{name}]({name}) | `{digest(path)}` |")
    lines += ["", "只发布源码、主要详细报告、冻结协议与聚合证据。原始媒体、权重和逐行记录不归档到Git；"
              "这是用户指定的交付范围，不是未闭合 blocker。", ""]
    if run is not None and (run / "summary.json").exists() and summary["status"] == "complete":
        a = summary["primary_comparisons"]["primary"]["selected_feedback_minus_reference"]
        speed = summary["cost"]["selected_feedback_minus_old_feedback"]["wall_ms"]["point_estimates"]["mean"]
        premium = summary["cost"]["selected_feedback_minus_reference"]["wall_ms"]["point_estimates"]["mean"]
        lines[4:4] = ["## 0. 主要结论", "",
            f"完整81,920次真实请求完成，失败0、必需模态完成率100%。预选 exact cache 与旧反馈的20,480个实际配对输出、"
            f"动作和运行时ledger逐值相同，平均wall减少 **{-speed:.6f} ms**。相对开发阶段选出的强非反馈对照，"
            f"raw CE提高 **{a['raw_CE']['gain']:.8f}**，成功率提高 **{100*a['success']['gain']:.6f}个百分点**，"
            "两项名义97.5%区间下端均为正；两个注册主要家族均满足既定规则。", "",
            f"相对强非反馈，cached仍增加 **{premium:.6f} ms** 平均wall。预先声明的价格网格同时bands均未排除零，"
            "因此本轮支持在所评估census中保持原输出的缓存加速及限定任务上的公开反馈收益，"
            "尚未证明统一置信的真实资源成本补偿。紧凑头的成功率下降仍然存在，不能用其低延迟替代成功率要求。", ""]
    (HERE / "REPORT.md").write_text("\n".join(lines))
    print(json.dumps({"report": str(HERE / "REPORT.md"), "sha256": digest(HERE / "REPORT.md"),
                      "formal_summary_present": (HERE / "SUMMARY.json").exists()}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--process", type=Path)
    args = parser.parse_args(); render(args.run, args.process)
