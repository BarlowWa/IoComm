# IoComm 待核实问题清单（2026-10-20）

> **⚠️ 最新批次见 [§8 2026-11-03 新一轮核实](#8-2026-11-03-新一轮核实)——15 条中 N-01 / N-02 / N-15 已按方案 A 处置，其余 12 条未处置。**
>
> **状态（2026-10-22 更新）**：审计来源的 **40 条已核实并处置**——C 37 条、R 3 条（D-08 / B-06 / B-12）。
>
> ⚠️ **本清单的覆盖边界**：审计只覆盖了 2026-10-20 时的 **6 份文档**；2026-10-21 新增的 `docs/api/wire-format.md`
> 与 `ADR-002` **不在其覆盖范围内**。它们的核查记录见 `.tmp_research/iocomm-*-audit/` 下的后续报告。
> **本清单的 `文件:行号` 指向 2026-10-20 版本，已全面漂移，不作为当前定位依据。**
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
| D-01 | B0 | `docs/api/c-abi.md:800`、`:473-479`、`:489-504`；`docs/requirements.md:263`（AC-41） | 丢弃原因 `ICOMM_DROP_TIMEOUT`（“异步发送在 timeout_ms 内未完成”）存在，但 `iocomm_send_options` 与两个 `*_send_async` 都没有 `timeout_ms` 参数 → AC-41 不可构造 | 补设计：`send_options` 尾部追加 `uint64_t queue_timeout_ms`（当时的 `timeout_ms` 命名已废弃）（尾部追加只升 minor）；写明超时后消息出队、`on_done(TIMEOUT)`、产生 `DROPPED(TIMEOUT)` | **C**（§7-V1）；**已处置 2026-10-21**：补 `send_options.queue_timeout_ms`（0 = 无截止，计时「入队→开始写」），并把 `on_done(OK)` 完成点定为「已完整交给传输层」 |
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
| D-10 | B3 | `docs/architecture.md:356`、`:361` | 架构/里程碑引用的 `run_until` 与 `pending_timer_count` 在 C ABI 中不存在 | `run_until` 删除；`pending_timer_count` 若只服务测试则删/改为测试接口 | **C**（§7-V6）；**已处置 2026-10-22**：T1 删除 `run_until`、T6 改为「v1 不提供公开入口」 |
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
| B-15 | 低 | `docs/adr/ADR-001-language-and-platform.md:90`；`IoComm/README.md`、`docs/architecture.md:154` | ADR“tokio 只作可选 feature” vs README/架构“不绑 tokio” | ADR 改为“不进入核心依赖，至多用于基准/示例”或删除 | **C**（已处置 2026-10-22：B-15 ADR-001 改为「tokio 不进入任何 crate 依赖」） |
| B-16 | 低 | `docs/adr/ADR-001-language-and-platform.md:92`；`docs/architecture.md:40` | ADR 依赖清单有 `socket2`，架构的 crate 依赖没有 | 补表或从 ADR 删除 | **C**（已处置 2026-10-22：B-16 架构 crate 表补 `socket2` 说明） |

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

---

## 8. 2026-11-03 新一轮核实

> **来源**：4 个独立只读 agent 对当前 `IoComm/` 全部 9 份文档的交叉核实（其中 1 个为 P0 断言的独立反方复核）。
> 报告在 `.tmp_research/iocomm-verify-2026-11-03/`：`p0-claims.md`、`p0-independent-refutation.md`、
> `protocol-gaps.md`、`identity-api-gaps.md`。每条均给逐字原文与当前行号。
>
> **判定口径**：本轮对每条先做「试图推翻」，推不翻才记为成立；下表「状态」一律为**未处置**，
> 与 §1–§3 的 C / R 标记不混用。**行号对应 2026-11-03 版本，后续改动会漂移**。
>
> **覆盖教训**：N-03 / N-04 / N-06 / N-09 / N-12 / N-13 在 `iocomm-design-audit/` 与
> `iocomm-session-audit/` 中**已被提出且标为重要/阻断**，但从未进入本清单，因此未被处置。
> 前轮 `finding-accuracy.md` 的「17/18 已修复」只覆盖 `iocomm-dryrun/`，**与本批零重合**。

### 8.1 阻断（M0/M2 冻结前必须裁决）

| ID | 严重度 | 位置 | 问题摘要 | 建议处置 | 状态 |
|---|---|---|---|---|---|
| **N-01** | **B0** | `architecture.md:225`、`c-abi.md:677`、`:841` ↔ `c-abi.md:714-715`、`:719-721`；`requirements.md:276`（AC-30）、`:286`（AC-39） | **端点扇出集合自相矛盾**。前两处说扇出到「该端点全部已建立的连接」；§6.1 却说被持有的入站连接「按不归属端点处理……**它们不参与端点扇出**」。`ep_owner` 只存在于出站 `connect*` 签名，入站路径从不取该参数 ⇒ 扇出集合只剩 `ep_owner == ep` 的出站连接。**纯服务端（只 accept）调 `endpoint_send` 必返回 `NO_RECEIVER`**。AC-30 的 N 无定义，服务端扇出零 AC 覆盖。**引入点**：`d8156aa`（2026-10-22）为解决旧问题「入站连接归属未定义（session-audit 2.5）」新增了这句，但未回改 `:677` 与 `architecture.md:225` | **已按方案 A 处置（2026-11-03）**：入站连接归监听端点；扇出 = 全部成员连接 | **C（已处置 2026-11-03）** |
| **N-02** | **B0** | `architecture.md:229`、`c-abi.md:526-534`、`:679-685`、`:920-926`、`:941-947`；`requirements.md:279`（AC-33）、`:323`（AC-75）；`ADR-002:30`、`:75` | **端点级 `iocomm_subscribe(ep)` / `endpoint_recv(ep)` 收不到入站消息**。持有动作是**封闭列表**（仅 `conn_retain` / `conn_subscribe`），端点级订阅不在其中；AC-33 也未给端点级订阅留豁免。更硬的一点：`c-abi.md:179` 把 `endpoint_accept` 与 `iocomm_subscribe` 同列在 `INVALID_STATE（recv 已启用）`，即 `endpoint_recv(ep)` 与 `endpoint_accept(ep)` **结构性互斥**，"用端点级拉取绕过 accept"这条路被 API 自身堵死。另：`iocomm_subscribe` / `endpoint_recv` 在 `requirements.md` 中**零 FR / AC** | 与 N-01 同根因，**一并裁决**。**已按方案 A 处置（2026-11-03）**：新增 FR-8.11 + 端点级持有规则 + AC-104 | **C（已处置 2026-11-03）** |
| **N-03** | **B1** | `c-abi.md:525`；`wire-format.md:162`、`:166`；旧账：`iocomm-design-audit/cross-doc-consistency.md` XD-22 | **accept 回调的交付时点未定义**（TCP 建立时 vs 双向 HELLO 完成后）。`wire-format.md` 全文 `accept` **零命中**。后果：`accept` 回调内用 `CLOSE_AFTER` 发首条数据（README 主推写法）在"TCP 建立即交付"的实现下会被对端以「未握手 DATA」直接断链（`wire-format.md:166`）。inproc 不跑 HELLO，即便定为「HELLO 后交付」，其 `peer_node_id` 来源仍空白 | M2 前二选一并写进 §5.2：① 交付时点 = 双向 HELLO 完成（`peer_node_id` 必有值，且与借用语义相容）；② 交付时点 = TCP 建立（须显式规定握手完成前禁止发送 DATA、`peer_node_id` 允许 0）。推荐 ① | 未处置 |

### 8.2 重要（实现前定）

| ID | 严重度 | 位置 | 问题摘要 | 建议处置 | 状态 |
|---|---|---|---|---|---|
| **N-04** | B2 | `architecture.md:190`、`:195`；`c-abi.md:254` | **`node_id` 派生分支与 v1 语义互斥**：不可写时「从 machine-id / 主机名 / MAC 派生稳定哈希」是主机级纯函数，同机多进程必得**同一个** NodeId，直接违反「NodeId 唯一标识一个 Runtime 实例」。另 `state_dir` 注释写「可 NULL」，但自动模式只描述"在 state_dir 下读写"，**NULL 无分支**；docs 全文未规定 Windows 派生源（`MachineGuid` 未出现） | 定 `state_dir == NULL` 的策略（建议：视为不可写路径，但派生值必须掺入进程唯一量，或直接拒绝自动模式并要求显式 `node_id`）；把「只读文件系统」分支改为与 v1 语义相容的方案；补 Windows 派生源 | 未处置 |
| **N-05** | B2 | `c-abi.md:575-581`、`:1030-1037`；`wire-format.md:258`；`architecture.md:340` | **`connect_node` 的地址解析规则不存在**。`connect_node` 只收 `node_id` + 端点名；`iocomm_endpoint_info.addr` 由 `ENDPOINTS` tag 原样上报，但**在 ABI 里没有任何消费者**。真正缺的是「`node_info` + 端点名 → 可拨号地址」的解析规则，以及「通配监听地址（`0.0.0.0:0` / `:0`）如何通告」的规则。（原判断「addr 被对端直接拿去 connect」不成立，已更正） | 补一节解析规则：成员查找 → 按 transport 选地址 → 通配地址用信标源 IP/端口替换 → 失败码；同时明确 `endpoint_info.addr` 的语义（通告值 vs 原始监听值） | 未处置 |
| **N-06** | B2 | `requirements.md:91`（FR-4.4）、`:266`（AC-20）；`architecture.md:235`、`:249-253`、`:318`；`c-abi.md:1399-1400` | **重连语义零文字**：重连成功后 `iocomm_conn_t` 是否复用；队列中在途消息是否跨重连保留；`sequence` 是否按连接重计；`peer_node_id` / 订阅是否保持。AC-20 只验 `reconnects` 计数 | 至少定四件事：句柄复用（建议复用，否则应用无法持有稳定句柄）、在途消息（建议断开即清空并按 `PEER_GONE` 结算，重连不重放）、`sequence`（建议随连接重置并在重连后以新 `peer_node_id` 标识）、订阅保持（建议保持）。补 AC | 未处置 |
| **N-07** | B2 | `architecture.md:264`、`:317`；`c-abi.md:331`、`:332`、`:402` | **`heartbeat_miss_limit` 默认值仍不可判定**：`:317` 写「N 可配，默认 ≥ 3」（下界），`:264` 的 `Healthy` 定义按「默认 3 个心跳周期」算，`:332` 只写「0 = 保持」。另 `c-abi.md:331` 的「默认 2000 ms（见架构 §6.2）」是**悬空引用**——`architecture.md:312-318` 全文没有 2000（该值由 `efb22bf` 改入，架构侧未同步） | 把 `heartbeat_ms = 2000`、`heartbeat_miss_limit = 3` 写成具体默认值并落到架构 §6.2；删除或修正悬空引用 | 未处置 |
| **N-08** | B3 | `c-abi.md:352-356`、`:168`；`architecture.md:93`、`:128`、`:384` | **`iocomm_runtime_run_for` 语义未定义**：无注释、无需求来源（`requirements.md` 零命中）、错误矩阵无 `TIMEOUT`；`duration_ms = 0` 与返回值语义完全无定义；与 `run_once` 的关系（是否等于循环）未写 | 补注释：`run_for(duration_ms)` = 循环 `run_once` 直到累计耗时达 `duration_ms`；`0` 的语义（建议 = 不等待）；返回码与 `run_once` 同口径。补一条需求来源 | 未处置 |
| **N-12** | B2 | `c-abi.md:408-427`、`:323-341`；`architecture.md:315` | **端点级套接字参数缺失**：`TCP_NODELAY`、监听 backlog、keepalive 开关在 `endpoint_config` / `tune_config` 中均无字段（docs + README 对 `TCP_NODELAY`、`backlog` 零命中）。对「小消息、低延迟」的工业 IO，Nagle 可能引入数十毫秒；backlog 溢出表现为连接被拒且计数不可见 | 至少在 `endpoint_config` / `tune_config` 尾部追加 `tcp_nodelay`（建议默认开）与 `listen_backlog`；若定为不可配置，须写进非目标并说明替代方案 | 未处置 |
| **N-13** | B3 | `requirements.md:46`（FR-2.6）、`:285`（AC-38）；`architecture.md:80`、`:334`、`:346-352` | **本机注册表（`publish_local`）缺实现机制**：FR-2.6/AC-38 要求发布并产生 `JOINED/LEFT`，架构只有「local-registry / 本机注册表」一行；对比 §6.4 跨进程名字表给了具体机制。§6.4 的名字锁只能回答「名字是否被占」，承载不了端点能力与事件；也未规定 `discovery_start` 是否为前置条件 | 明确机制（建议：Runtime 内共享内存/命名对象 + 段内链表，或复用 §6.4 名字锁并附加能力段），并规定未 `discovery_start` 时 `publish_local` 的行为（拒绝 or 延迟发布） | 未处置 |

### 8.3 次要（可后补，但不能丢）

| ID | 严重度 | 位置 | 问题摘要 | 建议处置 | 状态 |
|---|---|---|---|---|---|
| **N-09** | B4 | `c-abi.md:476`、`:175`、`:203-205`、`:356`；`requirements.md:343`（AC-95） | **无 `err` 参数的函数与错误通道契约冲突**（2026-11-03 扫描确认**三个**，不是两个）：`iocomm_endpoint_count`、`iocomm_runtime_wakeup`、`iocomm_discovery_snapshot_release` 的声明均无 `iocomm_error*`，但矩阵 `:175`/`:173` 给前两者列了 `STALE_HANDLE/INTERNAL`；AC-95 的「无错误通道」豁免清单（6 个函数）三者均不含 | 三选一并统一：① 给三者加 `err`；② 把它们补进 AC-95 豁免，矩阵行改为「无错误通道」；③ 保留返回值承载（如 `snapshot_release` 的 `STALE_HANDLE`）。**三者必须同一口径**，否则同一份头文件里有三套失败报告方式 | 未处置 |
| **N-10** | B4 | `c-abi.md:860-865` | **`op_id` 的唯一性范围未定义**：`send_cancel` 只拿 `op_id`，但没写它是每 Runtime / 每连接 / 每组唯一，也未写是否回绕复用（对比 `capture_id` 明文「永不复用」、`seq` 明文警告回绕） | 定为「每 Runtime 单调分配、不回绕（耗尽返回 `RESOURCE_EXHAUSTED`）」，并写明 `send_cancel` 对已完成 / 不存在 op 的返回 | 未处置 |
| **N-11** | B4 | `c-abi.md:913`；`wire-format.md:104`；`architecture.md:372`；`platform-support.md:222` | **`clock_synced` 永不置位**：三处只声明字段/tag，全文无时间同步机制、无置位规则（PTP 仅在平台支持「待核实」清单）。实质是恒 0 字段 | 二选一：删除该字段与 `CLOCK_SYNCED` tag（载荷不透明、库不提供时间同步）；或保留并在注释中写明「v1 恒 0，保留给 v2 时间同步扩展」 | 未处置 |
| **N-14** | B4 | `c-abi.md:414`、`:508`；`requirements.md:74` | **`listen_addr` / `listen_transport` 组合语义不完整**：只写了「`listen_addr` NULL = 不监听」，未规定 transport 非空而 addr 为 NULL、addr 非空而 transport 为 NULL、两者皆空的行为（「inproc 的 `listen_addr` 必填」已规定，不在此列） | 补一张组合表，每格给 `INVALID_ARGUMENT` / 不监听 / `NOT_SUPPORTED` 之一 | 未处置 |

> **N-15（并入 N-01，已随方案 A 处置）**：入站消息进「端点接收队列」还是「连接接收队列」——已在 `c-abi.md` §6.4 定稿：
> 默认进**端点接收队列**；被 `conn_subscribe` / `conn_retain` 单独接管的连接改进入该连接队列，不双投。

### 8.4 N-01 / N-02 的裁决方案

> **裁决结果（2026-11-03）：采用方案 A**，已落到 `requirements.md`（FR-8.6 / 8.8 / 8.11、AC-30 / 33 / 39 / 75 / 103 / 104）、
> `c-abi.md`（§5.2 / §6.1 / §6.3 / §6.4）、`architecture.md`（§5.2 + M2 里程碑）、`ADR-002`（决策 3 修订注）、`README.md`。
> 下表三方案保留作决策记录；**下面「裁决后必须同步的位置」除 AC-32 外已全部执行**——AC-32 未改动，
> 因为端点级订阅成立后 `endpoint_recv(ep)` 与 `endpoint_accept(ep)` 的互斥由既有 §6.4 规则继续覆盖，无需改写。

| 方案 | 内容 | 优点 | 代价 |
|---|---|---|---|
| **A（推荐）入站连接归监听端点** | 删除「入站连接不参与端点扇出」，改为「入站连接归属于监听它的端点」；`endpoint_send` 目标 = 端点全部已建立连接（入站 + `ep_owner == ep` 出站）；入站连接的 `conn_send` 用端点共享发送队列；`endpoint_recv` / `iocomm_subscribe` 随之成立 | 服务端扇出可用；与 `architecture.md:225`、`c-abi.md:677/920` 一致；FR-6.8 / AC-30 / AC-32 不需重写；符合「端点 = 监听者」直觉；与 `endpoint_destroy` 第 2 条（入站连接随端点 FIN）自然衔接 | 入站 peer 与出站连接共享端点队列（§6.1「代价一」已覆盖）；须新增端点级订阅的 FR + AC（当前零覆盖）；AC-30 的 N 需定义为「入站 + 归属出站」 |
| B 维持「不归属」，扇出只到出站 | 保留 §6.1 现有队列模型；把 `c-abi.md:677`、`:841`、`architecture.md:225` 改成「所有归属该端点的出站连接」；服务端扇出改为 `conn_count(ep)` + 逐条 `conn_send`。端点级 `recv/subscribe` 必须删除，或另定为「未注册 accept 时由库自动接受并持有」 | 不动已有队列决策；实现最简单 | 与「端点 = 监听者」直觉相反；服务端无法用一条 API 广播；FR-6.8 / AC-32 需重写或删除；`architecture.md:225` / `c-abi.md:920` 须改；并存两套所有权规则 |
| C 分离「队列归属」与「扇出成员资格」 | 入站连接不占端点队列，但计入端点扇出 | 看似最小改动 | **不自洽**：共享队列模型下 `endpoint_send` 必须把项放进端点队列，成员不在该队列就无法扇出；若改为放进各自队列，则「共享队列 + 队列项带目标连接」模型失效。**不推荐** |

> **裁决后必须同步的位置**（按方案 A）：`c-abi.md` §5.2 发送目标表、§6.1 队列归属规则、§6.3 `iocomm_subscribe` / `endpoint_recv` 注释；
> `architecture.md` §5.2 对象模型表与借用语义段；`requirements.md` AC-30（N 定义）、AC-33、AC-39（过滤口径）、AC-32（端点级互斥）；
> 新增端点级订阅的 FR + AC；`README.md` 第 3 步注释。

### 8.5 建议处置顺序

1. **N-01 / N-02 / N-15**（同根因，阻断）——先定 §8.4 的方案 A/B，再一次性改五处文档与三条 AC。
2. **N-03**（M2 线格式冻结前）——决定 README 主推示例是否可用。
3. **N-04 / N-05 / N-06 / N-07 / N-12**（M3/M4 前）。
4. **N-08 / N-09 / N-10 / N-11 / N-13 / N-14**（可随对应文档批次顺带修）。
