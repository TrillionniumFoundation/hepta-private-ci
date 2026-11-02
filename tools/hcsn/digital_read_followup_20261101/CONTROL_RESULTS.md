# 控制修复：冻结确认结果

**收益门仍未通过：14 项预登记比较为 0/14。** 多轮真实策略访问监督改善了部分描述性均值，但 IID 五族 value 均低于自身修复后 fixed；FPT 相对普通 bank 的 value 增量在 IID/OOD 均为负。

基线：`012bcf3505cb9306d9cef094a1acc3ca34c978be`；拟合前源码发布：`9cedb204b30eb62ec8d26ba5668fbe905e176b9a`；全部模型及原始 MODEL_FREEZE 发布：`bd8e8a4ff5adf63d7a246d4aaba04491f7ddd39d`。确认在最后一次发布后生成。

同一旧模型分别执行 old fixed/value；terminal-only 仅将旧头的 STOP/提交 Q 改为 0、1−2p、2p−1。修复组从旧头继续训练，fixed/value 共用修复后的头。p 是学习 belief，不是部署时调用教师后验。WAIT/READ/REPAIR 仍由学习的续行 Q 决策。

每族额外 240 次更新分四轮，每轮在 64 个新 TRAIN 世界收集实际 fixed/value 混合访问并以 ε=.2 探索，累计监督样本；五 fit 共 6,400 条采集 episode、31,913 个访问状态，另有 400 条 validation episode，仅诊断、不选 checkpoint。教师来自 TRAIN 拟合 law，进入目标及事后审计。全部旧 cell 参数、转移表与特征表冻结；这是 head 修复，不是全参数 cell 训练，也不是策略回报梯度。

确认含 400 个新世界、250 个唯一组、10,000 条 episode；每表格有五 fit×40 episode，统计单位是五个独立 fit。Python Owner 实际打开到期 packet 并调用固定 FullHX；该确认不是 Rust 运行。连续 renewal 新核没有接入这些效用比较，不能把此处结果归因于连续命中时间或多次复位。

| family | split | old fixed | old value | terminal-only value | repaired fixed | repaired value |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| ordinary_base | iid | 0.295725 | 0.236012 | 0.227300 | 0.255150 | 0.201238 |
| ordinary_base | ood | 0.127150 | 0.105850 | 0.120550 | 0.124100 | 0.095200 |
| ordinary_bank | iid | 0.335638 | 0.168512 | 0.129725 | 0.376013 | 0.311463 |
| ordinary_bank | ood | 0.309700 | 0.110100 | 0.120250 | 0.359200 | 0.284400 |
| clocked_bank | iid | 0.372712 | -0.014925 | -0.018262 | 0.374975 | 0.324225 |
| clocked_bank | ood | 0.256550 | 0.112900 | 0.144600 | 0.248300 | 0.280750 |
| first_passage_bank | iid | 0.372662 | 0.050775 | 0.080050 | 0.358038 | 0.249175 |
| first_passage_bank | ood | 0.244600 | 0.061800 | 0.116700 | 0.210350 | 0.250350 |
| raw_history | iid | 0.358137 | 0.299525 | 0.261912 | 0.342637 | 0.322263 |
| raw_history | ood | 0.237750 | 0.117500 | 0.082500 | 0.288100 | 0.159100 |

区间使用配对五 fit 均值、df=4 的双侧 Student t，Bonferroni 同时控制 14 项，familywise α=.05；通过条件为调整下限严格大于 +.02。五 fit 的区间依赖小样本近似假设且很宽，未通过不等于证明零效应或等效。全部五 fit 差值与全精度区间保留在 [JSON](evidence/control_primary_fit_differences.json)。

| 预登记差值 | 均值 | 调整区间 | 通过 |
| --- | ---: | --- | --- |
| iid/bank_increment | 0.110225 | [-0.290606, 0.511056] | 否 |
| iid/clocked_bank:value-fixed | -0.050750 | [-0.611812, 0.510312] | 否 |
| iid/first_passage_bank:value-fixed | -0.108863 | [-0.703238, 0.485513] | 否 |
| iid/first_passage_increment | -0.062287 | [-0.497925, 0.373350] | 否 |
| iid/ordinary_bank:value-fixed | -0.064550 | [-0.459004, 0.329904] | 否 |
| iid/ordinary_base:value-fixed | -0.053912 | [-0.480374, 0.372549] | 否 |
| iid/raw_history:value-fixed | -0.020375 | [-0.426413, 0.385663] | 否 |
| ood/bank_increment | 0.189200 | [-0.289108, 0.667508] | 否 |
| ood/clocked_bank:value-fixed | 0.032450 | [-0.428167, 0.493067] | 否 |
| ood/first_passage_bank:value-fixed | 0.040000 | [-0.282863, 0.362863] | 否 |
| ood/first_passage_increment | -0.034050 | [-0.318200, 0.250100] | 否 |
| ood/ordinary_bank:value-fixed | -0.074800 | [-0.348419, 0.198819] | 否 |
| ood/ordinary_base:value-fixed | -0.028900 | [-0.327913, 0.270113] | 否 |
| ood/raw_history:value-fixed | -0.129000 | [-0.527925, 0.269925] | 否 |

终止结构的代数一致性不保证实际收益：raw-history 的 terminal-only 均值在 IID/OOD 都低于旧 value。修复后 FPT/value 的均值相对旧 value 为 .050775→.249175（IID）、.061800→.250350（OOD）；这是额外训练后在相同新世界上的描述性变化，不能替代主门槛。

模型仍分配 1,799 个 head 坐标。结构化后 1,700 仅指名义参与目标的坐标；ordinary 的两个不可达 refractory flags 对应 64 个首层权重仍无任务信号，raw-history 信息形态也不同。因此不宣称各族有效容量相同。额外 240 更新也不能与旧轮 240 更新说成相同训练预算。

| 成本范围 | CPU 秒 | wall 秒 | 解释 |
| --- | ---: | ---: | --- |
| 新训练完整子进程 | 113.681440 | 126.225332 | 含解释器导入、校准、采集、优化、诊断、导出及退出 |
| 新训练内部 stage | 112.888051 | 见原 MODEL_FREEZE | 已包含在上一行，不再相加 |
| 确认完整子进程 | 143.584502 | 229.162757 | 含解释器、输入生成、执行、教师审计与序列化及退出 |
| 确认内部 stage | 142.584588 | 见原 SUMMARY | 已包含在上一行，不再相加 |

旧轮 283.018 CPU 秒是另一次完整进程**计时复现**，其 25 模型字节等于原模型；它不是原始训练完整计时，不能倒填，也不增加独立 fit 数。旧模型训练是此次 warm-start 的前置成本。本表也不涵盖本轮全部独立审计、Rust 构建、归档与传输；没有能耗、等 CPU 预算或无损加速结论。

`outcome.content_calls` 实际统计到期读取尝试，包含缺失失败；成功 FullHX decode 必须由 receipt.content 中的 observation 单独计数。独立确认审计分列 attempts/success/failure。每步 execution CPU 只归因于策略及 Owner 片段，外部进程计时才包含其余工作，不能混加。原始确认结束时为 14,726,097 bytes/3,155 files，后续审计与封包另计。

独立确认审计已从原始记录重建全部 10,000 episode、250 个配对组和 54,282 个动作，并按冻结种子逐字节重生成 400 个世界。17,104 次到期读取尝试中，15,063 次成功解码、2,041 次失败；1,617 个唯一成功 packet 另行执行 FullHX。全部效用、费用、指标及 14 个调整区间重算误差为零，head 数值最大差为 4.44e-16。见 [独立确认审计](evidence/independent_confirmation_audit.json) 和 [全部输入身份](evidence/input_manifest.json)。独立验证开销另记，不计作候选推理成本。

## 复现

从发布分支的完整仓库根目录运行，环境版本见 [environment.json](evidence/environment.json)。确认用的是归档内原始 MODEL_FREEZE.json；不要编辑其路径、confusion 或摘要。以下按索引核对全部训练分片、归档、每个成员后展开到一个不存在的新目录；只允许普通文件与规范相对路径。

```bash
python - <<'PYRESTORE'
from pathlib import Path, PurePosixPath
import hashlib, io, json, tarfile
e = Path('tools/hcsn/digital_read_followup_20261101/evidence')
a = json.loads((e/'CONTROL_TRAINING_ARCHIVE.json').read_text())
ix = json.loads((e/'control_training_index.json').read_text())
parts = [(e/r['path']).read_bytes() for r in a['parts']]
for raw, record in zip(parts, a['parts']):
    assert len(raw) == record['bytes']
    assert hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() == record['git_blob_sha']
raw = b''.join(parts)
assert len(raw) == a['archive_bytes']
assert hashlib.sha256(raw).hexdigest() == a['archive_sha256'] == ix['sha256']
expected = {r['path']: r for r in ix['members']}
dest = Path('/tmp/digital-control-restored'); dest.mkdir(exist_ok=False)
with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
    members = archive.getmembers()
    assert len(members) == len(expected) and {m.name for m in members} == set(expected)
    for member in members:
        path = PurePosixPath(member.name)
        assert member.isfile() and not path.is_absolute() and '..' not in path.parts
        assert str(path) == member.name
        payload = archive.extractfile(member).read()
        assert len(payload) == expected[member.name]['bytes']
        assert hashlib.sha256(payload).hexdigest() == expected[member.name]['sha256']
        target = dest.joinpath(*path.parts); target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(payload)
PYRESTORE
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m tools.hcsn.digital_read_followup_20261101.control_campaign confirm --train /tmp/digital-control-restored --out /tmp/digital-control-replay --freeze-commit bd8e8a4ff5adf63d7a246d4aaba04491f7ddd39d
OPENBLAS_NUM_THREADS=1 python -m tools.hcsn.digital_read_followup_20261101.independent_confirmation_audit --train /tmp/digital-control-restored --confirmation /tmp/digital-control-replay --out /tmp/digital-control-replay-audit.json
```

上面重用已登记 confirmation seeds，是执行重放，不是新增独立确认。新训练可用 `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m tools.hcsn.digital_read_followup_20261101.control_campaign train --out /tmp/digital-control-new-training`；须先发布该次全部模型及其 MODEL_FREEZE，再运行相应新确认，不能冒用本轮 freeze 提交身份。原始归档与审计索引由本目录 evidence 保存。
