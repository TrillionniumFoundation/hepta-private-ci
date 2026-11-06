# 当前审计与执行入口

**16项限定范围闭合、6项开放、1项科学验证保留；仅B23按原退出条件新增闭合，全部blocker尚未闭合。** 整理时间：2026-11-06 05:32:07 UTC。各统计按其原观察窗口解释，未合成实时原子快照。

- [完整项目方向与执行计划V7](PROJECT_DIRECTION_AND_EXECUTION_PLAN_V7.zh-CN.md)
- [本轮实际进度V9](CONTINUATION_PROGRESS_V9.zh-CN.md)
- [原23项机器台账V8](continuation-blocker-progress-v8.json)
- [本轮实际登记证据索引V10](evidence-index-v10-registered.json)

当前全量元数据为3555开放PR和5333分支，旧1103/5193保留为历史；PR数量差异原因UNKNOWN。默认main为732e934b/tree75dc1c1f，主修复PR4797仍为67cc/tree3982，未合入main。

主67最新完整切点为05:20:01–05:21:49的19runs/93jobs：68成功、9失败（7执行job、Windows汇总和总CI汇总）、10取消、6跳过，无排队或执行中。Rust required已成功，总CI仍失败；原main92及所有失败原件保留。新cargo PR4922已取得pin-utils0.1.1/RUSTSEC-2026-0441完整原件，不回填旧cargo UNKNOWN；arg0 PR4923原GNU Clippy与repo-checks已成功。Windows两cause仅在旧340源限定通过，当前18格式源与新PTY PR4927仍独立待验。各支线尚未整合成最终产品候选。[最新切点及实际发布包](reviews/root-followup-publication-native-20261106/registry.actual.json)。

B23 fresh GNU8shard307P/1I与最终原GNU cached成功形成独立接受链，原signal/drain/stdio-disabled语义及原退出全保；仅此项闭合。原诊断collector重复Fetch和8缺XML的job failure仍保留，未借新收件条件改变原退出。B21两个完整上下文仍30P/1F，B11 native13仍147P/7F/2I；严格外部删除、Root/Current/FinalUse和整库required保持开放。

两份当前入口同步指向同一套报告。旧入口按原字节留存于[旧LATEST](history/LATEST.pre-v10.md)和[旧中文LATEST](history/LATEST.pre-v10.zh-CN.md)，内部旧相对链接不改写。[上一版证据索引V9](evidence-index-v9-registered.json)仍完整保留。
