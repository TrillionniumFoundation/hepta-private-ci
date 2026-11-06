# main67 固定 92-job 切点与六份原作业产物

本包保全 2026-11-06 的一次有界非原子观察。root 已取得的 04:10:12–14 UTC 19-run list 与 blocking36 jobs 原响应保持不变；其余18 runs 的 jobs 于04:13:39–40 各读一次。完整分母19 runs/92 jobs，分别为11 success/5 failure/2 skipped/1 queued，与67 success/8 failure/10 cancelled/6 skipped/1 queued。8个失败作业包含Windows汇总；7个实际执行作业失败。API绿色不等同全部用例验收。

04:12:37 一次读取五个新失败作业完整日志及14-item完整artifact列表，随后取得五ZIP：Intel134成员、Win3 21、Win2 57、GNU clippy1、MacARM69。04:21:20–22 额外一次读取原GNU成功job127679861926及其95成员ZIP，以核原B23条件。六ZIP完整原字节、CRC、所有成员、原MCP响应与完整decoded日志均保留。源码固定67cc/实际checkout b7a/产品tree3982；与后续诊断分支严格区分。

`SUMMARY.json` 提供具体错误分组，`VERIFICATION.json` 是离线主验证器完整stdout。五份compact逐条解析；原失败目标共14实际test启动（含Core一次重试）及14辅助XML生成器。Intel Core第二XML重用了第一XML digest，其原ZIP实际新XML仍完整保留；没有把该缺口补造成一致。GNU另份compact证明原AppServer unit8shards全部缓存，不能称本次新native。

B23独审 actual `2dd76784a199d90906e98a773387fe9fc439ae71`、所有checker原件与精确stdout在bundle的`root/b23-review/`。结论仅推荐按原exit关闭B23 GNU产品scope；fresh结果来自单独diag8真实remote非cache，原main作业作为完整原CI cached接受。两组日志/action-cache digest不同，各自日志精确绑定各自compact XML输入；递归输入/工具图、binary、args/env/platform完全相等。原collector失败、8XML未物化、2Fetch误报保留，B15不随之关闭。

## 离线恢复与验证

用`restore_bundle.py bundle-manifest.json PARTS_DIRECTORY EMPTY_DESTINATION`还原，脚本核每base64分片、gzip与全部归档成员，然后从六个原ZIP完整展开原成员，核原member清单。之后在`root/main/`运行`decode_five_compacts.py`、`decode_gnu_compact.py`，再运行`verify_packet.py`；所有派生结果须与冻结原件逐字节相等。只在独立恢复目录运行会写derived的decoder，保护冻结原件。历史`download_five_artifacts.py`是采集记录，不属离线验证步骤，不要重试原API。

B23独审另依赖root保管的两原ZIP：artifact13476180428，782208 B，SHA25643bdccc192f96f95aebf3e7642df04ae0055f5c61970a27a8b03e05a6a9c91e3；artifact13475294944，5119057 B，SHAcf6546f57f595a26c0058d321c4b80846da4f8ff26628be77b7c4332bffde7e3，以及root对应原jobs/artifact API。它们由root单独封包，本包不重复大ZIP。`bind_b23_compacts_portable.py`仅额外支持历史显示路径alias，使独立恢复位置的实际读取仍可复现原stdout；原checker与actual REVIEW没有覆盖。明确实参`--main`、`--diagnostic`、`--decoder`，并按PORTABILITY_ADDENDUM指定display roots。`verify_original_scope.py`使用恢复后的14份source原字节、两组原件和已重放binding。

所有任务仅固定证据读取、离线解析和不可变Git对象登记；没有原生重跑、工作流派发、断言/预算/roster修改、ref或PR修改。

## v2 临时下载地址边界

本Git包排除六条含临时SAS下载URL的download-tool返回；它们只保留本地。原官方artifact API、完整ZIP/CRC/所有成员、原job日志保持。详见SAS-EXCLUSION.json；v1未出版对象中的已登记archive前缀经解压扫描不包含这些URL或签名，也没有六成员header。v1整体包未完成登记、不纳入新registry。
