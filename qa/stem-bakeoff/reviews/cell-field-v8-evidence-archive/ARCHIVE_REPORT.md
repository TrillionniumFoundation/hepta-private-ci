# V8 完整证据归档：交付、核验与保存状态

## 归档已经完成，研究结论仍是拒绝

完整本地 V8 包、独立清单和 fsynced 完成回执均已生成。独立 reader 验证全部成员、内容 SHA、硬链接、tar framing/footer 与 gzip CRC/EOF；最终大小与打包前只读测量完全一致。归档不产生科学准入：H8 网格和 remaining-terminal 两项开发研究均未通过确认进入规则。[网格结果](../cell-field-v8-development/GRID_DEVELOPMENT_REPORT.md) [终点结果](../cell-field-v8-remaining-terminal/REMAINING_TERMINAL_V8_REPORT.md)

| 本地交付文件 | 字节数 | SHA256 |
|---|---:|---|
| cell-field-v8-complete-evidence.tar.gz | 318,805,867 | `af02493df470aa28fd91970164f2c79acef3cd09caed740d4ac832d7f32fa524` |
| cell-field-v8-complete-evidence.manifest.json | 6,885,463 | `e344fc9d230a6ae18fb09d4ebb4666b7f99cace9c51b5cd3085cdbad8fe7050f` |
| cell-field-v8-complete-evidence.tar.gz.receipt.json | 2,076 | `46199f4f3ccc8f88a0a71466adcc538dd98fdde6c10865416ea22e7f53b3345c` |

原文件位于本次工作区的根目录，通过本次交付提供下载；318.8 MB 原始压缩包未提交到 Git。Git 中的 [归档回执](archive-receipt.json)、[完整压缩清单](manifest.json.gz) 和 [可还原来源记录](provenance-bundle.json.gz) 供远端审阅。解压后的精确身份及原文成员见 [元数据发布清单](metadata-publication-manifest.json)。

## 完整分母与核验范围

| 项目 | 已核对值 |
|---|---:|
| 批准的证据目录 | 15 |
| 证据文件路径 | 11,105 |
| 内嵌 MANIFEST.json | 1 |
| 普通证据文件 | 9,866 |
| 安全内部硬链接 | 1,239 |
| 原逻辑内容字节 | 442,583,066 |
| 去重后的普通文件内容字节 | 426,745,239 |
| 旧字节承诺不匹配 | 0 |
| 在批准目录中以 Git 引用省略的源码文件 | 0 |

每个硬链接指向包内更早出现、已独立验证且长度/内容/模式一致的普通成员。所有原路径和文件内容保持可还原；原 inode 与文件系统时间不作为科学身份。reader 不依赖原目录，也没有解压到工作区来进行验证。[归档工具合同](../../evidence_archive_v8/README.md)

唯一排除项是 `native-qualification-v8/admission-driver/target` 可重建构建缓存。最终保存的 37 个可执行工具全部在单独的批准目录中保留。完整研究与原生工作树由下面两个固定 Git 身份取得；它们没有被整个复制进本包。

## 历史封存与新增保存身份

完整 common、stop-r2、grid-r2 和 remaining 控制输出沿用各自原始封存映射。原停止诊断、网格和 native 中断尝试按其真实状态保留，包括空文件、截断 JSON、未完成槽和失败日志。

development 混合目录由 7,720 个已有身份绑定文件及 root 逐项审查批准的 21 个 flat 元数据文件构成。后 21 项是本次新增保存身份，包含未执行草案、写盘失败元数据和基础设施记录；不会被解释成早于实验存在的 raw seal。

native r3 的 73 项原外层字节承诺全部匹配。另有 48 个恢复 manifest/NPZ，当时没有完整目录字节清单；本次先与原 receipt 的完整 metadata、θ/m/v 原始字节、时钟/RNG/上下文和张量/payload 承诺核对，再登记新的外层保存 SHA。这个过程没有新的优化器更新，也没有补造历史清单。

早期 native 数值资格所用 executable 的 SHA 与回执仍保留，但该早期二进制本体未保留；37 个最终工具不被描述为它的逐位副本。合成 owner 文件系统的临时测试树也不被宣称为真实候选采用记录。

## 来源记录可以还原原字节

`manifest.json.gz` 是原 6,885,463 字节计划的无损压缩，解压 SHA 与交付清单一致。`provenance-bundle.json.gz` 包含 27 份原文文件：15 个最终目录映射及审批、来源、测量和发布核对记录。每条保留 `content_utf8`、原长度和 SHA；重编码后与原字节逐项一致。原文合计 3,023,246 字节，bundle 解压后为 3,144,974 字节。

| Git 元数据 | 压缩 SHA256 | 解压 SHA256 |
|---|---|---|
| manifest.json.gz | `6a610e2a6d786f8583a4eb48fc012a2a35b2f746779ddfb00942dab94e5e34cf` | `e344fc9d230a6ae18fb09d4ebb4666b7f99cace9c51b5cd3085cdbad8fe7050f` |
| provenance-bundle.json.gz | `91494d2625b347de3d95b0d7c02a71c3c6182907cb9c3c6c7167df44d03d2c16` | `4899c541c81a26af9bb66cccdb46c6b08eee1f28cfbcefaf2cf9905cfaff8306` |

完整 roots 配置的 SHA 为 `1b7ea668b9088c9250366a8d6c1c1b576d74ba1a6456854635e72a80c2e72b02`，配置对象已经嵌入计划并逐字段核对。两个 gzip 使用 `mtime=0`，原始输入在压缩前后保持不变。最终新发生的缓存清理单独发布，不反向改写本包或 27 份冻结元数据。

## 复现先决资料

| 资料 | 固定身份与位置 |
|---|---|
| 研究源码、已发布报告与审计 | [8f03117c9cd2079bd6f3eb71614f9daef97d21ef](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/8f03117c9cd2079bd6f3eb71614f9daef97d21ef) |
| 原生最终源码与资格 | [b899e46a07571a0cbc2b1f8487a1df3001e30313](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/b899e46a07571a0cbc2b1f8487a1df3001e30313) |
| V5 完整输入／证据包 | SHA `7bdb8e546203edbce708062bd6e9cdf060be3160d655ec4a37249aa605b746be`；已保存对象 `libfile_b11ae448256c81918f07de00e9283d4f` |
| V6 完整输入／证据包 | SHA `38320877b72201bd87cff42976af7daf097edf9a929b01ceb3e6bcf08cb0dd54`；已保存对象 `libfile_8130df8b79048191a92f95cecabd7493` |
| native V5/V6 历史证据包 | SHA `81780f9ea42d847c25dd29cd04b61622051deb0e9fdbe58276f20879729b648b`；已保存对象 `libfile_e2da3bb76c2c8191bf207028764522bc` |
| V7/V7b 完整证据包 | SHA `0a823de5a654011e5383396bdbd948dcc06c7a020bd0c323b66191397ec1af7c`；151,993,631 字节，本地可下载，目的地保存审批尚未完成 |

V5/V6 的特征、历史 cohort 和 warmup 是重放的先决输入；新 V8 包不能单独替代它们。所有先决包的完整文件名、长度、回执 SHA 与保存位置均在内嵌 provenance 中；本次没有重新下载或重复打包旧档案。新确认样本、私有评估密钥和 encoder 权重没有因此被获取。

## 独立验证命令

取得固定源码、V8 压缩包和外部 manifest 后，在仓库根目录使用标准库 reader：

```sh
python qa/stem-bakeoff/evidence_archive_v8/archive_cli_v8.py verify \
  --archive /absolute/path/cell-field-v8-complete-evidence.tar.gz \
  --manifest /absolute/path/cell-field-v8-complete-evidence.manifest.json \
  --manifest-sha256 e344fc9d230a6ae18fb09d4ebb4666b7f99cace9c51b5cd3085cdbad8fe7050f \
  --archive-sha256 af02493df470aa28fd91970164f2c79acef3cd09caed740d4ac832d7f32fa524
```

这里的两个 absolute path 需要替换成本地下载位置。验证不会启动模型、评分、bootstrap、owner 或网络请求。归档文件本身不是完成标记；本次已经存在并核验的 fsynced receipt 才表明发布步骤完成。

## 资源和保存状态

打包时所有逐写入前的 64 MiB 余量检查通过，但共享空间会变化；完成回执记录的余量为 16,973,824 字节，不宣称存在持续容量预留。后续仅新增 Git 元数据时遭遇 ENOSPC；核对无活跃 Rust 进程及全部 37 个保存 executable 后，只清理了任务专用构建目录的 225 个 `.rlib/.rmeta/.o` 生成文件。同一次执行视图中释放了 236,273,664 分配字节，并通过真实 mkdir/write/fsync 探针。下一独立执行视图又观察到 224 个缓存路径，可用空间回落至 19,263,488 字节，因而只把它记为当时的写入恢复，不声称持续释放了这部分容量，也没有重复删除。两个元数据 gzip 及发布清单已利用该恢复窗口一次写入成功。所有可执行文件、源码、锁文件、日志、raw 和归档均保留。[最终缓存清理回执](final-rebuildable-cache-cleanup.json)

**V8 和 V7/V7b 本地包均未保存到 ChatGPT Library。** 此前的自动审批明确要求对“将包含私有组织代码、研究输出和模型参数的证据文件保存到 ChatGPT Library”取得目的地专项授权。本次没有重试上传或绕过审批，也没有写入不存在的 LibraryID。报告、代码及这些可审阅元数据已经使用同一私有 Git 仓库承接。

工程归档完成与科学接受分别登记；本次科学结果保持两项开发拒绝，真实 native owner 未激活。[主关闭报告](../../CELL_FIELD_V8_CLOSURE_REPORT.md)
