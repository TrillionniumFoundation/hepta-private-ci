# P1 结果验收：严格区分增长轴和控制组

`acceptance.py` 补充已有 `hepta.e5.prospective-human-cell-design.v1`、
`hepta.circuit-readiness.v3` 与 `hepta.ablation-metrics.v3` 输出；不另建训练器。
固定总预算要求人数增加、worker 不变且完整资源向量不变；固定每用户预算
要求向量按人数同比增加；固定数据增加 worker 要求人群、数据、总预算不变。
CPU、加速器时间、训练 MACs、验证、服务与网络预算均须显式数值绑定。
把一种轴改名成另一种、换数据、换评测或超预算会直接拒绝。

Circuit 必须提供 learned/fixed/random/single_equal_budget/edge_deleted/
message_shuffled 全部同面板、同预算控制，保留完整的 v3 删 Cell/边清单，
对固定图持平明确记为没有严格优势。即便字段完整，状态至多为待原件核验；
此检查器不认证原件，不签发科学资格或奖励。

本次实际读取 #7047 保留的设计、旧 A readiness、#7020 原配对结果和原控制
文件，逐文件 SHA 在 `ACCEPTANCE_READBACK.json`。原 Circuit 新题成功 1，
固定连通图也成功 1，保留 tie。已存在固定连通/删边观测，但缺少完整资源绑定、
随机图、等预算单模型和消息置乱，不能升级为学得 Circuit 优势。
旧 A readiness 的 NOT_READY 属于另一个限定 selector 面板，不转移为本
Circuit 的 readiness 结论。

三条**授权用户与采用收益**曲线合格点均为 0。既有 #7033 的历史合成
worker 实验 317.97→535.79 模型对/小时、1.685 倍仍成立；本次没有重跑它，
也没有把这些吞吐点换算成用户增长或采用改善点。

采用改善率默认 null。只有宿主提供原授权/采用核验回调，且全部成本完整、
计量单位一致时才计算；重复 improvement_id 的收益只计一次，重试成本照计。
单独 JSON 自报授权或只提供训练成本不能解锁该指标。仍不宣称全球女巫独立性。
三项针对测试通过：轴冒充/数据变更、缺控制/tie/额外预算、未经原件核验和
不完整成本拒绝及重复收益去重。没有新增用户或推送。

复核命令（source-root 指向含上述既有接口与原件的 #7047 checkout）：

```sh
python -B -m unittest discover -s matched-edit -p 'test_acceptance.py' -v
python -B matched-edit/acceptance.py /absolute/source-root
```
