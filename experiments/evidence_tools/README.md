# 公开研究归档回收

`public_archive_retrieve.py` 从指定的完整 40 位 Git commit 下载公开证据，调用既有 `continuous_boundary_flow.evidence_bundle.unpack`，再独立核对恢复后的逐文件字节、权限、完整名册及内部科学 manifest/seal。它只支持下列两个包，使用 Python 标准库，成本字段按 Linux 解释。工具位于独立交付目录，不属于两项研究的封存科学源码。

所有证据载荷仅从 `raw.githubusercontent.com/TrillionniumFoundation/hepta-private-ci/<commit>/experiments/<package>/evidence/bundle/` 获取，不使用认证凭证；并发数默认且最多为 4。分片和完整 archive/manifest 均核对长度及 SHA-256。使用显式 `--index-sha256` 固定入口；省略该参数时，仅以工作副本 INDEX 的长度和摘要作为预期身份，不从本地复制证据载荷。源码中的既有解包器仍从当前工作副本加载，其 SHA 会写入回收收据。

## 恢复两个包

从具有完整研究源码的仓库根目录执行。将两个 commit 占位符分别替换成**实际包含该完整包的不可变公开提交**；分批发布期间它们可能不同。下面的命令是操作说明，是否完成恢复须查看实际产生的收据。

```sh
export PYTHONDONTWRITEBYTECODE=1
export HEPTA_PUBLIC_ROOT=/tmp/hepta-public-evidence-20261029
export HEPTA_READOUT_PUBLIC_COMMIT=REPLACE_WITH_FULL_PUBLISHED_READOUT_COMMIT
export HEPTA_REPRO_PUBLIC_COMMIT=REPLACE_WITH_FULL_PUBLISHED_REPRODUCTION_COMMIT

python experiments/evidence_tools/public_archive_retrieve.py \
  --commit "$HEPTA_READOUT_PUBLIC_COMMIT" \
  --package native_readout_objective \
  --index-sha256 1806fefb03898682c9ce4599a9b74da899552c92ddd2d658bc85e9875e57cf52 \
  --output "$HEPTA_PUBLIC_ROOT/readout"

python experiments/evidence_tools/public_archive_retrieve.py \
  --commit "$HEPTA_REPRO_PUBLIC_COMMIT" \
  --package continuous_boundary_policy_reproduction \
  --index-sha256 adfda2870eaf807df3d47fceb9cc64207b1c854cd6a904536b22d26fad963b73 \
  --output "$HEPTA_PUBLIC_ROOT/policy-reproduction"
```

每个输出目录必须尚不存在并位于源码 checkout 外。工具同时要求以下同级路径全新：`OUTPUT.public-bundle/` 保存公开下载，`OUTPUT.PUBLIC_RETRIEVAL.json` 保存 URL、commit、所有层级身份与成本，`OUTPUT.PUBLIC_FILE_VERIFY.jsonl.gz` 保存逐文件验证名册。恢复目录内保留原来的 `study/` 和 `engineering/`；不改写其原路径、时钟或内容。失败时保留已有载荷、尝试信息和失败收据；再次尝试使用另一个全新输出路径。

## 在恢复证据上重算独立科学审计

机械恢复成功不等于科学审计通过或收益门槛通过；回收收据明确记录 `scientific_semantics_reaudited: false`。先按各包的 [readout 指南](../native_readout_objective/REPRODUCE.md)和 [policy reproduction 指南](../continuous_boundary_policy_reproduction/REPRODUCE.md)恢复记录的 Python/NumPy/SciPy/Linux 数值环境。保留完整 Git 历史，并更新审计所需的明确远端引用：

```sh
git fetch origin \
  research/continuous-boundary-flow-20261028:refs/remotes/origin/research/continuous-boundary-flow-20261028
export OPENBLAS_NUM_THREADS=1

python -m experiments.native_readout_objective.audit \
  "$HEPTA_PUBLIC_ROOT/readout/study" \
  --repository "$PWD" \
  --output "$HEPTA_PUBLIC_ROOT/readout-recomputed-audit.json"

python -m experiments.continuous_boundary_policy_reproduction.audit confirmation \
  --study "$HEPTA_PUBLIC_ROOT/policy-reproduction/study" \
  --native-binary "$HEPTA_PUBLIC_ROOT/policy-reproduction/engineering/bin/continuous_host" \
  --score-binary "$HEPTA_PUBLIC_ROOT/policy-reproduction/engineering/bin/boundary_policy_score_host" \
  --output "$HEPTA_PUBLIC_ROOT/policy-reproduction-recomputed-audit.json"
```

审计输出也必须是全新文件，并置于恢复目录外。policy 命令读取两份二进制核对字节身份；这些命令不重新训练或生成确认轨迹。保存实际复算输出，并与相应 `engineering/audits/` 内的原审计逐项比较；工程重新执行另见各包指南，不由回收工具代替。

## 成本和工具身份

回收收据的总 wall、进程 CPU 和峰值 RSS 覆盖 Python imports 后的 `main` 主体，截止最终收据序列化之前。下载等待、长度和摘要核验、解包、逐文件复核均在该范围内；各阶段时钟是总时钟的子集，并发下载条目的 wall 相互重叠，不能再次相加。成本不含 Git clone/fetch、环境安装、独立科学审计或原研究训练/运行；未测量硬件能耗。

工具及本说明的精确 SHA-256 保存在 [SHA256SUMS](SHA256SUMS)，可在此目录执行 `sha256sum -c SHA256SUMS`。每次实际执行的回收收据还绑定工具自身与既有解包器的实际 SHA-256。
