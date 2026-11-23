# 同一条件读出在独立直接解与两条 BP 路径中的到达时间

三个种子的直接解、Profile BP 和 Joint BP 都在候选 1 产生了同一个条件读出。逐种子核对，三个臂的状态摘要、开发 MSE、保持 MSE 完全相同。BP 路径保留了这次求解，继续评估八个 BP 候选。因此可以比较完整运行的质量和成本，也可以比较到达同一状态的时间。[原始 45 次运行归档](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/0307d62f4d4226a979692cb4420746e8c84af0d4/qualification/hcsn_flow_integration_v1/evidence.zip) · [原报告逐次结果](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/0307d62f4d4226a979692cb4420746e8c84af0d4/qualification/hcsn_flow_integration_v1/RESULTS.md)

## 完成原定运行的成本

每格为选中开发 MSE / 冷进程秒。只取同一项下一传感器预测任务的 15 次适配。三个种子共用同一数据来源和划分，每个种子的五个臂具有同一初始状态、拟合数据及归一化参数。各臂选中态的开发和保持 MSE 均核对了存档的独立前向重放。

| seed | KEEP | 直接解 | 有界编辑 | Joint BP | Profile BP |
|---:|---:|---:|---:|---:|---:|
| 181391 | .291830 / 4.48 | .114102 / 8.69 | .113852 / 36.06 | .112958 / 66.29 | .112737 / 82.69 |
| 284729 | .350653 / 4.73 | .070955 / 8.54 | .070620 / 38.02 | .070076 / 62.48 | .070675 / 79.08 |
| 395201 | .308705 / 4.38 | .099511 / 8.84 | .098707 / 37.39 | .095676 / 65.19 | .087916 / 78.54 |

直接解在三个种子上都比两个 BP 臂更早结束；两个 BP 臂的最终开发误差在三个种子上也都更低。唯一被其他臂同时以更短时间、更低误差超越的端点是种子 284729 的 Profile BP。Joint BP 与有界编辑分别超越了它。KEEP、直接解、有界编辑、两个 BP 臂每种子分别查询开发集 1、2、9、10、10 次，保持门均未拒绝其选中态。

给定一个固定开发 MSE 上限，若要求**同一个完整方法在三个种子上都达标**，各方法恰好从以下上限起可用。上限越严格，可用方法越少。全精度边界和三种子中的最长冷进程时间见 [PAIRED.json](PAIRED.json)。

| 完整方法 | 三个种子中最大的选中开发 MSE | 三个种子中最长冷进程秒 |
|---|---:|---:|
| KEEP | .350653427 | 4.728 |
| 直接解 | .114102344 | 8.841 |
| 有界编辑 | .113852454 | 38.021 |
| Joint BP | .112958090 | 66.287 |
| Profile BP | .112737359 | 82.686 |

这些是已结束运行的描述性端点。若按共同的绝对上限提前停止，实际冷进程用时需要记录首次达标和当时退出的时刻。原计划只注册了开发改进及保持容忍度，未注册这里的任一绝对 MSE 上限。每个种子每种方法运行一次；开发数据参加选模，适配任务的测试集查询为 0。

## 同一参数状态的配对计时

每个种子的质量目标取其直接解的实际选中状态。表中先列候选 1 从方法入口开始的实测秒数，再列从冷进程启动到该候选被打分的保守区间。区间按最接近的毫秒显示，精确比较使用 JSON 中的原精度。

| seed | 同一状态开发 MSE | 直接解，方法秒 / 冷秒区间 | Profile BP，方法秒 / 冷秒区间 | Joint BP，方法秒 / 冷秒区间 |
|---:|---:|---:|---:|---:|
| 181391 | .114102344 | 6.253 / [8.239, 8.687] | 6.332 / [8.267, 9.033] | 6.299 / [8.273, 9.072] |
| 284729 | .070954880 | 6.154 / [8.088, 8.536] | 6.105 / [8.033, 8.805] | 6.219 / [8.184, 8.933] |
| 395201 | .099511488 | 6.441 / [8.439, 8.838] | 6.191 / [8.361, 9.191] | 6.737 / [9.099, 9.931] |

设方法入口到候选被打分的实测时间为 (e)。下界为 (e) 加原始模块准备、数据准备、当前 seed 初始化与保存这三段顺序在前的时间。上界为 (e) 加完整冷进程时间，减去整个内层方法时长与返回后候选文件写入时间。这个算法把尚未分配到前后两侧的开销全部计入上界。它衡量到达已评分状态，未模拟提前结束后保存和退出的开销。种子 395201 的直接解在到达同一状态时比 Joint BP 至少早约 0.26 秒，其余五个直接解对 BP 的配对区间重叠。原机使用共享 CPU，这三个种子均未提供同配置的重复计时。[候选计时定义](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/abb3e5012c5f48e3cb42759785429cb1d496acb3/qualification/hcsn_scale/adaptation.py) · [冷进程内的阶段顺序](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/abb3e5012c5f48e3cb42759785429cb1d496acb3/qualification/hcsn_scale/adaptation_study.py)

以下示例在本目录运行，以原归档逐项验证两个表所用的完整冷时间、选中误差、候选状态和首达区间。把下载的原 `evidence.zip` 放在本目录或将参数改为其路径。只需 Python 标准库。

```sh
python3 - evidence.zip <<'PY'
import hashlib, json, sys, zipfile
from pathlib import Path
archive = Path(sys.argv[1])
table = json.loads(Path('PAIRED.json').read_bytes())
assert hashlib.sha256(archive.read_bytes()).hexdigest() == table['archive_sha256']
with zipfile.ZipFile(archive) as z:
    def read(name):
        return json.loads(z.read(name))
    for trial in read('study/LAUNCH.json')['trials']:
        if trial['study'] != 'adaptation':
            continue
        arm, seed = trial['arm'], str(trial['seed'])
        original = f'study/adaptation/{arm}-{seed}'
        study = read(original + '/STUDY.json')
        result = read(f'{original}/seed_{seed}/{arm}/RESULT.json')
        ledger = result['ledger']
        row = table['per_seed'][seed]['arms'][arm]
        cold = trial['cold_wall_seconds']
        selected = ledger['candidates'][ledger['selected_index']]
        assert (cold, selected['dev_mse']) == (row['cold_seconds'], row['selected_dev_mse'])
        if 'shared_head_cold_hit_bounds_seconds' in row:
            c = ledger['candidates'][1]
            assert c['state_digest'] == table['per_seed'][seed]['shared_head_state']
            assert c['dev_mse'] == table['per_seed'][seed]['shared_head_mse']
            assert c['preservation_mse'] == table['per_seed'][seed]['shared_head_preservation_mse']
            e = c['elapsed_seconds']
            before = (study['module_import_seconds'] + study['shared_cost']['data_preparation_and_save_seconds']
                      + study['incumbents'][seed]['initialization_edit_assembly_and_save_seconds'])
            upper = e + cold - ledger['cost']['total_seconds'] - result['artifact_write_seconds']
            assert [before + e, upper] == row['shared_head_cold_hit_bounds_seconds']
        print(seed, arm, cold, selected['dev_mse'])
PY
```
