# Mac 原 57 项包装器对照：限定范围通过

**原 Mac Bash 空数组错误已得到真实修前失败和修后通过的对照：同一套原 57 项，修前 3 FAIL、修后 57 PASS，零跳过、零测试重试。** 执行在 macOS ARM 的真实 `/bin/bash 3.2.57` 与现有 Python 3.14.3 上完成。该结论只覆盖原 Python/Bash 包装器范围；完整产品、Windows 原生及 Intel PTY 的资格仍各自等待原结果。

## 实际运行与源码身份

| 项目 | 证据 |
| --- | --- |
| 原生任务 | `1a1aafc5f2d-fc05-4945`，controller `succeeded / exit 0`；无自动重试、取消或超时 |
| 原命令 | `python3 -m unittest discover -s .github/scripts -p 'test_run_bazel*.py'`，修前与修后参数相同 |
| 原字节来源 | `20fd174ded4e5ce01bda34e4f6d1d74803301f49` 的 13 个原文件、146,000 B；模式、内容、测试、collector 和目录布局保留 |
| 实际投影 HEAD | `9c1baebd638c99a4f89c84b91b33f94207eaf449`，真实 Git 提交，属于独立原生投影 |
| 修前投影树 | `69f329acffb8aba965f6ad943335afeba379d074` |
| 修后投影树 | `93fe0fedfdfd90e6d38216e30ab2adafdd3cbe19`；仅 wrapper 使用已发布的 `42b59b6354b5933c8155b992519682c06d024ca1` 后像 |
| 普通 index | 1,540 B，SHA-256 `6a4c1293e9aff60043aabf9e6976cb49f165b526090a07ebc9a3c1c2fb485d4f`，九次守卫保持 |

原完整 fetch 因 HTTP/2 stream CANCEL / early EOF 在 1,169.393 秒后退出 128，零测试执行；该原目录和失败没有覆盖。替代投影使用真实 Git，原 collector 和测试的 HEAD/tree 比较继续实际执行。来源 `20fd/4a` 与执行投影 HEAD/tree 分列，投影内没有完整仓库的双锁，记录明确为 `NOT_IN_THIRTEEN_FILE_PROJECTION`。

## 原失败与修后结果

修前原命令退出 1，命令耗时 14.367716 秒，unittest 本体报告 14.329 秒。三个失败与此前 hosted Mac 的原失败一致：

1. `test_conflicting_selected_summaries_do_not_read_existing_logs`
2. `test_missing_selected_logs_preserve_success_and_failure_status` 的 `original_status=0` 子场景
3. `test_success_retains_reported_targets_and_preserves_status_scope`

完整原 stderr 直接包含 `failed_targets[@]: unbound variable`。修复保护空失败目标数组，并保留成功目标的日志留存流程。修后命令退出 0，命令耗时 12.866936 秒，unittest 本体报告 **57 tests / 12.827s / OK**。原 57 个完整 ID 与固定五份测试文件的发现结果一致，没有通过减少用例、跳过断言或改变预算取得通过。

13 个文件中只改变已审 wrapper；父进程和 wrapper/collector 子进程使用相同 Python PATH，真实系统 Bash/Git 的身份保持。没有真实 Bazel 产品构建，Windows 参数模拟控制也不替代 Windows 原生验证。

## 完整原件及独立复核

原 73 个 records 加 terminal 共 **74 份原件、452,930 B**，包括实际原输入、真实二进制 index、九个整投影源码守卫、原发现名单、完整 stdout/stderr、状态和控制器终态。完整包 `693e3abc8b959983dfce70cd154bcec8092c3353` 为 364,469 B；其中较大的实际原输入通过精确 Git 对象引用提供，已单独 GET 并与原生回读相符。

根审逐件核对全部原件的 bytes、SHA-256、Git blob，重新计算两棵投影树，并核对九次源码、普通 index、真实工具身份、57 个原名字与两次输出。没有在复核过程中再次执行项目测试。

- [完整原生证据包](native/mac57-complete/complete-native-bundle.json)
- [原生实际输入](native/mac57-complete/request.json)
- [根审完整结论](reviews/mac57-complete-root-review.json)
- [投影执行器](native/mac57-complete/run_projection_controls.py)
- [投影来源与闭包](native/mac57-projection/source-map.json)

产品 [Draft PR #4797](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4797) 已在此结果返回前发布七个候选提交，头为 `5b633125…`。本原生对照补足该 wrapper 的本地 Mac 验证，**不把新头尚未执行的原平台 CI 改记为通过**。原 23 项台账仍为 8 项限定闭合、14 项开放、B18 科学 HOLD。
