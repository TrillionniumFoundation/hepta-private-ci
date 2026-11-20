# 联合 CI 基线身份差异的实际核验

根在原 238 CI 失败后独立读取 GitHub 原 commit、实际 base branch ref 和原始 PR API。PR 仍声明 base `2742bc37e9f4a74fba32bb534230de55f431e9ea`；实际同名基线分支 ref 则为 `061334747ce9d87690c40df48eeedf239156b57d`。后者只有一个 parent，正是前者。

CI 实际 prospective merge `79210ce76fba767e5860b492ff35501140edc5db` 的第一 parent 是 `06133474`、第二 parent 是被测 `238fc484`，与原失败日志一致。因而不是单凭日志臆测的未知分支：当前确有“PR 声明 base”和“实际分支 ref”不一致。尚未确定 GitHub 元数据为何没有同步，不能把因果归为确定的缓存或平台错误。

原 identity gate 要求两个 parents 分别与声明 base/source 完全相同，故该失败继续保留。没有重定向 PR、移动 base branch、放宽 checker 或把当前另一个基线冒充原声明身份；这次只读核验不给予 CI 或业务资格。原 API 的完整原件已归档，逐成员 SHA256 回读通过。
