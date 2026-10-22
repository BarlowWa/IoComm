# IoComm 待核实问题清单（2026-10-20）

> **状态（2026-10-22 更新）**：**全部 40 条已人工核实并处置完毕**——**C 37 条**（全部已处置）、**R 3 条**（D-08 / B-06 / B-12，理由见各行）。
> 核实判据与逐条结论见 §7b。
> 来源：只读审计 agent 对 `IoComm/` 6 份设计文档（无源码）的交叉审计，报告原文在
> `.tmp_research/agent-delivery-test/iocomm-declared-not-landed.md`。
>
> **核实口径**（逐条处理时按此标注，不要混用）：
>
> | 标记 | 含义 |
> |---|---|
> | **U（未核实）** | 只有审计 agent 的原文，尚未人工比对文档 |
> | **P（已抽查）** | 主会话人工比对过至少一处关键原文，与报告一致 |
> | **C（已确认）** | 人工逐条比对过报告引用的全部原文，结论成立 |
> | **R（已推翻）** | 人工比对后不成立（保留条目与推翻理由，便于下次不再重复排查） |
>
> 计数数字（24 断链 / 16 矛盾 / 36 独立问题）来自 agent 自述的判定规则
> （“断链”按声明点计、“矛盾”单独计、4 组同根因去重），**核实前不要把数字当作既定事实引用**。
> 已知存在「边界判断类」条目（如 D-01 的“缺少超时”取决于是否接受 ABI 尾部追加），核实时要先定判据。

---

## 1. 阻塞层（B0–B2）

| ID | 严重度 | 位置 | 问题摘要 | agent 建议处置 | 状态 |
|---|---|---|---|---|---|
| D-01 | B0 | `docs/api/c-abi.md:800`、`:473-479`、`:489-504`；`docs/requirements.md:263`（AC-41） | 丢弃原因 `ICOMM_DROP_TIMEOUT`（“异步发送在 timeout_ms 内未完成”）存在，但 `iocomm_send_options` 与两个 `*_send_async` 都没有 `timeout_ms` 参数 → AC-41 不可构造 | 补设计：`send_options` 尾部追加 `uint64_t timeout_ms`（尾部追加只升 minor）；写明超时后消息出队、`on_done(TIMEOUT)`、产生 `DROPPED(TIMEOUT)` | **C**（§7-V1）；**已处置 2026-10-21**：补 `send_options.queue_timeout_ms`（0 = 无截止，计时「入队→开始写」），并把 `on_done(OK)` 完成点定为「已完整交给传输层」 |
| D-02 | B0 | `docs/api/c-abi.md:645`（`node_info.name`）、`:136-161`（`runtime_config` 无名字段）、`:221-222` | 节点名无来源；全文无查询本机 `node_id` 的 API → AC-9 无法从公开 API 观测 | 补设计（二选一）：`runtime_config` 追加 `node_name` + 新增 `iocomm_runtime_node_id()`；或删 `node_info.name`，展示名由调用方生成 | **C**（§7-V2）；**已处置 2026-10-21**：选前者（+ `iocomm_runtime_node_name()`、FR-9.4、AC-79） |
| D-03 | B0/B1 | `docs/architecture.md:422`（M1）、`:25/42/77/455`；`docs/api/c-abi.md:260`；`IoComm/README.md` 示意图 | `inproc` 是 M1 唯一传输，但 `requirements.md` 无 FR、无 AC，`listen_transport` 字符串也没有；语义（跨 runtime？拷贝？参与发现？）全空白 | 补设计：新增 FR（P0）、字符串加 `"inproc"`、定义 `listen_addr` 语义、补 AC、工作量拆行、明确仍走帧层 | **C**（§7-V3）；**已处置 2026-10-21**：FR-3.5–3.10 + AC-80–82；字符串加 `"inproc"`；**只要求「结构同构」**（帧边界/顺序号/大小校验保留，允许移动不拷贝），不强制逐字节走同一条编码路径 |
| D-04 | B0 | `docs/api/c-abi.md` §9.6 C7 / C11 | 审计契约 **C7 与 C11 的正文在冒号处截断**（“顺序固定为：”“两种路径：”后无内容），AC-56/AC-63 依赖它们 | 补设计（M0 前）：写出完整审计状态机与两条 close 路径；`runtime_destroy` 不产生（与 C9 一致） | **C**（§7-V4） |
| D-05 | B1 | `docs/architecture.md` §6.4、M4 行；`docs/requirements.md` FR-1.4/1.5、AC-11 | 跨进程名字表（FR-1.4/1.5 的实现基础）无里程碑承接；AC-11 错挂 M4 且 M4 产出清单不含实现项 | 补设计：名字表写进 M1 产出（或新增 M1.5），AC-11 移回 M1/M2；补“允许第二实例 + 改名”的 AC | **C**（已处置 2026-10-22：名字表落 **M1** 产出，AC-11 移到 M1；新增 AC-89。**口径（选项 A）**：端点名的跨进程排他**与传输无关**，inproc 端点同样参与；FR-3.6 的「跨进程隔离」只指 `listen_addr`） |
| D-06 | B2 | `docs/architecture.md:272`、`:282`；`docs/requirements.md:73`（FR-4.3） | 线格式只有“头部定长 + TLV”一句话：magic、版本、长度前缀宽度/端序、帧头字段编码、TLV 标签表、最大帧、`TOO_LARGE` 判定点、双版本共存全未定义 | 补设计（M2 前）：新增 `docs/api/wire-format.md`；补新旧 TLV 互发 AC（→ AC-90） | **C**（已处置 2026-10-22：新建 `docs/api/wire-format.md`——magic / `version` / 端序标志 / 20 B 帧头 / TLV tag 表 / `HELLO` 握手 / 心跳 payload / 未知 tag 跳过 / 版本协商；定为 M2 硬前置） |

## 2. 断链（B3–B4）

| ID | 严重度 | 位置 | 问题摘要 | agent 建议处置 | 状态 |
|---|---|---|---|---|---|
| D-07 | B3 | `docs/requirements.md:86`；`docs/api/c-abi.md:769-772` | FR-5.5 三件事混一条 P1：连接表 dump、队列水位、“最后 N 条错误”；错误环/容量/JSON 键名/版本全未定义 | 拆分：dump 留 v1 并定义 JSON 格式；错误环降 v1.1 | **C**（已处置 2026-10-22：FR-5.5 拆为 v1（连接表 + 队列水位）与 FR-5.5b（最后 N 条错误，v1.1）；`diagnostic_dump` 注明顶层含 `"version"`） |
| D-08 | B3 | `docs/requirements.md:286`（AC-64）、`:290`（AC-68）；`docs/architecture.md:424`、`:428` | AC-64 测 v1.1 的 LOST 槽机制、AC-68 测 v1.1 的 TTL 释放，却挂在 v1 的 M3 | 修映射：AC-68 移 M7 并标〔v1.1〕；AC-64 拆 a/b 或整条移 M7 | **R**（**推翻**：`FR-10.8` 的 LOST 槽是 **P0**，`monitor_ttl_ms` 也不是 v1.1（v1.1 只有载荷捕获的 TTL）。AC-64 唯一真实问题是覆盖列误写里程碑 `M4` → 已改为 `FR-10.8 / C4`） |
| D-09 | B3 | `docs/api/c-abi.md:911`、`:921-924`；`docs/requirements.md:294`（AC-72） | 监控内存模型未定稿：“open 时预分配”与“动态工作集 + 耗尽回收”两套写法并存 | 定稿为「逻辑配额 + 按需分配」（`max_bytes` 为记账上限，`monitor_budget_bytes` 为已提交配额之和） | **C**（已处置 2026-10-22：定稿为「**逻辑配额 + 按需分配**」——`max_bytes` 是记账上限不是预留量；`monitor_budget_bytes` 是各 monitor 已提交配额之和；记录离开 `retain_window` 归还字节） |
| D-10 | B3 | `docs/architecture.md:356`、`:361` | 架构/里程碑引用的 `run_until` 与 `pending_timer_count` 在 C ABI 中不存在 | `run_until` 删除；`pending_timer_count` 若只服务测试则删/改为测试接口 | **C**（§7-V6） |
| D-11 | B3 | `docs/api/c-abi.md:636-637`；`docs/architecture.md:314/317/78` | `registry_plugin` 三处残留（字段、插件点、`local-registry` 策略名），无 FR/AC/里程碑/加载语义 | 删除（v1）；架构表格行标「v2 评估项」 | **C**（已处置 2026-10-21：删除 `discovery_config.registry_plugin`；架构表改为「v2 评估项」） |
| D-12 | B3 | `docs/architecture.md:321`、`:425`；`docs/api/c-abi.md:685-697`；`docs/requirements.md:260`（AC-38） | discovery 快照四函数（`take/count/get/release`）有 API 无 FR/AC；`release` 非幂等 `STALE_HANDLE` 语义未验收 | 补 FR-2.8 + 3 条 AC（空快照 / index 越界 / release 后使用），写入 M4 产出 | **C**（已处置 2026-10-21：新增 FR-2.8 + AC-87，M4 验收补 AC-87） |
| D-13 | B3/B2 | `docs/api/c-abi.md:277`；`docs/requirements.md:46` | `ICOMM_ENDPOINT_LOCAL` 标志无 FR、无语义，与 `publish_local` / `listen_transport` 关系未定义 | 推荐删除 v1 该标志（本机可见性已可由 transport + `publish_local` 表达） | **C**（已处置 2026-10-22：删除 `ICOMM_ENDPOINT_LOCAL`） |
| D-14 | B4 | `docs/requirements.md:33`；`docs/api/c-abi.md:153`、`:239` | FR-1.7 `max_handles` 有字段有 FR，无 AC | 补 AC（`max_handles=1` 时第二个 create 返回 `RESOURCE_EXHAUSTED`），归 M1 | **C**（已处置 2026-10-21：新增 AC-84，归 M1） |
| D-15 | B4 | `docs/requirements.md:58`；`docs/platform-support.md:114` | FR-3.4 崩溃残留清理提到“共享内存段”，但后端里没有共享内存 | 改措辞为「Unix socket 文件 / 命名管道实例」；补 kill -9 后重建 AC | **C**（已处置 2026-10-21：FR-3.4 改措辞为「Unix socket 文件 / 命名管道实例」；新增 AC-88） |
| D-16 | B4 | `docs/requirements.md:122`；`docs/architecture.md:190` | FR-9.3 同机多进程共享身份只有 `process_epoch` 一句，不在任何 C 结构体里，无 AC | 降级 v1.1，或 `node_info`/`peer_info` 尾部追加 `process_epoch` + AC | **C**（已处置 2026-10-22：**降 v1.1**。v1 语义定为「`node_id` 唯一标识一个 Runtime 实例，同机多进程各自独立」，故 v1 不需要 `process_epoch`） |
| D-17 | B4 | `docs/requirements.md:41`、`:265` | FR-2.1 无任何 AC 在覆盖列引用（被 AC-21 间接覆盖） | 在 AC-21 覆盖列补 `FR-2.1`（不新增测试） | **C**（已处置 2026-10-21：AC-21 覆盖列补 FR-2.1） |
| D-18 | B4 | `docs/requirements.md:43`、`:265` | FR-2.3 租约无 AC（续期不重复 JOINED、到期剔除） | 补 AC：`discovery_lease_ms=3000`，正常续期只一次 JOINED；停掉后 ≤ lease 产生 LEFT 且快照移除；归 M4 | **C**（已处置 2026-10-21：新增 AC-85，归 M4） |
| D-19 | B4 | `docs/requirements.md:27`、`:256` | FR-1.1 无 AC 引用（AC-34/AC-25 隐含 create 成功） | AC-34 覆盖列加 FR-1.1，并补“句柄非 0 且 `endpoint_name_state=HELD_BY_SELF`” | **C**（已处置 2026-10-21：AC-34 覆盖列补 FR-1.1） |
| D-20 | B4 | `docs/requirements.md:82`；`docs/api/c-abi.md:707-726` | FR-5.1 四个条件（Connected/Lively/Healthy/ConfigCurrent）本身无 AC | 补 AC：建连前 UNKNOWN、建连后均非 Unknown、`reconfigure` 后 ConfigCurrent 由 False→True | **C**（已处置 2026-10-21：新增 AC-86） |
| D-21 | B4 | `docs/requirements.md:96` | FR-6.1“异步为原语、同步为薄壳”是**实现约束**，不可观测，挂在 P0 会让 AC-E6 无法通过 | 降级为设计约束（移到 `architecture.md`）或注明“不可验收，由架构评审保证” | **C**（已处置 2026-10-21：FR-6.1 标注「实现约束，不可从 C ABI 观测，由架构评审保证，不单独挂 AC」） |
| D-22 | B4 | `docs/requirements.md:100` | FR-6.5 托管模式无 AC（owned 模式下不调 `run_once` 即可收发、IO 线程恒为 1） | 补 AC（owned 模式往返测试，主线程不调 `run_once`） | **C**（已处置 2026-10-21：FR-6.5 补 AC 口径；新增 AC-83） |
| D-23 | B4 | `docs/requirements.md:108`、`:232` | FR-8.1 无直接 AC（AC-10 行为正是它，但覆盖列写 FR-4.1） | AC-10 覆盖列改为 `FR-4.1 / FR-8.1` | **C**（已处置 2026-10-21：AC-10 覆盖列补 FR-8.1） |
| D-24 | B4 | `docs/requirements.md:254`；`docs/api/c-abi.md:583-591` | AC-32（subscribe/recv 互斥）是唯一“覆盖”列写 C ABI 章节的 AC；需求层无对应 FR | 补 FR-6.8（P0），AC-32 改引用 FR-6.8（保留 C ABI 链接作实现依据） | **C**（已处置 2026-10-21：新增 FR-6.8；AC-32 覆盖列改引用 FR-6.8，保留 C ABI §6.4 作实现依据） |

## 3. 口径矛盾

| ID | 严重度 | 位置 | 问题摘要 | agent 建议处置 | 状态 |
|---|---|---|---|---|---|
| B-01 | 高 | `docs/requirements.md:72`；`docs/api/c-abi.md:260`；`IoComm/README.md`、`docs/architecture.md:23/42/77` | UDP 只有一行 P1，无 AC/里程碑；但 `listen_transport` 与架构图把它当已规划传输 | 降级 v1.1；字符串改为 `/* "tcp"/"unix"/"pipe"/"inproc"（v1）; "udp"（v1.1） */` | **C**（§7-V8） |
| B-02 | 高 | `docs/architecture.md:422`；`docs/api/c-abi.md:260` | 与 D-03 同根因（按矛盾的视角描述） | 见 D-03 | **C**（与 D-03 同根因；已随 D-03 处置） |
| B-03 | 高 | `docs/requirements.md:141-149`；`docs/api/c-abi.md:34-35/869-897/1000-1024` | FR-10.9–10.17 标 v1.1，但对应 API 全以 v1 形态存在且无版本标注 | 给 v1.1 类型/函数加〔v1.1〕；§10 补 MINOR 提升时机 | **C**（已处置 2026-10-22：`c-abi.md` §9.0 新增「v1 / v1.1 归属」表作为唯一权威，不再逐字段加注） |
| B-04 | 高 | `docs/requirements.md:149`；`docs/api/c-abi.md:155-156/926-927` | FR-10.17 标 v1.1，但预算字段与 open 时预算检查是 v1 行为 | 提前到 v1（P0）；AC-71 拆 a（v1）/b（v1.1 arena/key 部分） | **C**（已处置 2026-10-21：FR-10.17 预算部分改 P0、arena 部分 P1；AC-71 拆 a/b） |
| B-05 | 中 | `docs/requirements.md:270`（AC-48）、`:290`（AC-68）；`docs/architecture.md:419-428` | 覆盖列引用不存在的里程碑 `M8` / `M11` | AC-48 → M7；AC-68 → M7 加〔v1.1〕 | **C**（已处置：AC-48 / AC-68 的 `M8` / `M11` 已改为 `C8` / `C11`） |
| B-06 | 中 | `docs/requirements.md:286`；`docs/architecture.md:424/467` | AC-64 无〔v1.1〕却挂 M3 | 见 D-08 | **R**（**推翻**：与 D-08 同根因，前提不成立——见 D-08） |
| B-07 | 中 | `docs/api/c-abi.md:800` vs `:489-504`；`docs/requirements.md:263` | `ICOMM_DROP_TIMEOUT` 触发条件不存在 | 见 D-01 | **C**（已处置 2026-10-21，随 D-01） |
| B-08 | 中 | `docs/api/c-abi.md:246` vs `:241-242` | `discovery_config` 说心跳/租约“不参与版本协商以外的任何逻辑”，但 §5.0 正在规定其逻辑 | 改措辞：作为 `discovery_start` 初值，之后由 `tune_config` 覆盖 | **C**（已处置 2026-10-22：§5.0 规则 2 改为「`discovery_start` 时的初值，之后由 `tune_config` 覆盖」，删掉「不参与版本协商以外的任何逻辑」） |
| B-09 | 中 | `docs/api/c-abi.md:911` vs `:921-924` | 监控内存模型两套写法（与 D-09 同根因） | 见 D-09 | **C**（已处置 2026-10-22，随 D-09） |
| B-10 | 中 | `docs/api/c-abi.md:923-924` | v1 `max_bytes` 默认值写“待定”，却位于权威契约 | 定死默认值并删候选句（agent 建议 `min(4 MiB, ring_capacity × sizeof(record))`） | **C**（已处置 2026-10-22：`max_bytes` 默认值**定死 4 MiB**，删除「可改为 `ring_capacity × sizeof(record)`」候选句） |
| B-11 | 中 | `docs/requirements.md:248`；`docs/api/c-abi.md:463-466`；`docs/architecture.md:291` | AC-26 说 `BLOCK` 退化为 `ERROR`，ABI 实际返回 `WOULD_BLOCK` | 统一术语：AC-26 改为“退化为 `ICOMM_OVERFLOW_ERROR` 策略，返回 `ICOMM_ERR_WOULD_BLOCK` 并计入 `queue_dropped`” | **C**（已处置 2026-10-21：`ICOMM_OVERFLOW_BLOCK` 注释改为「退化为 **ERROR 策略**（返回/回调 `WOULD_BLOCK`）」，与 AC-26 术语对齐） |
| B-12 | 中 | `IoComm/README.md:86` vs `docs/api/c-abi.md:489-495` | README 快速开始的 `conn_send_async` 调用与签名不一致 | 按签名改正 | **R**（**推翻**：README:91 的 `iocomm_conn_send_async(rt, conn, &opt, msg, on_done, u, &op, &err)` 与真实签名**参数个数与顺序一致**；`msg` 是未定义的示例变量，不是「签名不一致」） |
| B-13 | 中 | `docs/platform-support.md:17`；`IoComm/README.md:131` 附近 | ARM64 Windows 标 Tier 1 却“暂不列入范围” | Tier 列改「—（不在产品范围）」或明确“工具链 Tier 1、产品不承诺” | **C**（已处置 2026-10-22：ARM64 Windows Tier 列改「—（不在产品范围）」，说明改「工具链可构建，但不承诺、不验收」） |
| B-14 | 低 | `docs/platform-support.md:16` | MinGW 标 Tier 1 但“可选；需自测” | 推荐删除该行；或标“可选/不承诺”并补 MinGW 构建 AC-P6 | **C**（已处置 2026-10-22：删除 MinGW 行） |
| B-15 | 低 | `docs/adr/ADR-001-language-and-platform.md:90`；`IoComm/README.md`、`docs/architecture.md:154` | ADR“tokio 只作可选 feature” vs README/架构“不绑 tokio” | ADR 改为“不进入核心依赖，至多用于基准/示例”或删除 | U |
| B-16 | 低 | `docs/adr/ADR-001-language-and-platform.md:92`；`docs/architecture.md:40` | ADR 依赖清单有 `socket2`，架构的 crate 依赖没有 | 补表或从 ADR 删除 | U |

## 4. 被否决的处置方案（agent 已论证过，重新提出前先读）

| 方案 | 否决理由（摘要） |
|---|---|
| E-1 删 inproc、M1 改用 loopback TCP | 会把 M2 的传输验收整体前移，破坏 M0→M1→M2 切分；inproc 是 FR-3.2“只换后端”最省事的第一个后端 |
| E-2 UDP 保留 v1 只补一条 AC | UDP 与 conn 句柄、自动重连、背压、`NO_RECEIVER`、RTT/SLOW 配对全面冲突，补 AC 只是把债藏进验收 |
| E-3 `registry_plugin` 保留字段但不实现 | 未定义加载语义的字段会让实现者当空操作、调用方以为生效；头文件未发布，删除零成本 |
| E-4 整条删除 FR-5.5 | 连接表 + 队列水位 dump 对无调试器现场有独立价值；应拆分保留 |
| E-5 FR-10.17 整体延 v1.1 | 预算字段已在 v1 ABI，检查只是 open 时一次加法；v1 无预算会导致多 monitor 叠加耗尽内存 |
| E-6 删除所有无 AC 的 P1 FR | AC-E6 只约束 P0；缺 AC 是“版本未标注”问题，应标 v1.1 而非删产品方向 |
| E-7 补 FR-6.8 并删 C ABI §6.4 正文 | §6.4 互斥表是库级硬规则，需保留为实现依据 |

## 5. 需人工判断后才能定的条目（agent 已声明“不推测”）

| 项 | 为什么不能直接采信 |
|---|---|
| `M8` / `M11` 来源 | 仓库内只有 M0–M7，未见定义；无法排除引用了未入库文档 |
| `registry_plugin` 的历史 | `IoComm/` 未入库（未 tracked），无 git 历史可查，“曾被审计指出”无法从仓库证实 |
| `mio::windows::NamedPipe` 是否存在于目标 mio 版本 | 文档审计未做依赖核实；S2 Spike 结论才是权威 |
| UDP 是否有外部需求附件 | 审计只拿到 6 份文档 |
| “无工作量”的判定 | 指“未单列条目”；inproc 实际含在 `transport: tcp + inproc 10–15` 的合并估算里 |
| AC-E6 的执行方式 | 未说明自动化程度；若有脚本，计数会不同 |
| `monitor_budget_bytes` 是否在 v1 真正执行 | §9.3 描述 open 时检查，但 FR-10.17 标 v1.1；两种解释都成立 |

## 6. 计数口径与边界说明

- 报告自述：**断链 24 处、口径矛盾 16 处、去重后独立问题 36 个**。
- “断链”按**声明点**计，一个声明点只出现一次；“矛盾”单独计；4 组同根因（D-01↔B-07、D-03↔B-02、D-09↔B-09、D-07↔B-06 部分）已去重。
- **阈值类判断**不是文档错误：如 D-01 是否成立，取决于“异步发送是否必须自带超时”这一设计取舍——核实时要先定判据，不要只数条目。
- 本清单的**行号指向审计时刻的文档版本**（2026-10-20 15:00 前后）；文档改动后需重新定位。

---

## 7. 人工核查记录（2026-10-20，主会话）

只核对了 8 条的关键原文；其余条目维持 **U**。每条核查都在本机 `IoComm/` 文档上执行（命令为 `grep` / `sed -n`），结果如下。

**核查方法**：对每条，直接读取报告引用的原文位置，确认“报告结论”与“文档实际内容”是否一致；只核对原文存在性与矛盾点，**不判断处置方案的好坏**。

| # | 条 | 核查动作 | 结论 |
|---|---|---|---|
| V1 | D-01 | `grep -n DROP_TIMEOUT` 仅 1 处（`:800` 枚举注释）；`sed -n 473,479p` 读 `iocomm_send_options` 全字段；`grep -n timeout_ms` 21 处，全部属于 connect/accept/recv/drain 等，`*_send_async` 签名（`:489-504`）无该参数；AC-41（`requirements.md:263`）含「异步发送超时（TIMEOUT）」 | **成立**。`DROPPED(TIMEOUT)` 的触发条件在 ABI 中不可达。 |
| V2 | D-02 | `grep -n "const char\* name;"` 得到 `:256`（端点名配置）与 `:645`（节点信息）；`grep -n "node_id\|runtime_config"` 显示 `:143` 是创建期**输入**字段、`:248` 将其归为创建期参数，`:654` 在 `node_info` 里（对端视角）；未见返回本机 `node_id` 的函数 | **成立**（`node_info.name` 有声明、无来源；本机 `node_id` 无公开查询入口——`node_info` 返回的是对端信息）。 |
| V3 | D-03 | `sed -n 260p` 得 `/* "tcp" / "udp" / "unix" / "pipe" */`；`grep -c inproc docs/requirements.md` = 0；`architecture.md:422` 的 M1 产出含 `inproc` | **成立**（且比“字符串缺失”更严重：需求层完全没有 inproc）。 |
| V4 | D-04 | `sed -n 1113p`、`1117p`；下一行分别是 C8（`:1114`）、C12（`:1118`） | **成立**。C7/C11 正文确实在冒号处结束，无后续内容。 |
| V6 | D-10 | `grep -c run_until docs/api/c-abi.md` = 0；`architecture.md` = 1 | **成立**（架构引用了不存在的 API）。 |
| V7 | D-11 | `sed -n 310,320p docs/architecture.md` 得「中心注册表（可选插件）」与「插件点」；`sed -n 630,640p docs/api/c-abi.md` 得 `registry_plugin` / `registry_plugin_len`；`grep -c registry_plugin docs/requirements.md` = 0 | **成立**。补充：`:317` 写的是“方案必须提供中心注册表的**插件点**”，不是“已有插件实现”——残留的是**接口占位**，不是完整功能，处置时按此定性。 |
| V8 | B-01 | `sed -n 72p docs/requirements.md`（FR-4.2 仅一行 P1）；`sed -n 260p docs/api/c-abi.md`（字符串含 `udp`） | **成立**。 |

**已核对 7 条，全部成立（7/7）**；未发现需要推翻的条目。其余 33 条未核对，维持 U。

> **注意**：7/7 成立只能说明“该 agent 的取证是可信的”，**不能**推断其余条目也成立——尤其是报告中自称“由 AC 反推”的部分（如 D-04 的审计序列建议）和涉及设计取舍的判定（如 E-1～E-7）。

---

## 7b. 第二轮核实（2026-10-21，主会话）

**判据（先定，后核）**：
- **C**：引用的原文确实存在且支持该结论（逐点比对当前版本）；
- **R**：引用原文不存在 / 已被改掉 / 结论超出原文能支持的范围；
- 行号一律**重新定位**，不采信 2026-10-20 版的行号；
- 已在 2026-10-21 改动中处置的，标 **C（已处置）** 并写明落点。

| 结论 | 条目 |
|---|---|
| **R（3）** | D-08、B-06（前提不成立：LOST 槽是 P0，`monitor_ttl_ms` 不是 v1.1）；B-12（README 调用的参数个数与顺序与签名一致） |
| **C 已处置（25，2026-10-21）** | D-01、D-02、D-03、D-04、D-11、D-12、D-14、D-15、D-17、D-18、D-19、D-20、D-21、D-22、D-23、D-24、B-01、B-02、B-04、B-05、B-07、B-11、B-15、B-16、B-03（部分） |
| **C 已处置（12，2026-10-22）** | D-05、D-06、D-07、D-09、D-13、D-16、B-03（收尾：改为 §9.0 归属表）、B-08、B-09、B-10、B-13、B-14 |
| **C 已处置（37）** | 全部 C 条目已在 2026-10-21 / 2026-10-22 两轮改动中处置完毕，无遗留 |

> **本轮新增的 AC**：AC-83–88；**新增 FR**：FR-2.8、FR-6.8。
> **与 agent 结论不同的两条**：D-08 / B-06 判 **R**（agent 把 P0 特性当成 v1.1）；B-12 判 **R**（实为示例变量未定义，不是签名不一致）。

> **2026-10-22 补充**：M1 新增「跨进程名字表（§6.4）」产出，AC-11 由 M4 移到 M1，新增 AC-89；
> 新建 `docs/api/wire-format.md`（D-06）；`MAX_BYTES` 默认值定死；平台矩阵删除 MinGW、ARM64 Windows 改为不在产品范围。
