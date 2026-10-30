"""Self-contained Chinese report presentation; no evidence I/O or scoring."""

import html

from .report_dynamics import dynamics_section

ARM = {
    "analytic": "解析 Call–Put",
    "matched_c1": "匹配 C1",
    "sigmoid": "Sigmoid",
    "ordinary": "普通控制器",
    "frozen_flow": "冻结控制器",
}
TASK = {"selective_copy": "选择性复制", "mqar": "多查询关联检索"}
BUDGET = {"cpu30": "≤30 秒训练 CPU", "updates384": "≤384 次更新"}
STATUS = {"passed": "通过", "failed": "未通过", "reference_unresolved": "参照未解决"}
GROUP = {
    "all": "全部",
    "content": "内容",
    "boundary_input": "边界输入",
    "boundary_dynamics": "动力学",
    "rate_head": "率头",
}
BRANCH = "https://github.com/TrillionniumFoundation/hepta-private-ci/tree/research/hcsn-callput-rebuild-20261028"
BASE = "https://github.com/TrillionniumFoundation/hepta-private-ci/blob/research/hcsn-callput-rebuild-20261028/"


def e(value):
    return html.escape(str(value), quote=True)


def f(value, precision=5):
    return "—" if value is None else f"{value:.{precision}g}"


def pct(value):
    return f"{100 * value:.3f}%"


def yes(value):
    return "是" if value else "否"


def stats(value, percent=False):
    factor, suffix = (100, "%") if percent else (1, "")
    return f"{value['mean'] * factor:.5g} ± {value['sample_sd'] * factor:.4g}{suffix}"


def raw(value, percent=False):
    return " / ".join(f(v * 100 if percent else v, 6) for v in value["seed_values"])


def table(headers, rows, caption=""):
    header = "".join(f"<th>{e(v)}</th>" for v in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{e(v)}</td>" for v in row) + "</tr>" for row in rows
    )
    return f'<div class="table-wrap"><table><caption>{e(caption)}</caption><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>'


def detail(title, content):
    return f"<details><summary>{e(title)}</summary>{content}</details>"


def fig(images, name, caption):
    return f'<figure><img src="{images[name]}" alt="{e(caption)}"><figcaption>{e(caption)}</figcaption></figure>'


def label(row):
    return [TASK[row["task"]], ARM[row["arm"]], str(row["seed"]), BUDGET[row["regime"]]]


def scientific_definition(data):
    accounting = {}
    for row in data["training"]["candidates"]:
        accounting[row["specification"]["arm"]] = row["accounting"]
    counts = table(
        ["控制器", "总参数", "可训练参数", "内容", "边界输入", "动力学", "率头"],
        [
            [
                ARM[arm],
                r["parameters_total"],
                r["parameters_trainable"],
                *[
                    r["group_trainable"][g]
                    for g in (
                        "content",
                        "boundary_input",
                        "boundary_dynamics",
                        "rate_head",
                    )
                ],
            ]
            for arm, r in accounting.items()
        ],
    )
    return f"""
<section id="definition"><h2>1. 实际被实现和检验的模型</h2>
<p>本轮将 Hepta 定义为一个可训练的连续边界控制器：共享安全距离驱动 Call–Put 两通道，
快边界与慢恢复状态形成反馈，控制共享关联矩阵的遗忘率和写入率。训练采用普通 BP/BPTT，
无需为神经元阈值配置替代梯度。模型输出通过当前关联矩阵读出；不存在直接读取标签或最后状态回放答案的路径。</p>
<p><strong>金融来源的精确范围。</strong>He–Xiong 的 <em>Rollover Risk and Credit Risk</em> 包含债务到期、
滚续融资、流动性与违约边界的联立结构。本轮使用的是从最优停止结构得到的<strong>简化永续 Put</strong>，
并以 C=V+P−K 构造 Call 型非负余值，再进行归一化；没有实现原文完整的滚续债务定价系统，
也没有把原文全部 equity/default 解析结果逐字搬为神经元。[HX]</p>
<div class="equation">β = κ/(1+κ)，B = βK，x = log(V/B) = v − q − log β，v = log V，q = log K。</div>
{
        table(
            ["区域", "Call 通道 a", "Put 通道 p"],
            [
                ["x ≤ 0", "0", "1 − β exp(x)"],
                ["x > 0", "1 − (1+κ)/(κ exp(x)+exp(−κx))", "exp(−κx)/(1+κ)"],
            ],
        )
    }
<p>这里 p=P/K，a=C/(V+P)。边界值满足 a(0)=0、a′(0)=0、p(0)=1/(1+κ)、p′(0)=−β。
两个通道均为 C1，但二阶导数在边界跳变。因此普通一阶自动微分具有明确依据，
不能把它们描述成处处无限阶光滑。固定 κ 时，(a,p) 只依赖一个标量 x，其对 (v,q,z) 的雅可比秩至多为 1；
“双通道”并不等于两个独立状态自由度。共享边界 B 是本轮简化合同的参数化结果，并非每一步重新求解原金融模型的完整自由边界。[T]</p>
<div class="equation">τ<sub>v</sub> v̇ = −v + I<sub>v</sub><br>
τ<sub>q</sub> q̇ = −q + q<sub>*</sub> + g<sub>C</sub>(a−a<sub>*</sub>) + g<sub>P</sub>(p−p<sub>*</sub>) − (z−z<sub>*</sub>) + I<sub>b</sub><br>
τ<sub>z</sub> ż = −z + g<sub>z</sub>p，q<sub>*</sub>=−x<sub>*</sub>−log β，z<sub>*</sub>=g<sub>z</sub>p(x<sub>*</sub>)。</div>
<p>初态为 (0,q<sub>*</sub>,z<sub>*</sub>)，包含参数依赖并保留梯度。对有限原始参数，在实数算术下，参数化给出 κ∈(.25,4)、
τ<sub>v</sub>,τ<sub>q</sub>∈(.25,8)、τ<sub>z</sub>∈(τ<sub>q</sub>+.25,32)，三个反馈增益位于 (0,4)，
两个输入电流通过 3tanh 投影限制在 [−3,3]；浮点 sigmoid 饱和时可取参数区间端点，不能把严格开区间当成浮点保证。
静态 Call/Put 算子可解析计算，v/q/z 的耦合轨迹仍用 ETD2 数值积分。
正式最大内步长固定为 h=1/16；未按验证或测试任务成绩选择步长。</p>
<h3>对照回答的具体问题</h3>
{
        table(
            ["对照", "实际差异与归因"],
            [
                [
                    "analytic 与 matched_c1",
                    "同样保留边界值、一阶粘贴和近界局部约束；主要检验全局函数形状，不单独识别自由边界约束有没有价值。",
                ],
                [
                    "sigmoid",
                    "同参数张量布局，a+p=1，反馈存在代数冗余；名义参数数目相同不保证功能自由度相同。",
                ],
                [
                    "ordinary",
                    "采用 sigmoid 状态演化，但率头读取不同的状态特征；比较整体控制器，而非单独替换 Call/Put。",
                ],
                [
                    "frozen_flow",
                    "冻结控制器参数而保留状态演化，内容与率头仍训练；是不同可训练参数数目的诊断对照。",
                ],
            ],
        )
    }
{counts}
<p>总参数数目不是“每个标量均有效学习”的证明。选择性复制只使用部分地址列，活动情况应看实际梯度及更新记录。
所有控制器共享显式任务解析器、Q/K/V 投影、读出和 rank-one delta 矩阵记忆；这些共享部件的收益不能归为 Hepta 独有创新。
原始参数初值跨控制器一致，但由算子导出的恢复平衡 z<sub>*</sub>可不同，不能声称所有初始状态字节相同。</p>
<p>解析器依据已知 one-hot role/selection 字段使用 &gt;0.5 等离散判断。固定观测元数据下，它不阻断本轮模型参数训练；
它<strong>不证明从未知模态输入、可学习编码器到角色预测再到输出的整条路径都可微</strong>。本轮没有训练通用输入编码器来发现这些角色和地址。</p>
</section>"""


def task_results(data, images):
    protocol, primary = data["protocol"], data["primary"]
    rows = []
    for row in data["score_groups"]:
        m = row["metrics"]
        rows.append(
            [
                TASK[row["task"]],
                ARM[row["arm"]],
                BUDGET[row["regime"]],
                stats(m["accuracy"], True),
                raw(m["accuracy"], True),
                stats(m["cross_entropy"]),
                raw(m["cross_entropy"]),
                stats(m["sequence_accuracy"], True),
                raw(m["sequence_accuracy"], True),
            ]
        )
    comparisons = []
    for row in primary["comparisons"]:
        scale = 100 if row["metric"] == "accuracy" else 1
        comparisons.append(
            [
                TASK[row["task"]],
                BUDGET[row["regime"]],
                ARM[row["comparator"]],
                "accuracy（百分点）" if scale == 100 else "CE（对照−analytic）",
                " / ".join(f(v * scale) for v in row["paired_seed_differences"]),
                f(row["mean"] * scale),
                "[" + ", ".join(f(v * scale) for v in row["adjusted_ci"]) + "]",
                row["family_size"],
                yes(row["quality_floor_passed"]),
                yes(row["metric_improvement_gate"]),
            ]
        )
    initial = table(
        [
            "任务",
            "控制器",
            "种子",
            "step0 test accuracy",
            "step0 test CE",
            "step0 sequence accuracy",
        ],
        [
            [
                TASK[r["task"]],
                ARM[r["arm"]],
                r["seed"],
                pct(r["test"]["accuracy"]),
                f(r["test"]["cross_entropy"]),
                pct(r["test"]["sequence_accuracy"]),
            ]
            for r in primary["step0"]
        ],
    )
    selected = []
    candidate_map = {
        r["specification"]["id"]: r for r in data["training"]["candidates"]
    }
    for row in primary["results"]:
        checkpoint = candidate_map[row["id"]]["checkpoints"][row["checkpoint"]]
        selected.append(
            [
                *label(row),
                f(row["learning_rate"]),
                row["checkpoint"],
                checkpoint["updates"],
                f(checkpoint["training_cpu_seconds"]),
                pct(row["validation"]["accuracy"]),
                pct(row["test"]["accuracy"]),
                f(row["test"]["cross_entropy"]),
                row["checkpoint_sha256"][:12],
            ]
        )
    sensitivities = []
    for row in primary["results"]:
        s = row["solver_sensitivity"]
        sensitivities.append(
            [
                *label(row),
                f(s["max_abs_logit_difference"]),
                f(s["relative_logit_l2_difference"]),
                f(
                    s["refined_metrics"]["accuracy"]
                    - s["registered_metrics"]["accuracy"]
                ),
                f(
                    s["refined_metrics"]["cross_entropy"]
                    - s["registered_metrics"]["cross_entropy"]
                ),
            ]
        )
    return f"""<section id="tasks"><h2>2. 两个任务、两种预算和全部种子结果</h2>
<p>选择性复制每条序列从可见选择标记中保留 4 个值，并按因果计数器顺序查询；多查询关联检索使用可见 KEY→VALUE 语法，
包含覆盖写入与覆盖前后查询。序列长 32，地址词表 16，值类别 8，随机均匀分类基线为 12.5%。
解析器不读取标签、不把值放入查询地址，也不读取未来 token；但这些明确的地址先验显著降低了学习问题的难度。
它们是合成记忆任务，并非自由文本、图像、音频或全模态大模型评测。</p>
<p>每任务 train/validation/test 为 {protocol["split_counts"]["train"]}/{protocol["split_counts"]["validation"]}/{protocol["split_counts"]["test"]} 条。
5 个控制器 × 2 个任务 × 3 个种子 × 2 个学习率形成 60 个候选。每种预算分别在两个学习率与两个允许终点中，
按最低验证 CE 选择；CPU30 可选 cpu15/cpu30，updates384 可选 update192/update384。因此“384 次预算”不代表每个选中模型都刚好更新 384 次。
全部训练完成后才封存验证选择并读取测试分数。CPU30 是训练更新所耗进程 CPU 的上限，和总进程耗时、墙钟时间分开统计。[P]</p>
{fig(images, "task_quality", "20 个任务×控制器×预算组。实点为三个种子，误差线为种子样本标准差；不是置信区间。两个预算分别解释。")}
<h3>20 组完整汇总：mean ± sample SD 与三个原始种子</h3>
<p>原值依次为 81301 / 81302 / 81303。accuracy 与 sequence accuracy 的原值和均值均按百分数显示；
sequence accuracy 要求同一序列全部查询正确。CE 为查询位置平均交叉熵。下表不删除低质量或未获益控制器。</p>
{table(["任务", "控制器", "预算", "accuracy 均值±SD", "accuracy 原值 %", "CE 均值±SD", "CE 原值", "sequence 均值±SD", "sequence 原值 %"], rows)}
{detail("全部 60 个选中别名、实际终点与预算用量", table(["任务", "控制器", "种子", "预算", "学习率", "checkpoint", "实际更新", "训练 CPU 秒", "验证 accuracy", "测试 accuracy", "测试 CE", "CP SHA 前缀"], selected))}
{detail("全部 30 个未训练 step0 测试结果", initial)}
<h3>24 个预声明指标比较：不能跨指标挑选赢家</h3>
<p>每一行以三个配对种子计算均值差和 Student-t 区间，自由度为 2。accuracy 的正差表示 analytic 更高；
CE 的正差表示 analytic 更低。主要比较为 analytic 对 matched C1，每个指标 family 有 4 次比较；
次要比较覆盖 sigmoid/ordinary，每个指标 family 有 8 次比较，分别做 Bonferroni 校正。
accuracy 和 CE 是<strong>分开的 family</strong>，没有跨两个指标的整体错误率控制。n=3 时无法可靠检验正态假设，区间属于探索性证据。</p>
<p>三个配对种子共享同一固定测试集，区间描述训练种子变化下的分数差异，没有计入更换测试样本或任务分布的不确定性，
也不是总体多模态性能区间。</p>
<p>指标提升门要求：比较双方每个种子验证 accuracy≥90%，analytic 每个种子测试 accuracy≥90%；
校正区间下界&gt;0；平均效果至少为 accuracy 0.5 个百分点或 CE 0.01。质量门、效果门和区间门须同时满足。
未通过不等于已证明等效；某一指标通过也不自动变成跨任务、跨预算或跨模态的总体优势。</p>
{fig(images, "comparison_intervals", "全部 24 个指标区间；绿色仅表示该行通过原注册的指标提升门。不能按图中某个单独赢家作一般优越性结论。")}
{table(["任务", "预算", "analytic 对照", "指标 / 方向", "三个配对差", "平均差", "校正区间", "family 次数", "质量门", "指标提升门"], comparisons)}
{detail("全部选中 checkpoint 的测试前 64 条 h 与 h/2 敏感性", "<p>该诊断不参与选择、不替换主分数；下列差为 h/2 − h。它不是新的独立统计样本，也不是联合连续系统真解验证。</p>" + table(["任务", "控制器", "种子", "预算", "最大 logit 绝对差", "logit 相对 L2", "accuracy 差", "CE 差"], sensitivities))}
</section>"""


def training_section(data):
    training = data["training"]
    cost, activity, phase_rows, silent = [], [], [], []
    for row in training["candidates"]:
        s, p, d = row["specification"], row["process_cost"], row["observed_diagnostic"]
        base = [TASK[s["task"]], ARM[s["arm"]], s["seed"], f(s["learning_rate"])]
        cost.append(
            [
                *base,
                row["updates"],
                f(row["training_cpu_seconds"]),
                f(row["total_process_cpu_seconds"]),
                f(p["child_total_cpu_seconds"]),
                f(p["external_wall_seconds"]),
                f(p["peak_rss_bytes"] / 2**20),
                pct(row["step0_train"]["accuracy"]),
                pct(row["final_train"]["accuracy"]),
            ]
        )
        group_cells = []
        for group in ("content", "boundary_input", "boundary_dynamics", "rate_head"):
            a = row["parameter_activity"][group]
            changed = sum(r["changed_numel"] for r in a["parameters"])
            total = sum(r["numel"] for r in a["parameters"])
            group_cells.append(
                f"{changed}/{total}; Δ={f(a['update_l2'])}; G={f(a['gradient_l1_sum'])}"
            )
        activity.append([*base, *group_cells])
        phase_rows.append(
            [
                *base,
                f(d["margin_min"]),
                f(d["margin_max"]),
                f(d["call_min"]),
                f(d["call_max"]),
                d["sampled_post_tick_sign_changes"],
                d["episodes_with_sampled_sign_change"],
                pct(row["final_train"]["accuracy"]),
            ]
        )
        if (
            s["arm"] == "analytic"
            and d["call_identically_zero_on_probe"]
            and row["final_train"]["accuracy"] >= 0.9
        ):
            silent.append(
                [
                    s["id"],
                    pct(row["final_train"]["accuracy"]),
                    f(d["margin_min"]),
                    f(d["margin_max"]),
                    f(d["call_max"]),
                ]
            )
    totals = [
        [
            "训练更新 CPU 合计",
            training["training_update_cpu_seconds"],
            "用于训练预算；不含评估与文件 I/O",
        ],
        [
            "60 个候选内部 total_process CPU",
            training["candidate_internal_total_cpu_seconds"],
            "候选函数计时范围；不是解释器完整生命周期",
        ],
        [
            "60 个成功子进程完整 CPU",
            training["successful_child_total_cpu_seconds"],
            "wait4 user+system，含导入、评估及进程内全部工作",
        ],
        [
            "失败启动完整 CPU",
            training["unsuccessful_child_total_cpu_seconds"],
            "单列环境启动失败；不混成模型训练失败",
        ],
        [
            "选择和测试评分子进程 CPU",
            training["selection_and_scoring_child_cpu_seconds"],
            "按 phase_execution 回执计量",
        ],
        [
            "数值附录逐 checkpoint CPU",
            data["numerics"]["measured_checkpoint_cpu_seconds"],
            "附录自计时范围；不等于完整子进程/全研究费用",
        ],
        [
            "调度会话墙钟之和",
            training["orchestration_session_wall_seconds_sum"],
            "训练并发调度耗时；不能与 CPU 秒混加",
        ],
    ]
    return f"""<section id="training"><h2>3. 训练成本、参数活动与机制归因</h2>
{table(["计量项", "秒", "解释"], [[name, f(value), description] for name, value, description in totals])}
<p>训练采用 4 个并发 worker，每个 worker 的 Torch 线程为 1。候选预算比较使用累计训练更新 CPU，
完整成本另以 wait4 记录。峰值 RSS 是各完整子进程的实际观测，包含 Python/Torch、参数、临时数组等，
不能当成神经元状态大小。60 个成功子进程中最大峰值 RSS 为 {f(training["maximum_successful_child_peak_rss_bytes"] / 2**20)} MiB；
不同进程峰值发生时刻不同，不能相加充当机器同时峰值。没有测量能耗，也没有统一计量整项研究全部开发、审计、归档和系统开销。</p>
{detail("60 个候选完整成本与 step0→最终训练 accuracy", table(["任务", "控制器", "种子", "学习率", "最终更新", "更新 CPU 秒", "内部 total CPU", "完整 child CPU", "child 墙钟秒", "child 峰值 MiB", "step0 train", "最终 train"], cost))}
<h3>参数确实发生了什么变化</h3>
<p>下表每格为“改变标量数 / 总标量数；更新 L2；训练累计梯度 L1”。它描述候选完成全部训练后的终点，
<strong>不自动代表被验证选中的 CPU30 早期 checkpoint</strong>。冻结参数零变化是设计的一部分；
某个任务未用到的地址列零梯度也不应被名义参数数掩盖。选中模型的数值梯度另见下一节。</p>
{detail("60 个候选的四组参数活动", table(["任务", "控制器", "种子", "学习率", "内容", "边界输入", "动力学", "率头"], activity))}
<h3>任务准确率不能替代脉冲证据</h3>
<p>候选最终训练模型在固定前 32 条训练序列上保存了每个 token 结束时的 margin/Call/Put/遗忘率/写入率。
这些是<strong>post-tick 采样</strong>：相邻符号变化数不是精确事件时刻，不能据此宣称离散 spike 数、事件稀疏性、
不应期、生物脉冲拟合或周期轨道在已训练模型中出现。</p>
<p>实际数据中，满足“analytic 的该 32 条探针 Call 恒为零且整体最终 train accuracy≥90%”的候选有
<strong>{len(silent)}</strong> 个。高准确率可以与这个有限探针的 post-tick Call 恒零共存；
这不能排除内部亚步、其余训练样本或训练历史中的 Call 活动和边界穿越，也不是剥离 Call 因果作用的消融实验。
因此不能仅凭准确率判定实际使用了何种脉冲或恢复机制。</p>
{table(["实际候选 id", "整体最终 train accuracy", "探针最小 margin", "探针最大 margin", "探针最大 Call"], silent)}
{detail("全部 60 个候选 post-tick 活性观测", table(["任务", "控制器", "种子", "学习率", "margin 最小", "margin 最大", "Call 最小", "Call 最大", "相邻符号变化", "有变化序列 /32", "整体 train accuracy"], phase_rows))}
</section>"""


def numerical_section(data):
    numerical, d = data["numerics"], data["diagnostics"]
    status_rows, stages, flow_rows = [], [], []
    for record in numerical["aliases"]:
        result, alias = record["end_to_end"], record["alias"]
        status_rows.append(
            [
                *label(alias),
                STATUS[result["status"]],
                *[
                    yes(result["comparisons"][name]["passed"])
                    for name in (
                        "same_h_precision",
                        "reference_consistency",
                        "registered_h_mesh",
                    )
                ],
            ]
        )
    for name, heading in (
        ("same_h_precision", "同 h：FP32 对 FP64"),
        ("reference_consistency", "FP64：h/2 对 h/4 参照一致性"),
        ("registered_h_mesh", "FP64：注册 h 对 h/4"),
    ):
        rows = []
        for record in numerical["aliases"]:
            comp = record["end_to_end"]["comparisons"][name]
            cells = [
                f"{f(comp['gradient'][g]['relative_l2_difference'])} / {f(comp['gradient'][g]['reference_norm'])}"
                for g in GROUP
            ]
            rows.append(
                [
                    *label(record["alias"]),
                    *cells,
                    f(comp["logit_scaled_max"]),
                    f(comp["loss_absolute_difference"]),
                    yes(comp["passed"]),
                ]
            )
        stages.append(
            detail(
                heading + "：全部 24 个别名、全部梯度分组",
                table(
                    [
                        "任务",
                        "控制器",
                        "种子",
                        "预算",
                        *[GROUP[g] + "：相对误差 / ref范数" for g in GROUP],
                        "logit scaled max",
                        "CE 绝对差",
                        "该比较通过",
                    ],
                    rows,
                ),
            )
        )
    for record in numerical["dop"]:
        m = record["metrics"]
        flow_rows.append(
            [
                *label(record["alias"]),
                STATUS[record["status"]],
                f(m["scaled_state_max"]),
                f(m["directional_gradient_relative_l2"]),
                f(m["oracle_scaled_state_change"]),
                f(m["oracle_fd_gradient_relative_change"]),
                f(m["same_h_precision_directional_gradient_relative"]),
                f(record["gradient_reference_norm"]),
                " / ".join(f(x) for x in record["sampled_endpoint_margin_range"]),
                record["sampled_endpoint_sign_changes"],
            ]
        )
    qualified = []
    for run in d["qualification"]:
        for row in run["qualification"]:
            qualified.append(
                [
                    run["run"],
                    row["mode"],
                    row["case"],
                    f(row["max_step"]),
                    f(row["state_scaled_max"]),
                    f(row["gradient_l2_relative"]),
                    yes(row["passed"]),
                ]
            )
    return f"""<section id="numerics"><h2>4. 数值资格：精度、离散化和参照分别报告</h2>
<p>稳定实现使用 φ1/φ2 的近零 Taylor 分支、远区 expm1 表达及无危险 inactive branch，Call 在边界附近用二阶表达消除线性抵消。
每条序列自己的 dt 决定自己的内步数，避免同一个样本因同 batch 其他样本的步长而改变轨迹。
参数、参考平衡和 ETD 系数只在单次 forward 内缓存，保留自动微分图，优化器更新后重建。</p>
<p>最初候选 h=.25/.125 未全部达到预声明资格门，失败回执保留；随后以相同门限、同固定探针的独立工程细化选择 h=.0625。
此选择早于任务正式评分。资格约束为 state scaled max≤10⁻³、四方向梯度相对 L2≤10⁻²。
该结论限定于预定义探针；极端刚性参数压力测试仍有约百分量级的误差，状态有界不等于积分或梯度准确。</p>
{detail("早期失败与最终资格探针的原始指标", table(["run", "mode", "probe", "h", "state scaled max", "四方向 gradient rel", "通过"], qualified))}
<h3>选中 checkpoint 的固定训练探针</h3>
<p>注册范围为 24 个 analytic/matched C1 别名，涵盖两任务、三种子、两预算；实际不同物理 checkpoint 有
{numerical["summary"]["physical_checkpoints"]} 个。相同权重允许去重执行，别名全部保留。数据固定为前 4 条 TRAIN、完整 32 ticks，
目标为查询 CE；先加载原始 FP32 权重，再精确提升为 FP64。未修改权重、重新选择模型或替换主测试分数。</p>
{table(["状态口径", "按别名计数"], [["端到端 CE 梯度附录", str(numerical["end_to_end_alias_status"])], ["独立 flow DOP 附录", str(numerical["flow_alias_status"])]])}
<p>同 h 的 FP32/FP64 比较识别计算精度影响；FP64 的 h/h2/h4 比较识别内层积分网格影响。
同 h 门为每组梯度相对误差≤10⁻⁴、logit scaled max≤10⁻⁵；参照 h/2 对 h/4 门为 2.5×10⁻³ 与 2.5×10⁻⁴；
注册 h 对 h/4 门为 10⁻² 与 10⁻³。每组梯度和全参数梯度都要通过，防止大量内容参数掩盖少量边界参数。
分母使用 max(10⁻⁸,‖g<sub>ref</sub>‖)，原始范数同时保留。</p>
<p><strong>reference_unresolved</strong> 表示预定有限网格参照一致性不足，不能把 h/4 直接当真解或据此宣布注册 h 合格。
“附录执行完成”与“所有数值门通过”是两件不同的事。报告保留未通过和未解决状态，不追加网格来筛选好看的结果。</p>
{table(["任务", "控制器", "种子", "预算", "总状态", "同 h 精度", "h/2–h/4 参照", "h–h/4"], status_rows)}
{"".join(stages)}
<h3>独立 DOP853：8 个预定别名</h3>
<p>seed=81301 的两任务×两控制器×两预算，在前一条 TRAIN 的完整轨迹上独立重建参数转换、通道与 RHS。
状态参照采用 DOP853，比较原容差与更严容差；四个预定单位参数方向用两种有限差分 ε 检查一致性。
方向导数的目标是 flow 轨迹函数 <code>audit.numpy_loss</code>，<strong>不是端到端 CE，也不是完整连续雅可比</strong>。
状态容差 10⁻³、方向梯度相对误差 10⁻²；oracle/FD 一致性必须先通过才可解释资格。[N]</p>
{table(["任务", "控制器", "种子", "预算", "状态", "state scaled", "gradient rel", "oracle state Δ", "FD grad Δ", "同 h dtype grad", "ref 梯度范数", "端点 margin范围", "端点符号变化"], flow_rows)}
<p>所有固定参数梯度结论均以当前离散图为条件。内步数 ceil(dt/h) 在切换点不可按平滑函数理解；
更不能从固定 dt 的参数梯度推导对任意采样时间或离散角色解析器输入都光滑。</p>
</section>"""


def runtime_section(data, images):
    runtime = data["runtime"]
    grouped, raw_rows = {}, []
    for row in runtime["aliases"]:
        alias, case = row["alias"], row["case"]
        key = (alias["task"], alias["arm"], alias["seed"], alias["regime"])
        grouped.setdefault(key, {"alias": alias})[case["batch_size"]] = case
        raw_rows.append(
            [
                *label(alias),
                case["batch_size"],
                " / ".join(f(v * 1000, 6) for v in row["raw_cpu_seconds"]),
                " / ".join(f(v * 1000, 6) for v in row["raw_wall_seconds"]),
            ]
        )
    rows = []
    for _, row in sorted(grouped.items()):
        cells = []
        for batch in (1, 32):
            for clock in ("cpu_seconds", "wall_seconds"):
                s = row[batch][clock]
                cells.append(
                    f"{f(s['median'] * 1000)} [{f(s['minimum'] * 1000)}, {f(s['maximum'] * 1000)}]"
                )
        rows.append(
            [
                *label(row["alias"]),
                *cells,
                f(row[32]["sequences_per_second_from_median_wall"]),
            ]
        )
    quality = []
    for row in runtime["quality_join"]["comparisons"]:
        ratios = row["matched_band_cost_ratios"]
        quality.append(
            [
                TASK[row["task"]],
                BUDGET[row["regime"]],
                ARM[row["comparator"]],
                yes(row["empirical_quality_band_eligible"]),
                f(row["absolute_score_gaps"]["test_accuracy"]),
                f(row["absolute_score_gaps"]["test_cross_entropy"]),
                *[
                    f(ratios[str(batch)][clock]) if str(batch) in ratios else "不报告"
                    for batch in (1, 32)
                    for clock in (
                        "analytic_to_comparator_cpu_median_ratio",
                        "analytic_to_comparator_wall_median_ratio",
                    )
                ],
            ]
        )
    payloads = sorted(
        {
            row["case"]["state_payload"]["total_counted_payload_bytes_per_episode"]
            for row in runtime["aliases"]
        }
    )
    return f"""<section id="runtime"><h2>5. 推理成本：全部 20 个别名、两种 batch</h2>
<p>推理附录在训练期间、验证和测试评分前登记，区别于训练开始前已登记的数值附录。
计时在训练与数值检查结束后，由 root 安排空闲执行窗口；不能保证无关宿主进程完全不存在。
固定 seed81301、全部 5 个控制器×2 任务×2 预算，读取前 32 条 TRAIN；B1 使用第 0 条，B32 使用全部 32 条。
每次计时均是<strong>从初态开始的完整 32-token forward</strong>，包含 prepare_sequence 和初态构造，
不包含模型加载、磁盘 I/O 或输出校验；3 次预热、11 次计时，各轮随机化 case 顺序。</p>
<p>单 CPU 线程，eval+no_grad；CPU 返回同步，结束计时后检查有限输出与位级一致摘要。
进程 CPU 与墙钟均保留。这里没有流式单 token API 或 KV decode 基准；11 次重复计时属于同一机器上的重复测量，
不是 11 个训练种子。全部低质量模型也照常计时并展示。[R]</p>
{fig(images, "inference_cost", "全部别名的完整序列墙钟成本，点为中位数、线为 11 次样本最小至最大。不同质量模型仍展示，图本身不表示同等质量。")}
{table(["任务", "控制器", "种子", "预算", "B1 CPU ms 中位[范围]", "B1 wall ms 中位[范围]", "B32 CPU ms 中位[范围]", "B32 wall ms 中位[范围]", "B32序列/s（wall）"], rows)}
{detail("全部 40 个别名×batch 的 11 次 CPU/wall 原始毫秒值", table(["任务", "控制器", "种子", "预算", "batch", "11次 CPU ms", "11次 wall ms"], raw_rows))}
<h3>质量窄带只作描述性连接</h3>
<p>配对限定同任务、同预算：双方验证和测试 accuracy≥90%，测试 accuracy 绝对差≤0.005，CE 绝对差≤0.01。
当前满足该经验窄带的配对为 {runtime["eligible_pairs"]} / {len(runtime["quality_join"]["comparisons"])}。
这不是统计等效检验，也不证明总体质量相同；不满足时保留各自计时，但不报告“同质成本比”。
合格配对的比值为 analytic / 对照，中位成本比&gt;1 表示 analytic 较慢。计时身份与终点没有依质量或速度重新挑选。</p>
{table(["任务", "预算", "analytic 对照", "经验窄带合格", "accuracy绝对差", "CE绝对差", "B1 CPU比", "B1 wall比", "B32 CPU比", "B32 wall比"], quality)}
<h3>605 B 的含义</h3>
<p>实际计数的每条序列持久标量 payload 为 {e(payloads)} 字节：147 个 FP32 标量为 588 B，
两个 int64 计数器加一个 bool 为 17 B，总计 605 B；B32 为 19,360 B。
其中包含关联矩阵、三个 flow 状态、pending key 和因果计数状态。
该数字<strong>不是实测峰值 RAM，也不是已实现的 streaming/KV cache</strong>；它不含输入、输出、prepared 系数、
临时激活、模型参数、Python 对象和分配器开销。没有能耗、GPU、长上下文或其他架构的可比测量。</p>
</section>"""


def provenance_section(data):
    missing = table(
        ["旧包名", "已知旧大小 bytes", "旧 SHA256（无对应原包）"],
        [[r["name"], r["bytes"], r["sha256"]] for r in data["recovery"]["missing"]],
    )
    manifest = table(
        ["消费输入路径", "bytes", "SHA256", "用途"],
        [
            [r["path"], r["bytes"], r["sha256"], ", ".join(r["roles"])]
            for r in data["consumed_inputs"]
        ],
    )
    archive = "hepta_stable_flow_complete_20261029.tar.gz"
    return f"""<section id="limits"><h2>7. 研究结论的边界与后续判别条件</h2>
{
        table(
            ["问题", "本轮可以支持的范围", "仍未建立的结论"],
            [
                [
                    "算子与训练",
                    "共享边界的 C1 Call/Put、稳定数值实现和固定元数据下参数 BP/BPTT",
                    "自由边界约束本身独立于近界匹配和全局形状的贡献",
                ],
                [
                    "动力学",
                    "有界性、反馈符号、特定未训练参数下周期轨道存在性",
                    "已训练模型必须以 spike 完成任务、事件稀疏性、唯一稳定极限环",
                ],
                [
                    "序列能力",
                    "两种带显式因果地址先验的短合成任务、预声明预算和逐种子分数",
                    "普通语言长上下文、未知地址发现、任意采样率不变",
                ],
                [
                    "计算",
                    "固定 CPU、T32、B1/B32 完整 forward 的原始计时和经验质量窄带",
                    "GPU/硬件能效、流式延迟、KV优势、全研究总能耗",
                ],
                [
                    "架构对照",
                    "本轮五种共享 memory/parser 的控制器比较",
                    "传统 SNN、CfC、Mamba、优化注意力 Transformer 的直接优势",
                ],
                [
                    "规模与模态",
                    "当前小模型实验的可复查证据",
                    "训练全模态大模型或通用 encoder 的扩展优势",
                ],
            ],
        )
    }
<p>下一轮若要识别自由边界约束本身，需要真正破坏相应边界约束而又匹配容量和其他机制的对照；
若要识别神经元的放大、适应、恢复贡献，需要 Call-only、Put-only、去慢恢复等干预。
若要证明时间处理优势，需要物理输入一致的采样率改变，并分别控制外层输入事件语义与积分离散化。
多模态和规模结论则要求相同输入编码器、数据、参数与计算预算下的独立架构比较。这些未执行的研究项目不能被写成已通过。</p>
<h3>旧证据丢失与新执行分开</h3>
<p>旧 scratch 清理后保留下来的主要是报告和部分回执，旧权重、预测和完整原始数组未恢复。
旧本地提交 <code>{
        e(data["recovery"]["previous_local_commit_not_recovered"])
    }</code> 也未恢复。
本轮是新的源码、数据、检查点和运行身份；新实验不能补写成旧实验的逐字节重放，不能宣称修复了已不可获得的旧 checkpoint。</p>
{missing}
<p>用户已明确授权本轮新工作公开发布到
<a href="{
        BRANCH
    }">TrillionniumFoundation/hepta-private-ci / research/hcsn-callput-rebuild-20261028</a>。
完整证据包的预期文件名为 <code>{archive}</code>，本地完整包下载由最终交付入口提供。
公开仓库采用 2 MiB 分片，目标为
<a href="{
        BASE
    }research_evidence/hepta_stable_flow_20261029/releases/complete_parts_20261029/PARTS.json">PARTS.json 分片清单</a>及同目录全部分片；
另提供完整包的<a href="{BASE}research_evidence/hepta_stable_flow_20261029/releases/{
        archive
    }.receipt.json">原始归档回执</a>和
<a href="{BASE}research_evidence/hepta_stable_flow_20261029/releases/{
        archive
    }.manifest.json">原始归档 manifest</a>。
最终完整包和各片的字节大小与 SHA256 以实际发布清单为准，此处不预填未知哈希，亦不提前宣称远端读取或最终审计成功。</p>
<p>取得该分支源码和清单列出的全部分片后，在仓库根目录执行以下命令。组装输出必须尚不存在；
第一步验证分片及拼接字节身份，第二步重建原始 tar.gz，第三步逐项验证归档内 manifest 和全部成员。
这些步骤只做字节校验，不重新训练或生成科学数据。</p>
<pre class="proof"><code>python experiments/call_put_stable_flow_analysis/release_parts.py verify --manifest research_evidence/hepta_stable_flow_20261029/releases/complete_parts_20261029/PARTS.json
python experiments/call_put_stable_flow_analysis/release_parts.py assemble --manifest research_evidence/hepta_stable_flow_20261029/releases/complete_parts_20261029/PARTS.json --output {
        archive
    }
python experiments/call_put_stable_flow_analysis/release.py verify --archive {
        archive
    }</code></pre>
<p>本 HTML、图表、<code>report_summary.json</code> 与 <code>report_receipt.json</code> 是同次生成的产物。
receipt 记录每个消费输入的路径、大小和 SHA256，并绑定生成器；不依赖尚未生成的最终审计，避免循环论证。
独立最终审计应在报告生成后检查报告及其输入绑定。本报告不宣称“所有研究 blocker 已闭合”。</p>
</section><section id="sources"><h2>8. 来源、数学合同和逐文件绑定</h2>
<p>[HX] He &amp; Xiong, <em>Rollover Risk and Credit Risk</em>, Journal of Finance 67(2), 2012.
<a href="https://www.princeton.edu/~wxiong/papers/rollover.pdf">作者论文 PDF</a>。引用范围为金融建模来源及完整模型与本轮简化的区别。</p>
<p>[PB] Immler &amp; Tan, <a href="https://isa-afp.org/entries/Poincare_Bendixson.html">Poincaré–Bendixson theorem, Archive of Formal Proofs</a>。
本轮应用论证写在 [T]，没有声称 Hepta 的证明已经由 Isabelle 形式化。</p>
<p>[T] <a href="{
        BASE
    }experiments/call_put_stable_flow_analysis/ANALYSIS.md">ANALYSIS.md</a>：实际方程的证明与限制。
[P] formal_run001/protocol.json、results.json 与候选完成回执。
[N] trained_numerics_appendix001/protocol.json、execution/summary.json 及原始数组。
[R] inference_cost_appendix001/protocol.json、execution/summary.json、quality_join.json。
所有本轮实测数字均来自以下清单中的文件；图表由标准 Matplotlib 生成，数据表保留失败和未解决状态。</p>
{
        detail(
            "完整数学合同原文（Markdown，含证明细节）",
            '<pre class="proof">' + e(data["theory_markdown"]) + "</pre>",
        )
    }
{detail(f"全部 {len(data['consumed_inputs'])} 个消费输入及 SHA256", manifest)}
</section>"""


def render(data, images):
    comparisons = data["primary"]["comparisons"]
    main_counts = {
        metric: sum(
            r["metric_improvement_gate"]
            for r in comparisons
            if r["metric"] == metric and r["comparator"] == "matched_c1"
        )
        for metric in ("accuracy", "cross_entropy")
    }
    secondary = {
        metric: sum(
            r["metric_improvement_gate"]
            for r in comparisons
            if r["metric"] == metric and r["comparator"] != "matched_c1"
        )
        for metric in ("accuracy", "cross_entropy")
    }
    nstatus = data["numerics"]["end_to_end_alias_status"]
    summary = f"""<section id="overview"><h2>本轮结果如何解读</h2>
<p>这是一轮<strong>新执行的受控小模型研究</strong>：60 个训练候选、两种合成任务、五种共享解析器与关联记忆的控制器、
两个预算口径，以及训练后独立数值与 CPU 成本附录。它将金融类比落实为可训练模型和可核查证据，
但不能把有限任务结果扩大成通用脉冲网络或全模态大模型优势。</p>
<div class="cards"><div><b>主要比较：analytic 对 matched C1</b><strong>accuracy {main_counts["accuracy"]}/4 · CE {main_counts["cross_entropy"]}/4</strong><span>通过各自指标提升门；两个指标分别统计</span></div>
<div><b>次要比较：sigmoid / ordinary</b><strong>accuracy {secondary["accuracy"]}/8 · CE {secondary["cross_entropy"]}/8</strong><span>探索性 n=3 配对区间，不能择指标称总优势</span></div>
<div><b>训练后端到端数值状态</b><strong>{nstatus.get("passed", 0)} 通过 · {nstatus.get("failed", 0)} 未通过</strong><span>{nstatus.get("reference_unresolved", 0)} 个参照未解决；全部 24 别名保留</span></div></div>
<p>analytic 与 matched C1 的主要比较保留了相同边界局部约束，因此其辨别对象主要是<strong>全局算子形状</strong>。
即便主任务 accuracy 很高，也不能直接归因于自由边界机制；共享的因果地址解析器和 delta 关联矩阵可能承担大量任务能力。
训练后固定探针 Call 恒零的观测、未训练参数诊断和数值失败均在下文原样呈现。</p>
<p class="notice">报告生成时间：{e(data["generated_utc"])}。所有正式结果与附录已具备才生成此报告。
该状态不等于所有科学假设成立，也不提前声明最终独立审计或远端发布成功。</p></section>"""
    body = (
        summary
        + scientific_definition(data)
        + task_results(data, images)
        + training_section(data)
    )
    body += (
        numerical_section(data)
        + runtime_section(data, images)
        + dynamics_section(data, images, table=table, f=f, yes=yes, fig=fig)
        + provenance_section(data)
    )
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Hepta：共享自由边界 Call–Put 网络的新执行科学报告</title><style>
:root{{--ink:#18293a;--muted:#526478;--blue:#1768a8;--line:#dbe4ed;--paper:#fff;--wash:#f3f6fa}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--wash);color:var(--ink);font:16px/1.8 system-ui,-apple-system,'Noto Sans CJK SC','Microsoft YaHei',sans-serif}}
header{{background:#102e47;color:white;padding:54px max(24px,calc((100vw - 1180px)/2)) 36px}}header .eyebrow{{letter-spacing:.14em;color:#a3c9ea;font-size:13px}}
h1{{font-size:clamp(27px,4vw,43px);line-height:1.35;margin:12px 0}}header p{{color:#d4e3ef;max-width:900px}}nav{{background:#fff;border-bottom:1px solid var(--line);padding:12px 24px;display:flex;gap:20px;flex-wrap:wrap;justify-content:center;font-size:14px}}
a{{color:var(--blue);text-decoration-thickness:1px;text-underline-offset:3px}}main{{max-width:1260px;margin:28px auto;padding:0 22px 64px}}section{{background:var(--paper);border:1px solid var(--line);border-radius:12px;margin:22px 0;padding:28px 32px}}
h2{{font-size:25px;line-height:1.4;margin:0 0 21px}}h3{{font-size:20px;margin-top:30px}}p{{margin:15px 0}}strong{{font-weight:700}}.equation{{background:#eef4f9;border-left:4px solid var(--blue);padding:18px 22px;line-height:2;font-family:Georgia,'Noto Serif CJK SC',serif;overflow:auto}}
.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}}.cards>div{{padding:20px;background:#f0f5fa;border-radius:9px}}.cards b,.cards strong,.cards span{{display:block}}.cards strong{{font-size:22px;margin:10px 0;color:#164e7e}}.cards span{{font-size:13px;color:var(--muted)}}
.notice{{padding:15px 18px;background:#fff6e8;border-left:4px solid #bb8436;font-size:14px}}.table-wrap{{overflow:auto;max-height:820px;border:1px solid var(--line);border-radius:6px;margin:20px 0}}table{{border-collapse:collapse;width:100%;font-size:12px;line-height:1.55;font-variant-numeric:tabular-nums}}caption{{caption-side:bottom;text-align:left;color:var(--muted);padding:6px}}th{{position:sticky;top:0;background:#eaf1f7;z-index:1;text-align:left;min-width:70px;font-weight:650}}th,td{{border-bottom:1px solid var(--line);padding:10px 12px;vertical-align:top}}tbody tr:nth-child(even){{background:#fafcfe}}td{{max-width:460px;overflow-wrap:anywhere}}
details{{border:1px solid var(--line);border-radius:7px;padding:12px 16px;margin:18px 0}}summary{{font-weight:650;cursor:pointer;color:#245577}}details .table-wrap{{margin-bottom:4px}}figure{{margin:24px 0}}figure img{{display:block;width:100%;height:auto;border:1px solid var(--line);border-radius:5px}}figcaption{{font-size:13px;color:var(--muted);margin-top:9px}}code{{font-size:.88em;background:#eef3f7;padding:2px 4px;overflow-wrap:anywhere}}pre.proof{{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.7 ui-monospace,monospace;max-height:900px;overflow:auto}}
footer{{font-size:13px;color:var(--muted);text-align:center;padding:25px}}@media(max-width:800px){{main{{padding:0 10px}}section{{padding:22px 17px}}.cards{{grid-template-columns:1fr}}header{{padding:35px 22px}}}}@media print{{body{{background:white}}header{{background:white;color:#18293a}}header p,header .eyebrow{{color:#526478}}nav{{display:none}}section{{border:0;padding:10px 0;break-before:page}}.table-wrap{{max-height:none;overflow:visible}}th{{position:static}}details{{break-inside:avoid}}}}
</style></head><body><header><div class="eyebrow">HEPTA · NEW EXECUTION · 2026-10-29</div><h1>共享自由边界 Call–Put 网络<br>实现、对照实验与证据边界</h1><p>新源码与新检查点的科学报告。将解析算子、动力学、训练效果、数值资格和计算成本逐项连接到可核查证据。</p></header>
<nav><a href="#overview">结果概览</a><a href="#definition">模型</a><a href="#tasks">任务与区间</a><a href="#training">训练与活性</a><a href="#numerics">数值</a><a href="#runtime">成本</a><a href="#dynamics">动力学</a><a href="#limits">限制</a><a href="#sources">来源</a></nav>
<main>{body}</main><footer>完整数据见 report_summary.json；输入与产物绑定见 report_receipt.json。所有图像已内嵌，无外部脚本或字体依赖。</footer></body></html>"""
