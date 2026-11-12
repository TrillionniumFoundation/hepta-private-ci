# Evaluated CURRENT：固定 b298 的三方合并候选

**状态：CANDIDATE_NOT_EXECUTED。** 没有创建 commit/ref，没有新 h 请求、actor 或重启原 native run。
候选代码 tree：`f1e27187d8747db95a74ded11e256b56995f03c6`。

## 精确输入与保留

| 角色 | Commit | Tree |
| --- | --- | --- |
| 共同祖先 | `094958b83a8fd19e3bc6d01a092793c0f420bb75` | 由两方向 compare 及直接 compare 确认 |
| 当前我方 | `088aadac3c88a5be6299ece1561d1ed54dd7d494` | `e338a817d39a7269ea815bf4b1a594d9985779d9` |
| 固定上游 | `b29869e856d08db1bfb066116a9c443376ccc57d` | `906546af39b07474f0b9d046a6e780b6d3342743` |

直接 compare 为 diverged：上游领先 7、我方领先 4；实际共同祖先是 0949。
上游相对祖先修改 129 路径，我方修改 24；实际同文件重叠仅 CALLERS 与 blob-size allowlist。
合并从完整 b298 tree 出发，应用我方 22 个非冲突路径及两个合并文件；没有改写上游生产 Rust。
逐路径检查了 24 个候选路径与 34 个上游源码路径，均匹配预期 Git blob。
上游 93 个证据路径的整个目录 subtree `05e732070e1420665a49045c898d389156a11130` 保持不变。

## 三项具体适配

1. CALLERS 按 boundary ID 保留双方：537 个唯一 ID；534 个上游 ID 与 530 个我方 ID 的顺序均保留。
   上游新增七个边界完整保留，我方新增三个 evaluated CURRENT 边界保留；五个相关保护块采用我方原字节。
   其余保护块内容原样保留，末块仅增加新 boundary 之前的空分隔行。
2. 上游 `circuit_evaluated_selection_readback_owner.rs::serve_readback` 实际调用原 `original_owner_command_channel_v1`，
   但上游 manifest 漏登记。仅为该原函数精确追加一个已存在的调用路径，24→25，并同步 NoUpdate QA tuple。
   原 24 个调用者和所有反例保留。Selection 的六路径集合逐个读源核对，保持不变；新 NextUse 使用 `read_learning_next_use`。
3. 上游 Observer 已采用 `evaluated::authenticate_predecessors`、显式 `&self.profile` 和 RemoteOwner|EvaluatedOwner 分支。
   将 Published-read QA 三个旧标记改为实际形状；全文件 22 处 `self.rejects` 调用、原循环与拒绝测试全部保留。

allowlist 仅保留双方原精确 hash 并登记本候选 CALLERS 的精确 SHA-256，没有扩大为目录或通配规则。

## CURRENT / T/E / NextUse 接口

`PublicationFixture` 仍为 `0254a9257c0a6f2f2c21a3b4ea37284235b13802`。
我方正例 `b500835023c268bf7253049bc2264e93d5117b75` 不需接口修改：
仍消费原 `publish_and_retain_original_evidence` 返回的 T/E 客户端，保持真实 retained publication 与 fresh/readback-origin CURRENT 往返。
源码中的 T/E [5,5]、CURRENT [2,2] 是待验证断言，不能写作本候选的运行结果。
上游的新 evaluated Selector readback / NextUse 全链源码与测试完整继承；这不意味着普通 owner、跨 UID、Root 冷恢复或独立来源资格已通过。

## 下一执行门

冻结新 commit 后使用同一原 `scripts/hepta_ci_exec.py`，SOURCE_SHA=TESTED_SHA=新 commit，lane=source-head，
PYTHONPATH 仅为同一新 checkout 的 scripts、仓库及第三方依赖，保全 clean tracked inventory 的 before/after。

```sh
python -B -m unittest discover -s qa/b4-no-bypass -p '*source_closure.py' -v
python -B -m unittest discover -s scripts -p test_hepta_c_observer_coverage.py -v
python -B scripts/verify_hepta_callers.py verify
```

前两条沿原 wrapper 的 timeout 600 / minimum-tests 1 入口执行。首条自动发现上游新增 NextUse 文件的 22 个方法；全套实际数量仍待执行确认。
原 088 的 376+16 历史结果不转记到本候选。原 088 native 身份继续原样运行。
本候选的 Python QA、TOML parser、caller proof、Rust formatter、编译与 native 全部 **NOT_RUN**；owner_decision 仍为 null。
