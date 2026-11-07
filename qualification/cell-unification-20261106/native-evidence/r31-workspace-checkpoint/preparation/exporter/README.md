# R31 工作区闭合归档器：惰性准备

`export-r31-closed-template.py` 保持 `FROZEN=False`，`TERMINAL_PIN`、`CLOSED_ORIGINAL_PINS`、`CONTROLLER_ORIGINAL_PINS` 三个未来绑定均为 `None`。本目录只进行了文本派生、AST 与静态接口检查；没有执行、import 或上传归档器，没有读取 R31 活动测试日志。

实际 producer 为 source53 的 `native-run-r31.py`，128,291 字节，SHA256 `2dc7b84b7dad0d6e150817e0dfc4105c4bb4d343103aacef0fb932eab698a6f9`。它绑定 commit `f74be175de66a4b351cd239d39d98cd34fe9cc1b`、tree `440d4a8e09af4009e4d9ea067388826308da8803`、197 条源码、原 HEAD `bef6fa7645df9df12b69fda499e97eed25de6c75` 与未变双锁。原 job 为 `1a1b275ba33-fc05-7e17`，使用直接文件 argv `/usr/bin/python3 …/native-run-r31.py`。

## 原件与结果边界

成功情形要求 actual producer 的 18 份完整原件及自然发布的 outer terminal；未来绑定须来自实际闭合文件清单。失败情形保留真实存在的原件，以及实际 `incomplete` 或 `orchestration-error`，不会补造一套 18 文件的成功目录。完整原日志仍去除尾部重复摘要，按 `(binary, name)` 重建执行身份。20228 个 R29 原身份只用于事后集合比较，不成为任何执行 selector。

原 nextest 没有完整 Starting/Summary 时，终态测试总数和结果计数保持 `null`，即使日志中已经出现部分执行行。原 raw return、receipt、resource exit、源码守卫、完整 controller ranges 分别保存；派生审计问题另列，不覆盖原非零返回。新的归档结果不能把编译失败或不完整执行改称运行零个测试。

三个前置来源分别保存并读取：

- **R30/source53**：19 原件和自然 outer 0；原 strict 与完整 1345 个 app-server 身份通过。它是同源项目门，仍不是 R31 工作区终态。
- **R28/source52**：26 原件和自然 outer 0；32 个 Python 测试及原四包 1564 身份通过。它保留历史 source52 身份，不替代当前 R30 或 R31。
- **R29/source52**：原 metadata、完整日志、rows、review 四大件及失败回执，保留原 `20227 PASS / 1 FAIL` 和 130 reported skip。该失败不会因后续重跑而改标。

实际 source53 的七成员 apply 输入、父级 195 行、source50 原锁链、source51/52 ancestor、R24/R26/R29 原失败来源，以及当前原环境与指导文件随归档保全。完整 197 个源文件使用当前 raw SHA/Git blob/Git mode 检查，前后 HEAD/tree/双锁守卫必须一致。发现源码变化会停止，绝不 reset、apply、重跑测试或格式化。

## 复用与审计

13 个稳定读取、哈希、controller 绑定、源码守卫和 create-only 写入 helper 与已审 R30 exporter 逐字相同；6 个 parser/guard 与实际 R31 producer 逐字相同。`build_template.py`、精确差分和 `MECHANICAL-READBACK.json` 可重现这种关系。`verify_static.py` 只做 AST、静态全局引用和真实旧 raw argv 比较，不执行模板。

自审发现初始准备稿把 R28 和 R30 的历史 tests argv 顺序当成一致：R28 原 `--retries 0` 在 package selectors 之后，R30 在之前。已仅修正归档器的历史比较表达式；初始稿、修正差分与实际五个 phase 的原 raw command pins 都保留在本目录。没有改变任何历史命令或实际门禁行为。

以后实际绑定和执行仍由 root/native 独立审阅与授权。模板只允许原 Git 读取，不执行 Rust、Cargo metadata、apply、fix、fmt、工具安装或探针。gzip 的 mtime 为 0，tar 的逐成员 raw/mode 与整体读回均保留。归档完成只说明证据已封存，不授予工程、科学或全平台资格；source53 的 `diagnostic_only=true`、`behavior_repair_claimed=false` 边界不变。
