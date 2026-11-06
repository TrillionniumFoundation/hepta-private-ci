# source53 finalization 正式组装

这里只读取已闭合本地原件，不运行 native、Git、Cargo、metadata、fix、fmt、版本查询或测试，不写源码、ledger、INDEX、canonical 报告或既有正式组。

`prepare_actual_bindings.py` 对 native 的 24 份实际输出、root 唯一下载的三份完整源码归档，以及实际授权、35 项绑定、fresh scope、工具盘点、scope 上传和根审查逐项重算原字节 SHA256/Git blob。未提供完整 peer HANDOFF 时只产生 `frozen:false` 的明确待封计划；不会据小件推断三份归档已经完整验收。

收到完整独立读回后，生成一个新的、不可覆盖的实际绑定文件：

```sh
python source53-finalization-formal-preparation/prepare_actual_bindings.py \
  --peer-handoff <真实独立读回目录>/HANDOFF-MANIFEST.json \
  --output ACTUAL-BINDINGS.json
```

随后由本地组装器一次创建新组：

```sh
python source53-finalization-formal-preparation/assemble_finalization.py \
  --bindings source53-finalization-formal-preparation/ACTUAL-BINDINGS.json
```

组装器独立核三 tar 的完整 member 集合、模式、大小、SHA256、Git blob 和 embedded manifest；核两个原命令的 raw/effective/资源退出码、guard、实际 delta 与 stage、完整 controller 和警告原始 byte offsets。完整 Git tree 的重建和 patch 的正反机械核另由附入的 root 与 peer 读回说明，不能把本组自己的 raw-member 核验冒称全部源码树重建。

三份 197 路径快照只保留在各自 tar 内，不再复制三套展开源。原始 `complete.json` 的 `final_formatted_commit:null` 保持原文；真实最终 code commit 由 root 另行登记。原测试资格固定在 f74be175de66a4b351cd239d39d98cd34fe9cc1b / 440d4a8e09af4009e4d9ea067388826308da8803，格式化后没有本地测试，资格不自动转授给新树。

`just fix` 原退出码 0 与严格 `-D warnings` 门分开；原两条 i18n lifetime 诊断及一条 agentd large_enum_variant 诊断、package/重复摘要和完整日志均保留。不添加 allow，不为抹去 warning 运行额外命令。source53 的 diagnostic-only、根因未修复主张、科学 HOLD、权限 DENY_ALL 及历史失败保持。

组装成功只产生新 `native-evidence/source53-finalization-checkpoint/`、完整映射/manifest 和待 root 上传的 `BINARY-PLAN.json`。它不创建分支、PR、Git 对象或 CI 结果。
