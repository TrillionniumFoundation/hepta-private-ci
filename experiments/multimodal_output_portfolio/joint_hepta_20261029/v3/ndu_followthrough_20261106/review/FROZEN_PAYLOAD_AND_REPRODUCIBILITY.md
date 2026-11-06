# Payload and reproducibility review

审核对象：`frozen_work/`，共 **66 个普通文件、454,023 字节**；本报告放在该目录之外。此次仅检查文件、哈希、源码与包版本元数据，**未运行 LLM、任务工具或研究审计脚本，未修改冻结源码，未上传或推送**。9 个冻结输入／源码及结果绑定的 50 个原始文件均与既有哈希一致。

## 载荷检查

- **未发现凭据或非公开账户输入。** 文本及解压后的 SQL 经 token／私钥／授权头／带凭据 URL 模式检查，零命中；也没有环境变量快照、账户消息、支付信息或模型服务密钥。此结论是文件检查结果，不是通用秘密检测保证。
- **没有模型权重、虚拟环境或软链接。** 两份模型 JSON 只含公共模型身份、文件 URL、字节数和哈希。
- 包中完整保留带许可的公共 Chinook SQL 与 CPython `statistics.py`。逐项字节数、SHA-256、Git blob 以及 gzip 哈希均匹配 `inputs/sources.json`；许可文件随包。
- **不能将载荷描述为“零个人信息样式字段”。** 完整 Chinook 示例 SQL 含 Customer／Employee 的姓名、地址、电话、生日等字段，以及 67 个不同的 email 样式值。它们来自固定的公共上游示例数据，不是用户连接账户的数据；这些联系字段并非本轮计数任务所需，但已包含在原始冻结输入内。本次没有删除、脱敏或复制到报告中。私有完整 ZIP 可保留原始证据；若决定制作更小的公开分发包，应另立打包清单，不能静默改动冻结 SQL 或其哈希。
- `private_expected.json` 是从公共输入计算的评价参考答案，“private”表示不向模型控制器提供，并非私人账户数据。原始 receipt 中还有通用绝对运行路径（`/workspace/scratch/...`、`/opt/codex/runtimes/...`）、UTC 时间、版本及资源数据；没有发现真实姓名式用户目录。历史路径仅作执行记录，不是重放必须复建的路径。

## 两种可重放范围

| 目的 | 包内是否足够 | 外部要求与限制 |
| --- | --- | --- |
| 阅读并校验既有结果 | **足够**：源码、协议、freeze、全部原始 receipt／episode、参考数据与许可齐全 | `audit.py` 只用 Python 标准库（包括 `sqlite3`），不需要权重、tokenizer、Torch、联网或 LLM。它会从随包 SQL／源码重建评价参考，不会启动模型或任务工具子进程。原审核环境为 Python 3.12.14；本次没有重跑审核。 |
| 重新执行八次 forward 与工具比较 | **不自包含**：模型身份与所有输入齐全，模型／运行时须另备 | POSIX／Linux 运行环境；`study.py` 使用 `resource`、process groups 和 `SIGKILL`。需要下述完整模型文件及兼容 Python 环境。CPU 即可，实际协议使用 float32、两线程。不能承诺其他硬件的数值逐位一致或相同墙钟。 |

既有证据的审核命令（输出路径必须尚不存在）：

```bash
cd /path/to/frozen_work
python3 audit.py --results results/run-01 --output /tmp/ndu-review-new.json
```

重新 forward 所需固定模型为 **Qwen/Qwen2.5-0.5B-Instruct**，revision **`7ae557604adf67be50417f59c2c2f167def9a775`**。`inputs/model_manifest.json` 注册全部 **9 个文件、999,602,607 字节**，包含 `model.safetensors`、tokenizer／配置及 LICENSE／README；所有文件必须实际物化为普通文件，不能使用缓存软链接。公开下载 URL 与精确 SHA-256 都在 `inputs/materialized-model.json`；模型加载为 offline、`trust_remote_code=False`、safetensors。

现有运行时的只读版本元数据为：Python **3.12.14**、Torch **2.15.0+cpu**、Transformers **5.22.1**、safetensors **0.8.0**、NumPy **2.5.4**、tokenizers **0.23.3**、huggingface-hub **2.4.0**。包内**没有完整环境锁、依赖 wheel 或自动安装器**；这份列表不是全部传递依赖或二进制环境证明。重做 forward 应先配齐匹配环境，并传入新的输出目录：

```bash
python3 study.py run \
  --runtime /path/to/pinned/venv/bin/python \
  --model-dir /path/to/materialized/model \
  --output /tmp/ndu-forward-new
```

脚本按自身位置定位输入，freeze／原始结果哈希使用相对路径，因此整目录搬迁无需改源码。勿重新生成 `freeze.json` 来掩盖方法或输入变化。包不含此前三轮研究的全部原始档案；对旧研究的完整重建仍须取得其既有独立交付。

## 结论与发布边界

本轮仅表明：**更简单、公开命名操作的新有限动作任务上，冻结模型 3/8 正确，literal router 8/8 且更快。** 新任务仍使用两个已披露的 source clusters。绝不能将它说成旧 **54 次 responses／48 个 episodes** 的自由 SQL／源码任务已修好，也不能把八次 forward-only 决策混称为旧自由生成 benchmark 的成功。当前候选强基线比较为负；独立泛化、NDU 机制优势与全成本净收益仍未建立。

**本交付检查不构成对实际 public 仓库的发布授权。** 当前文件仍是待交付／待确认的研究载荷；本次没有外传。
