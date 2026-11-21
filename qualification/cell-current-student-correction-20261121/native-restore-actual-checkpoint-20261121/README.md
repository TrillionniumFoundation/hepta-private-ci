# E2：实际来源冻结、部署、格式化与独立验证环境恢复

本包保全 E2 新发生的工程证据：固定来源清单已经实际发布，源码和选择证据已完成 create-only 部署，独立验证环境已经完成一次离线恢复及唯一一次纯数据准入。它不提供新的训练收益、独立新任务提升或 Adopt 结论。

## 实际发布与输入

来源冻结的实际 commit 为 `4c55d9bfe1898c0066b3ae7cb05744fe99f6b418`，parent 为 `c1ce4de7c9bd6c48bae155aeedbfe04f7ccf3196`。tree、commit、非 force 分支更新、固定 commit 的原字节回读、62 个路径/blob 对应关系，以及 Draft PR #6833 的原始回执都在侧包中。

`SELECTION.json` 里面原有的准备状态文字没有改写。实际发布由单独的 `SELECTION_PUBLICATION.json` 和真实 Git 回执证明。原文件 SHA256 与协议 canonical JSON digest 是两个口径；SUMMARY 分别列出，避免把行尾换行造成的差异误认为内容漂移。

固定池仍为 8 个来源，jaraco/inflect 与 agronholm/exceptiongroup 在扫描前拒绝，其余 6 个只取得按既定顺序扫描的资格，不能据此称已经获得 6 个合格新任务。

11 个固定运行源码文件和 4 个固定选择证据文件的实际创建、完整 SHA256 回读均保留。源码部署首次元数据读取的 3 个 connection error 原文仍在；之后只补取缺失元数据，没有重新创建文件或改写冻结清单。

## 格式化的真实范围

唯一 formatter H job `1a1fddf36ac-ffbe-2000` 真实 succeeded/exit 0，H 输出 complete、durable、publication confirmed。12 份所选源码 before/after 字节一致，实际 `just fmt --base` 结束，stdout 记录没有需要格式化的已匹配变更。

原 checkout 和实际命令 base 是 `7f790fb2f907ef9e618c3c7d233d22135ab00580`，发布参考是 `4c55d9…`；不是完整的 4c55 checkout。这些 qualification 路径不在当次 formatter registry 的 Python 检查范围内，因此不把命令退出 0 写成完整 Ruff 或全仓库格式检查通过。

本包补全 driver 明确写出的全部 28 份 owner 原件：PLAN、8 份命令记录、16 份完整 stdout/stderr、FILES_BEFORE、FILES_AFTER 和 RESULT，总计 330,281 B。已有 5 份原件直接复用保留字节，23 份缺件按固定路径/版本完整取回；没有扫描 checkout 或重跑格式化。

补取时发生 1 次元数据 SSH255 和 1 次 binary SSH255。两份原错误完整保留，分别对同一路径缺失元数据、同版本同 offset 的缺失日志片段补读一次。最终 23 次成功 file_info、27 个成功二进制分片均核对，空日志也实际读取。完整 H stdout 的原 bytes_hex 绑定最终 RESULT 的长度与 SHA256。

## 独立验证环境恢复

唯一实际执行是 desktop 的 H persistent operator PTY：`dpty-fadb7d99e0695d559d4b7d91aa8342d723d880174dd089e97d9cdc45532deed5`。终态 exited/exit 0，完整 merged stream 为 534 B，并与独立读取的 output.log whole SHA256 一致。PTY 不被冒充为 process_job H，也不推断它具有后者的终态标志。

五个阶段分别为：新建无 pip 的独立 venv、原 pip24 离线引导、安装原 9 个 wheel、pip check、包 metadata 与 pytest import identity 检查。五阶段实际 wait returncode 均为 0，记录的 owned process group 在 wait 后均已消失。恢复 owner 内层用时约 18.844 秒；阶段时间包含于 owner 时间，不能相加当作新的总成本。

原始 owner 清单是 RESULT 中的 46 项，加 RESULT 和 POST_FSYNC，恰为 48 份、1,516,453 B。它与实际 admission request、物理 owner 文件集合完全一致。68 个成功传输片段的 base64、chunk SHA、version、offset 及完整文件 SHA 均从原响应独立核过；唯一 60,000 B 片段的 SSH255 原错误和同 pin 单次补读保留，没有重新执行恢复。

唯一 frozen 纯数据 admission 实际退出 0；它从已完成执行的原件建立准入，未再次安装、运行测试或调用模型。最终 `NATIVE_ENVIRONMENT.json` 为 447,364 B，SHA256 `5d86a0fa1260f171ba1cc2e9ac01e4a015b915bb48e3dcd06b55d8b74328a7ed`。原候选、实际 request、claim、stdout/stderr、退出回执、最终准入文件和 root 接受记录全部保留，封包者没有再次运行 admission。

两个原始 inventory pass 完全相同，包含 1,724 个文件和 130 个目录，每 pass 按原范围哈希 38,179,403 logical bytes。范围为新 venv 及明确哈希的外部文件符号链接目标；host system-library/mount closure 仍为 false。Python socket/process audit hook 也不被扩大解释为整个操作系统网络隔离证明。

恢复阶段记录的科学调用、模型调用、native 测试和训练更新均为 0。后续 first-source metadata/scan 另行保全；本包不声称整个会话此后仍零新来源访问，也不是推进该后续工作的新门槛。

## 归档、错误与依赖

侧包包括实际 root 控制原件、完整 formatter owner、恢复线程冻结的 158 个文件、独立字节复核及所有相关原始传输错误。物理成员中有用于追溯的重复字节和分片，它们不是新增独立科学样本。

既有 11 个 restoration envelope blobs 和 17 个 preparation blobs 仅以精确路径、长度、SHA256、Git SHA1 引用，见 `reviews_and_capture_indexes/EXISTING_IMMUTABLE_DEPENDENCY_REFERENCES.json`。本包不重装其 payload，不递归复制旧 wheel、旧 selection 大归档，也不改变已有失败探测、准备草稿、固定清单或训练结果。

本地独立 review 的一次错误比较也单独保留：最初把原文件 SHA 与不含行尾换行的协议 canonical digest 相比，断言失败；原 Git 回读字节当时已经一致。按已有协议定义修正的是复核逻辑，没有改变任何被审计原件，且这不是原生执行或模型失败。

## 取回与复核

按 `CHUNKS.jsonl` 的 numeric index 顺序连接 `.bin` 原字节，先核 `CONTAINER.json` 的完整长度和 SHA256，再只读打开 tar.xz。每片最多 350,000 B。`MEMBERS.jsonl` 覆盖每个物理成员；归档内 `SIDECAR_MANIFEST.json` 保留实际来源及类别。

所有归档成员均为普通数据文件、mode 0644；保留的旧代码不会被自动执行。主要审计入口为 `reviews_and_capture_indexes/INDEPENDENT_RESTORE_ORIGINALS_REVIEW.json`、`CONTROL_ORIGINALS_REVIEW.json`、`ADDITIONAL_SELECTION_INPUTS_REVIEW.json` 和 `format_owner_originals_complete/COMPLETE_READBACK_REVIEW.json`。

本次交接只创建新的不可变 Git blobs，root 独占后续实际 tree/commit/ref/PR 操作。已发生的 selection 发布回执和之后的新包发布是两个独立事件。
