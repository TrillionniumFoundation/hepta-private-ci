# 五模型 reader：Arctic 兼容、Harrier 冻结与 NumPy 依赖修复

更新日期：2026-11-26。源基线为 `eadf2999991c147759785f5eec722b9d6e796a9a`。下述原始失败取自 run 45725442385 / head `61a32d54afbb57af1dfeb52e7f8c703fc2599d63`；作业状态以原日志对应 head 为准。

**Harrier 清理合同与 Arctic 固定模拟合同各执行一次，均为 PASS，登记源码字节未变；没有新增真实模型、前向、反向或优化器更新。历史五模型成功仅属于旧协议，全仓与生产资格仍为 HOLD。**

## 修复的问题

原 Harrier job 139594026260 在训练结束后进入 fanout 时，被原“evaluation-only and frozen”检查拒绝。原因是最后一次 AdamW 更新留下 param.grad；eval 与 requires_grad_(False) 不清理已有梯度。新 finalizer 清理梯度并完成原冻结状态转换，原检查保持不变。

原 Arctic job 139594026266 的首个真实前向在 RoPE position lookup 越界。源端缺少已存在的四个非持久 buffer 重建和 Transformers 5 的单行 unpadded mask 兼容处理。本候选从既有修复链恢复这些实现，并保留加载参数的前后身份与严格回执检查。

physical-contracts 的独立 venv 只装 Torch，原 tensor_digest 的 .numpy() 因缺 NumPy 失败。workflow 只补装同仓固定的 NumPy 2.2.6，两行命令；原触发器、五模型矩阵、超时和实际调用都不变。

## 源码与协议保留

Arctic 改动来自 [#3970](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3970) → [#3985](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3985) → [#3989](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3989) → [#3990](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3990)，末端源 `1adc9c57449964f5848b29c7e2063a983e110b43`。

| 变更组 | 实际差分 |
|---|---:|
| Arctic：2 个新实现、2 个现有实现、2 个新测试、2 个现有测试 | +567 / -0 |
| 叠加 Harrier finalizer 后的 8 文件 | +576 / -3，共 579 行 |
| 独立 NumPy workflow 恢复 | +2 / -0 |

组合保留当前的真实 fanout、来源审计、模型 hash、200-step 训练、初始化、学习率、校准、Laya 路径和原拒绝条件。COMPOSITION.json 比较确认 finalizer 与完整训练函数字节和已验证 Harrier 候选相同，没有再次执行 Harrier 合同。

五模型的旧/新 requirements 与原日志均为 Transformers 5.20.2。专用 shim 仍拒绝其他版本、已有 get_extended_attention_mask、非 CPU float32、启用 unpadding/xFormers 或非法 mask，不覆盖已存在的方法。

qa/ 和 qa/stem-bakeoff/ 没有更近 AGENTS.md，适用根规则。四个新增 Python 文件没有 __future__ import；现有文件的原 import 保持原状。

## 已观察：Harrier 清理合同

原 RESULT 的 SHA256 为 `e9546450e9fa0203baf32a70edf214bb250524c852e75cbaf448661050eb0578`。它记录一个 CPU float32 Linear(4,4)、两个原 guard 调用、一次 finalizer 和两次原 digest；forward/backward/optimizer/真实 checkpoint/训练函数调用全部为 0。

人工梯度使原冻结 guard 先拒绝。清理后相同 guard 被穿过，随后 features=None 被原 feature 检查拒绝，未进入 fanout。两个参数逐项 torch.equal、完整 state_dict digest 相同；Linear 没有 buffer，原结果明确记录 0 个 buffer。

原执行环境为 Python 3.14.4、Torch 2.15.0+cpu、NumPy 2.5.5、threads/interop_threads=1。launcher wall 1.472955896 秒、child CPU 1.152633 秒；所有登记源字节未变化。

该合同证明固定生命周期清理与拒绝边界，不证明原五模型 Torch 2.10.0 / NumPy 2.2.6 环境、真实 Harrier 任务效果或新的五模型工作流成功。

## 历史证据：旧 Arctic 已真实成功

[#3989 的 run 40261162978](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40261162978) 在 exact head `3ee6d658c34762c886d4fa4a9772d8cc1740fd8a` 的七个 job 全部 success。原 Arctic job 121373660461 日志记录 40 次真实前向；cross-arm job 121411135431 记录五份 ZIP digest 匹配。

原审计仍输出 SHADOW_ONLY / DENY_ALL / HOLD_NO_GO / REVIEW_REQUIRED。当前 artifact API 列表已空；本次保留仍可读取的原日志、元数据和日志内原 artifact digest，不声称已重新下载原 raw output。

这些成功属于旧源码和旧协议。它们不能转移为当前新增 fanout 的完整通过，也不构成再次执行成功模型的预算。

## 已观察：Arctic 固定模拟合同

原 RESULT SHA256 为 `862013b1f7e91e0fe7f5eb6e26a0bd2d58c5dd08ddb5f2175ffb86ed49748d69`，原 LAUNCH_RESULT 为 `8c1e05c3ed6fdf2724d45a2ab97f371eb25dc7f6d9c7d4cd753b1894955350dd`。它们均为 PASS；外层 wall 1.417693151975982 秒、child CPU 1.101132 秒。原 STARTED 启动回执、准备时 NOT_EXECUTED 文本、registration 和原始 streams 全部保留，不回写历史状态。

实际计数与注册精确相同：普通 Python Gte/Embeddings/Rotary 对象各一个，假参数 4 bytes；restore=3、parameter identity=6、合成 RoPE 索引=2、install mask=5、mask=8。坏 position_ids/NaN cache 的拒绝和重建、参数 torch.equal/digest 保全、版本/API/输入负控均通过。

没有 nn.Module 构造、真实 GTE、模型 forward、backward、optimizer、200-step 训练或 seed search。实际环境同为 Python 3.14.4 / Torch 2.15.0+cpu / NumPy 2.5.5，Transformers distribution 记录为 null；metadata.version 的 4.57.1/5.20.3/5.20.2 是明确模拟输入，不是实际 Transformers 运行期通过。

一次预算已消耗，外层 hard wall 30 秒及 CPU soft/hard 20/21 秒实际生效；driver 另验收 wall≤30 / CPU≤20。FORMAT05/06 均为 PASS，所有登记源未变；原 formal 与 Harrier 已消耗预算不变，不自动重试或重跑旧成功。

## 原件保全与发布范围

有界归档 `FIVE_MODEL_REPAIRS_01.tar.xz` 包含两个独立合同的登记、执行源码、完整输入、launcher、原结果和 stdout/stderr，FORMAT05/06、组合证明、原修复来源、历史真实成功与当前失败日志。完整成员大小/SHA256 位于归档内 MANIFEST.json，外部精简 index 绑定 manifest 与 archive digest；原始失败不改写。

正文保留必要实现/测试、此说明、原结果和精简索引；未修改的验证依赖放归档，不重复发布。最终 commit 按实际差分确认小于 800 行，不能通过删原始证据或改 guard 达标。

候选以独立源码分支审阅；当前不创建会重新触发全部五模型的 PR，不 dispatch/rerun 成功模型。新源码的托管全协议尚需其自己的证据，任何合成都不等于整套 workflow 已通过。

N256 历史宿主观察已经有原成功终局；当前 ubuntu-latest 的宿主漂移另行记录。它不通过更新旧 freeze hash 或重开已成功的数值预算处理。
