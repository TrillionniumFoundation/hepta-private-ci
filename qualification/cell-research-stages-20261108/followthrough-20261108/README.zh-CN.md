# S0–S5 后续证据来源与 VERIFY-1 独立审计

本目录把现有研究分支和一次已完成的真实模型运行接入可核对的来源索引。
VERIFY-1 原件审计为 **43/43 PASS**；科学准入仍为 **HOLD**，生产权限仍为 **NONE**。
这些原件不证明多个分支已经组成一个共同冻结、共同预算且可晋级的候选。

## 文件与版本身份

| 文件 | 用途 |
| --- | --- |
| `SOURCE_MAP.json` | 七个独立来源身份，区分历史 fixture、已发布快照、原生运行和本地候选。 |
| `REMOTE_SOURCE_OBSERVATION.json` | 保留观察时的 PR、分支、head 与 base；它是有时间范围的快照。 |
| `VERIFY1_AUDIT.json` | 独立审计结果；与归档内 `verify1-live/AUDIT_V2.json` 字节相同。 |
| `verify1-independent-audit.tar.gz` | 原始导出、SQLite 状态、实际执行源码、审计程序和失败历史。 |

源码提交、实际执行源码、证据提交、原始归档、远端 CI 各有自己的身份。
本文依据所保留的观察说明结果，不把后来的分支状态改写进历史回执。
`SOURCE_MAP.json` 保留原始字节；其中 `path` 的解包根规则见下文。

## VERIFY-1：实际执行与独立复算

原始运行是 Mac job `1a1bb3d51b5-13c47-15f`，终态为 succeeded、exit 0。
审计复用既有导出，没有重跑模型、训练、原始 exporter 或主机动作。
原生归档 SHA256 为 `567746d6842545e264617fa62a772aed3e5ed48547fde86c5d9562b52e065796`。
独立副本核对了 178 个归档成员、177 个 inventory 绑定原件和 132 个 SQLite 状态库。

| 原始计数 | 独立复算结果 |
| --- | --- |
| 计划 / 完成策略轨迹 | 108 / 108：84 个主比较、24 个实际策略干预。 |
| train / calibration 不间断参考轨迹 | 24；不计作额外 confirmation 轨迹。 |
| operation started / terminal | 1,966 / 1,966；运行失败 0、策略轨迹失败 0。 |
| 模型执行 | 428 个 score、169 个 feature operation，共 652 次前向、88,151 input tokens。 |
| 输出与主机回执 | 408 个聚合 assessment、156 个风险预测与决策、178 个 property receipt。 |
| 实际训练的读出头 | 3 个 frozen-feature logistic readout；基础模型权重未更新。 |

运行设备为 Apple M5，记录的 MLX / MLX-LM 版本为 0.31.1 / 0.31.2。
Qwen/Qwen3-0.6B revision 为 `c1899de289a04d12100db370d81485cdf75e47ca`；
HuggingFaceTB/SmolLM2-360M-Instruct revision 为 `a10cc1512eabd3dde888204e902eca88bddb4951`。
预训练权重留在原主机；本审计复核导出的 native asset receipts 与调用绑定，没有重新散列权重文件。

train、calibration、confirmation 各有 12 cases、2 个分组标识；case/group IDs 互不重叠。
36 个训练特征仅来自 train 的 ticks 0、2、3；训练操作先于 calibration 和 confirmation。
读出头 seeds 为 17、29、43；主比较使用前两个，43 仅用于单独诊断。
这些分组复用合成模板，三个读出头不构成三个独立自然任务训练试验。

七个主比较 arm 均接受 4/12 条轨迹，接受错误为 0；最终接受记录均可追溯至主机 mandatory readback。
独立审计逐库读取真实值与接受状态，重新计算模型分数、计数、14 份 Brier 报告及六组 risk/cost 干预。
风险事件与 property receipt 的事件、scope 分开绑定；模型分数不能替代具体属性检查。
每个 arm 的初始分数在 12 cases 内都只有一个取值，分数未校准，选择器的净收益尚未建立。
fixed_check 使用 12 次 optional check，single/repeat_two 使用 16 次，其余主比较使用 18 次。
相同投票调用机会并不等于相同 token、前向、训练或 wall 成本。

实际运行 wall 为 27.356104459 秒，controller CPU 为 4.635582 秒。
准备累计 wall 为 5,807.030543 秒，覆盖首次准备至最终 Mac 复核，包含取消、超时与编排间隔。
应用层下载 payload 记录为 2,246,266,895 bytes；wire bytes、energy、provider cost 和完整历史建设成本未知。
不同范围的 wall 分项不相加冒充总时长；完整物理成本与同实际预算资格均为 false。

保留观察中的 #5351 head 为 `6eb0f8d717cfd1234bbbe385d5d5fb99bde5c521`，仍是 neural calls 0 的 phase1。
真实运行依赖的 runtime.py、contracts.py、metrics.py 与该 head 逐字节相同，比较记录保留在归档内。
新增 model_* 源码由 source capsule 与 manifest 绑定；不能据此称其已经属于上述 #5351 head。
本次收编原件也不把 `publication.source_commit=null` 改写为一个未验证的执行提交。

## S3–S5 的证据范围

| 来源 | 已有证据 | 尚未满足的科学门槛 |
| --- | --- | --- |
| S3 #5347，head `9aa9fa75`，执行 source `d967d91c` | 两环境各 68 tests、54 slots；相同 seeds 11、29、47。 | diffusion 未显示优势；HCSN/GRU 冻结内核 accuracy 0.5；18 个学习目标预算内 censored。 |
| S3 #5368，head `03a90226` | native FP64 71 tests 与 4 个数值预算 fixtures；保留 64-cell 失败。 | 正式真实任务比较 fits 为 0；保留的专用 CI 观察仍 queued。 |
| S3 本地 HCSN 后续 CURRENT | 声明 75 tests、18 次接口 smoke fits、72 optimizer updates。 | 容量不等、短片段类别偏斜；formal comparative fits 为 0，身份与 #5368 分开。 |
| S4 #5345，head `6736d8ac` | D 拓扑/迁移/回滚证据契约，以及已有 B 执行原件。 | D 实际配对执行尚缺；apply/recovery 原语不证明组织净效益。 |
| S5 #5348，head `c600204c` | 41 tests、12 synthetic runs、72 attempts、3 lineages；专用 CI success。 | 后代改进器是收益/遗忘权衡；完整成本 qualified 0、unresolved 12；native successor 未验证，broader CI failure。 |

重复环境不增加独立 seeds；接口 smoke、数学资格、源码组合与科学比较资格分别保留。
EVOLVE 内部 S0/S1 指父/子 solver 轴，与路线图阶段 S0/S1 不同。
所有这些来源仍保留 HOLD；来源表不授予研究晋级、部署或执行权限。

## 归档路径与只读重放

外层归档为 1,177,531 bytes，SHA256 为：
`ac8863c2893869db846801d825e89863cf168e87782571dd009733b921643de0`。
`SOURCE_MAP.json` 与归档内 `verify1-live/CURRENT.json` 的 22 个 path/bytes/SHA256 绑定均以**外层解包根**为基准。
例如 `verify1-live/AUDIT_V2.json` 只加一次前缀，不能再相对于 CURRENT 的所在目录追加。
原始导出的 inventory 使用自己的原始导出根，即 `verify1-live/original/`；不同 schema 的路径根不能混用。
下面从仓库根目录运行，要求 Python 3.12+，先验 hash/绑定，再在临时目录重放。

```bash
evidence_dir="$PWD/qualification/cell-research-stages-20261108/followthrough-20261108"
replay_root="$(mktemp -d)"
python3 - "$evidence_dir" "$replay_root" <<'PY'
import hashlib, json, shutil, sys, tarfile
from pathlib import Path, PurePosixPath
source, temporary = map(Path, sys.argv[1:])
archive = source / "verify1-independent-audit.tar.gz"
expected = "ac8863c2893869db846801d825e89863cf168e87782571dd009733b921643de0"
assert hashlib.sha256(archive.read_bytes()).hexdigest() == expected
with tarfile.open(archive, "r:gz") as bundle:
    members = bundle.getmembers()
    assert len({item.name for item in members}) == len(members)
    assert all(item.isfile() and not PurePosixPath(item.name).is_absolute()
               and ".." not in PurePosixPath(item.name).parts for item in members)
    checked = []
    def verify(value):
        if isinstance(value, dict):
            if {"path", "bytes", "sha256"} <= value.keys():
                raw = bundle.extractfile(value["path"]).read()
                assert len(raw) == value["bytes"]
                assert hashlib.sha256(raw).hexdigest() == value["sha256"]
                checked.append(value["path"])
            for child in value.values(): verify(child)
        elif isinstance(value, list):
            for child in value: verify(child)
    verify(json.loads((source / "SOURCE_MAP.json").read_bytes()))
    verify(json.loads(bundle.extractfile("verify1-live/CURRENT.json").read()))
    assert len(checked) == 22
    bundle.extractall(temporary / "retained", filter="data")
retained, replay = temporary / "retained/verify1-live", temporary / "replay"
replay.mkdir()
for name in ("audit_originals.py", "original", "provenance", "verify1-model-run-v2.tar.gz"):
    item = retained / name
    if item.is_dir(): shutil.copytree(item, replay / name)
    else: shutil.copyfile(item, replay / name)
print("Verified 22 bindings; retained history:", retained)
PY
python3 -B "$replay_root/replay/audit_originals.py"
```

输出为新临时目录中的 `AUDIT_V2.json`；不删除或覆盖任何历史报告，且不会加载模型。
重放观察时间会改变，因此比较 43 项检查及其结论，不要求新报告的整文件 SHA 与历史报告相同。
首次审计误将重序列化 asset manifest 副本与原件按同字节比较，失败及修正均保留。
随后一次 create-only 输出冲突也保留；当前有效结果由 `CURRENT.json` 指向 `AUDIT_V2.json`。

## 精确 blob-size 例外与下一阶段依据

仓库普通 blob 上限 512000 未修改；allowlist 仅增加上述完整 SHA256 与这个归档的精确路径。
归档同时保留 native 原始压缩包和其展开原件，方便核对与直接重放；这是同一份证据的两个视图。
移除展开副本的内存试算仍约 586,634 bytes，并须额外解包才能重放；未通过拆分规避上限。
任何归档字节或路径变化都不继承该 exact allowlist 条目。

| 阶段 | 下一步必须补齐的证据 |
| --- | --- |
| S0 | 共同配置/协议/源码冻结；真实 owner、轨迹、恢复、后继消费及完整预算绑定。 |
| S1 | 对强基线的同实际预算终局净收益、旧能力保持和独立确认任务。 |
| S2 | 延迟与故障条件下，无效取证、规划和动作减少的实际轨迹。 |
| S3 | 充分训练的强时序/梯度基线、匹配调参机会，以及明确收益或完整成本优势。 |
| S4 | 固定图加优秀调度的 D 配对执行，计入组织、迁移、重学与恢复成本。 |
| S5 | 共同起点、完整建设与运行成本、独立评价，以及原生后继消费与恢复回执。 |
