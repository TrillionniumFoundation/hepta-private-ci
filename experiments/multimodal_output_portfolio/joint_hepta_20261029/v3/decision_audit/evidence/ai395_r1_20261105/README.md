# R1：真实条件输入诊断与历史同文复现

**诊断与证据一致性已完成；语义质量未通过，保持 no-update。** 本目录是独立研究证据，不能计入产品统一候选的测试通过数，也不代表生产资格。

## 固定身份与范围

| 项目 | 身份 |
| --- | --- |
| 原始诊断源码 | `975e1a264c14ed3da02dcee23a64327825387e42`，PR #4835 |
| 原始源码 tree | `cb612abe0d02afaf711d37f5d8575a577da5524e` |
| 历史九份文本来源源码 | `4e3b8c3c242d7d6d83086e7375a354a30647e040` |
| VLM | `HuggingFaceTB/SmolVLM2-256M-Video-Instruct`，revision `067788b187b95ebe7b2e040b3e4299e342e5b8fd` |
| VLM 权重 SHA256 | `dcc8f4c00d30d70bb3028a1bfc373e1b1972e25919f8788183cae4ae72431ce2` |
| 同时固定的扩散模型材料 | `segmind/tiny-sd`，revision `cad0bd7495fa6c4bcca01b19a723dc91627fe84f`；本次没有新增扩散生成 |
| 独立执行环境 | ai395，CPU bfloat16，2 线程，Python 3.12.16 |
| 原 Actions 环境差异 | Python 3.12.14；实际包版本 freeze 与 ai395 逐字节相同 |

原生运行使用 [SOURCE_SUBSET.json](SOURCE_SUBSET.json) 所列六个字节校验文件的源码投影，不是完整产品 checkout。三个运行模块均与固定 Git blob/SHA256 一致；补充观察脚本独立保存，不能冒充原 PR 自带代码。实际模型配置、tokenizer、所有权重的大小与 SHA256 在 [model manifests](native/models/vlm/MANIFEST.json) 和 [全文件清单](native/RETAINED_FILE_MANIFEST.json) 中。

## 原始 Actions 与原生补充运行分别记录

[原始 Actions run 41973374316](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41973374316) 已为 `completed / success`，head 为上表固定 SHA，事件为 push。唯一 job `127066499318` 的六案例步骤、获取模型和 artifact 上传均成功，没有把 queued 或未运行当作成功。

原 artifact `13393254163` 大小 396,825 bytes，下载后的实际 SHA256 与 GitHub digest 一致：

`d84b6451b4b70e2dcc25b01c72ed5553357c0a9081c96d2f8ebd5248a0cca7aa`

完整小型文件已从原 ZIP 取回。见 [Actions receipts](actions/RECEIPTS.json)、[artifact 字节清单](actions/ARTIFACT_RECEIPT.json) 和 [跨环境逐项对照](actions/NATIVE_COMPARISON.json)。Actions 的六例输出文本、input/output token IDs、所有输入张量指纹和视觉特征指纹，全部与 ai395 的原始六例一致。这是另一次六调用运行，不并入下面的 23 次原生调用。

| ai395 原生作业 | 用途 | 权威终态 |
| --- | --- | --- |
| `1a1aa61b4a7-fc05-4217` | 环境、模型获取、原始六案例 | succeeded / exit 0 |
| `1a1aa6bab03-fc05-42cf` | 六案例实际张量补存 | succeeded / exit 0 |
| `1a1aa7162ff-fc05-4330` | 历史九次输入和两个白图对照 | succeeded / exit 0 |
| `1a1aa7f38b5-fc05-43aa` | 全文件重哈希及张量数值重读；没有模型调用 | succeeded / exit 0 |

所有终态均有 `terminal_publication_confirmed=true`、完整持久日志且无截断。回执在 [native/receipts](native/receipts)，操作关联在 [OPERATIONS.json](OPERATIONS.json)。最后一项的启动 RPC 曾超时；一次完全相同 idempotency key 的 reconciliation 返回 `reused=true`，确认的是原作业，没有重复启动。

## 六个中性案例

| 输入 | 指令类型 | 原样输出 | 输出 tokens（含 EOS） | 停止 |
| --- | --- | --- | ---: | --- |
| 原图 | 简短描述 | `a bee on a pink flower` | 7 | EOS |
| 生成图 | 简短描述 | `A computer screen displays a 3D model of a flower.` | 14 | EOS |
| 白图 | 简短描述 | `The text is a simple, straightforward description of the content.` | 13 | EOS |
| 白图 | 主体对象 | `A bird flying in the sky` | 7 | EOS |
| 生成图 | 主体对象 | `cat` | 2 | EOS |
| 原图 | 主体对象 | `bee on pink flower` | 5 | EOS |

每例均重新装载模型，6 次实际 `generate`，产生 3 种像素张量、2 种指令 token 输入、3 种视觉特征和 6 份不同文本。像素张量为 `[1,1,3,512,512]`，视觉编码器输出为 `[1,1024,768]`，实际 bfloat16 值均有限。完整提示、token IDs、stop reason、模型身份和逐例成本在 [23 次调用索引](RESULT.json) 指向的 TRACE 中。

这排除了本组案例中“所有图像被接成同一输入”的解释，但不能据此宣布理解正确。白图被描述成鸟、生成图在对象问题下回答猫，是实际的质量失败。没有从这几个开发案例制造独立准确率或统计增益。

## 九份同文的来源与边界

首先从原始 archive 独立重开九个文本文件，确认为同一段 356-byte 文本，SHA256 为：

`e868d31e1cdee549254b25203d775363f10b19ab97a01ba7f19e60873caf52d6`

随后按 [事先写定的复现方案](LEGACY_PROBE_PLAN.json)，固定历史图片、生成图、refined 图，以及保留下来的 plan/explanation/critique，重放历史九次 VLM 输入。**9/9 逐字节复现该文本，均生成 80 tokens，以 `max_new_tokens` 停止，没有 EOS。** 每次重新装载模型，因此产生该现象不需要跨调用 KV 残留或应用层复用旧输出文件。

两个白图对照把图像固定，只改变提示中的计划：

- 旧蜜蜂／花计划得到 `The diagram is a simple and uses a simple color scheme, with the bee and flower being the main`，21 tokens，EOS。
- 红球／蓝方块计划得到以 `The diagram shows a red ball on a blue square...` 开始的转述，80 tokens，长度上限停止。

实际像素与视觉特征保持一致，提示改变后输出跟随计划变化。结合 `dual_runtime.run` 把 plan/explanation/critique 反复写回后续提示的源码路径，这直接支持“提示中的共同计划主导了输出，80-token 上限造成重复截断”的解释。它证明这一机制足以复现历史结果，不扩大为所有模型、所有提示或所有历史系统状态的唯一成因。文本自我一致性不能充当独立的图像语义评价。

## 数值证据与成本

29 个 `.safetensors` 共 **26,239,504 bytes** 保留在：

`ai395:/home/qq/work/hepta-r1-4835-20261105-w0-r1/evidence`

此目录内原始六例、数值补存和历史复现分开保存。所有 134 个声明范围内的源码、输入、模型和证据文件已重新计算 SHA256；29 个张量文件又实际重读并验证 raw tensor 指纹、dtype、shape 和有限性。完整清单文件 SHA256 为 `c31c58c0dfb3803ee14cec06baa81a1b9b8c6d8ace15da0a0e4791dc249cd5d4`。本提交保留小型清单和轨迹，大型 tensor 本体留在该持久隔离目录。

| 原生测量范围 | CPU 秒 | wall 秒 |
| --- | ---: | ---: |
| 环境安装、模型获取校验与原始六例 | 62.537423 | 571.481420 |
| 六例实际数值补存 | 16.213814 | 11.375481 |
| 历史九例与两个对照 | 104.808760 | 64.655945 |
| 三批合计，23 次 VLM 调用 | **183.559998** | **647.512847** |

wall 合计是互不重叠的已测进程区间之和，不是整个会话历时。内层逐例时间不能再加到外层。另有清单重读 1.635805 CPU 秒、1.860938 wall 秒，和单独 Git 可用性探测。原 Actions 六例本身为 22.041747 CPU 秒、15.303040 wall 秒；其完整 setup CPU 没有被这些诊断时钟覆盖。

[COST_LEDGER.json](COST_LEDGER.json) 保留各时钟边界和未知成本。能耗、代理协调、工具传输、部分最终记录写入与发布流程均没有被偷偷记为零；因此不据此计算完整净效用收益或生产延迟。没有训练或模型晋级。

## R2 的可复核冻结与剩余工作

[R2 partial freeze](r2/PARTIAL_FREEZE.json) 将原始来源、四臂、gamma=2 CE、七个目标差、32 个完整拟合种子、成对 source/fit 统计单位、完整成本类别和强 fixed/greedy/planner/检索定义固定下来。固定字段的 canonical SHA256 为：

`f720cbb1e97087c8be4ffaec5f006589876b1b3e67dba1cc7ea47c93f4bb108b`

R1 测量门已满足；差的 baseline 不禁止未来按预注册尝试改进。当前仍不能以 R1 样本、同组 fixture 或同一生成器自评替代新测试集与独立评价。R2 没有训练、没有打开新 test、没有比较结果；[剩余门槛](r2/REMAINING.md) 明确列出真正未固定的部分。

## 只读复核

```bash
python scripts/verify_evidence.py . --receipt VALIDATION.json
```

该脚本校验文件清单、23 个原生调用、9/9 历史同文、两个计划对照、三份模型作业终态、清单重读终态、Actions artifact 关联和 R2 固定字段摘要。成功只表示证据一致，不表示语义验收或产品测试通过。原运行脚本保留在 `scripts/`，其中使用原隔离目录，不能直接对同一目录重跑覆盖已有证据。仓库整体 Rust 格式检查在该源码投影中没有可用的 `codex-rs` 工作区，实际尝试与范围见 [FORMAT_SCOPE.json](FORMAT_SCOPE.json)。

## 发布记录

第一次原生发布在自设空白检查处停止，原因是作为执行证据保留的 launcher 末尾有一空行；尚未 commit/push。原字节保留，失败终态和成本在 [publication](publication/NATIVE_ATTEMPT_1.json)。父任务已报告 normal Git 账户 suspended/403，后续使用明确授权的 GitHub app；不重复原生 push，不改凭据，也不更新 #4835、main 或产品集成分支。最终 publication SHA/tree 对照作为独立回执保留，避免把自引用 SHA 写入自身提交。
