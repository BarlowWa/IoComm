# IoComm 待核实问题清单（2026-10-20）

> **⚠️ 最新批次见 [§10 2026-11-05 第二轮复核](#10-2026-11-05-第二轮复核对-039fc19-的验收)——N-53 / N-54 契约缺陷已修，N-55 / N-57 / N-60（seed bootstrap 端口语义，2026-11-10 新增）待办，N-56 / N-58 已闭合，N-59 已核实（降 B4）**。
> 上一批 [§9](#9-2026-11-05-用户清单核实n-36--n-52) 的 N-36 ～ N-52 已全部落笔（**N-46 / N-47 于 2026-11-09 裁决，N-48 于 2026-11-10 裁决，三项均已落笔**）。
> 此前批次：[§8 2026-11-03](#8-2026-11-03-新一轮核实) 的 15 条**全部已处置**（N-01 / N-02 / N-15 按方案 A、N-03 按方案 ①、N-04 ～ N-14 于 2026-11-04 收口），另新增 N-16 / N-17 / N-18 / N-19 四项（均已处置并落文档），不计入原 15 条。**
> **2026-11-05 补充二**：用户清单核实新增 **[§9 N-36 ～ N-52 十七项](#9-2026-11-05-用户清单核实n-36--n-52)**——其中 **N-36 ～ N-41、N-49 ～ N-52 是 B1/B3 契约缺陷**（多处契约互斥，M0 冻结前必修），
> N-42 ～ N-45 是「取舍正确但没写清」，N-46 / N-47 已于 2026-11-09 裁决、N-48 于 2026-11-10 裁决，**本节已无待拍板项**。与 §8 不同，本节多数是「文档没写」而非「写错」。
>
> **2026-11-05 补充**：M0 冻结前的残留核对又收口 **N-20 ～ N-35 十六项**（见 [§8.8](#88-2026-11-05-收口核实与裁决n-20--n-35)），其中 N-20 ～ N-25 是**需要先定口径**的，裁决写在该节 8.8a；同样不计入原 15 条。**N-34 为收尾阶段新发现、N-35 为登记项（许可证，待负责人决策）**。
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
| D-05 | B1 | `docs/architecture.md` §6.4、M4 行；`docs/requirements.md` FR-1.4/1.5、AC-11 | 跨进程名字表（FR-1.4/1.5 的实现基础）无里程碑承接；AC-11 错挂 M4 且 M4 产出清单不含实现项 | 补设计：名字表写进 M1 产出（或新增 M1.5），AC-11 移回 M1/M2；补“允许第二实例 + 改名”的 AC | **C**（已处置 2026-10-22：名字表落 **M1** 产出，AC-11 移到 M1；新增 AC-89。**口径（选项 A）**：端点名的跨进程排他**与传输无关**，inproc 端点同样参与；FR-3.6 的「跨进程隔离」只指 `listen_addr`）。**2026-11-04 推翻其中「允许第二实例 + 改名」部分，见 §8 的 N-16）（本条本身仍为已处置，不因推翻部分内容而回到未处置）** |
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
> **判定口径**：本轮对每条先做「试图推翻」，推不翻才记为成立。下表「状态」栏记录处置进展
> （2026-11-04 起 **15 条全部已处置**），与 §1–§3 的 C / R 标记不混用。**行号对应 2026-11-03 版本，后续改动会漂移**。
>
> **覆盖教训**：N-03 / N-04 / N-06 / N-09 / N-12 / N-13 在 `iocomm-design-audit/` 与
> `iocomm-session-audit/` 中**已被提出且标为重要/阻断**，但从未进入本清单，因此未被处置。
> 前轮 `finding-accuracy.md` 的「17/18 已修复」只覆盖 `iocomm-dryrun/`，**与本批零重合**。

### 8.1 阻断（M0/M2 冻结前必须裁决）

| ID | 严重度 | 位置 | 问题摘要 | 建议处置 | 状态 |
|---|---|---|---|---|---|
| **N-01** | **B0** | `architecture.md:225`、`c-abi.md:677`、`:841` ↔ `c-abi.md:714-715`、`:719-721`；`requirements.md:276`（AC-30）、`:286`（AC-39） | **端点扇出集合自相矛盾**。前两处说扇出到「该端点全部已建立的连接」；§6.1 却说被持有的入站连接「按不归属端点处理……**它们不参与端点扇出**」。`ep_owner` 只存在于出站 `connect*` 签名，入站路径从不取该参数 ⇒ 扇出集合只剩 `ep_owner == ep` 的出站连接。**纯服务端（只 accept）调 `endpoint_send` 必返回 `NO_RECEIVER`**。AC-30 的 N 无定义，服务端扇出零 AC 覆盖。**引入点**：`d8156aa`（2026-10-22）为解决旧问题「入站连接归属未定义（session-audit 2.5）」新增了这句，但未回改 `:677` 与 `architecture.md:225` | **已按方案 A 处置（2026-11-03）**：入站连接归监听端点；扇出 = 全部成员连接 | **C（已处置 2026-11-03）** |
| **N-02** | **B0** | `architecture.md:229`、`c-abi.md:526-534`、`:679-685`、`:920-926`、`:941-947`；`requirements.md:279`（AC-33）、`:323`（AC-75）；`ADR-002:30`、`:75` | **端点级 `iocomm_subscribe(ep)` / `endpoint_recv(ep)` 收不到入站消息**。持有动作是**封闭列表**（仅 `conn_retain` / `conn_subscribe`），端点级订阅不在其中；AC-33 也未给端点级订阅留豁免。更硬的一点：`c-abi.md:179` 把 `endpoint_accept` 与 `iocomm_subscribe` 同列在 `INVALID_STATE（recv 已启用）`，即 `endpoint_recv(ep)` 与 `endpoint_accept(ep)` **结构性互斥**，"用端点级拉取绕过 accept"这条路被 API 自身堵死。另：`iocomm_subscribe` / `endpoint_recv` 在 `requirements.md` 中**零 FR / AC** | 与 N-01 同根因，**一并裁决**。**已按方案 A 处置（2026-11-03）**：新增 FR-8.11 + 端点级持有规则 + AC-104 | **C（已处置 2026-11-03）** |
| **N-03** | **B1** | `c-abi.md` §5.2 `iocomm_accept_fn` / `iocomm_peer_info`；`wire-format.md` §5、§7；`architecture.md` §5.2b；旧账：`iocomm-design-audit/cross-doc-consistency.md` XD-22 | **accept 回调的交付时点未定义**（TCP 建立时 vs 双向 HELLO 完成后）。`wire-format.md` 曾全文 `accept` **零命中**。后果：`accept` 回调内用 `CLOSE_AFTER` 发首条数据（README 主推写法）在"TCP 建立即交付"的实现下会被对端以「未握手 DATA」直接断链（`wire-format.md` §5 规则 3）。inproc 不跑 HELLO，其 `peer_node_id` 来源亦空白 | M2 前二选一并写进 §5.2：① 交付时点 = 双向 HELLO 完成（`peer_node_id` 必有值，且与借用语义相容）；② 交付时点 = TCP 建立（须显式规定握手完成前禁止发送 DATA、`peer_node_id` 允许 0）。推荐 ① | **C（已处置 2026-11-03）**：采用**方案 ①**（与预设倾向一致）。交付时点 = 双向 HELLO 完成；握手期连接为**内部会话占位**（不分配句柄、不占 `max_handles`、应用不可见）；握手失败/超时不产生 `accept`；`peer_node_id` 必有真实值。**inproc 显式定义**为「建立即交付」，`peer_node_id` 取对端 Runtime `node_id`（仅竞态为 0）。落点：`c-abi.md` §5.2 / §6.0 / §6.1、`wire-format.md` §5 规则 7 / §7、`architecture.md` §5.2b（新增 `Handshaking` 态）、`requirements.md` FR-8.5 + AC-92 ⑦、`README.md` 第 3 步。否决方案 ② 理由见 §8.4b |

### 8.2 重要（实现前定）

| ID | 严重度 | 位置 | 问题摘要 | 建议处置 | 状态 |
|---|---|---|---|---|---|
| **N-04** | B2 | `architecture.md` §5.1b；`c-abi.md` `runtime_config` / 错误码矩阵 `iocomm_runtime_create` | **`node_id` 派生分支与 v1 语义互斥**：不可写时「从 machine-id / 主机名 / MAC 派生稳定哈希」是主机级纯函数，同机多进程必得**同一个** NodeId，直接违反「NodeId 唯一标识一个 Runtime 实例」。另 `state_dir` 注释曾写「可为空」，但自动模式只描述"在 state_dir 下读写"，**空值无分支**；docs 全文未规定 Windows 派生源 | 定 `state_dir == NULL` 的策略；把「只读文件系统」分支改为与 v1 语义相容的方案；补 Windows 派生源 | **C（已处置 2026-11-04）**：**v1 不派生**。自动模式仅在 `state_dir` 下原子持久化随机 64 位；`node_id == 0` 且 `state_dir` 为空/不可写 → `runtime_create` 返回 `INVALID_ARGUMENT`（错误信息指明需显式 `node_id`）。理由：主机级派生违反「每 Runtime 独立」，掺随机盐违反 FR-9.1，两约束夹逼下唯一解是「只读场景显式配置」。Windows 与 Linux 同规则，无派生源。**口径已闭环（2026-11-05 确认，不再是待确认项）——`architecture.md` §5.1b 的取舍说明保留为决策记录，标注「已闭环」** |
| **N-05** | B2 | `c-abi.md` §5.2 `connect_node` / `endpoint_info`；`wire-format.md` §8 `ENDPOINTS`；`architecture.md` §6.3 | **`connect_node` 的地址解析规则不存在**。`connect_node` 只收 `node_id` + 端点名；`iocomm_endpoint_info.addr` 由 `ENDPOINTS` tag 原样上报，但**在 ABI 里没有任何消费者**。真正缺的是「`node_info` + 端点名 → 可拨号地址」的解析规则，以及「通配监听地址（`0.0.0.0:0` / `:0`）如何通告」的规则 | 补一节解析规则：成员查找 → 按 transport 选地址 → 通配地址用信标源 IP/端口替换 → 失败码；同时明确 `endpoint_info.addr` 的语义 | **C（已处置 2026-11-04）**：新增 c-abi §5.2a——`node_id` 精确查找 → `endpoints` 按 `name` 精确匹配 → 取 `transport`+`addr`；失败码 `NOT_FOUND`（节点/成员）/`NOT_SUPPORTED`（transport）。`endpoint_info.addr` 定为**通告值**：发送端在编码 `ENDPOINTS` 前把通配地址/端口 0 替换为实际值（实际仍通配则用发送 socket 本地地址）；`endpoint_local_addr()` 仍返回**原始监听值**。新增 FR-8.12 + AC-107（M4）；wire-format §8 规则 6 |
| **N-06** | B2 | `requirements.md` FR-4.4 / AC-20；`architecture.md` §5.2b；`c-abi.md` `connect` 注释 / `iocomm_peer_status` | **重连语义零文字**：重连成功后 `iocomm_conn_t` 是否复用；队列中在途消息是否跨重连保留；`sequence` 是否按连接重计；`peer_node_id` / 订阅是否保持。AC-20 只验 `reconnects` 计数 | 至少定四件事：句柄复用 / 在途消息断开即清空 `PEER_GONE` / `sequence` 随连接重置 / 订阅保持；补 AC | **C（已处置 2026-11-04）**：四项全部定案——① **复用同一 `iocomm_conn_t`**；② 断开即在途项逐条 `DROPPED(PEER_GONE)` + `on_done(DISCONNECTED)`，**不重放**；③ `sequence` 随连接从 1 重置（跨重连顺序靠应用层 `correlation_id`）；④ 订阅挂在连接对象上**保持**，`peer_node_id` 以新握手结果更新。落点：FR-4.4 扩写、架构新增 §5.2c + 状态图、c-abi 注释；新增 AC-105（M3）。**AC-86 的 `connected = UNKNOWN` 重连子项已回写为指向 AC-105**（N-03 遗留已清） |
| **N-07** | B2 | `architecture.md` §5.2b Healthy 定义 / §6.2；`c-abi.md` `tune_config` | **`heartbeat_miss_limit` 默认值仍不可判定**：§6.2 曾把默认写成「≥ 3」的下界（而非具体值），Healthy 定义按「默认 3 个心跳周期」算，`tune_config` 只写「0 = 保持」。另 `heartbeat_ms` 注释的「默认 2000 ms（见架构 §6.2）」是**悬空引用**——架构 §6.2 全文没有 2000 | 把 `heartbeat_ms = 2000`、`heartbeat_miss_limit = 3` 写成具体默认值并落到架构 §6.2；删除或修正悬空引用 | **C（已处置 2026-11-04）**：**`heartbeat_ms = 2000`、`heartbeat_miss_limit = 3`** 定为具体默认值；架构 §6.2 与 Healthy 定义（`2000 ms × 3 = 6 s`）同步，`tune_config` 两字段注释写死默认值，删除悬空引用 |
| **N-08** | B3 | `c-abi.md` `runtime_run_for` / 错误码矩阵；`architecture.md` §10.1 M3 | **`iocomm_runtime_run_for` 语义未定义**：无注释、无需求来源（`requirements.md` 零命中）、错误矩阵无 `TIMEOUT`；`duration_ms = 0` 与返回值语义完全无定义；与 `run_once` 的关系（是否等于循环）未写 | 补注释：`run_for(duration_ms)` = 循环 `run_once` 直到累计耗时达 `duration_ms`；`0` 的语义（建议 = 不等待）；返回码与 `run_once` 同口径。补一条需求来源 | **C（已处置 2026-11-04）**：`run_once(timeout_ms)`——本轮干了活 → `OK`；**纯空闲 → `TIMEOUT`**（正常事件，非故障，置 `err`）；`timeout_ms = 0` 只轮询一次。`run_for(duration_ms)` = **循环 `run_once` 至累计驱动满 `duration_ms`**，`0` 为空操作，**从不返回 `TIMEOUT`**（内部空闲不向外传播）。两者均仅 manual 模式、仅 loop 线程。落点：c-abi §4 注释、矩阵 `run_once` 增 `TIMEOUT`、架构 §3.3、requirements **FR-6.4 扩写** + 新增 **AC-109**（归 M1） |
| **N-12** | B2 | `c-abi.md` `endpoint_config` / `tune_config`；`architecture.md` §6.2 | **端点级套接字参数缺失**：`TCP_NODELAY`、监听 backlog、keepalive 开关在 `endpoint_config` / `tune_config` 中均无字段。对「小消息、低延迟」的工业 IO，Nagle 可能引入数十毫秒；backlog 溢出表现为连接被拒且计数不可见 | 至少在 `endpoint_config` / `tune_config` 尾部追加 `tcp_nodelay`（建议默认开）与 `listen_backlog`；keepalive 若不可配置须写进非目标并说明替代 | **C（已处置 2026-11-04）**：`endpoint_config` 尾部追加 `tcp_nodelay`（0 = 默认**开** / 1 = 开 / 2 = 关；非 0/1/2 → `INVALID_ARGUMENT`）与 `listen_backlog`（0 = 默认 128）；`tune_config` 尾部追加同名字段（0 = 保持）。新增 FR-4.8 + AC-106（M2）；§5.0 优先级表、§3.3 合法性、初始化宏、§10 发布前调整同步。**keepalive 不新增**：v1 依赖应用层心跳，写入需求非目标与 c-abi 注释 |
| **N-13** | B3 | `requirements.md:46`（FR-2.6）、`:285`（AC-38）；`architecture.md:80`、`:334`、`:346-352` | **本机注册表（`publish_local`）缺实现机制**：FR-2.6/AC-38 要求发布并产生 `JOINED/LEFT`，架构只有「local-registry / 本机注册表」一行；对比 §6.4 跨进程名字表给了具体机制。§6.4 的名字锁只能回答「名字是否被占」，承载不了端点能力与事件；也未规定 `discovery_start` 是否为前置条件 | 明确机制（建议：Runtime 内共享内存/命名对象 + 段内链表，或复用 §6.4 名字锁并附加能力段），并规定未 `discovery_start` 时 `publish_local` 的行为（拒绝 or 延迟发布） | **C（已处置 2026-11-04）**：机制定为 **每 Runtime 一个单元文件 + 原子 rename**（读者不见半个文件），内容复用线格式 §8 TLV；按 **`lease_ms` 判陈旧**（`kill -9` 残留自动 `LEFT` 并清理）。**目录是每用户固定目录**（Linux `$XDG_RUNTIME_DIR/iocomm/local/`，回退 `$HOME/.iocomm/local/`；Windows `%LOCALAPPDATA%\iocomm\local\`），文件名 `<node_id>-<pid>.bin`——**不使用 `state_dir`**：§5.1b 要求每个 Runtime 用自己的 `state_dir`，若把发现目录绑上去则「互相发现」与「各自独立」直接冲突；也**不使用 `process_epoch`**（那是 v1.1 的字段）。同一用户下互相可见，跨用户不可见。**`discovery_start` 不是前置条件**——之前创建的端点由启动扫描补齐，`endpoint_create` 不失败（延迟发布语义无损：没有发现就没有事件）。写失败：启动时 → `INTERNAL`；启动后 → ERROR 日志并每周期重试。落点：架构新增 **§6.4b**、c-abi `discovery_start` 注释、requirements FR-2.6 / **AC-38 补四条边界** |

### 8.3 次要（可后补，但不能丢）

| ID | 严重度 | 位置 | 问题摘要 | 建议处置 | 状态 |
|---|---|---|---|---|---|
| **N-09** | B4 | `c-abi.md:476`、`:175`、`:203-205`、`:356`；`requirements.md:343`（AC-95） | **无 `err` 参数的函数与错误通道契约冲突**（2026-11-03 扫描确认**三个**，不是两个）：`iocomm_endpoint_count`、`iocomm_runtime_wakeup`、`iocomm_discovery_snapshot_release` 的声明均无 `iocomm_error*`，但矩阵 `:175`/`:173` 给前两者列了 `STALE_HANDLE/INTERNAL`；AC-95 的「无错误通道」豁免清单（6 个函数）三者均不含 | 三选一并统一：① 给三者加 `err`；② 把它们补进 AC-95 豁免，矩阵行改为「无错误通道」；③ 保留返回值承载（如 `snapshot_release` 的 `STALE_HANDLE`）。**三者必须同一口径**，否则同一份头文件里有三套失败报告方式 | **C（已处置 2026-11-04，选 ②）**：三者**统一为「无错误通道」**。矩阵行改标「无错误通道（AC-95 豁免）」，并各自写明失败如何体现：`runtime_wakeup` 返回错误码、`snapshot_release` 返回 `STALE_HANDLE`/`INTERNAL`、`endpoint_count` **`rt` 无效返回 0，与「无端点」不可区分**（需要区分时用带 `err` 的 `endpoint_get` 探测）。AC-95 豁免清单 **6 → 9 个**，同步落点：c-abi §3.2.1 矩阵与 §3.2「豁免」段、requirements AC-95。选 ② 而非 ①：给 `endpoint_count`（`uint32_t` 返回值）加 `err` 会逼所有调用点多一个参数，而它唯一的失败形态「句柄无效」在正确的使用序列里不该出现 |
| **N-10** | B4 | `c-abi.md:860-865` | **`op_id` 的唯一性范围未定义**：`send_cancel` 只拿 `op_id`，但没写它是每 Runtime / 每连接 / 每组唯一，也未写是否回绕复用（对比 `capture_id` 明文「永不复用」、`seq` 明文警告回绕） | 定为「每 Runtime 单调分配、不回绕（耗尽返回 `RESOURCE_EXHAUSTED`）」，并写明 `send_cancel` 对已完成 / 不存在 op 的返回 | **C（已处置 2026-11-04）**：**作用域 = 每 Runtime**；**单调分配、永不回绕**（与 `capture_id` 同口径），耗尽 → `send_async` 返回 `RESOURCE_EXHAUSTED`。`send_cancel` 四态表：未完成且成功取消 → `OK`（`on_done(CANCELLED)` 仍触发一次）；已完成 → `NOT_FOUND`（不再触发）；**已被取消过** → `NOT_FOUND`（幂等失败）；从未在本 Runtime 分配 → `NOT_FOUND`。**跨 Runtime 传入不在契约内**——`send_cancel` 只查目标 Runtime 自己的操作表，行为完全由上表决定，与数值原本属于谁无关（原稿的「属于其它 Runtime → NOT_FOUND」是错的：两边独立从 1 编号必然重号，无法判定归属）。落点：c-abi `send_cancel` 注释、新增 **FR-8.14** + **AC-111**（归 M1） |
| **N-11** | B4 | `c-abi.md:913`；`wire-format.md:104`；`architecture.md:372`；`platform-support.md:222` | **`clock_synced` 永不置位**：三处只声明字段/tag，全文无时间同步机制、无置位规则（PTP 仅在平台支持「待核实」清单）。实质是恒 0 字段 | 二选一：删除该字段与 `CLOCK_SYNCED` tag（载荷不透明、库不提供时间同步）；或保留并在注释中写明「v1 恒 0，保留给 v2 时间同步扩展」 | **C（已处置 2026-11-04，选「保留并写明恒 0」）**：`iocomm_message.clock_synced` 与线格式 `CLOCK_SYNCED` tag **保留，v1 恒发 0**。选保留而非删除的理由：`iocomm_message` 是**库写出的公开结构体**，删字段要动 ABI 布局；保留成本只有一个恒 0 字节。落点：c-abi 字段注释、wire-format §3 tag 行、架构 §6.5 补理由段、新增 **AC-112**（归 M2） |
| **N-14** | B4 | `c-abi.md:414`、`:508`；`requirements.md:74` | **`listen_addr` / `listen_transport` 组合语义不完整**：只写了「`listen_addr` NULL = 不监听」，未规定 transport 非空而 addr 为 NULL、addr 非空而 transport 为 NULL、两者皆空的行为（「inproc 的 `listen_addr` 必填」已规定，不在此列） | 补一张组合表，每格给 `INVALID_ARGUMENT` / 不监听 / `NOT_SUPPORTED` 之一 | **C（已处置 2026-11-04）**：新增 c-abi **§5.1c** 四格表——① 两者皆空 = **纯出站端点（合法）**，`endpoint_local_addr()` → `INVALID_STATE`；② 只填 addr → `INVALID_ARGUMENT`（不猜默认传输）；③ 只填 transport → `INVALID_ARGUMENT`；④ 皆非空 → 按传输校验，**未知传输名 → `NOT_SUPPORTED`（优先于地址格式）**。判定在注册之前，失败不占用名字。落点：新增 **FR-8.13** + **AC-110**（归 M2）、`endpoint_local_addr` 的 `errors` 与矩阵行补 `INVALID_STATE` |

> **N-15（并入 N-01，已随方案 A 处置）**：入站消息进「端点接收队列」还是「连接接收队列」——已在 `c-abi.md` §6.4 定稿：
> 默认进**端点接收队列**；被 `conn_subscribe` / `conn_retain` 单独接管的连接改进入该连接队列，不双投。

### 8.4 N-01 / N-02 的裁决方案

> **裁决结果（2026-11-03）：采用方案 A**，已落到 `requirements.md`（FR-8.6 / 8.8 / 8.11、AC-30 / 33 / 39 / 75 / 103 / 104）、
> `c-abi.md`（§5.2 / §6.1 / §6.3 / §6.4）、`architecture.md`（§5.2 + M2 里程碑）、`ADR-002`（决策 3 修订注）、`README.md`。
> 下表三方案保留作决策记录；**下面「裁决后必须同步的位置」除 AC-32 外已全部执行**——AC-32 未改动。
>
> ⚠️ **2026-11-05 更正**：本段原文曾写「AC-32 未改动，因为端点级订阅成立后 `endpoint_recv(ep)` 与
> `endpoint_accept(ep)` 的互斥由既有 §6.4 规则继续覆盖，无需改写」。**该免责不成立**——§6.4 全文从未提到
> `endpoint_accept`（已 grep 确认），而矩阵把二者写进同一错误码行是 `95c8fa6` 引入的**错误**，不是设计。
> 二者实为**正交的两条轴**（见 [§9 N-37](#9-2026-11-05-用户清单核实n-36--n-52)）。原「互斥」结论已废止，
> AC-104 的末位断言同步删除、新增 AC-117 锁定正交性（N-51）。

| 方案 | 内容 | 优点 | 代价 |
|---|---|---|---|
| **A（推荐）入站连接归监听端点** | 删除「入站连接不参与端点扇出」，改为「入站连接归属于监听它的端点」；`endpoint_send` 目标 = 端点全部已建立连接（入站 + `ep_owner == ep` 出站）；入站连接的 `conn_send` 用端点共享发送队列；`endpoint_recv` / `iocomm_subscribe` 随之成立 | 服务端扇出可用；与 `architecture.md:225`、`c-abi.md:677/920` 一致；FR-6.8 / AC-30 / AC-32 不需重写；符合「端点 = 监听者」直觉；与 `endpoint_destroy` 第 2 条（入站连接随端点 FIN）自然衔接 | 入站 peer 与出站连接共享端点队列（§6.1「代价一」已覆盖）；须新增端点级订阅的 FR + AC（当前零覆盖）；AC-30 的 N 需定义为「入站 + 归属出站」 |
| B 维持「不归属」，扇出只到出站 | 保留 §6.1 现有队列模型；把 `c-abi.md:677`、`:841`、`architecture.md:225` 改成「所有归属该端点的出站连接」；服务端扇出改为 `conn_count(ep)` + 逐条 `conn_send`。端点级 `recv/subscribe` 必须删除，或另定为「未注册 accept 时由库自动接受并持有」 | 不动已有队列决策；实现最简单 | 与「端点 = 监听者」直觉相反；服务端无法用一条 API 广播；FR-6.8 / AC-32 需重写或删除；`architecture.md:225` / `c-abi.md:920` 须改；并存两套所有权规则 |
| C 分离「队列归属」与「扇出成员资格」 | 入站连接不占端点队列，但计入端点扇出 | 看似最小改动 | **不自洽**：共享队列模型下 `endpoint_send` 必须把项放进端点队列，成员不在该队列就无法扇出；若改为放进各自队列，则「共享队列 + 队列项带目标连接」模型失效。**不推荐** |

> **裁决后必须同步的位置**（按方案 A）：`c-abi.md` §5.2 发送目标表、§6.1 队列归属规则、§6.3 `iocomm_subscribe` / `endpoint_recv` 注释；
> `architecture.md` §5.2 对象模型表与借用语义段；`requirements.md` AC-30（N 定义）、AC-33、AC-39（过滤口径）、AC-32（端点级互斥）；
> 新增端点级订阅的 FR + AC；`README.md` 第 3 步注释。

### 8.4b N-03 的裁决方案

> **裁决结果（2026-11-03）：采用方案 ①（交付时点 = 双向 HELLO 完成后）**。与预设倾向一致。
> 落点见 §8.1 N-03 行「状态」栏。下表保留作决策记录。

| 方案 | 内容 | 优点 | 代价 |
|---|---|---|---|
| **① 双向 HELLO 后交付（采用）** | `accept` 回调在双方都收到合法 `HELLO` 后触发；握手期连接为内部会话（无 conn 句柄、不占 `max_handles`、不参与 `conn_count`/扇出）；`peer_node_id` 必有真实值；握手失败/超时不产生回调 | 与借用语义自洽（借出的是**可用**连接）；README 主推的「回调内 `CLOSE_AFTER` 发首条」天然合法；`peer_node_id` 取值可无条件承诺；`max_handles` 只计应用可见句柄，口径干净；应用只被通知「可用连接」，无「半可用」窗口 | 握手期需一个**内部会话**结构（不等同于 `iocomm_conn_t`）；`max_handles` 口径从「accept 分配即计入」改为「交付时计入」；`endpoint_destroy` 需额外说明「握手期会话一并 FIN、不回调」 |
| ② TCP 建立即交付 | 接受 socket 即回调；`peer_node_id` 允许 0；规定握手完成前禁止发 DATA（含 `CLOSE_AFTER`） | 回调更早，理论上可做「连接准入过滤」 | **准入过滤不成立**：`accept` 回调没有接受/拒绝返回值，拒绝只能靠回调内 `conn_destroy`，而握手期本就无数据可判；**「回调内发首条」被禁用**，README 主推写法回到「先缓冲、握手后再发」的复杂语义，且需定义 `send_async` 在握手期的缓冲/失败规则；`peer_node_id` 恒可能为 0，现场排障时「谁连进来了」无法第一时间回答；借用语义下借出一条「尚不能发」的连接，应用必须自行处理握手态 |

**否掉方案 ② 的核心理由**：它把「连接建立」与「连接可用」拆成两个应用可见的时点，却没有给应用任何观测二者差别的机制（无握手完成回调、无「握手态」条件位），于是「回调内发数据」要么被静默缓冲（无法区分已发/在缓冲），要么被禁止。方案 ① 让「交付 = 可用」成为不变量，代价只是一个不占句柄名额的内部会话，小于方案 ② 引入的语义分叉。

### 8.5 建议处置顺序

1. **N-01 / N-02 / N-15**（同根因，阻断）——**已处置（方案 A，提交 95c8fa6）**。
2. **N-03**（M2 线格式冻结前）——**已处置（方案 ①，双向 HELLO 后交付，提交 e0d266b）**；同批顺带定义了出站 `connect*` 的返回时点与握手期内部会话上限。
3. **N-04 / N-05 / N-06 / N-07 / N-12**（M3/M4 前）——**已处置（2026-11-04）**：N-04 只读场景改为「显式 `node_id`」、N-05 补 §5.2a 地址解析 + FR-8.12、N-06 四项重连语义定案 + AC-105、N-07 默认值写死、N-12 套接字参数尾部追加 + FR-4.8/AC-106。
4. **N-08 / N-09 / N-10 / N-11 / N-13 / N-14**（可随对应文档批次顺带修）——**已处置（2026-11-04）**：N-08 手动驱动语义 + AC-109、N-09 三个无 `err` 函数统一为「无错误通道」、N-10 `op_id` 每 Runtime 不回绕 + AC-111、N-11 `clock_synced` 恒 0 + AC-112、N-13 本机注册表单元文件机制（架构 §6.4b）、N-14 listen 组合表 + AC-110。
5. **N-16 / N-17**（本轮新增，2026-11-04 已处置，见 §8.6）——不占用上面 15 条的计数。
6. **N-18 / N-19**（2026-11-04 复审新发现，已定口径、随本批落文档，见 §8.7）。
7. **N-20 ～ N-35**（2026-11-05 收口核实，见 §8.8）——**已处置（2026-11-05，提交 `39d7ad2`）**：N-20 ～ N-25 六项口径按 §8.8a 裁决落笔、N-26 ～ N-33 直接落笔、N-34 改验收观测通道、N-35 仅登记不落笔；新增 AC-114 / AC-115 / AC-116。
8. **N-36 ～ N-52**（2026-11-05 用户清单核实，见 [§9](#9-2026-11-05-用户清单核实n-36--n-52)）——**已落笔（2026-11-05）**：
   N-36 ～ N-41 / N-49 ～ N-52 契约缺陷、N-42 ～ N-45 取舍声明，均已按裁决落文档；**N-46 / N-47 于 2026-11-09 裁决并落笔，N-48 于 2026-11-10 裁决并落笔（端口块迁至 `23100..23200`）**（见 §9.4）。

### 8.6 2026-11-04 新增核实（N-16 / N-17）

> 本轮处置 N-04 等 5 条时新发现的缺口；**不计入 §8 开头的 15 条**。

| ID | 严重度 | 位置 | 问题摘要 | 建议处置 | 状态 |
|---|---|---|---|---|---|
| **N-16** | **B2** | `architecture.md` §6.4；`c-abi.md` §5.1 `ICOMM_ENDPOINT_UNIQUE` / §3.2.1；`requirements.md` FR-1.4 / AC-89 | **跨进程同名端点存在两套互斥语义**：FR-1.4（P0）规定「重名注册被拒绝」，但架构 §6.4 对非 `UNIQUE` 端点规定「`OK`，自动以 `<name>#<pid>` 注册」，AC-89 还把该行为固化为验收项。自动改名出来的名字是远端**无法预测**的寻址身份，`connect_node` 按名字精确匹配时可能连到错误进程；「第二实例可被发现」的初衷也未实现 | 改为 fail-fast，删除 UNIQUE 标志 | **C（已处置 2026-11-04）**：**推翻** 2026-10-22 的「允许第二实例 + 自动改名」，改为 fail-fast——跨进程同名 → `CONFLICT` 且**不注册**；同进程同名仍 `ALREADY_EXISTS`。删除 `ICOMM_ENDPOINT_UNIQUE` 宏，`endpoint_config.flags` 改为 v1 保留字段（非 0 位 → `INVALID_ARGUMENT`）；保留 `endpoint_name_state()` 三态查询（仅注册前探测/诊断，权威是 `create()` 返回值）。落点：架构 §6.4 三态表、c-abi §5.1 / §3.2 / §3.2.1 / §10、requirements FR-1.4 / FR-1.5 / AC-89 / §6 演进记录、D-05 追加推翻说明。**决策依据与行业对照见 [ADR-003](adr/ADR-003-endpoint-name-uniqueness.md)** |
| **N-17** | **B2** | `c-abi.md` §5.1 `endpoint_config.name`；§7 `iocomm_endpoint_info.name_len`；`requirements.md` FR-1 | **端点名无长度上限、无字符约束**（只写「可带 '/' 分层，UTF-8」）。而**线格式** `ENDPOINTS` 的 `name_len` 是 `u16`（C 结构体 `iocomm_endpoint_info.name_len` 为 `uint64_t`）、发现报文单包 ≤ 1400 B 按条目分页，名字长度不定会让「条目上限 / 分页」不可计算，且空名、含 NUL、非法 UTF-8、空段（`//`、首尾 `/`）的行为未定义 | 见 c-abi §5.1a 与 FR-1.8 | **C（已处置 2026-11-04）**：新增 **FR-1.8**（P0）+ **AC-108**（归 M1）与 c-abi §5.1a——UTF-8 编码后 **1–255 B**、不得含 NUL、必须合法 UTF-8、`/` 层级不得有空段；违反 → `INVALID_ARGUMENT`。写明 255 B 与 `name_len(u16)`、1400 B 分页的关系（单条端点条目远小于 1400 B）。名字按**字节**比较，不做 Unicode 归一化 / 大小写折叠 |

### 8.7 2026-11-04 复审新发现（N-18 / N-19）

> 本轮处置 N-08 等 6 条时，回顾 §8.1 的 N-03 落点发现的**两条遗留**——它们不是新缺口，
> 而是 N-03「握手期内部会话不占 `max_handles`」这条规定的**推导后果**此前没写全。
> 二者随本批落文档，**不占用** §8 开头的 15 条计数，也不占用 §8.6 的 2 条。

| ID | 严重度 | 位置 | 问题摘要 | 建议处置 | 状态 |
|---|---|---|---|---|---|
| **N-18** | B3 | `c-abi.md` §6.0 `max_handles` 行；「握手期内部会话的上限」段 | **握手期会话的「聚合上限」逻辑不成立**：N-03 的原文写「每端点并发握手会话数 ≤ `max_handles`（独立计数器）」，理由是「防止 5000 ms 握手窗口内 fd 耗尽」。但若按「每端点独立计数」，**总量是 `端点数 × max_handles`**（默认 4096 × 4096 ≈ 1.7e7）——这既不是「防 fd 耗尽」（远超任何实际 fd 上限），也不是「保护端点名额」（已由独立计数器实现）。原句把两种保护混为一谈 | 保留「每端点独立计数」的**局部保护**含义（防止单端点被半开会话淹没），删掉「防 fd 耗尽」的错标；明写「聚合上界 = 端点数 × `max_handles`，是软上界，全局 fd 仍由 `ulimit -n` / 系统上限兜底」；全局旋钮若需要，v1.1 尾部追加到 `runtime_config` | **C（口径已定 2026-11-04，随本批落文档）**：保留每端点独立计数；**删去「防止 fd 耗尽」的表述**；明写聚合上界 = `端点数 × max_handles` 是**软上界**，全局 fd 由部署侧兜底；被拒 socket 的可见性**只靠 `log_fn` WARN**（含端点名、当前会话数、上限），不新增计数（保留 `protocol_errors` / `queue_dropped` 的唯一含义）。若将来要全局上限，属 v1.1 尾部追加，不改既有布局 |
| **N-19** | B3 | `c-abi.md` §5.2 `iocomm_accept_fn` 交付时点；§6.0「握手期内部会话的上限」 | **交付时句柄表已满的分支未定义**：N-03 规定「双向 HELLO 完成后 `accept` 分配 conn 句柄时才占用 `max_handles`」，但**没有**规定「HELLO 已完成、句柄表已满」时怎么办。可能的实现有「排队等句柄」「拒绝并 FIN」「回 ERROR 帧」三种，后果差异极大（前者长期占 fd，后者在客户端看起来像网络故障） | 定一个分支：**不交付、不回调、立即 FIN**，写 `log_fn` ERROR；不计入 `protocol_errors` / `queue_dropped`；与握手表满同口径；补一条 AC | **C（口径已定 2026-11-04，随本批落文档）**：**不交付、不触发 `accept`、立即 FIN 关闭**（不留内部会话，避免长期占 fd），并写 `log_fn` ERROR（含端点名与对端地址）；**不**计入 `protocol_errors` / `queue_dropped`（与握手表满同口径）。拒绝「排队等句柄」的理由：会无限期占用一条已可用的 socket，且在资源紧张时放大问题。落点：c-abi §5.2 `accept` 注释 / §6.0 新增一段；FR-8.5 补一句；新增 **AC-113**（归 **M2**——需 TCP + HELLO，M1 只有 inproc） |

### 8.8 2026-11-05 收口核实与裁决（N-20 ～ N-35）

> **来源**：对 M0 冻结前的全库残留核对——5 路只读 agent 交叉核实 + 主会话逐条回原文复核。
> **它不是新审计**：N-20/N-21/N-24/N-25/N-27/N-28/N-31 是**历史审计报了、但从未进本清单**因而没人跟进的条目；
> N-22/N-23/N-26/N-29/N-30/N-32/N-33 是本批（2026-11-03 / 11-04 两次改动）**引入或未跟改**的。
> 不占用 §8 开头的 15 条、§8.6 的 2 条、§8.7 的 2 条。
>
> **判定口径**：每条都做了「试图推翻」，推不翻才记。要求「先定口径再改文档」的六项（N-20 ～ N-25）**裁决在本文给出**，
> 各文档只负责照此落笔——改动方不得在落笔时另立口径。

#### 8.8a 需要先定口径的六项（裁决已给出）

| ID | 严重度 | 位置 | 问题摘要 | 裁决（**唯一口径，落笔方照此执行**） |
|---|---|---|---|---|
| **N-20** | **B1** | `c-abi.md:15`、`:280`、`:932`、`:939`、`:942`、`:949`；`architecture.md:178`；`requirements.md:368`（AC-113）、`:339`（AC-84） | **「六类句柄」口径自相矛盾**：`§1:15` 与 `architecture:178` 把 Runtime 计入六类；`§6.0:932` 写「六类合计，**不含 Runtime 自身**」——排除后只剩五类。AC-113 依赖「Runtime 不占名额」（`max_handles=3` 时端点+订阅=2、conn 余 1）；AC-84 也依赖「`max_handles=1` 时第一次 create 成功」 | **Runtime 句柄是句柄表的「主人」、不占 `max_handles`**；计入名额的是**五类对象句柄**：endpoint / conn / subscription / snapshot / monitor。① `c-abi.md:15`：保留「六类对象共用同一张表」的**查找**表述，补一句「Runtime 是表的主人，**不占 `max_handles`**」；② 凡 `max_handles` 处的「六类」一律改为 **「五类对象句柄」** 并明示排除 Runtime（`:280`/`:932`/`:939`/`:942`/`:949`）；③ `architecture.md:178` 同改；④ AC-113 的「六类句柄合计——端点、订阅、conn 各占 1」改为「五类对象句柄合计（Runtime 不占）——端点、订阅、conn 各占 1」；AC-84 补一句「Runtime 不占名额，故 `max_handles=1` 时首个 `endpoint_create` 成功」。**理由**：Runtime 在 `max_handles` 生效时必然已存在；把它计入等于所有部署隐形减 1，且与 AC-84 的既有验收直接冲突。 |
| **N-21** | **B1** | `c-abi.md:168`（矩阵）vs `:314`（状态机） | **Stopped 下写操作的返回码冲突**，且范围比分看到的更大：矩阵把 `stop`/`drain` 也归入「Stopped 下 `start` 以外的写操作」→ `INVALID_STATE`，而状态机明写 `stop` 幂等、`drain` 合法；状态机对写操作给 `ICOMM_ERR_CLOSED`。两处都自称「唯一权威」。 | **Stopped 下的返回码统一为 `ICOMM_ERR_CLOSED`**（语义：该 Runtime 已停止接受写）。① 改 `c-abi.md:168` 矩阵行：拆成两行——`runtime_start`/`runtime_stop`/`runtime_drain` 一行（错误码去掉 `INVALID_STATE`，`stop`/`drain` 在 Stopped 下合法，`start` 见 N-22）；**新增一行**「Stopped 下的其余写操作（`endpoint_create`/`connect*`/`subscribe`/`*_send*`/`discovery_start`/`monitor_open` 等）」→ `CLOSED`；② `runtime_reconfigure` 行已是 `CLOSED`（`:170`），保持不变；③ 状态机 `:314` 原文保留为权威。**理由**：`CLOSED` 的枚举语义就是「对象已关闭」，`INVALID_STATE` 是「参数/状态组合非法」——把「Runtime 已停」说成后者，会让调用方误以为是自己的调用顺序错了。 |
| **N-22** | B2 | `c-abi.md:308`（状态图）、`:317`（`start` 幂等）vs `:168`（矩阵措辞「`start` 以外」） | **Stopped 能否重新 `start` 未定义**：状态图只有 Created→Running→Stopped→销毁，无回边；`:317` 只说「`start`/`stop` 均幂等」，「幂等」通常指同状态重复调用返回 `OK`（暗示可回 Running），但未写。矩阵措辞反推 `start` 在 Stopped 下可调用。 | **不允许从 Stopped 回到 Running**。① 状态图保持单向前进（`Created→Running→Stopped→销毁`）；② `:317` 改为「`start` 在 Running 上重复调用返回 `ICOMM_OK`（幂等）；在 Stopped 上调用返回 **`ICOMM_ERR_CLOSED`**（stopped 不可重启，恢复需重建 Runtime）」；③ `c-abi.md:168` 矩阵 `runtime_start` 的 `INVALID_STATE` 措辞改为 `CLOSED`（与 N-21 一致）。**理由**：v1 的生命周期是「一次创建、一次使用、销毁」；允许重启就要定义「重启时已登记的 `on_done`、已入队的消息、已建立的连接、发现的租约」怎么办，这是一整张状态矩阵，收益远大于成本。需要重启的服务应重建 Runtime（`destroy` + `create`），语义无歧义。 |
| **N-23** | B2 | `wire-format.md:69`（`FRAME_TOO_LARGE` 行「`DROPPED(TOO_LARGE)` + 计数」）、`:65`（`protocol_errors` 口径）、`:31`（§1 上限）；`c-abi.md:1442`/`:1447` | **入站超限帧的计数归属未定**：本端**发** `ERROR(FRAME_TOO_LARGE)` 时，是否计入 `protocol_errors`？是否计入 `queue_dropped`？`queue_dropped` 的值定义只有「每次丢弃/拒绝都计入」（`:1025` 专指 `ERROR` 溢出策略）与几处「不计入」（`:945`/`:948`）——全局定义空白。 | **计数规则（唯一口径）**：① `protocol_errors` **只计接收侧**（收到 `ERROR` 或判定帧损坏），**本端因超限/畸形而发出 `ERROR` 不计**——与 §2.1 既有口径一致，不新增例外；② **入站超限 / 畸形帧一律计入 `queue_dropped`**（它是「未被接收的入站数据」计数，与溢出丢弃同属「收到但没交付」）；③ **`queue_dropped` 的值定义写入 §8：该 Runtime 内「入队失败 / 被策略丢弃 / 入站帧被判超限或畸形」的累计条数**，运行期事件都计、调用方编程错误（`TOO_LARGE` 发送侧、句柄无效）不计；④ `wire-format.md:69` 的「`DROPPED(TOO_LARGE)` + 计数」改为「`DROPPED(TOO_LARGE)` + `queue_dropped++`」，并注明 `protocol_errors` 不计；⑤ `c-abi.md:1025` 的「每次丢弃/拒绝」收窄为「本表所列的运行期丢弃/拒绝」。**理由**：`N-18`/`N-19` 已确立「本地资源保护不计入这两个计数」，此处不要动摇它——超限/畸形是**从线路上收到的**，与「本地拒绝连接」性质不同。 |
| **N-24** | B2 | `c-abi.md:697`（accept 回调「什么都不做 → 自动收回」）、`:905-908`（所有权段）、`:1197`（未注册 accept 时由端点级订阅持有）；`requirements.md:137`（FR-8.8）、`:286`（AC-33）、`:359`（AC-104） | **监听端点「既未注册 `endpoint_accept`、也未启用端点级订阅/`endpoint_recv`」时，交付时点的入站连接归谁**——所有持有/回收判据都以其中一个为前提，这对「两者皆无」无定义。 | **交付即回收**：该端点接入的入站连接在双向 HELLO 完成后**立即以 FIN 关闭**，不产生 `accept` 回调，不产生任何监控记录/计数（与「回调返回未表态 = 拒绝」同口径），写 `log_fn` 的 **WARN**（含端点名）。① `c-abi.md` §5.2 所有权段补一条；② `requirements.md` FR-8.8 补「端点既无 accept 回调、也无端点级订阅/拉取时，入站连接在交付时即关闭」；③ 新增 **AC-114**（见 8.8b）。**理由**：没有应用侧消费者时，把连接留成「无人拥有的存活连接」= 泄漏；`CLOSE_AFTER` 不是持有动作（§6.1）也说明「连接必须有明确消费者」。**否决方案**：「由库隐式持有直到有人订阅」——这会让 `conn_count(ep)` 随对端行为无限增长，且与「unsubscribe 之后连接怎么办」连锁出一整张矩阵。 |
| **N-25** | B3 | `architecture.md:208-211`（共用 `state_dir`）；`c-abi.md:260-265`（`node_id` 自动模式） | **两个 Runtime 共用同一可写 `state_dir`** 会读到同一 `node_id`，文档只说「配置错误、库不检测」，且同一段既写「后创建者**会**共享同一 NodeId」（确定性后果）又写「**共用目录属未定义行为**」——自相矛盾，且无任何检测/报错/缓解（N-04 只兜住 `state_dir` 为空/不可写）。 | **检出即拒绝**：自动模式（`node_id == 0`）下，`runtime_create` 在 `state_dir` 内**用独占创建**占住属主标记文件 `<state_dir>/iocomm.owner`（**与持久化 NodeId 的 `iocomm.nodeid` 分开**——前者每次创建都要反映当前属主、后者须跨重启不变，合并会让「重启后仍判旧 pid 存活」）；若文件已存在且**其属主标记指向另一个仍存活的进程**（文件内记 `<node_id>` + `<pid>` + 启动时间），返回 **`ICOMM_ERR_CONFLICT`**（`message` 指明「state_dir 已被另一进程使用」）。① `architecture.md:208-211` 把「未定义行为」改为「检出即 `CONFLICT`」；② `c-abi.md` 的 `node_id` 注释补该分支；③ `requirements.md` FR-9.2 补口径；④ 新增 **AC-115**（见 8.8b）。**理由**：`CONFLICT` 已是「名字被别的进程占用」的既有语义（§6.4），复用它比发明新码好；「未定义行为」在多租户现场是最坏的答案——故障现场无从判断。代价是一次 `O_EXCL` 创建 + 存活探测，发生在 `runtime_create` 一次。**否决方案**：派生每进程子目录——那会让「重启后 `node_id` 稳定」失效（子目录名含 pid）。 |

#### 8.8b 其余八项 + 两项收尾发现（口径唯一，直接落笔）

| ID | 严重度 | 位置 | 问题摘要 | 落笔要求 |
|---|---|---|---|---|
| **N-26** | B1 | `c-abi.md:1070` vs `:1073-1074`；`requirements.md:328`（AC-73）、`:337`（AC-82）、`:347`（AC-92⑤） | **`TOO_LARGE` 的报告通道自相矛盾**：CLOSE_AFTER 段相邻两行——`:1070` 写「入队前失败（`TOO_LARGE`）→ 同**同步返回**报告」，`:1073-1074` 写「`accept` 回调内用 CLOSE_AFTER 时，上述**任何**失败路径……**`on_done` 先报失败码**」。AC-73 仍写「异步经 `on_done(TOO_LARGE)`」（旧口径），AC-82/AC-92⑤ 措辞含糊 | ① `c-abi.md:1073-1074` 改为「`accept` 回调内用 CLOSE_AFTER 时：**入队前的失败仍走同步返回**（该连接随后关闭，因为回调返回后无人持有）；入队后的失败（被丢弃/超时）走 `on_done`」；② AC-73 改为「异步**同步返回** `TOO_LARGE` 且不入队、**不触发 `on_done`**」（与 AC-78 对齐）；③ AC-82 改为「返回 `TOO_LARGE`（同步，与 tcp 同口径，无 `on_done`）」；④ AC-92⑤ 改为「A 侧**同步返回** `TOO_LARGE`（无 `on_done`）」 |
| **N-27** | B2 | `requirements.md:165`（FR-10.3）vs `c-abi.md:1684`（§9.3） | FR-10.3 把 `too_large` 列为「丢弃必带原因」，但 §9.3 明写「**发送侧**超限不产生 DROPPED」（只有**接收侧**超限产生 `DROPPED(TOO_LARGE)`） | FR-10.3 的 `too_large` 加括注：「**仅接收侧**（入站帧超限）；发送侧超限走返回值，不产生 `DROPPED`」 |
| **N-28** | B2 | `c-abi.md:171`（矩阵）vs `:421-432`（原型） | `iocomm_runtime_node_id` / `node_name` 合成一行，列了 `INVALID_ARGUMENT`（`buf` 为 NULL）与 `RESOURCE_EXHAUSTED`（缓冲不足）——`node_id` **没有 buf 参数**，这两个码对它不可达 | 拆成两行：`node_id` → `STALE_HANDLE`、`INVALID_ARGUMENT`（`out_node_id` 为 NULL，按 §3.2 通用出参规则）、`INTERNAL`；`node_name` → `STALE_HANDLE`、`INVALID_ARGUMENT`（`buf`/`out_len` 为 NULL）、`RESOURCE_EXHAUSTED`（缓冲不足，`out_len` 给所需长度）、`INTERNAL` |
| **N-29** | B2 | `c-abi.md:326`（`runtime_start`/`stop` 无注释）；`:168`（矩阵列 `TIMEOUT`） | `iocomm_runtime_stop(rt, timeout_ms)` 超时后的**返回值**与**是否已停止**均未定义 | 在 `:326` 前补注释：「`runtime_stop(timeout_ms)` 等待在途操作完成至多 `timeout_ms` 后**返回**；超时返回 `ICOMM_ERR_TIMEOUT` 且 **Runtime 已进入 Stopped**（不再接受新写）。**在途操作不被取消**——与 `runtime_destroy` 不同，见 §5.2 的取消表：已登记的 `on_done` 仍会在 `run_once` / IO 线程上触发，manual 模式须继续驱动 loop 排空（AC-116④ 的前提）。`timeout_ms = 0` = 不等待，立即进入 Stopped」。矩阵行保留 `TIMEOUT`。**（2026-11-05 更正：原裁决写「按 `destroy` 同口径逐条 `CANCELLED`」，与 §5.2「`runtime_stop` 不终止在途操作」直接冲突——以 §5.2 为准，`CANCELLED` 只属 `runtime_destroy` / `endpoint_destroy` / `conn_destroy` 路径）** |
| **N-30** | B2 | `architecture.md:413`（Windows 名字锁 `Global\`）；`platform-support.md`（无回退说明） | `Global\iocomm_<hash>` 需 `SeCreateGlobalPrivilege`（默认仅管理员/服务账户持有），普通用户进程创建失败；文档未说明回退或特权要求 | 架构 §6.4 Windows 行改为：「优先 `Global\`（跨会话可见）；创建失败（权限不足）时回退 `Local\`（同会话可见，同机跨会话的端点名唯一性不保证），并在 `log_fn` 写 WARN」。`platform-support.md` 平台差异表补一行说明。**理由**：`Local\` 已覆盖「多个服务在同一会话」这一主场景；跨会话唯一性要求属于部署选择，不该让普通用户进程建不了端点 |
| **N-31** | B2 | `c-abi.md:1032` | 「队列满 + `DROP_OLDEST` / `DROP_NEWEST` → 消息**曾被接受又丢弃** → `QUEUE_FULL`」——对 `DROP_NEWEST` **与事实相反**（新消息从未被接受） | 改为「`DROP_OLDEST`：旧项曾被接受、后被挤出 → `QUEUE_FULL`；`DROP_NEWEST`：**新消息从未被接受** → 仍记 `QUEUE_FULL`（理由：按**策略**分界而非方向，见 §6.1；实现者不要因‘未被接受’改记为 `BACKPRESSURE`）」 |
| **N-32** | B2 | `c-abi.md:221`、`:931`（`max_message_size` 下限） | 只规定「小于**帧头**（20 B）→ `INVALID_ARGUMENT`」，但必填 TLV 使**最小可用整帧为 56 B**（`20 + 36`）；配 20–55 B 合法却让**所有 `DATA` 必然 `TOO_LARGE`** | 下限改为 **56 B**（`20` 头 + `SEQ`/`TS_SEND`/`SOURCE_NODE` 三项必填 TLV 共 36 B），并注明「低于此值则任何 `DATA` 帧都无法通过校验」。`c-abi.md:221` 的举例与 `§9.3` 同步 |
| **N-33** | B2 | `c-abi.md:1334`（`node_info.endpoints` 注释）、`:1341-1345`（`iocomm_discovery_event`）；`:1258`（`@lifetime`） | `node_info.endpoints` 注释写「指针有效至下次快照失效」（只对快照路径成立），但 `iocomm_discovery_event` 内嵌 `node_info` 时生命周期只能是「仅本次回调」；`discovery_event` / `node_info` 均无 `size` 字段，字节演进方式未定义 | ① `endpoints` 注释改为「快照路径：有效至 `snapshot_release`；`discovery_event` 路径：**仅本次回调**（见 `@lifetime`）」；② `iocomm_discovery_event` 补注释「生命周期仅本次回调；字节演进只做尾部追加，本结构体**不带 `size`**（v1 不承诺跨版本二进制兼容，宿主须用 `abi_version` 协商）」 |
| **N-34** | B3 | `requirements.md:341`（AC-86）vs `api/wire-format.md:63`/`:74-75`（收到 `ERROR` 必关连接） | **AC-86 的「注入一次 `ERROR` 帧后 `healthy` 变 `FALSE`」不可可靠观测**：`ERROR` 是终止性帧——发出方必须关连接，接收方进入「终止中」后也关闭。连接一关，`conn_status` 要么句柄失效，要么（出站自动重连）进入 `Reconnecting` 而按 AC-105 报 `UNKNOWN`，`FALSE` 只是一瞬间的中间态，测不稳。 | **改测推送而非拉取**：AC-86 该子项改为「注入 `ERROR` 帧后，`iocomm_condition_fn` **至少推送一次** `healthy = FALSE`（发生在连接关闭前的同一回调序列内）；随后连接断开按 FR-4.4 处理」。理由：`healthy` 的语义是「本判定窗口内收到过 `ERROR`」，窗口在连接生命周期内就要用得上，只有推送通道能在关闭前捕获它。 |
| **N-35** | B4 | `IoComm/README.md:170` | 许可证一栏写「待定。」——这是**真实的未决项**，但未登记进本清单，状态盘点会漏。 | **不阻塞当前阶段**（2026-11-09 更新）。已确认：仓库 **private**、**单人负责**、未发布 crates.io、未对外交付、无第三方源码内嵌 ⇒ 三个「后补成本失控」的触发条件（外部贡献者 / 对外分发 / 引入 copyleft 代码）**均未发生**，此时定与写代码后再定成本相同（约 10 分钟，机械替换）。**故维持「待负责人决策」，但从 P1 降为 P3。**<br>**改在下列任一事件发生之前必须定**（写进此条即为触发条件）：① 第一个**外部贡献者**提交 PR 之前（版权将不再单人独占，改许可证需每个贡献者同意）；② 第一次**对外交付 / 发布 crates.io / 装进设备**之前；③ 第一次把**第三方源码**复制进仓库之前（copyleft 传染会反向锁死选择）。<br>**落点三处**（届时同步）：`README.md` 许可证节、各 `Cargo.toml` 的 `license` 字段、仓库根 `LICENSE` 文件。<br>**依赖侧已核实无约束**：`mio` = MIT、`socket2` = MIT OR Apache-2.0（crates.io 元数据实测），均为宽松许可，不传染出站选择。 |

**新增验收项**（8.8a 三项裁决各需一条可构造的用例，归 **M1**：AC-114 用 inproc、AC-115 只用文件系统、AC-116 只需一个 Runtime）：

| 编号 | 归属 | 验收内容 | 覆盖 |
|---|---|---|---|
| **AC-114** | M1（inproc 可构造） | **无消费者端点的入站连接（N-24）**：端点 A 只 `create`，**不注册** `endpoint_accept`、也不启用 `iocomm_subscribe(ep)` / `endpoint_recv(ep)`。对端 `connect` 成功后：① 对端观测到优雅 FIN（`recv` 返回 0）而非 RST；② `conn_count(A) == 0`；③ `log_fn` 出现一条含端点名的 WARN；④ `stats.protocol_errors` 与 `queue_dropped` 均不递增。对照组：同一端点在 `connect` 前调 `iocomm_subscribe(ep)` → 连接存活、消息正常投递、`conn_count(A) == 1` | FR-8.8 |
| **AC-115** | M1（文件系统可构造，不需网络） | **共用 `state_dir`（N-25）**：进程 P1 以 `node_id = 0` + 可写 `state_dir = D` 创建 Runtime → `OK`；同机进程 P2 用**同一** `D`、`node_id = 0` 创建 → **`CONFLICT`**，`message` 含 `D`；P2 改用显式 `node_id` 或另一个 `state_dir` → `OK`。对照组：P1 退出（`destroy`）后 P2 用同一 `D` 重新创建 → `OK`（存活探测随进程结束而失效） | FR-9.2 |
| **AC-116** | M1 | **Stopped 后不可重启（N-22）+ 写操作返回码（N-21）**：`stop` 后：① 对同一 Runtime 调 `runtime_start` → `ICOMM_ERR_CLOSED`；② `endpoint_create` / `iocomm_subscribe` / `conn_send` 各返回 `ICOMM_ERR_CLOSED`（**不是** `INVALID_STATE`）；③ `stop` 重复调用返回 `ICOMM_OK`（幂等）、`drain` 合法；④ `run_once` / `run_for` 仍可调用（用于排空）；⑤ `destroy` 后重建 Runtime 一切正常 | FR-6.5 / FR-8.1 |

---

## 9. 2026-11-05 用户清单核实（N-36 ～ N-52）

> **来源**：用户提供的三张盲点表（监控边界 / 线程安全 / per-connection 指标；单线程投递 / 连接集合事件；多通信域）+ 四条契约对齐项。
> 主会话逐条回原文核实后，删去 3 条**不成立**的条目（见 §9.1），其余分派 **4 路只读调研 agent**
> （监控可观测性 / 单线程投递与事件 / 多域隔离 / 契约对齐）深入调查，报告在 `.tmp_research/iocomm-gaps-2026-11-05/`：
> `monitoring.md`、`post-and-events.md`、`domain-isolation.md`、`contract-alignment.md`。
> **行号对应 2026-11-05 版本（HEAD `39d7ad2`），后续改动会漂移。**
>
> **与 §8 的区别**：§8 是「文档内部自相矛盾」，本节多数是「**文档没写**」——前者改错，后者补缺，两者都要在 M0 冻结前落笔。
> 不占用 §8 开头的 15 条、§8.6 的 2 条、§8.7 的 2 条、§8.8 的 16 条计数。
>
> **编号顺序**：按「可落笔 → 需讨论 → 待拍板」排，不按严重度排。**N-36 ～ N-41 是第一批（B1，纯对齐）**，
> N-42 ～ N-45 是第二批（B2，补声明），N-46 ～ N-48 是第三批（须拍板）。

### 9.1 已驳回（不成立，勿重复提）

| 原提法 | 驳回理由 |
|---|---|
| `iocomm_monitor_config` 同时设 `ep` 与 `conn` 未定义 | **已定义**：`c-abi.md:1733-1734` 明写「`ep` 与 `conn` 同时非 0 … 均返回 `INVALID_ARGUMENT`」。§9.0b 管的是「多个 monitor 作用域重叠」，不是同一 monitor 的两个字段 |
| N-08 `run_for` 语义空白 / 工业单线程用法模糊 | **已处置（2026-11-04）**：`c-abi.md:413-419` 写死「循环 `run_once`、`duration_ms == 0` 空操作、从不返回 `TIMEOUT`、单调时钟累计」，且有 AC-109。同类误判适用于 N-09 / N-10 / N-11 / N-13 / N-14——六条均已于 §8.5 第 4 条处置 |
| 「`monitor_poll` 是唯一明确允许从任意线程阻塞等待的入口」 | **与事实相反**：`architecture.md:133` 把 `monitor_poll` 列为「**否**（同一 monitor 单线程串行；SPSC 消费端）」；而 `conn_recv` / `endpoint_recv` 带 `WOULD_DEADLOCK`（`c-abi.md:191`），本就允许在非 loop 线程阻塞 |

### 9.2 问题（契约缺陷，**第一批**修）

| ID | 严重度 | 位置 | 问题摘要 | 裁决 / 落点 | 状态 |
|---|---|---|---|---|---|
| **N-36** | **B1** | `c-abi.md:184`（矩阵）vs `:716`（accept 回调可用动作）、`requirements.md:282`（AC-29）、`:294`（AC-40） | **`conn_retain` 的错误矩阵与它自己的验收标准互相否决**。矩阵把 `conn_retain` 列进 `WOULD_DEADLOCK（loop 线程）`，而它的**唯一主用法**正是在 loop 线程上的 accept 回调内调用。按字面执行，AC-29 / AC-40 的示例 100% 失败。**两路 agent 独立命中，主会话已复核** | `conn_retain` 从 `:184` 拆出**单独一行**：只留 `STALE_HANDLE`、`INTERNAL`（**任意线程**；纯所有权表变更，不阻塞不等待 → 去 `WOULD_DEADLOCK` 与 `TIMEOUT`）；`@special` 允许清单补 `conn_retain` / `conn_subscribe` | **C（2026-11-05，已落笔）** |
| **N-37** | **B1** | `c-abi.md:183`（矩阵把 `endpoint_accept` 与 `iocomm_subscribe` 写在同一行）vs `:191`（`endpoint_recv` 的 `INVALID_STATE` 只写「已 subscribe」）、`:727`（端点级持有时「accept 回调仍会触发」）；`open-questions.md:213`（声称由 §6.4 覆盖） | **`endpoint_accept` 被误纳入「接收对象二选一」**。`endpoint_recv` 的 `INVALID_STATE` 并未提 accept，而矩阵行暗示二者互斥；**§6.4 全文零次提到 accept**（已 grep），`:213` 的免责不成立。根因：`95c8fa6`（N-02 落地）时把 endpoint 与 subscription 两类对象混用来表达所有权 | 定为**两条正交的轴**：`endpoint_accept` 只注册「新入站连接交付」回调，与 `iocomm_subscribe(ep)` / `endpoint_recv(ep)` **无互斥关系，可任意顺序注册**；§6.4 的二选一**只约束接收对象本身**。落点：`c-abi.md` §3.2.1 / §5.2 / §6.4 开头 + 更正本节 `:213` 的免责；**AC-104 现有子项需复核**（其来源即该缺陷）。行业口径：Asio / Netty / OPC UA 均把「谁被交付」与「怎么收数据」分为两条轴 | **C（2026-11-05，已落笔）** |
| **N-38** | **B1** | `c-abi.md:727`（端点已持有时 `conn_retain` 幂等返回 `OK`）vs `:1271`（§6.4：只有「通过 `conn_subscribe` / `conn_retain` 单独接管」的连接才进连接队列） | **端点级持有后 `conn_retain` 是否迁移投递队列未定义**，两处对同一次调用给出相反后果；对这类连接调 `conn_recv` 的行为亦未落笔 | **路由在「端点级持有」成立那一刻就已定死**：此后 `conn_retain` 只做**所有权确认**、不改路由，消息继续进端点接收队列；此时 `conn_recv` 返回 **`ICOMM_ERR_INVALID_STATE`**。**否掉「迁移路由」**：违反 FR-8.11「此后由端点接管」的承诺、`conn_count` / 扇出集合会隐式缩水、回到 N-15 想消除的双归属，且没有用例需要（§6.4 明说需要两种消费方式就用两个端点） | **C（2026-11-05，已落笔）** |
| **N-39** | **B1** | `architecture.md:130` §3.3 线程表缺项 vs `c-abi.md:742`（`endpoint_accept`）、`:1452`（`conn_condition_subscribe`）、`:1456`（`endpoint_condition_subscribe`）、`:183`（矩阵把这五个函数写在同一行） | **三个入口不在线程表中**，从任意线程注册是否安全不可判定 | ~~§3.3 补一行「是（内部投递到 loop）」~~ → **2026-11-05 改判为「否」**：注册类入口要求**同步生效**（返回时已登记，随后的 `connect` 不漏交付），与「内部投递」矛盾；若改「内部加锁 + 同步生效」则 loop 线程（含回调内）调用会自锁。故归入与 `subscribe` / `conn_subscribe` **同一行**：**调用方串行化，或在 loop 线程上调用**。另补**默认规则**（未列出且注释未写「任意线程可调用」者，默认非线程安全） | **C（2026-11-05，已落笔）** |
| **N-40** | **B1** | `requirements.md:349`（AC-94 要求每条连接含 `send_queue_depth`）vs `c-abi.md:980`（成员连接**共用该端点的一条发送队列**） | **AC-94 的逐连接 `send_queue_depth` 无唯一语义**——队列是端点共享的，「这条连接的发送队列深度」不可定义。接收方向则确实是每连接一条（`:983`）。**本轮新发现，不在用户清单内** | 推荐把 AC-94 的 `send_queue_depth` 改为**端点级**、连接级只保留 `recv_queue_depth`；**否掉**「定义『本连接在共享队列中的待发条数』」：需要逐项扫描队列，实现成本高且语义脆弱 | **C（2026-11-05，已落笔）** |
| **N-41** | B2 | `c-abi.md:834-840`（`conn_retain` 注释）vs `adr/ADR-002:80`（否决理由里暗示「`retain` 之后订阅是合法需求」） | **`conn_retain` 之后能否在回调外 `conn_subscribe` 未定义**。正文从未写；按字面从严执行，FR-8.8 的「retain / subscribe 三选一」流程走不完 | 正文补一句「**合法**」（与 ADR-002:80 一致）+ 新增 AC 锁住 | **C（2026-11-05，已落笔）** |

### 9.3 部分取舍（设计不改，**第二批**补声明）

> 这四条的**取舍本身正确**，问题是文档没写清导致使用者误判为「漏了」或「v2 会有」。
> 处置原则：写进 `requirements.md` §4 非目标表 + 补作用域注 / 决策记录，**零 API 增量、零 ABI 变更、不动线格式**。⚠️ 原写「零 FR/AC 改动」**不准确**——实际改了 FR-5.2 / FR-5.4 / FR-5.5（补口径）并新增 **AC-121**（N-45 需要可构造的验收）。

| ID | 严重度 | 位置 | 现状 | 拟落笔 | 状态 |
|---|---|---|---|---|---|
| **N-42** | B2 | `c-abi.md:1933`（只在一句「信任同进程调用方」里）vs `requirements.md:213`（§4 非目标表**无此条**）；FR-5.4 / FR-5.5 无作用域注 | **跨进程集中监控不存在**。监控入口全挂 `iocomm_runtime_t`，BEACON 自述 TLV 只有节点身份 + `ENDPOINTS`，不含对端运行时状态 ⇒ 管理进程只能「每个被管进程各嵌一个 Runtime、由应用自己汇总」。v1 取舍合理（行业先例：iceoryx 靠**中心守护进程** RouDi、OPC UA 走 `ServerDiagnosticsSummary` + 按对象数组、ZeroMQ monitor 绑 `inproc://` **仅同进程**——跨进程集中监控在业界都意味着引入一个中心组件） | §4 非目标表加一行 + FR-5.4 / 5.5 补「**作用域 = 本 Runtime**」注 + `c-abi.md` §9.8 显式行 + v2 登记。**否掉**把运行时状态塞进 BEACON / 单元文件：发现是身份与寻址（1400 B 分页、6 s 租约、所有对端可见、无法表达 per-conn），且违反 FR-2.7 | **C（2026-11-05）** |
| **N-43** | B2 | 全库无 `iocomm_runtime_post` 类符号（已 grep）；§9.8 / §11 反例清单 / D-N 清单**零条**涉及 post | **manual 模式缺「回调 → 下一轮」的一等入口**。回调内可用清单（`c-abi.md:1285-1299`）只有异步发送 / 建连、`send_cancel`、`discovery_stop`、`runtime_wakeup` 等。判为**取舍**（契约极简的副产物，非明确非目标）。**规避形态成立**：回调内只「拷贝 payload + 置标志 + 异步发送」，数据处理放 `run_once` 返回后，需要句柄的下一轮用 `conn_get` 枚举。**真正做不到的只有「回调内延迟 N ms」——而 `post` 也做不到**（v1 本无定时器公开入口，`architecture.md:509` T6）。**否掉新增 `iocomm_runtime_post`**：C ABI 上需新增 6 条契约（取消语义、`user` 生命周期、队列满策略、自我投递是否让 `run_once` 永不返回、与 `run_for` 的交互、stop/destroy 时未执行任务怎么办）；若引入 `iocomm_post_t` 句柄会**推翻 N-20 刚定的「五类对象句柄」**（AC-113）；5–8 人日 vs 文档化 0.5 人日。行业先例印证代价：libuv 的 `uv_async_send` **只唤醒、不带数据、还会合并**（连发 5 次只回调 1 次）；GLib 真做投递必须额外要 `GDestroyNotify` | §4 非目标表加一行 + 把「manual 模式下的推荐形态」补到 `c-abi.md` §4（`run_once` 注释旁）。**不新增 API** | **C（2026-11-05）** |
| **N-44** | B2 | `wire-format.md:319-320`（仅一行事实陈述「v1 不可配置」）；`requirements.md:243`（只讲跨不可信网段）与 `c-abi.md:1933`（讲进程 / 租户隔离）易被误读为「域在 v2」；`open-questions.md` **原无相关条目** | **多通信域 / 网络级隔离不存在**：组播 `239.255.73.77` + 端口 `47377` 硬编码（**2026-11-10 已迁至 `23100..23200`**，见 §9.4 N-48）、名字锁是机器级、无认证无加密 ⇒ 同网段无法有两个互不可见的域。v1「同网段 = 单发现域」与「受控工业局域网 + 不做认证」自洽，判为**取舍**。**行业对照**：ROS 2 / DDS 的 Domain ID 端口公式 `7400 + 250×domainId + …`，上限 232；RTI 原文「**一个域的发现流量对另一域不可见**」；代价明确——ROS 2 实测建议 Linux 只用 0–101 与 215–232（避开临时端口），且 121 个进程即溢出到相邻域端口 | §4 非目标表 / §4.1 安全边界 / `architecture.md` §6.3 / README / `discovery_config` 注释各补一句「**v1 单域；硬隔离请用 VLAN / ACL / 独立网卡 / netns**；域 ≠ 安全边界」。**否掉** v1.1 可配置组播（只做发现层，`connect(addr)` 仍可绕过；同机多组还需 Linux `IP_MULTICAST_ALL=0`）与 v2 `domain_id` + HELLO 校验（6–10 人日、动线格式，无认证时仍非安全边界，应与 TLS 同批） | **C（2026-11-05）** |
| **N-45** | B2 | `c-abi.md:183` + `:1445-1457`（仅签名与一句「适用于 conn 或 endpoint」）；`requirements.md` FR-5.1 / 5.2（`:102-103`）与 AC-12（`:265`）均无端点级语义 | **`endpoint_condition_subscribe` 事件语义为空**（全文仅 2 次出现）。判为**取舍**（v1 可不实现端点级聚合），但语义空白导致它被误当成「无需逐连接预订阅」的天然答案 | 补语义：**端点级状态订阅 = 对「当前与未来全部成员连接」条件集变化的聚合**，等价于对每个成员连接各订阅一次但**只产生一个订阅句柄**；新成员自动纳入、**不需在 accept 回调补订阅**；**成员离开**：其状态变化照常推送（含最后一次 `connected = FALSE`，**推送先于摘除**），摘除后停止投递；**不额外推送「成员离开」这类独立事件**（上线归 `endpoint_accept`，节点上下线归 `discovery`）。**成员定义 = 计数成员**（扇出集合 + inproc 排空窗口内连接，见 FR-5.2 carve-out）；回调 `conn` 与 `ep` 恒非 0，**端点无自身状态、永不以 `conn == 0` 触发**。**否掉**另发上线 / 下线事件：与 `discovery` 的 JOINED/LEFT 及 `accept` 重复，形成第三套观测，且 `iocomm_peer_status` 无承载字段。**待定**：「订阅后是否立刻推一次当前值」须先在连接级 `conn_condition_subscribe` 定死，本项最不确定 | **C（2026-11-05）** |

### 9.4 需负责人拍板（**2026-11-10：N-46 / N-47 / N-48 全部已裁决，本节无待定项**）

| ID | 议题 | 争点 | 建议 |
|---|---|---|---|
| **N-46** | **连接快照 API 做不做** | **两路 agent 结论冲突**。A 路：「独立监控线程拿不到一致视图」→ 应在 v1 新增 `conn_snapshot_take/count/get/release`（**复用已有 `snapshot` 句柄类，不新增第六类**，否则与 N-20 / AC-113 冲突），4–6 人日。B 路：`conn_count(rt, 0)` + `conn_get` 在 **loop 线程**调用完全合法（`architecture.md:127`「loop 线程或串行化」），而工业单线程 manual 模式的应用线程**就是** loop 线程 → 轮询方案成立，v1 只需文档化，v1.1 在 monitor 加 `CONN_OPENED` / `CONN_CLOSED` 两个 kind 值（`kind` 是 `uint16` 枚举，**只追加不改布局**），0.5 人日 | **已裁决（2026-11-09）：A、B 都不采纳——走「补全既有两层」**。方向定位为**面向普通应用**（负责人 2026-11-09 确认）⇒ owned 是默认主路径 ⇒ `conn_count` / `conn_get` 在应用线程上确实不可用（UB），A 路指出的问题成立。但三路独立调研（三路独立调研，结论摘录于本行；报告未入库）一致表明：**业界对「off-loop 看连接状态」的答案不是「同步枚举 API」，而是「事件流 + 值快照」**——libuv `uv_walk` 不可跨线程且全仓无 loop 归属校验、Asio 根本没有枚举入口、ZeroMQ 用 `zmq_socket_monitor` 事件流、NNG 用 `nng_stats_get` 深拷贝值树、DDS 用 built-in topic 订阅、iceoryx 用 introspection 主题、ROS 2 用后台线程维护 `GraphCache`。**「应用线程同步点进 IO 线程取列表」九家调研中一次都没出现**；线程违规的处理上**返回错误码的一个都没有，UB 是压倒性主流**（ZeroMQ 原文「Doing so results in undefined behaviour.」）。IoComm 已有这两层（`monitor_open` 事件流 / `iocomm_diagnostic_dump` 值快照），缺的是**完整性**。<br>**落地（三件，零 ABI 成本）**：① `diagnostic_dump` 的 `connections[]` 补全为 `ep` / `lively` / `healthy` / `config_current` / `last_rx_ns` / `last_heartbeat_ns` / `reconnect_count` / `send_queue_depth` / `recv_queue_depth`（`version` 1→2）；② 架构 §3.3 与 C ABI 的 `conn_count` / `conn_get` 明写 owned 模式下的跨线程调用为 UB 并指向 dump；③ 非目标表补两条（专用快照句柄 API、同步投递进 loop 并阻塞）。把跨线程枚举语义**并进 FR-5.5**（不新增编号）与 **AC-122**（归 M2）。<br>**已否决的备选**：`conn_foreach(rt, fn, user)` 回调枚举（1.5–2 人日）——成本不在工作量而在**合同污染**：它是**调用方线程 + pull** 语义，而本库已有六类回调（`message_fn` / `accept_fn` / `condition_fn` / `discovery_fn` / 三个 `on_done`）全部是 **loop 线程 + push**（`c-abi.md:1386`「@thread 在 Runtime 的事件循环线程上调用」），全库「回调内」出现 58 处；引入第二类回调形会让此后每写一次「回调内允许 X」都得先问「哪个回调」。**也已否决** `buf + cap + out_n` 两次调用形状：踩 `readdir_r` 废弃的第一条理由（接口不允许调用方指定返回项缓冲长度——数组步长由调用方 `sizeof` 决定，结构体尾部追加后老宿主会静默写坏内存），且微软在 `GetAdaptersAddresses` Remarks 里明写两次调用法「strongly discouraged」。**也已否决**把 `conn_count` / `conn_get` 改为线程安全：无锁方案需 epoch/RCU 回收（当前架构无此设施），加锁则违反 `architecture.md:98`「回调无锁」 |
| **N-47** | **`iocomm_peer_status` 尾部追加 per-connection 计数** | FR-5.4 六项指标 Runtime 级全有（AC-15 也只测 Runtime 级 RTT），故「无 per-conn」本身是取舍。但 `iocomm_peer_status` 只有条件集 + `last_rx_ns` / `last_heartbeat_ns` / `reconnect_count`，无字节 / 消息 / 丢弃 / 队列深度；唯一每连接水位在 `diagnostic_dump` 的 JSON（字符串分配、粒度粗） | **已裁决（2026-11-09）：`peer_status` 不动；盲区改由 dump 关闭**。理由：`peer_status` 同时是 `iocomm_condition_fn` 的**回调载荷**，加计数字段会让每一次状态推送都驮着一组几乎不变的累加值，而条件订阅的语义是「状态变化」；FR-5.4「作用域 = 本 Runtime，无 per-connection 维度」这条已文档化的取舍保持不变。<br>**原登记的盲区**（`ep_owner == 0` 的出站连接各自一条发送队列、不在任何端点下、`send_queue_depth` 不出现在 dump 中）**改由 dump 关闭**：`connections[]` 条目新增 `ep` 与 `send_queue_depth`，无主出站连接报 `ep == 0` 并报**自身**队列深度（与成员连接报「所属端点共享队列深度」并存，同一端点的成员连接报同一值、聚合时不可相加）。已在 C ABI `diagnostic_dump` 注释与 AC-94 / AC-122 落笔 |
| **N-48** | B2 | **`47377..47477` 落在 Linux 默认临时端口段内**（**2026-11-10 已迁至 `23100..23200`**，本行保留为当时快照） | 内核文档 `ip_local_port_range` 示例即 `32000 60999`（主会话已复核）。启动顺序不利时内核可能已把该端口分配给出站 socket → `discovery_start` 因 `bind` 失败返回 `RESOURCE_EXHAUSTED`。**与多域无关，本轮新发现** ｜ **已裁决（2026-11-10，D-4）：换默认端口块，不加字段**。端口块迁至 **`23100..23200`**（组播 `23100` / 单播 `23101..23200`），脱离 Linux `32768–60999` 与 Windows `49152–65535` 两个默认动态段；IANA 官方 CSV 逐端口核对全段未注册，两端余量充足（紧邻块下方的最近注册端口 `23053` / 上边界 `23272`）。**否掉「加 `listen_port` 字段」**：① 端口撞车是**宿主机级**事实（同机所有进程共享内核端口池），字段只能改本库想绑哪个口，管不了内核是否先把该口分给出站连接；② 更要紧的是**端口同时就是发现域**——A 机配 `23100`、B 机配 `23150` 会**静默**互不可见（唯一症状是 `discovery_snapshot` 空表），等价于偷渡半个 `domain_id`，与 N-44 的「v1 单发现域、`domain_id` 留到 v2 与 TLS 同批」直接冲突。**否掉「维持 `47377` + 只靠 sysctl」**：要求每台 Linux 机改内核参数，与「面向普通应用」定位冲突，且漏改时只在特定启动顺序下概率性失败。**组播组 `239.255.73.77` 不动**——组播组不存在内核自动分配问题，迁移零收益。**核查证据**（2026-11-10 主会话）：Linux 文档 `32000 60999`；本机 `netsh int ipv4 show dynamicport udp` / `... tcp` 均为 `49152 + 16384`；IANA `service-names-port-numbers.csv` 中 `47377` / `47378` / `47477` 与 `23100..23200` 全段均**未注册**（20000–24999 注册密度仅 103/5000）。落地见 §9.6b|

### 9.5 附带发现（主会话已复核）

| ID | 项 | 结论 | 说明 |
|---|---|---|---|
| **N-49** | **`*_destroy` 的 `WOULD_DEADLOCK` 未进矩阵** | **成立（B2）；已修，但「收窄 `@allow`」的建议已被否决（见右）** | `c-abi.md:175` 的 `endpoint_destroy` / `conn_destroy` / `conn_abort` 行只列 `STALE_HANDLE`、`INTERNAL`；而 `@forbid`（`:1286-1288`）明写「销毁**非本回调交付的**连接 / 订阅 → 违反一律返回 `WOULD_DEADLOCK`」。**矩阵漏列**。<br>⚠️ **agent 原报「三重矛盾」表述过头**——`@forbid` 与 `@special`（`:1291`）并不矛盾：前者管「非本回调交付的对象」，后者管「本回调交付的对象」，是两条互补规则。**真缺陷只有矩阵漏列**。<br>**另一处真问题**：`@allow`（`:1298`）允许回调内「创建新的端点 / 连接」，但 `@forbid`（`:1286`）禁止 `endpoint_destroy` / `runtime_destroy`——**回调内创建的端点无合法销毁途径**。处置：**只补矩阵**（`:175` 已加 `WOULD_DEADLOCK`）。**`@allow` 维持原样**——2026-11-05 复核认为「回调内创建端点会泄漏」的理由不成立：`@forbid` 只约束**回调执行期间**，回调返回后可合法销毁，无泄漏；收窄反而制造「不在 `@forbid`、矩阵也无对应码」的三不管状态 |
| **N-50** | **`runtime_wakeup` 后 `run_once` 的返回值** | **成立（B3）** | `c-abi.md:401` 的「本轮干了活」清单是「就绪 IO / 到期定时器 / 内部任务」，**未含「被唤醒」**。纯 `runtime_wakeup` 唤醒后返回 `OK` 还是 `TIMEOUT` 不可判定。处置：清单补「被唤醒（纯唤醒不产生业务事件，但仍算作本轮从等待中返回）」并明确返回码——**建议返回 `OK`**（唤醒的语义就是「别睡了，有事」），否则调用方无法区分「被唤醒」与「超时」 |
| **N-51** | **AC-104 的末位断言正是 N-37 要否掉的口径** | **成立（B1，与 N-37 同源）** | `requirements.md:359` AC-104 末尾：「再对照：同一 `ep` 上先 `endpoint_recv` 再 `endpoint_accept` → 后者返回 `INVALID_STATE`（§6.4 互斥）」。这正是 N-37 裁决要推翻的「accept 与 recv 互斥」。**AC-104 必须随 N-37 一并修订**，不能只改契约不改验收 |
| — | **`runtime_wakeup` 的语义** | 已复核 | 「只唤醒 loop、不带数据、不执行代码」；与 N-50 互证 |
| **N-52** | **`monitor_poll` 超时的报告方式矩阵与注释相反** | **成立（B3，既有缺口，非本批引入）；已修** | 矩阵 `c-abi.md` 列了 `TIMEOUT`，而 §9.4 注释写「超时返回 `OK` + `out_n == 0`」。**以注释为准**（已改矩阵去 `TIMEOUT`）：`out_n == 0` 是**正常空闲**，与 `run_once` 的 `TIMEOUT` 是两种不同设计——`poll` 返回的是**条数**，0 条即空，无需额外错误码 |

### 9.6 建议处置顺序（管理视图）

| 批次 | 内容 | 前置条件 | 预估 |
|---|---|---|---|
| **第一批：契约对齐** | N-36 / N-37 / N-38 / N-39 / N-40 / N-41 / N-49 / N-50 / N-51 | **无**（纯文档自洽，不动设计决策） | 3 人日 |
| **第二批：如实声明** | N-42 / N-43 / N-44 / N-45 + N-48 短期提示 | 无 | 1 人日 |
| **第三批：需拍板** | N-48 中期（**2026-11-10 已裁决**，同 N-46 / N-47） | 无 | 已闭合 |

> **第三批已全部闭合（2026-11-10）**：N-46 / N-47 于 2026-11-09 裁决落笔，N-48 中期于 2026-11-10 裁决落笔（换默认端口块 `23100..23200`，**不加字段**）。
> **N-46 / N-47 的裁决结果（2026-11-09，零 ABI 增量）**：把跨线程枚举语义**并进 FR-5.5**（不新增编号）与 **AC-122**，`diagnostic_dump` 的 `connections[]` 补字段并升 `version` 1→2 —— **不改任何 C 结构体、不新增导出函数**。
> 前两批**没有任何一条**需要动 ABI major、动线格式、或推翻已提交的 ADR；新 AC 编号从 **AC-117** 起（现有最高为 AC-116）。
> **ABI 面确认干净**（独立 agent 复核，针对 2026-11-05 那一批）：无新增函数、无新增结构体字段、无新增枚举值；`wire-format.md` 仅一行文字说明。
> **2026-11-10（D-4）追加核对**：端口块 `47377..47477` → `23100..23200` **仍是零 ABI 增量**（无新增/删除字段、无新增导出函数），
> 但**不是「仅一行」**——`wire-format.md` §8.1 的寻址表新增一行、并新增「端口块的选择」整段（四项核对 + 两条「不做」）。
> 该改动动的是**常量取值**而非结构布局或线格式编码，故不升 `abi_minor`；若已有部署方按 `47377` 配过防火墙规则，属**运维配置失效**而非 ABI 破坏。

### 9.6b 落地状态（2026-11-05 收尾）

| 项 | 落点 |
|---|---|
| N-49 / N-50 / N-51（复核中发现的契约缺陷） | `c-abi.md` §3.2.1（destroy 行补 `WOULD_DEADLOCK`）/ §4（wakeup 优先级）；`requirements.md` AC-33b / AC-109 / AC-117 |
| **N-52**（既有缺口，本批顺带修） | `c-abi.md` §3.2.1 `monitor_poll` 行去 `TIMEOUT` |
| **新增 AC** | AC-117（accept 正交）/ AC-118（端点持有后 retain 不改路由）/ AC-119（retain 线程与订阅顺序）→ **M2**；AC-120（wakeup 唤醒）→ **M1**；AC-121（端点级条件订阅）→ **M3** |
| **改动的既有 AC** | AC-5 / AC-6 / AC-29 / AC-33 / AC-33b / AC-40 / AC-94 / AC-104 / AC-109（共 9 条） |
| N-36 ~ N-41（契约缺陷） | `c-abi.md` §3.2.1 / §3.1 / §4 / §5.2 / §6.3 / §6.4 / §8；`architecture.md` §3.3；`requirements.md` AC-5/6/29/33/33b/40/94/104/109 + 新增 **AC-117~121** |
| N-42 / N-43 / N-44 / N-45（取舍声明） | `requirements.md` §4 / §4.1 / FR-5.2/5.4/5.5；`c-abi.md` §4（N-43 推荐形态）/ §7（N-44）/ §9.8（N-42~44 非目标）；`architecture.md` §6.3 / §3.3；`wire-format.md` §8；`platform-support.md` §3.3；`README.md` |
| N-48 短期 | ~~`platform-support.md` §3.3（`ip_local_reserved_ports`）~~ → 2026-11-10 随 D-4 重写为「默认不冲突 + 仅 `ip_local_port_range` 被调宽时才需保留」 |
| **N-46 / N-47**（2026-11-09 裁决） | `c-abi.md`（`diagnostic_dump` 注释补全字段 + `version` 2 + 「v1 唯一的线程安全连接枚举」段）；`architecture.md` §3.3（`count/get` 行 + 监控线程段）；`requirements.md` FR-5.5 扩写（并入跨线程枚举，不新增编号）/ AC-94 重写 / 新增 **AC-122** / §4 非目标补两行 + per-conn 指标行（顺带关闭 N-56 断链）；本文 §9.4 N-46 / N-47 |
| **N-48 中期（2026-11-10 裁决）→ 端口块迁移** | `wire-format.md` §8.1（寻址表拆成「组播组地址 / 组播 UDP 端口 / 单播 UDP 端口块」三行 + 新增「端口块的选择」段，含四项核对与两条「不做」）；`platform-support.md` §3.3（风险行重写为「默认不冲突 + `ip_local_port_range` 被调宽时的核对与保留方法」）；`architecture.md` §6.3（发现节首段补端口块与理由）；`requirements.md` §4 非目标表新增「发现端口可配置」行 + §4.1 域隔离注补「不要依赖同机配不同端口」；`c-abi.md` §7（`discovery_config` 上方注补 `listen_port` 不做及理由）+ §9.8 非目标表补行；本文 §9.4 |
| N-58（2026-11-11 裁决，D-5）→ inproc 不跑心跳 | `requirements.md` **新增 FR-3.11 / FR-3.12**、FR-5.1 补 transport 作用域、FR-4.4 补「仅 tcp / unix / pipe」、**新增 AC-124（归 M3）**、AC-86 / AC-123 标注为 tcp 连接、§4 非目标表新增「inproc 的心跳与自动重连」行、变更记录新行；`architecture.md` §5.2b（条件表下新增 inproc 注 + 已知盲区）、§5.2c 首段（不适用 inproc）、§6.2（新增「四个心跳别名」辨析表 + inproc 不发声明确）；`wire-format.md` §7（心跳同 HELLO、不走帧层，含判据与盲区）；`c-abi.md` §5.1b（「有意不同」补第 ③ 条）、`peer_status`（`lively` / `healthy` / `last_heartbeat_ns` / `reconnect_count` 四处 inproc 注）、`stats.rtt_*`、`diagnostic_dump.lively`、端点级 keepalive 非目标注；本文 §10.4 N-58 + 文首待办清单 |
>
> **既有 AC 的实际改动（2026-11-05 复核更正）**：本行原写「AC-104 是唯一一条需要改的」，**不准确**。
> 实际改动的是 **9 条** —— AC-5 / AC-6（补非阻塞调用例外）、**AC-29 / AC-40**（补「端点级收消息未启用」限定，
> AC-40 另加对照组）、AC-33 / **AC-33b**（补多次注册的持有与销毁边界）、AC-94（`send_queue_depth` 改端点级，
> **因为 AC 本身写错了语义**，不是契约错）、AC-104（删 accept/recv 互斥的末位断言，见 N-51）、
> AC-109（「空闲」排除有 `wakeup` 待处理）。**AC-121 同时是新增项**，不计入这 9 条。

### 9.6c 第三轮验收的残余（2026-11-05 收尾）

第三轮验收判 10/13 已闭合，其余 3 条与新引入的 4 条已在本轮修复。**仍未闭合、需后续跟进的**：

| 项 | 状态 | 说明 |
|---|---|---|
| **`diagnostic_dump` 的 `ep_owner == 0` 发送水位盲区** | **已闭合（2026-11-09，随 N-47 裁决）** | `connections[]` 条目新增 `ep` 与 `send_queue_depth`：无主出站连接报 `ep == 0` 并报**自身**队列深度。已落 C ABI `diagnostic_dump` 注释、AC-94 与 AC-122 |
| **端点级条件订阅「订阅瞬间是否补推当前值」** | **未定口径，但已消除矛盾** | 现口径为「与连接级共用同一条规则」，两级不再打架；规则**本身**仍是开放的，由连接级先定 |

> **本节此前若再出现「未闭合」条目，一律先在本表登记再动手**——避免下一轮审查把同一问题当作新发现。

### 9.7 本轮同时确认的既有结论（避免下轮重复排查）

- **N-01 ～ N-34 全部已处置**，无一未决。**N-35（许可证）除外**——它是负责人决策项，未决，见 §8.8 与 `README.md` §许可证。用户清单中「已记录但未处置的 6 条」（N-08 / 09 / 10 / 11 / 13 / 14）均为误判，见 §9.1。
- **截至 §9 登记时（本轮改动之前）工作区是干净的**：`git status --porcelain IoComm` 为空，`39d7ad2` / `d97c8c1` / `c6313e8` 已把 N-04/05/06/07/12 与 N-20~N-35 入库；用户清单第五节「git HEAD 还没有这几项」在当时不成立。
- **§9 的落笔改动已入库**：`039fc19`（N-36~N-52 第一批/第二批）；其后的复核修复见 §10。工作区在每次提交后均为干净。

---

## 10. 2026-11-05 第二轮复核（对 `039fc19` 的验收）

对已入库提交 `039fc19` 做独立复核（改动一致性 + 残留待办真实性两路），发现 2 条契约缺陷与 3 条登记瑕疵。

### 10.1 已修（契约缺陷）

| ID | 严重度 | 位置 | 缺陷 | 处置 |
|---|---|---|---|---|
| **N-53** | **B1** | `c-abi.md:173`（矩阵）、`:350`（注释）、`:1377`（`@forbid`）、`architecture.md:112` | **`runtime_drain` 的 `WOULD_DEADLOCK` 三处互斥**：矩阵写「两者都没有」、`@forbid` 写「回调内一律返回」、架构 §3.2 的豁免清单不含 `drain`。且 `drain` 去掉 `TIMEOUT` 后，**owned 模式 `timeout_ms` 语义全库未定义**。根因：`039fc19` 把 `start/drain` 错误合并成一行，而 `drain` 与 `stop` 同族。 | **拆成三行**（`start` / `drain` / `stop` 各一行）：`start` 三类阻塞码全无；`drain` 恢复 `TIMEOUT`（owned 等满不收敛，不保证已排空）+ `WOULD_DEADLOCK`（`timeout_ms > 0` 且在 loop 线程）+ `WOULD_BLOCK`（manual 未排空）；注释补 `timeout_ms` 的两种模式口径（manual 下不起作用，按架构传 0）；`@forbid` 改为区分 `timeout_ms` 是否为 0 |
| **N-54** | **B2** | `c-abi.md:181`（矩阵）vs `:1377`（`@forbid`）vs `requirements.md:269`（AC-5） | 矩阵把 `WOULD_DEADLOCK` 条件限定为「销毁连接/订阅」，**`iocomm_endpoint_destroy` 永远拿不到该码**；而 `@forbid` 无条件禁止回调内 `endpoint_destroy`，AC-5 也断言「回调内销毁**端点**/订阅 → `WOULD_DEADLOCK`」。 | 矩阵该行改为**两种情况并列**：① 回调内调 `endpoint_destroy`（无条件）；② 回调内销毁非本回调交付的连接/订阅。`@forbid` 同步重写，并澄清 **`runtime_destroy` 返回 void、无错误通道**——它是「不得调用」而非「返回某码」，把既有的「void 还说要返回码」的自相矛盾一并消掉 |

### 10.2 已修（登记瑕疵）

| 位置 | 原文缺陷 | 处置 |
|---|---|---|
| `open-questions.md:431`（§9.7） | 「**N-01 ～ N-35 全部已处置，无一未决**」——与 `:312` 的 N-35「待负责人确定」及 `README.md:170`「待定。」直接矛盾 | 改为「N-01 ～ **N-34** 全部已处置；**N-35 除外**」 |
| `open-questions.md:432`（§9.7） | 「§9 的落笔改动……**尚未提交**」——已随 `039fc19` 入库 | 改为「已入库 `039fc19` + N-53 复核修复」 |
| `open-questions.md` §9 内的行号引用 | 提交后**大面积漂移**（两路复核分别测得 29 与 32 处，口径差异在是否按 `(文件,行号)` 去重；主要落在 `c-abi.md`，其次 `requirements.md`），另有 2 处**对自述基线 `39d7ad2` 就写错**（N-40 的 `:983` 应为 `:982`；§9.1 的 `architecture.md:133` 应为 `:135`） | 见 §10.3 —— **不批量重算，改为章节锚点口径** |

### 10.3 行号引用的处理口径

§9 声明「行号对应 `39d7ad2`」，但本文件本身会被后续提交改动，行号指针**必然随时间失效**。
**结论**：正文与证据列**改用章节锚点或函数名**，仅在必要时保留行号并标注基线提交。

- 已更新 §10 新增内容一律用 `§x.y` 段号 / 函数名。
- §9 既有的漂移行号**暂不批量重算**——理由：任何一次提交都会再次让它们失效，重算是重复劳动；
  登记在本节，随 M0 冻结前的一次性「文档指针清理」统一处理。§9 已自述基线为 `39d7ad2`，
  这些行号仍可回溯到当时的证据。

### 10.4 未修（登记，待后续）

| ID | 严重度 | 项 | 说明 |
|---|---|---|---|
| **N-55** | B2 | **`iocomm_stats.send_queue_depth` / `recv_queue_depth` 语义零定义** | `c-abi.md` 的 `iocomm_stats` 里，`queue_dropped` / `protocol_errors` / `audit_events` 都有口径注释，唯独这两个裸字段没说「是全 Runtime 聚合还是快照时点瞬时值」。补一句注释即可，不涉 ABI |
| ~~**N-56**~~ | ~~B3~~ | ~~**`FR-5.4` 引用「§4 非目标表」是断链**~~ | **已闭合（2026-11-09，随 N-46 / N-47 裁决）**：`requirements.md` §4 非目标表已补「per-connection 的指标维度」一行，说明 FR-5.4 作用域 = 本 Runtime、`peer_status` 为何不带累加计数、逐连接队列水位走 `diagnostic_dump` |
| **N-57** | B3 | **`runtime_node_id` 在 Stopped 下返 `CLOSED`，与状态机冲突** | 状态机写「只读查询不受影响」，而 `node_id` 是只读；同族 `runtime_node_name` **无**此码。二者应统一 |
| ~~**N-58**~~ | ~~B3~~ | ~~**inproc 的心跳 / `healthy` 语义未定义**~~ | **已裁决（2026-11-11，D-5）**：inproc **不跑心跳、不自动重连**。判据不是「离得近」——心跳解决「半开」（断了没人告诉你）与「对端卡死」（连着但不跑）两件事，inproc **免掉前者、免不掉后者**。故：① **卡死信号与 tcp 同构**（接收方不消费 → 接收队列满 → 发送方 `Transport::write` 返回 `WouldBlock` → **发送方发送队列**堆积 → 按端点策略丢弃并计**发送方** `queue_dropped`；inproc 与 tcp 共用同一段「写不动回 `WouldBlock`」的代码，区别只是「传输层」是接收队列 vs 内核缓冲）；② **断开改由直接通知驱动**（对端 Runtime 销毁 → `connected = FALSE` **条件值立即变**、断开**事件**延后到排空窗口结束，不经 `Reconnecting`，连接对象终结——对端先断时先入排空窗口、队列取空后才失效（本端销毁立即失效），应用重建拿**新句柄**）；**定序**：断开事件延后到**该连接的可交付残留为 0** 之后才推送（端点级只算该连接在端点队列中的项），本端主动销毁不排空；③ inproc 上 `lively` / `healthy` **恒 `TRUE`**（不存在 `UNKNOWN` 窗口；**不表示健康探测通过**），`last_heartbeat_ns` / `reconnect_count`（逐连接字段）**恒 0**、RTT 分位**无 inproc 样本**（仅当 Runtime 只有 inproc 连接时为 0）。**行业对照**：libzmq 的 inproc 同样受 HWM 约束、无重连、monitor 不覆盖 inproc（与本库一致）；nng 的 inproc 无界且有重连（本库有意不抄——无界是公认缺陷，重连是策略）。**盲区与 tcp 相同**：缓冲未满前无信号（不是 inproc 特有缺陷），per-connection 卡死定时器 v1 不做（进需求 §4 非目标）。**否掉「inproc 也跑心跳」**（要把定时器与 `HEARTBEAT` 帧从 M3 提前进 M1，为可直接观测的事付推测性检测成本）；**否掉「两条件恒 `UNKNOWN`」**（「不适用」与「窗口未满」共用一个值，监控侧无法区分，AC-86 需分叉）。落点：需求 **FR-3.11 / FR-3.12**（新增）、FR-5.1 / FR-4.4 补作用域、**AC-124**（新增，归 M3）、AC-86 / AC-123 标注 tcp；架构 §5.2b / §5.2c / §6.2；线格式 §7；c-abi §5.1b / `peer_status` / `stats`（含 `heartbeat_timeouts` / `reconnects`）/ `diagnostic_dump` / keepalive 非目标注 |
| **N-59** | B4 | **QPC 跨处理器一致性与 tick 粒度** | 2026-11-10 时钟口径定为 Windows 用 `QueryPerformanceCounter`（架构 §6.5）。**跨处理器一致性已核实**：MS Learn《Acquiring high-resolution time stamps》原文——「the performance counter results are **consistent across all processors** in multi-core and multi-processor systems, even when measured on different threads or processes」；列出的例外仅限「**Pre-Windows Vista**」（非不变 TSC / TSC 同步算法不适配大量处理器）。产品最低要求 WS2016，**不落在例外范围内**。多时钟域的大型服务器上 Windows 会退化为 platform counter，原文称「still yields reliable time stamps」但访问延迟与伸缩性变差 ｜ **降为 B4，不再阻塞**。剩余唯一注意事项：**跨线程取的两个 QPC 值相差 ≤ 1 tick 时，先后顺序是模糊的**（原文：「When you compare performance counter results that are acquired from different threads, consider values that differ by ≤ 1 tick to have an ambiguous ordering」；本机 `freq = 14,318,180` ⇒ 1 tick ≈ 70 ns）。心跳/超时的判定窗口是毫秒级，70 ns 的模糊完全可忽略，**不需要在实现里特殊处理**。S1 Spike 可顺带记录本机 `QueryPerformanceFrequency` 值，无需专门做多 NUMA 实测 ｜ **已核实（2026-11-10）** |
| **N-60** | B2 | **seed 的 bootstrap 端口语义为空**（2026-11-10 查 D-4 时发现，**与端口迁移无关**） | `wire-format.md` §8.1 **已规定查询目标端口 = 对端 `BEACON` 上报的实际源端口**，也要求 `BEACON` 的源端口必须被记录——**稳态没问题**。空白在 **bootstrap**：seed 要发的**第一条** `CAP_Q` 该发到哪个端口？此时还没有任何 `BEACON` 可依，而单播接收端口由对端运行时从 `23101..23200` 里**取第一个可用**挑出，本端**无从得知**。填组播口 `23100` 也不行——同机多个 Runtime 都 join 了该组且绑同一端口，**单播**发到该端口只会被其中一个 socket 收到（内核不按组播语义复制单播），这正是单播段存在的理由。于是「关组播 + 配 seed」这条 P0 路径（FR-2.4 / AC-7）的**首包寻址规则是未定义的** ｜ **未落笔，待定口径**。候选：① seed 只填 `<host>`（端口忽略）、接收端在端口区间**逐个探测**——代价是最多 100 次探测 × seed 数，且探测报文本身要定义；② seed 必须填完整 `host:port`，并对**区间内全部 100 个端口**逐个发送 `CAP_Q`——不需要新报文类型，代价同上；③ **bootstrap 用组播口 `23100` 收单播**——需在单播 socket **之外**再绑定组播口（组播 socket 已占该端口，Linux 需 `SO_REUSEADDR` + 额外 socket，Windows 上语义待验证），且**关组播的部署可能连防火墙都不通该端口**；④ **单播固定端口 + `SO_REUSEPORT`**——Windows 没有该选项，且与「单播 socket 不设 `SO_REUSEADDR`」的既有约束冲突；⑤ 引入专用的 `SEED_QUERY` 探测报文 + 固定接收端口。**建议先定 ①/② 的取舍再落笔**（两者都不新增报文类型、都在现端口块内），并在 AC-7 补可执行的地址构造步骤 ｜ **状态**：待定 |

> **N-46 / N-47 的范围收窄**（复核发现）：N-46 的顺带项「`diagnostic_dump` 不在 §3.3 线程表」**已修**（`c-abi.md` 已标可跨线程、`architecture.md` §3.3 已补表），只剩「`conn_count` 与 §3.3 标『否』冲突」一项。N-47 的「唯一每连接水位在 dump」**只对发送方向成立**——`recv_queue_depth` 仍逐连接。**两项已于 2026-11-09 裁决并落笔**（见 §9.4）。
