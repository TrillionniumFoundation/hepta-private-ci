# V12 复现与证据恢复

本指南按实际 CLI 整理；编写时只读源码，没有启动新实验或测试。行为回归、科学实验重放、原生验证和跨 VM 验收分别留存证据。新运行不能覆盖已有冻结目录。

## 1. 环境与新输出根目录

从完整研究 checkout 的仓库根目录运行以下 Bash。需要 Python 3.12、Git，以及固定源提交 `527218f9b823540830907f861a309310b71d38c9` 的 Git 对象和 40 份 `docs/modules/*/TECHNICAL.md`。语料构造器逐文件核对 Git blob；缺少或修改来源时应修复 checkout，不要关闭身份校验。

```bash
set -euo pipefail
HEPTA_V12_REPO="$PWD"
HEPTA_V12="$HEPTA_V12_REPO/qualification/memory-cell-v12"
HEPTA_V12_RUN="$(mktemp -d "${TMPDIR:-/tmp}/hepta-v12-reproduce.XXXXXXXX")"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1
python3 -m venv "$HEPTA_V12_RUN/venv"
HEPTA_V12_PY="$HEPTA_V12_RUN/venv/bin/python"
"$HEPTA_V12_PY" -m pip install --disable-pip-version-check \
  numpy==2.3.5 scipy==1.17.0 scikit-learn==1.8.0 joblib==1.5.3 threadpoolctl==3.6.0
git rev-parse HEAD > "$HEPTA_V12_RUN/source-commit.txt"
"$HEPTA_V12_PY" --version > "$HEPTA_V12_RUN/python-version.txt"
"$HEPTA_V12_PY" -m pip freeze > "$HEPTA_V12_RUN/dependencies.txt"
```

这些是隔离 Python CI 的明确依赖版本。科学实验还记录各自运行环境；Python patch、BLAS、平台、时间和 gzip 元数据等不保证跨机器逐字节相同。先确认有足够可用磁盘；原 CE attempt 确实曾因磁盘耗尽中断。保留失败和中断输出，下一次使用新的输出根目录。

## 2. 当前版本的 38 项行为回归

```bash
"$HEPTA_V12_PY" -m unittest discover -s "$HEPTA_V12" -p '*_tests.py' -v \
  2>&1 | tee "$HEPTA_V12_RUN/python-tests.log"
```

当前测试清单为 content 4、document cell 4、factorized 3、federation 10、learned 3、network 9、typed 5，共 38 项。该命令不代表重新取得科学优越性结果；当前代码的行为通过也不能回填为旧实验曾执行的保证。

## 3. 用当前修复版生成新实验

下列每个输出子目录必须不存在。document cell/content 使用 `--out`；network/factorized/typed 使用 `--output`。`typed_analysis.py` 的唯一位置参数是新 typed 输出目录，它会在其中写入 `ANALYSIS.json`。

```bash
"$HEPTA_V12_PY" "$HEPTA_V12/document_cell_experiment.py" \
  --repo "$HEPTA_V12_REPO" --out "$HEPTA_V12_RUN/current-document"
"$HEPTA_V12_PY" "$HEPTA_V12/content_experiment.py" \
  --repo "$HEPTA_V12_REPO" --out "$HEPTA_V12_RUN/current-content"
"$HEPTA_V12_PY" "$HEPTA_V12/network_experiment.py" \
  --repo "$HEPTA_V12_REPO" --output "$HEPTA_V12_RUN/current-network-bce" \
  --protocol "$HEPTA_V12/NETWORK_PROTOCOL.json"
"$HEPTA_V12_PY" "$HEPTA_V12/network_experiment.py" \
  --repo "$HEPTA_V12_REPO" --output "$HEPTA_V12_RUN/current-network-ce" \
  --protocol "$HEPTA_V12/NETWORK_FOLLOWUP_PROTOCOL.json"
"$HEPTA_V12_PY" "$HEPTA_V12/factorized_experiment.py" \
  --repo "$HEPTA_V12_REPO" --output "$HEPTA_V12_RUN/current-factorized" \
  --protocol "$HEPTA_V12/FACTOR_PROTOCOL.json"
"$HEPTA_V12_PY" "$HEPTA_V12/typed_experiment.py" \
  --repo "$HEPTA_V12_REPO" --output "$HEPTA_V12_RUN/current-typed" \
  --protocol "$HEPTA_V12/TYPED_PROTOCOL.json"
"$HEPTA_V12_PY" "$HEPTA_V12/typed_analysis.py" "$HEPTA_V12_RUN/current-typed" \
  > "$HEPTA_V12_RUN/current-typed-analysis.log"
```

document cell 的 `--crash`、`--artifact` 是父进程编排故障子进程的内部入口；正常复现使用上面的完整 driver。其受控更正、撤销及 SIGKILL 均发生在新输出目录，不是仓库生产历史。

## 4. 验证与恢复已发布证据包

每个包须具备 manifest 列出的全部分片。`verify` 检查分片、完整 archive、每个原始成员的 SHA-256 和长度；`restore` 再执行同样检查，并拒绝覆盖已有输出目录。以下只写新的恢复树：

```bash
HEPTA_V12_FROZEN="$HEPTA_V12_RUN/restored"
for pack in document-cell-v2 content network network-categorical \
  network-categorical-seed51047 factorized typed; do
  "$HEPTA_V12_PY" "$HEPTA_V12/evidence_pack.py" verify \
    --pack "$HEPTA_V12/evidence-packs/$pack"
  "$HEPTA_V12_PY" "$HEPTA_V12/evidence_pack.py" restore \
    --pack "$HEPTA_V12/evidence-packs/$pack" --out "$HEPTA_V12_FROZEN/$pack"
done
```

其他历史、原生及 federation 包可用相同接口，选择不同的新恢复目录。若要封装自己的新运行：

```bash
"$HEPTA_V12_PY" "$HEPTA_V12/evidence_pack.py" pack \
  --source "$HEPTA_V12_RUN/current-content" \
  --out "$HEPTA_V12_RUN/new-content-pack" --label local-content-reproduction
```

归档压缩仅为传输与保留证据；不能用压缩包大小代替模型、来源、索引、optimizer 或训练成本。详见 [EVIDENCE_AUDIT.md](EVIDENCE_AUDIT.md)。

## 5. 用旧冻结源码重放

当前源码含 optimizer 校验、network lifecycle、document cell 等后续修复。旧运行的准确代码在各包 `EXECUTED_SOURCE`，应从该目录启动脚本，使同目录模块与协议一起加载；显式传 `--repo`，因为恢复后默认相对仓库路径已失效。不要将当前文件拷进冻结源码树。

```bash
"$HEPTA_V12_PY" "$HEPTA_V12_FROZEN/document-cell-v2/EXECUTED_SOURCE/document_cell_experiment.py" \
  --repo "$HEPTA_V12_REPO" --out "$HEPTA_V12_RUN/replay-document-v2"
"$HEPTA_V12_PY" "$HEPTA_V12_FROZEN/content/EXECUTED_SOURCE/content_experiment.py" \
  --repo "$HEPTA_V12_REPO" --out "$HEPTA_V12_RUN/replay-content"
"$HEPTA_V12_PY" "$HEPTA_V12_FROZEN/network/EXECUTED_SOURCE/network_experiment.py" \
  --repo "$HEPTA_V12_REPO" --output "$HEPTA_V12_RUN/replay-network-bce" \
  --protocol "$HEPTA_V12_FROZEN/network/EXECUTED_SOURCE/NETWORK_PROTOCOL.json"
"$HEPTA_V12_PY" "$HEPTA_V12_FROZEN/network-categorical/EXECUTED_SOURCE/network_experiment.py" \
  --repo "$HEPTA_V12_REPO" --output "$HEPTA_V12_RUN/replay-network-ce" \
  --protocol "$HEPTA_V12_FROZEN/network-categorical/EXECUTED_SOURCE/NETWORK_FOLLOWUP_PROTOCOL.json"
"$HEPTA_V12_PY" "$HEPTA_V12_FROZEN/factorized/EXECUTED_SOURCE/factorized_experiment.py" \
  --repo "$HEPTA_V12_REPO" --output "$HEPTA_V12_RUN/replay-factorized" \
  --protocol "$HEPTA_V12_FROZEN/factorized/EXECUTED_SOURCE/FACTOR_PROTOCOL.json"
"$HEPTA_V12_PY" "$HEPTA_V12_FROZEN/typed/EXECUTED_SOURCE/typed_experiment.py" \
  --repo "$HEPTA_V12_REPO" --output "$HEPTA_V12_RUN/replay-typed" \
  --protocol "$HEPTA_V12_FROZEN/typed/EXECUTED_SOURCE/TYPED_PROTOCOL.json"
```

以上 CE 命令执行原方案的全部三个 seed；复现单独补跑 seed 51047 时，应把其 `FREEZE.json` 的 `protocol` 导出到新文件，再通过 `--protocol` 传给该补跑包的冻结脚本。不要改原协议，也不要把原 7/9 阶段中断 attempt 覆盖成完整运行。中断 wall/CPU 缺口及训练成本下界不会因重放成功而消失。

typed 重放完成后，可用当前 `typed_analysis.py "$HEPTA_V12_RUN/replay-typed"` 作明确标注版本的后处理。`ANALYSIS.json` 记录分析源码和 summary 哈希。三个 seed 共用同一语料和任务；typed 的 618 次未来评估是 206 个任务的重复评估，不是 618 个独立样本。

## 6. 原生验证与固定输出生成器

原生验收使用 [memory-cell-v12-native.yml](../../.github/workflows/memory-cell-v12-native.yml) 的准确净提交。该 workflow 从同一源码构建实际 `codex-app-server`，绑定 `HEPTA_TEST_CODEX_EXECUTABLE`，保留工具版本、二进制摘要、JUnit、阶段源码 diff 和退出码；输出放入该 run 的新 runner 临时目录。

测试顺序固定为 `just test --locked --lib --retries 0 -p codex-hepta-memory -p codex-hepta-agentd`，随后 scoped `just fix --locked -p codex-hepta-memory -p codex-hepta-agentd`，最后 `just fmt --base 527218f9b823540830907f861a309310b71d38c9`。遵守仓库要求，使用 `just test`，同一验证 run 在 fix/fmt 后不再重跑测试。如果 finalization 改变源码，审查 patch、创建新提交，再验证该准确提交。科研文档提交不能自动继承未核对源码身份的旧通过结论。

`export_native.py` **没有输出路径 CLI**：它固定创建 `evidence/native-export`，并改写 `codex-rs/hepta-agentd/src/memory_mlp_v12_python_fixture.rs`。不要在保存冻结证据的 checkout 中直接运行它，也不要删除原 evidence 来使它通过。通常恢复 `native-export` 包并使用已提交 fixture 即可。需要重新生成时，在单独准备的全新 checkout 中执行，作为源码变更审查并提交，再走上述原生验证流程；该 fixture 是有界合成数值回归，不是语言能力实验。

## 7. 真实跨 VM 验收

运行 [串行恢复 workflow](../../.github/workflows/memory-cell-v12-federation.yml) 或 [三 VM live workflow](../../.github/workflows/memory-cell-v12-live.yml) 时，重跑**整个 run**。repository、源码 SHA、workflow、run ID、attempt、nonce、checkpoint 和阶段 artifact 必须匹配；不能只重跑失败 job 后混用不同 attempt 的快照。

live 验收需三个 jobs 成功、final 收据以及两个 `completed-<node>` artifact；检查不同 boot/instance、同一 worker PID 的递增请求序号、实际旧 owner 拒绝和撤销后新请求拒绝。final 在末端 ack 前发布，单独 final 不足以证明完整闭环。

本机 `federation_live.py selftest` 只验证三个本地进程，不能宣称跨机器。真实 workflow 也只是 GitHub artifact relay 加单 authority；进程 SIGKILL 不等于物理主机故障，不能由此声称分布式共识、分区可用性或参数遗忘。
