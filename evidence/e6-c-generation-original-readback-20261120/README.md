# 1a979 有限原件的本云封存

本包封存已经保存的真实源码身份、执行输出和只读回收材料。对应源码为 **`1a9799686243c2be0ee393ba364e091029cfb944`**，tree 为 `931a344b1ea3e2ddf45e917ea4b3ae37c504ed05`。没有调用宿主、补造锁或 ELF、重新运行测试、模型或训练，也没有写 Git 对象或移动 ref。

**原 NoUpdate13 整父仍为 FAIL，新 C drain 未到达。** 封存成功只表示以下有限输入的字节和来源闭合；它不是新的业务物理闭环、文件系统原子快照或运行资格。原 host pack 所依赖的第三把锁和 ELF 在后续观察中缺失，本次未调用或修补那个 host pack。

## 范围与计数

| 范围 | 实际封存结果 |
| --- | --- |
| 原有限宿主路径计划 | 256 条均有去向：160 条完整正文、90 条根据实际观察或执行绑定的 SHA 复用完整正文、6 条保留原缺失事实 |
| 本次只读回收 | 全部 201 个新 purpose-built RPC 原件，含 3 个新失败 RPC；此前失败原件也保留 |
| Root 三份大原件 | 完整 CLI stdout 558,904 B、targeted proof 176,258 B、物理 source inventory 3,641,800 B，并保留其分块 RPC、版本和覆盖验证 |
| Hia 独立 child 捕获 | 12 份实际日志 25,528 B、原 capture 结果/清单、实际读取和 owner 原件；旧三锁捕获失败仍保留 |
| 本包逻辑输入 | 637 个有限的已保存文件；每项记录完整 size、SHA256、Git blob OID、用途和存储位置 |
| 复用现有 535 项清单 | 94 项直接引用其原文件，17 项引用旧 archive 内已重新逐字核对的成员；没有重包整个 535 集合 |
| 新档案对象 | 526 个新增逻辑输入按相同字节合并为 482 个对象，共 27,314,349 B |
| 压缩与核验 | 压缩包 3,214,228 B；482 对象加 6 份冻结元数据共 488 个成员，全部读回校验；七片重组后与完整压缩包逐字一致 |

压缩包 SHA256：`6cacce7c649381a42a9af51854b281d4fda72e7fe4838e694aa40928fa20ce56`。

这里的“160/90/6”沿用原 `READBACK_MANIFEST.json` 分类，不表示 256 个路径都存在，也不把历史复用正文重新计作本次物理读取。六条缺失事实逐项列在 `MISSING.json`，均绑定原 `TARGET_LSTAT_RESULT.json`；不推断删除原因、操作者或其后状态。

## 原始证据和本次生成层

`INPUT_MANIFEST.json` 对每份逻辑输入区分三种存储方式：新的内容寻址 archive 对象、535 清单中的已有仓库文件、已有 archive 的确切 member。相同正文可以在不同实际路径使用；每个宿主路径的来源和复用依据仍在 `SOURCE_REUSE_MAP.json` 及原 readback manifest 中保留，没有以去重掩盖重复路径。

本次引用的 535 项清单 SHA256 为 `10e1e469f5f2fa85daab4fb6ea9244d3babbb5beb2fb0ed55347422e7cbe371a`。发布者必须保留该清单引用的已有 evidence 路径；本包不独立声称这些准备文件已经组成某个发布 head。`DEPENDENCIES.json` 给出旧 archive 的完整摘要、原部件仓库路径和实际复用成员。所需部件均逐字匹配 535 清单及其已有 blob 身份。

原冻结计划中包含对 startup 首因的静态归属和未执行的两文件产品草稿 peer。这些材料以其原角色保留，不能当成 `1a979` 的运行输入或新产品资格。此后恢复环境的 preflight2/3、typed startup 七源 policy 和相应独立 peer，只在 `FOLLOWUPS_NOT_INCLUDED.json` 中记录确切 pin，留给独立后续证据层；没有放进本次 `1a979` 的源码执行链。

第一版输入冻结含 621 项，尚未执行压缩。随后显式补入独立 12-log 捕获的实际 RPC/owner 收据、Root 对完整 readback 的独立复核，以及该首版冻结本身，形成当前 637 项。第一版文件没有改写。当前压缩前 freeze SHA256 为 `9c9004b3f612aeecb93b0710cd36cd39296875ba94996ad97707aa46b4d28f8a`。

## 恢复与复核

七个 `cloud-1a979-finite-originals.tar.xz.part-*` 部件按 `archive-parts.json` 顺序拼接，即得到完整压缩包。单片至多 480,000 B；切点使用压缩包内已有的 NUL 字节，不填充、不删改原字节，且每片首 1,024 B 均含 NUL，避免原 Codespell 二进制分类误读。不需要扩大原 blob allowlist。

压缩包的 `objects/` 是正文，`metadata/` 保存压缩前冻结输入、复用关系、缺失记录和依赖。所有完整元数据也在本目录公开；如某份元数据将来必须分片，`METADATA_STORAGE.json` 和对应 reassembly 索引负责逐字重建，不能把摘要代替完整正文。

提供的只读恢复器可对一个含已有 535 项 evidence 的 checkout 验证全部引用，并恢复到全新的目录：

```sh
python verify_restore.py --repository /path/to/checkout --output /path/to/new-evidence-directory --receipt /path/to/new-readback.json
```

省略 `--output` 时只核验，不创建恢复副本。输出目录或 receipt 已存在会拒绝覆盖。恢复器不访问网络、不执行任何保存的源码、测试、RPC 或宿主命令。它核对新 archive 全部成员、被引用旧 archive 的确切成员、所有 637 个逻辑输入和 256 条宿主路径映射。

`RESULT.json` 是本次本云压缩核验结果；`RESTORE_READBACK.json` 是本云用原 535 清单解析实际依赖、独立走完整恢复读取路径的结果。二者均不是新的测试成绩。最终 Git head 的原完整范围 blob 门仍须由发布流程单独执行，本包没有提前授予该资格。

## 文件入口

- `INPUT_MANIFEST.json`：全部有限逻辑输入和存储映射。
- `SOURCE_REUSE_MAP.json`：256 条原宿主路径的正文/复用/缺失去向。
- `MISSING.json`：6 条原缺失事实与原观察来源。
- `DEPENDENCIES.json`：已有仓库文件与旧 archive 部件依赖。
- `FOLLOWUPS_NOT_INCLUDED.json`：恢复 preflight 与 typed startup 后续层边界。
- `FREEZE.json`、`ARCHIVE_MEMBERS.json`、`archive-parts.json`：压缩前身份、完整成员和重组关系。
- `archive_finite_readback_v2.py`、`verify_restore.py`：本云封存和恢复逻辑，均无宿主执行接口。
- `FILE_MANIFEST.json`：本目录完整发布文件的逐项身份，自身除外。
