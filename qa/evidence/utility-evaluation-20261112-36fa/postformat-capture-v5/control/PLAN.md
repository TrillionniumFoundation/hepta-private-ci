# V5 实际 postfmt 只读采集器

状态为 HOLD，尚未执行。Root 审阅并生成独立批准配置后，由 native_ci_audit 单一执行者启动一次。此程序不调用 Cargo、formatter、原 caller verifier 或 f868 extractor，不写源码、Git 对象、index 或 refs。

## 已观察到的输入

实际 V5 作业为 `1a1d16f37be-2564-1c4a`。原 RESULT、fix/fmt terminal、normal SDK、V5 EX lease 和 ARTIFACTS 已完整读取；配置中的身份来自这些原件。fix 返回 0 且没有源码变化；fmt 返回 0、产生 43 个 Rust postimages。HEAD/tree 保持 `9c4a11f6… / ee42ec7e…`，完整实际 inventory 为 5,614,211 B、SHA256 `3f28f2ea4b78a0b3faa41024bd1664c2201ad21cb3c3f3465cb40192b034f58f`，工作树物理 Merkle 为 `65b898bad23cd58c7f6fd53fafe618f9cf9562dc`。

程序仅从冻结的 `3480e178…` handoff 请求复用 73 路径及分组，路径文本锁定 `66a19f69…`。该旧请求的 V4 历史 provenance 不充当当前输入；当前 V5 records、job、原始成功状态和真实 EX lease 在本配置及代码中单独绑定。

## 原生执行合同

独立 create-only control 目录拟为 `fresh-maintenance-86dd-v1/postformat-capture-control-v1`。需准备 collector、批准配置、原 handoff 请求、原路径清单，以及已观测 normal SDK 的精确字节。原 inventory driver 继续使用既有外置 `inventory-driver-v2.py`，精确身份 `51181866…`。

建议唯一 idempotency key 为 `hepta-utility-36fa-postformat-handoff-v5-v1`；原 argv 为：

```text
python3 -B <control>/collector.py --config <control>/APPROVED_CAPTURE_CONFIG.json --config-sha256 <actual-approved-config-sha256>
```

拟独立观察预算 300 秒、结束保全 60 秒、外层 420 秒。它们只约束本次只读传输准备，不改变原维护或任何资格门禁预算。任何现存 output 目录都会拒绝；不得换 key 重复运行来替代未观察终态。

## 采集与保全

程序核真实 V5 normal0、原 RESULT、两阶段 original execute_logged 及 terminal、完整 final audits。然后对已建立的 `SOURCE_COORDINATION.lock` 取得非阻塞 SH，核同 device 2050、inode 50139448、uid 1000、0600、nlink1，并另存本次实际 SH lease。锁仅协调本任务合作写者，不回溯证明历史或阻止全机所有进程。

使用原 `51181866…` inventory 函数取得完整 source before/after；两个原字节必须与已观察的完整 final inventory 一致。另保存完整 Git metadata before/after 并要求相同，所有输入也在结束阶段重新校验。73 个实际文件必须逐项符合完整 physical row 的 bytes、SHA256、working_blob 和 permissions；index_blob 不替代 changed working bytes。原 dirty status、HEAD tree 与工作树物理 Merkle 分开保留。

包包括 73 文件的完整 base64 原字节和完整 inventory row，另保留原 final inventory gzip、完整 final postimages gzip、原记录、实际锁记录与前后 inventory。新大包使用 gzip 和不超过 262,144 decoded bytes 的 base64 分片，逐分片保存身份；原件不改写。实际物理树来源是固定原 V5 summary 与 Root 对完整 raw inventory 的独立重算，此采集不伪称再次执行原维护。

成功仅标 `CAPTURED_ACTUAL_POSTFMT_REVIEW_REQUIRED`。任何前置、读回、原输入、源码、Git 或锁核验异常保留为 Unknown，并保全已有记录；不得将包内部分字节视为成功整包。原 f868 仍需独立 Root-reviewed 实际合同与完整 46-source pins，采集器不生成审批、不执行 extractor、不写最终 markers。

最后 non-Rust/protection/QA/allowlist 修改完成后仍须原 `just fmt --base c0f78493…`、900 秒，然后再核实际 postimages 并冻结。该命令不等于格式化 `qa/b4-no-bypass/*.py`、CALLERS.toml 或 allowlist。若 protected Rust 再变化，必须重新按实际字节同步。
