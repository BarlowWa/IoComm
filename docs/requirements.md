# IoComm 产品需求

> 状态：设计阶段（需求已确认，实现未开始）
> 相关：[架构设计](architecture.md) · [C ABI 契约](api/c-abi.md) · [平台支持](platform-support.md) · [ADR-001](adr/ADR-001-language-and-platform.md)

---

## 1. 需求原文

> 新建一个项目，用于工业局域网通信，支持**句柄注册、发现**，**终端内通信和终端间通信**，**状态监控和控制**，通信同时支持**同步和异步**。不要包含具体的数据格式，只提供通信基本功能。

后续确认的四条约束：

1. 开发一个**独立的 IO 工具库**（不绑定既有 monorepo 的构建/语言约束）。
2. **Rust 核心 + 纯 C ABI**。
3. 目标架构 **x86_64 与 ARM64**（排除国产私有指令集）。
4. 运行环境：**Windows Server 2016+**、**Linux（麒麟 V10 / 统信 UOS 20）**；RHEL 7 为 best-effort 前向兼容。

---

## 2. 功能拆解

### FR-1 句柄注册

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-1.1 | 注册具名端点（句柄），返回可用的句柄值 | P0 |
| FR-1.2 | 注销句柄；**重复注销返回 `STALE_HANDLE`**（不幂等，以便区分「我记错了」与「已释放」） | P0 |
| FR-1.3 | 按名字查询 / 枚举句柄 | P0 |
| FR-1.4 | 重名注册被拒绝，返回明确错误码。**（2026-11-04，N-16）** 同进程已持有同名 → `ALREADY_EXISTS`；**跨进程**已持有同名 → **`CONFLICT`**；两者都**不注册**、**不自动改名**。判定权威是 `create()` 的返回值 | P0 |
| FR-1.5 | 提供三态名字查询：空闲 / 本进程持有 / 他进程持有。`endpoint_name_state()` **仅用于注册前探测与诊断**（与随后 `create()` 之间存在 TOCTOU 窗口，见[架构 §6.4](architecture.md#64-跨进程名表fr-15-三态查询)）；**权威判定是 `create()` 返回值**。不再是「单实例排他注册」开关——见 FR-1.4 | P1 |
| FR-1.6 | 句柄失效后再使用 → 返回 `STALE_HANDLE`，**绝不 UB** | P0 |
| FR-1.7 | 句柄数量上限可配置，超限明确报错 | P1 |
| FR-1.8 | **端点名格式与长度上限（2026-11-04 新增，N-17）**：UTF-8 编码后 **1–255 字节**（按字节，不按字符）；不得含 NUL 字节；必须是合法 UTF-8；`/` 为层级分隔符，**不得有空段**（不以 `/` 开头/结尾、不出现 `//`）。任一违反 → `INVALID_ARGUMENT`。上限来源：**线格式** `ENDPOINTS` 条目用 `u16` 编码 `name_len`（C 结构体的 `iocomm_endpoint_info.name_len` 是 `uint64_t`），且发现报文按条目分页（单包 ≤ 1400 B）；255 B 保证单条端点条目远小于报文条目上限。详见 [C ABI §5.1a](api/c-abi.md) | P0 |

**要求**：句柄是**整数 + 代际计数**（索引 + generation），不暴露裸指针。代际用于检测「槽位复用导致的误指向」。

### FR-2 发现

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-2.1 | 局域网内发现对端节点 | P0 |
| FR-2.2 | 节点上线/下线事件 | P0 |
| FR-2.3 | 租约（lease）机制：心跳续期、超时剔除 | P0 |
| FR-2.4 | **单播 seed 列表**（组播不可用/跨网段时的兜底） | P0 |
| FR-2.5 | 多网卡：显式指定出接口 | P0 |
| FR-2.6 | 本机进程间发现：`endpoint_config.publish_local=1` 时发布到本机注册表，并通过 `JOINED/LEFT` 事件上报 | P1 |
| FR-2.7 | 重复宣告去重：元信息未变不触发事件 | P0 |
| FR-2.9 | **发现报文分页**：单包 ≤ 1400 B；端点列表超出时按条目边界分页（`PAGE_NO`/`PAGE_TOTAL`），**收不全不更新节点表**；单条端点条目本身超限时不发送并计入 `stats.discovery_oversize` | P0 |
| FR-2.8 | **发现快照**：晚加入者可一次性取当前节点表（`take/count/get/release`）；`release` 非幂等，重复释放返回 `STALE_HANDLE`；快照句柄失效后使用同样返回 `STALE_HANDLE` | P1 |

**网络现实**：组播在工业交换机上不可靠（IGMP snooping 配置不当会静默失效）。**不能把「组播可用」当默认假设。**

### FR-3 终端内通信

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-3.1 | 同机进程间通信 | P0 |
| FR-3.2 | 与终端间通信**共用同一套抽象**（只换传输后端） | P0 |
| FR-3.3 | 对端崩溃后可靠检测。**另一面**：本进程被 `kill -9` 后，残留的 pathname socket 文件 / 命名管道实例须在下一次启动时被识别并清理（FR-3.4） | P0 |
| FR-3.4 | 崩溃残留清理（Unix socket 文件、命名管道实例；**不含共享内存段**——本库后端没有共享内存） | P1 |

**后端选择**：

| 平台 | 主 | 兜底 |
|---|---|---|
| Linux | Unix domain socket | loopback TCP |
| Windows | **命名管道**（Server 2016 无 AF_UNIX） | loopback TCP |

#### 进程内传输 `inproc`（FR-3.5–3.10）

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-3.5 | **进程内传输**：`listen_transport = "inproc"`，连接**同一进程内的 Runtime**（也允许同一 Runtime 连自己的端点），不走 socket / 管道 | P0 |
| FR-3.6 | inproc 的 `listen_addr` 是**进程内唯一名字**（≤255 B，必填），与端点名是两套独立命名空间；同进程重名返回 `ALREADY_EXISTS`。**「跨进程天然隔离」只指 `listen_addr` 这个名字**——端点名（FR-1.4/1.5）无论用哪种传输都参与跨进程名字表 | P0 |
| FR-3.7 | **投递经接收方 loop 的任务队列，绝不在 `send` 调用栈内同步回调**（避免回调重入与死锁） | P0 |
| FR-3.8 | 与 tcp 保持一致：帧结构（消息边界 / `sequence` / `original_len`）、**出站大小校验**（`TOO_LARGE`）、端点队列与溢出策略、监控打点 | P0 |
| FR-3.9 | **不参与发现**：`publish_local = 1` 时 `endpoint_create` 返回 `INVALID_ARGUMENT`，不做静默空操作 | P0 |
| FR-3.10 | **有意放宽**：编解码后的缓冲可以以移动代替拷贝交给接收方（零拷贝收益）。**大小校验不在此列**——见 FR-3.8 | P1 |

> **为什么 M1 需要它**：M1 是「只碰句柄表 / 会话 / 队列 / 回调，不碰 socket 与平台差异」的闭环。删掉 inproc 会把 M2 的传输验收整体前移（已否决方案 E-1）。
>
> **与行业的分歧（有意）**：nng 在 inproc 上**忽略** `NNG_OPT_RECVMAXSZ`（理由是同地址空间「implicitly trusted」）。本库保留出站校验，理由是 ① 有界队列（FR-4.6）要求队列占用有上界，否则「有界」只在部分传输上成立；② 同一 payload 在 tcp / inproc 上行为一致。代价只是每消息一次比较。入站超限分支保留同一代码路径——在 inproc 上不可达，不为它单独分叉。

### FR-4 终端间通信

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-4.1 | 跨机 TCP 通信 | P0 |
| FR-4.2 | UDP（含组播/广播） | **v1.1**（v1 的 `listen_transport` 不含 `"udp"`，见 [C ABI §5.1](api/c-abi.md)） |
| FR-4.3 | 帧定界：有界消息，不暴露字节流 | P0 |
| FR-4.4 | 自动重连（指数退避 + 抖动）。**四件确定的语义（2026-11-04，N-06）**：① **复用同一 `iocomm_conn_t` 句柄**（重连窗口内句柄有效）；② 断开时在途未发项**逐条 `DROPPED(PEER_GONE)`**、`on_done(DISCONNECTED)`，**重连不重放**；③ `sequence` **随连接重置**（新连接从 1 起，跨重连顺序只能靠应用层 `correlation_id`）；④ **订阅保持**（挂在连接对象上），`peer_node_id` 以新握手结果更新。详见 [架构 §5.2c](architecture.md) | P0 |
| FR-4.5 | 背压策略可配（阻塞 / 丢最旧 / 丢最新 / 报错），**按端点配置** | P0 |
| FR-4.6 | 有界队列 + 溢出可见（丢弃计数） | P0 |
| FR-4.7 | **队列双上限**：条数 ≤ `send_queue_max`（默认 1024），字节 ≤ `min(条数上限 × max_message_size, 64 MiB)`；两者先到者生效 | P0 |
| FR-4.8 | **端点级套接字参数（2026-11-04 新增，N-12）**：TCP 的 `TCP_NODELAY` 与监听 `backlog` 可按端点配置（`endpoint_config` 尾部字段）或全局热更新（`tune_config`）。`tcp_nodelay` **默认开**（小消息低延迟优先于带宽）；`listen_backlog` 默认 **128**。0 一律表示「用默认 / 保持当前值」，与其它字段口径一致。v1 **不暴露**内核 keepalive 开关——半开检测依赖应用层心跳（FR-5.3） | P0 |

### FR-5 状态监控与控制

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-5.1 | 连接/节点状态（**条件集**，不是扁平枚举） | P0 |
| FR-5.2 | 状态变化**可订阅**（不只是 `get_state()`） | P0 |
| FR-5.3 | 应用层心跳（带序号 + 双向确认） | P0 |
| FR-5.4 | 指标快照：吞吐 / 延迟 / 队列深度 / 丢弃 / 重连次数 / **协议错误数**（`protocol_errors`） | P0 |
| FR-5.5 | 诊断 dump：**连接表 + 队列水位**，JSON 文本（顶层含 `"version"` 键，供格式演进） | P1 |
| FR-5.5b | 诊断 dump：**最后 N 条错误**（需持续记录，有内存与抖动成本） | **v1.1** |
| FR-5.6 | 控制面：启停、重配置（只动通信参数）、关闭/排空 | P0 |
| FR-5.7 | 环境指纹日志（OS/内核/glibc/ulimit/网卡/安全模块），通过 `log_fn` 在 `runtime_start` 时输出一次 | P1 |

**边界**：库只暴露**原始事实**（状态、计数、事件），不定义「好/坏」「该不该切」——那是上层策略。

### FR-6 同步 + 异步

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-6.1 | 异步为原语（回调），同步为薄壳 | P0（**实现约束**：不可从 C ABI 观测，由架构评审保证，不单独挂 AC） |
| FR-6.2 | 同步 API 阻塞**调用者线程**，不阻塞 IO 线程 | P0 |
| FR-6.3 | 所有阻塞 API 带超时 | P0 |
| FR-6.4 | **库支持「无内部线程、调用方驱动」**（`run_once`） | P0 |
| FR-6.5 | 也可托管运行（自带**单** IO 线程）。**AC 口径**：owned 模式下主线程不调 `run_once` 也能完成收发，且 IO 线程恒为 1 | P0 |
| FR-6.6 | 取消语义明确（取消后仍回调一次，带 `CANCELLED`） | P1 |
| FR-6.7 | 在回调线程 / loop 驱动线程内调用同步 API → 返回 `WOULD_DEADLOCK`，而不是死锁 | P0 |
| FR-6.8 | **同一接收对象上 `subscribe` 与 `recv` 二选一**：先设置者生效，后调用者返回 `INVALID_STATE`（实现依据：[C ABI §6.4](api/c-abi.md#64-拉取与推送的互斥规则)） | P0 |

### FR-8 远端寻址与连接

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-8.1 | 显式连接远端地址（`transport` + `addr`）→ 得到**连接**句柄 | P0 |
| FR-8.2 | 通过发现结果连接（`node_id` + 端点名）。**地址解析规则（2026-11-04，N-05）**：在发现表的 `node_info.endpoints` 中按 `name` **精确匹配** → 取该条目的 `transport` + `addr`（**通告值**，见 FR-8.12）拨号；成员不存在 / 节点不存在 → `NOT_FOUND`；transport 未实现 → `NOT_SUPPORTED` | P0 |
| FR-8.3 | 连接是双向的：出站连接也能接收对端数据 | P0 |
| FR-8.4 | 发现阶段二上报**端点能力**（对端注册了哪些端点） | P0 |
| FR-8.5 | **入站连接必须可被应用拿到**：`endpoint_accept` 回调交付连接句柄（**借用**：仅在回调期间有效）。**交付时点**：tcp/unix/pipe 上为**双向 HELLO 完成后**（此时 `peer_node_id` 必有值、连接已可发 DATA）；inproc 为**连接建立即交付**（无 HELLO，见 FR-3.5 / 线格式 §7）。握手期的连接是内部会话，不分配句柄、不占 `max_handles`；握手失败/超时**不触发** `accept` | P0 |
| FR-8.6 | 发送目标语义明确：连接 = 点对点；端点 = **扇出到该端点的全部成员连接（入站 + `ep_owner == ep` 出站）** | P0 |
| FR-8.7 | 收到消息时可从 `from` 取得来源连接，用于**回发** | P0 |
| FR-8.8 | **入站连接的持有**：显式 `conn_retain`、隐式 `conn_subscribe`、**端点级持有**（端点已启用 `iocomm_subscribe(ep)` / `endpoint_recv(ep)`）三者之一即持有；都不做则回调返回时自动关闭（优雅 FIN）。**发送不是所有权开关**：「发完即关」用 `ICOMM_SEND_CLOSE_AFTER`（ADR-002） | P0 |
| FR-8.10 | **端点销毁时的出站连接**：`ep_owner == ep` 的出站连接**继续存活**，未发项原子迁移到各自的连接队列（容量取 runtime 默认），不再计入该端点扇出 | P0 |
| FR-8.9 | **连接的四种关闭**：`conn_destroy`（立即取消在途发送、丢弃缓冲、FIN，各回调一次 `CANCELLED`）/ `conn_close_graceful(linger_ms)`（flush 后关）/ `ICOMM_SEND_CLOSE_AFTER`（发完即关）/ `conn_abort`（RST 异常中止） | P0 |
| FR-8.11 | **端点级接收（2026-11-03 新增）**：`iocomm_subscribe(ep)` / `iocomm_endpoint_recv(ep)` 一经启用，即**隐式持有**该端点此后的全部入站连接（accept 回调仍会触发，仅用于观测）；不注册 `endpoint_accept` 时同样可正常接收。入站消息默认进入**端点接收队列**；被 `conn_subscribe` / `conn_retain` 单独接管的连接改进入该连接的接收队列，不再参与端点级投递（不双投） | P0 |
| FR-8.12 | **端点地址的通告值（2026-11-04 新增，N-05）**：库在发布端点能力（`ENDPOINTS` tag 与 `iocomm_endpoint_info.addr`）时，若 `listen_addr` 是通配地址（`0.0.0.0` / `[::]`）或端口为 0，则**替换为实际监听地址 + 实际端口**；实际地址仍是通配地址时，用**发送该发现报文所用 socket 的本地地址**替换。`iocomm_endpoint_local_addr()` 返回**原始监听值**（端口 0 时返回系统分配的实际端口，`0.0.0.0` 原样保留）。两者不混用：`endpoint_info.addr` = 可拨号通告值；`endpoint_local_addr()` = 本端监听事实 | P0 |

### FR-9 节点身份

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-9.1 | 节点身份（`node_id`）跨进程重启**保持稳定** | P0 |
| FR-9.2 | 支持显式配置或自动持久化（`state_dir`）。**自动模式要求 `state_dir` 非空且可写**；不满足 → `runtime_create` 返回 `INVALID_ARGUMENT`（v1 **不派生**自 machine-id / 主机名 / MAC——见 [架构 §5.1b](architecture.md)） | P0 |
| FR-9.3 | 同机多进程可共享同一主机身份，用进程实例区分（`process_epoch`） | **v1.1**（v1 语义：`node_id` 唯一标识**一个 Runtime 实例**，同机多进程各自独立） |
| FR-9.4 | **节点名**：`runtime_config.node_name`（创建期不可变），随发现上报；本机可通过 `iocomm_runtime_node_id()` / `iocomm_runtime_node_name()` 查询 | P1 |

### FR-10 消息级监控

> **定位**：原始需求中的「状态监控」包含两层 ——
> **连接/节点级**（FR-5：链路健康吗）与**消息级**（这一条消息去哪了）。
> 后者是必要需求，不是附加的调试能力。理由：现场「收不到消息」时，
> 只有计数器无法回答「哪一条、为什么」；而抓包工具不懂本库的消息边界。

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-10.1 | 逐消息**信封事件**：SENT / RECEIVED / DELIVERED / DROPPED / LOST（`SLOW` 属 v1.1） | P0 |
| FR-10.2 | 记录含 `capture_id` / `seq` / 单调时间 / 墙钟 / 来源 / 连接 / `original_len` / `correlation_id` | P0 |
| FR-10.3 | **丢弃必带原因**（`queue_full` / `no_subscriber` / `timeout` / `peer_gone` / `backpressure` / `too_large`）。**`timeout` 的口径**：异步发送排队超过 `iocomm_send_options.queue_timeout_ms`（从入队成功到开始写传输层；开始写之后不再超时） | P0 |
| FR-10.4 | **有界环形缓冲**（条数 + 字节双上限），默认 1024 条 | P0 |
| FR-10.5 | **监控永不反压主链路**：满则丢弃并计数 | P0 |
| FR-10.6 | **每个监控者独立队列**，互不影响 | P0 |
| FR-10.7 | **拉取式 `poll`**（不用回调） | P0 |
| FR-10.8 | 监控自监控：`emitted` / `lost` / `business_dropped` / `degraded`；每满 1024 次丢失**更新预留的聚合 LOST 槽位** | P0 |
| FR-10.9 | **载荷捕获**（默认关闭）：单条截断 / 速率 / 累计 / `capture_ttl_ms` 四重限制 | **v1.1** |
| FR-10.10 | 载荷视图在记录被取出后的 `retain_window` 次 poll 内有效，期间槽位与 arena 不复用 | **v1.1** |
| FR-10.11 | 二进制 `dump` 导出（magic + version）。**回放不在本库实现**：dump 的原始字节可直接经 `send` 注入，`REPLAYED` 标志由调用方在 payload 之外自行标记 | **v1.1** |
| FR-10.12 | **开启/关闭载荷捕获产生审计事件** | **v1.1** |
| FR-10.13 | 审计事件（端点增删、连接、订阅、重配置、控制、监控开关）**不含业务载荷**；v1.1 走创建期不可变的 `audit_fn` 回调 sink，**无句柄 / 无环 / 无 poll**（ADR-002） | **v1.1**（v1 以 `log_fn` 结构化事件承担） |
| FR-10.14 | 载荷捕获的**运行时开关**（open 后可开可关，用于限时调试） | **v1.1** |
| FR-10.15 | **SENT 的落点定义**：仅在成功入队后产生（同步与异步**同口径**）。`SENT` 只表示「已入队、生成了 op_id」，**不是已送达**——其后出现 `DROPPED(TIMEOUT / PEER_GONE)` 是正常序列 | P0 |
| FR-10.16 | **SLOW 的定义**：`RECEIVED.ts_mono - SENT.ts_mono`（同一次本端往返，适用于 `direction=BOTH`）；单侧监控不产生 SLOW | **v1.1** |
| FR-10.17 | 监控预分配受**全局内存预算**约束（`runtime_config.monitor_budget_bytes`，默认 64 MiB），超预算返回 `RESOURCE_EXHAUSTED`。**预算字段与 open 时的检查属 v1**；v1.1 才需要的是 arena 载荷捕获部分 | **P0**（预算）/ arena 部分 P1 |

**边界**：库只回答「这一条消息去哪了」——边界、长度、方向、序号、时间、去向、结局。
**不回答**：字段含义、业务正确性、协议级语义（那需要懂数据格式）。


### FR-7 C ABI

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-7.1 | 对外只暴露 C ABI | P0 |
| FR-7.2 | 头文件可被 **C99** 编译 | P0 |
| FR-7.3 | 版本协商：`size` + `abi_major/minor` + `features` | P0 |
| FR-7.4 | 不透明整数句柄，不传裸指针 | P0 |
| FR-7.5 | panic 不跨边界 | P0 |
| FR-7.6 | 定宽整数；`long`/`size_t` 不上 ABI | P0 |

---

## 3. 非功能需求

| 编号 | 需求 | 目标 |
|---|---|---|
| NFR-1 | 平台 | x86_64 + ARM64；WS2016+ / Linux glibc ≥ 2.17 |
| NFR-2 | 可嵌入 | 支持调用方驱动事件循环；不强制运行时 |
| NFR-3 | 可诊断 | 现场无调试器，必须能只靠 API 输出定位问题 |
| NFR-4 | 长稳 | 连续运行数月；fd/句柄/内存增量有界（24h soak 为代理验收） |
| NFR-5 | 确定性 | 超时/心跳/重连可用假时钟做确定性测试 |
| NFR-6 | 离线构建 | 依赖 vendor，不依赖联网获取 |
| NFR-7 | 加载体积 | 单库产物 ≤ 数 MB 量级（待实测） |
| NFR-8 | 许可证 | 核心依赖只用宽松许可（MIT / Apache-2.0 / BSL） |

---

## 4. 非目标（明确不做）

| 不做 | 原因 |
|---|---|
| 数据格式 / 序列化 / schema | 需求红线 |
| **传输加密 / 认证（TLS / mTLS）—— v1 不做** | 见下方「安全边界」 |
| **全量载荷默认落盘 / 内容级审计** | 见 FR-10：载荷捕获默认关闭，且不做字段解析 |
| **替代 Wireshark / PRONETA 等协议分析器** | 库不含数据格式，无法解析协议字段 |
| 硬实时协议（EtherCAT / PROFINET IRT / POWERLINK / SERCOS III） | 需专用硬件，软件层达不到 |
| TSN 特性实现 | 配置入口在 OS/网卡 |
| PRP / HSR 零切换冗余 | L2 能力，应用层做不到 |
| 私有协议（S7comm 等） | 法律与范围风险 |
| 证书签发 / PKI / GDS | 运维职责 |
| 业务语义控制（启动/校准/配方） | 越界 |
| 国产私有指令集（LoongArch / MIPS64 / SW64） | 见 ADR-001；保持可移植 |
| 硬实时承诺（任何 OS 上） | 端到端抖动无法保证 |
| **内核 TCP keepalive 开关（v1 不暴露）** | 半开检测依赖应用层心跳（FR-5.3）：内核 keepalive 默认 2 小时、WS2016 缺 `TCP_KEEPIDLE`（架构 §6.2）。`endpoint_config` / `tune_config` 只暴露 `tcp_nodelay` 与 `listen_backlog`（FR-4.8） |
| 32 位 / Win7 / Server 2008 R2 | 超出范围 |

### 4.1 安全边界（**必须显式声明**）

v1 **不提供**传输加密与认证。这不是「漏了」，而是**首版明确的范围取舍**：

| 项 | v1 | v2 计划 |
|---|---|---|
| 传输加密 | ❌ | 可插拔 TLS 后端（`feature = "tls"`） |
| 对端认证 | ❌ | mTLS 或 PSK |
| 消息级完整性 | ❌（依赖下层） | 可选 |
| 审计事件（连接/断开/拒绝） | ✅ 结构化日志 | 同左 |

> **部署要求（写进文档）**：v1 只应部署在**受控工业局域网**内；跨不可信网段时必须在外部加隧道（VPN / wireguard / 交换机 ACL）。
> **API 预留**：`iocomm_runtime_config` 已保留 `features` 能力位，v2 的 TLS 会以 `ICOMM_FEAT_TLS` 发布，**不破坏 ABI**。

---

## 5. 验收标准

### 5.1 功能验收

| 编号 | 验收项 | 判定 | 覆盖 |
|---|---|---|---|
| AC-1 | 两进程（同机）互发消息，字节完全一致 | 通过 | FR-3.1 |
| AC-2 | 两机（跨网）互发消息，字节完全一致 | 通过 | FR-4.1 |
| AC-3 | 对端被 `kill -9` 后，N 秒内检测到并触发事件 | 通过（检测时间可调） | FR-3.3 / FR-5.3 |
| AC-4 | 句柄失效后再使用返回 `STALE_HANDLE` | 通过 | FR-1.6 |
| AC-5 | **回调内销毁端点/订阅** 返回 `WOULD_DEADLOCK`，进程不崩溃。**唯一例外**：在**本订阅自己的回调内**用 `unsubscribe` 取消本订阅 → `ICOMM_OK`（见 C ABI §6.4 @special） | 通过 | FR-6.7 |
| AC-6 | 回调中调用同步 API 返回 `WOULD_DEADLOCK` | 通过 | FR-6.7 |
| AC-7 | 组播被禁时，靠单播 seed 仍能发现 | 通过 | FR-2.4 |
| AC-8 | 慢消费者**不阻塞**发布者（丢弃 + 计数）。**不要求**「不影响同端点的其他连接」——共享队列的代价见 [C ABI §6.1](api/c-abi.md) | 通过 | FR-4.5 / FR-4.6 |
| AC-9 | 进程重启后重新注册，`node_id` 不变、被识别为同一逻辑节点（用 `iocomm_runtime_node_id()` 观测） | 通过 | FR-9.1 / FR-9.2 / FR-9.4 |
| **AC-10** | 远端连接：A 进程 `connect` B 的端点并收发 | 通过 | FR-4.1 / FR-8.1 |
| **AC-11** | 重名注册被拒，且三态查询能区分「本进程持有 / 他进程持有」 | 通过 | FR-1.4 / FR-1.5 |
| **AC-12** | 状态变化通过订阅回调推送（不轮询也能观测） | 通过 | FR-5.2 |
| **AC-13** | 通过 `iocomm_runtime_reconfigure` 改心跳周期与队列上限，热生效且现有连接不中断 | 通过 | FR-5.6 |
| **AC-14** | 多网卡机器上通过 `iface_index` 指定网卡后，组播只在该网卡收发 | 通过 | FR-2.5 |
| **AC-15** | `iocomm_stats_snapshot()` 的 `rtt_p99_ns` 在注入已知延迟的测试传输下落在预期区间 | 通过 | FR-5.4 |
| **AC-16** | 重复宣告（元信息未变）不触发 `UPDATED` 事件 | 通过 | FR-2.7 |
| **AC-17** | 终端内与终端间使用**同一套** send/subscribe API（仅传输配置不同） | 通过 | FR-3.2 |
| **AC-18** | 版本协商能拒绝 `abi_major` 不同、`features_required` 不满足、`size` 过小的对端 | 通过 | FR-7.3 |
| **AC-19** | manual 模式单线程：`connect_async` + `run_once` 建连，再用 `conn_send_async` + `conn_subscribe`（**不得用同步 API**）完成收发 | 通过 | FR-6.4 / FR-8.1 |
| **AC-20** | 自动重连：断开后按退避序列重连，`iocomm_stats.reconnects` 递增 | 通过 | FR-4.4 |
| **AC-21** | 节点上下线事件（`JOINED` / `LEFT`）均被推送 | 通过 | FR-2.2 / FR-2.1 |
| **AC-22** | 通过 `node_id` + 端点名连接（`iocomm_connect_node`）成功 | 通过 | FR-8.2 |
| **AC-23** | 发现阶段二能拿到对端上报的端点列表 | 通过 | FR-8.4 |
| **AC-24** | 回调抛异常（C++ 包装层）不会穿越到库；C ABI 入口的 panic 被转为 `INTERNAL` | 子进程探针验证 | FR-7.5 |
| **AC-25** | 重复 `endpoint_destroy` 第二次返回 `STALE_HANDLE` | 通过 | FR-1.2 / FR-1.6 |
| **AC-26** | 同一端点的 4 种溢出策略分别生效（`0` = 用 runtime 默认，zero-init 不会变成 `BLOCK`）；`BLOCK` 在同步发送上阻塞至 `timeout_ms`、在异步发送与接收侧入队上退化为 `ERROR`，返回或回调 `ICOMM_ERR_WOULD_BLOCK` 并计入 `queue_dropped` | 通过 | FR-4.5 |
| **AC-27** | 建连失败 / 超时 / 销毁 Runtime 三种情况下，`connect_async` 的 `on_done` 均恰好触发一次（销毁时为 `CANCELLED`），且失败路径无 fd/句柄残留 | 通过 | FR-8.1 |
| **AC-28** | 同一参数在 runtime/endpoint/tune 三处设置时，按 [C ABI §5.0](api/c-abi.md#50-配置优先级唯一的权威定义) 优先级生效 | 通过 | FR-5.6 |
| **AC-29** | 服务端在 `endpoint_accept` 回调内 `conn_retain`，另一线程用 `conn_send` 回发；客户端能收到（回调内不得用同步 `conn_send`，会返回 `WOULD_DEADLOCK`） | 通过 | FR-8.5 / FR-8.7 / FR-8.8 |
| **AC-30** | `endpoint_send` 扇出到 **N = 该端点的全部成员连接**（入站成员 + `ep_owner == ep` 的出站连接），`out_delivered == N`；无成员连接时返回 `NO_RECEIVER` | 通过 | FR-8.6 |
| **AC-31** | 出站连接上 `conn_subscribe` 能收到对端数据（双向） | 通过 | FR-8.3 |
| **AC-32** | 同一接收对象上 `subscribe` 与 `recv` 同时使用，第二个调用返回 `INVALID_STATE` | 通过 | FR-6.8（实现依据 [C ABI §6.4](api/c-abi.md#64-拉取与推送的互斥规则)） |
| **AC-33** | `accept` 回调返回时既未 `conn_retain` 也未 `conn_subscribe`、**且该端点未启用端点级订阅/拉取**的连接被自动收回（连接数回到 0，对端观测到优雅 FIN 而非 RST） | 通过 | FR-8.5 / FR-8.8 |
| **AC-33b** | 回调内显式 `conn_destroy` 拒绝同样以 FIN 关闭；`conn_abort` 才产生 RST | 通过 | FR-8.8 / FR-8.9 |
| **AC-34** | `endpoint_create` 返回非 0 句柄，且 `endpoint_name_state` 为 `HELD_BY_SELF`；按名字查询 / 枚举端点返回正确结果；不存在时返回 `NOT_FOUND` | 通过 | FR-1.1 / FR-1.3 |
| **AC-35** | 三项静态检查全过：① 所有句柄最终 typedef 为 `uint64_t`（经 `iocomm_handle_t` 间接亦算），声明中无 `void*` 句柄；② **声明部分**（结构体字段 + 函数参数 + 返回值，排除注释）无 `long` / `size_t` / `bool`；③ **cdylib** 的公开 API 符号均为 `iocomm_*`（Linux `nm -D`，Windows `dumpbin /exports`；M0 先取实际清单，必要时给白名单）；staticlib 不做此检查 | 通过 | FR-7.1 / FR-7.4 / FR-7.6 |
| **AC-36** | 把 `conn` 句柄传给 `endpoint_*` 函数返回 `STALE_HANDLE`（不误用） | 通过 | FR-1.6 |
| **AC-37** | `log_fn != NULL` 时，`runtime_start` 后环境指纹**恰好输出一次**（P1） | 通过 | FR-5.7 |
| **AC-38** | `publish_local=1` 的端点出现在 discovery 快照（本机注册表条目并入同一节点表）中，并产生 `JOINED/LEFT` 事件（P1） | 通过 | FR-2.6 |
| **AC-39** | `connect_async(ep_owner=ep)` 建立的出站连接计入 `endpoint_send` 扇出与 `conn_count(ep)`；`ep_owner=0` 时两者均不计入。**入站成员连接同样计入两者**（N-01 修正） | 通过 | FR-8.6 |
| **AC-40** | 在 accept 回调内 `conn_retain` 后，另一线程可对该入站连接 `conn_recv` 收到数据 | 通过 | FR-8.5 / FR-6.2 / FR-6.3 |
| **AC-41** | 环**有空位**时分别诱发：**接收**队列满（`QUEUE_FULL`）、扇出无连接（`NO_SUBSCRIBER`）、异步发送超时（`TIMEOUT`）、对端已断开时发送（`PEER_GONE`）、**发送**队列满且策略 `ERROR`（`BACKPRESSURE`，同步与异步各一次）；各产生一条 `DROPPED` 且 `drop_reason` 正确 | 通过 | FR-10.3 |
| **AC-42** | 同一构建、同一发送脚本（≥1e6 条、固定 256 B），monitor **关闭** vs **开启但不 poll** 各 5 轮，msgs/s 中位数差值 &lt; 1% | 通过 | FR-10.5 |
| **AC-43** | 环满时新记录**写入失败**（不覆盖），`monitor_stats.lost` 递增；每满 1024 次丢失更新预留 LOST 槽位，`degraded=1` | 通过 | FR-10.4 / FR-10.8 |
| **AC-44** | 两个监控者配置不同（一个不读），互不影响 | 通过 | FR-10.6 |
| **AC-45** | `poll` 返回的记录字段与发送时的 `seq`/`correlation_id`/`original_len` 一致 | 通过 | FR-10.2 |
| **AC-46** | 载荷 1 KB、`max_payload_bytes=64` → `captured_len==64`、`original_len==1024`、`TRUNCATED` 置位 | 通过 | FR-10.9 | 〔v1.1〕
| **AC-47** | 达到 `max_total_bytes` 后停止捕获，监控者**不关闭**，元数据仍完整 | 通过 | FR-10.9 | 〔v1.1〕
| **AC-48** | `capture_ttl_ms` 到期后**载荷捕获停止、元数据继续**（`captured_len=0` 且 `SAMPLED_OUT`）；`monitor_ttl_ms` 到期后 loop 停止写入、`poll` 返回 `CLOSED`；`monitor_ttl_ms > 24h` 被拒绝；`monitor_ttl_ms = 0` 表示不自动关闭。**`monitor_ttl_ms` 部分属 v1**（见 AC-101），`capture_ttl_ms` 部分属 v1.1 | 通过 | FR-10.9 / C8 | 〔v1.1〕
| **AC-49** | 载荷视图在被取出后的 `retain_window` 次 poll 内保持有效；窗口结束后查询返回 `NOT_FOUND` | 通过 | FR-10.10 | 〔v1.1〕
| **AC-50** | `dump` 导出后可解析，内容与捕获时一致 | 通过 | FR-10.11 | 〔v1.1〕
| **AC-51** | 开启/关闭载荷捕获各产生一条审计事件 | 通过 | FR-10.12 | 〔v1.1〕
| **AC-52** | 审计记录不含业务载荷（`iocomm_audit_record` 为定长 POD，无 payload 字段，也无指针） | 通过 | FR-10.13 | 〔v1.1〕
| **AC-53** | SENT / RECEIVED / DELIVERED 三种事件在一次往返中均被记录，且 `capture_id` 单调递增、不复用 | 通过 | FR-10.1 / FR-10.2 |
| **AC-54** | `direction=BOTH`、`correlation_id != 0`、`slow_threshold_ms=1` 且注入 10 ms 延迟时产生 `SLOW`；阈值设 0 时不产生 | 通过 | FR-10.1 | 〔v1.1〕
| **AC-55** | `max_bytes < (ring_capacity+1) × sizeof(record)` 时，**字节上限先触发**，`monitor_stats.lost` 递增 | 通过 | FR-10.4 / 9.3 |
| **AC-56** | 审计序列固定为 `MONITOR_OPEN` →（`max_payload_bytes>0` 时）`CAPTURE_ON` → `capture_set(on=0)` 产生 `CAPTURE_OFF` → `monitor_close` 产生 `MONITOR_CLOSE`；`audit_fn` 按此顺序收到 | 通过 | FR-10.12 / FR-10.13 | 〔v1.1〕
| **AC-57** | manual 单线程模式下，在 loop 线程以 `timeout_ms=0` 调 `iocomm_monitor_poll` 成功返回（不返回 `WOULD_DEADLOCK`） | 通过 | FR-10.7 / FR-6.4 |
| **AC-58** | 以 `max_payload_bytes>0` 打开 → 自动产生 `CAPTURE_ON`；`capture_set(on=0)` 产生一条 `CAPTURE_OFF`；再 `capture_set(on=1)` 产生一条 `CAPTURE_ON` | 通过 | FR-10.14 / C7 | 〔v1.1〕
| **AC-59** | 入队失败（队列满）时**不产生 `SENT`**；策略为丢弃时产生 `DROPPED(QUEUE_FULL)`（接收侧）/ `DROPPED(BACKPRESSURE)`（发送侧 ERROR）| 通过 | FR-10.15 |
| **AC-60** | `direction=BOTH`、`correlation_id != 0`、单机往返 10 ms、`slow_threshold_ms=5` → 产生 `SLOW`；`direction=OUT` 或 `correlation_id==0` 时不产生 | 通过 | FR-10.16 | 〔v1.1〕
| **AC-61** | `audit_fn` 在多线程并发调用下无数据竞争（TSan/压力），且 `seq` 单调、无重复 | 通过 | FR-10.13 | 〔v1.1〕
| **AC-62** | `max_payload_bytes==0` 时 `capture_set(on=1)` 返回 `INVALID_STATE` 且**不产生**审计；已开启时重复 `on=1` 不重复产生审计 | 通过 | FR-10.14 / C7 | 〔v1.1〕
| **AC-63** | 显式 `monitor_close` 与 `monitor_ttl_ms` 到期各产生一条 `MONITOR_CLOSE` 审计；`runtime_destroy` 路径不产生 | 通过 | C11 / C9 | 〔v1.1〕
| **AC-64** | 持续满环（消费者不 poll）时 `monitor_stats.lost` 与 `degraded` 正确递增；预留 LOST 槽位的 `lost_count` 等于最近一批条数（`monitor_close` 前的尾批也须写入，1..1024）；消费恢复后 `poll` 能取得该 LOST 记录 | 通过 | FR-10.8 / C4 |
| **AC-65** | 取出记录后，在 `retain_window` 次 poll 内其 payload 视图有效且内容正确；窗口结束后查询返回 `NOT_FOUND` | 通过 | FR-10.10 / 9.3 | 〔v1.1〕
| **AC-66** | *（2026-10-21 随 `key` 删除撤销，编号不复用——见 §6）* | — | — |
| **AC-67** | `max_total_bytes` 耗尽后 `capture_set(on=1)` 返回 `RESOURCE_EXHAUSTED`；`capture_ttl_ms` 到期与 `max_total_bytes` 达到各产生一次 `CAPTURE_OFF` | 通过 | FR-10.9 / 9.4 | 〔v1.1〕
| **AC-68** | `monitor_ttl_ms` 到期后，消费线程下一次 `poll` 返回 `CLOSED`，期间无跨线程释放（压力测试 + TSan）。**v1 行为**（`monitor_ttl_ms` 属 v1；C11 中的审计部分属 v1.1） | 通过 | FR-10.4 / C9 |
| **AC-69** | 速率限制：`max_bytes_per_sec` 设为 1 MB/s，注入 10 MB/s → 超额消息置 `SAMPLED_OUT` 且 `capture_throttled` 递增，元数据完整；窗口滚动后恢复捕获 | 通过 | FR-10.9 | 〔v1.1〕
| **AC-70** | 非监控类审计：`endpoint_create`/`endpoint_destroy`/`connect`/`disconnect`/`subscribe`/`unsubscribe` 各触发一次对应 `iocomm_audit_kind` 的 `audit_fn` 调用；`runtime_start`/`stop`/`drain`/`endpoint_set_overflow` 产生 `CONTROL` 且 `detail` 为对应 `ICOMM_CTRL_*`；**`runtime_reconfigure` 只产生 `RECONFIGURE`（不重复记 `CONTROL`）**；`subject` 为操作句柄，`result` 为实际返回码 | 通过 | FR-10.13 | 〔v1.1〕
| **AC-71** | 多个监控者的**环预留总量**超过全局预算时，`monitor_open` 返回 `RESOURCE_EXHAUSTED`（`runtime_config.monitor_budget_bytes`） | 通过 | FR-10.17 / 9.3 |
| **AC-71b** | 环 + arena 的预留总量超过全局预算时 `monitor_open` 返回 `RESOURCE_EXHAUSTED`（v1.1 载荷捕获部分） | 通过 | FR-10.17 / 9.3 | 〔v1.1〕 |
| **AC-72** | 记录离开 `retain_window` 后，其占用的 `max_bytes` 被回收（持续捕获不会因总量口径而提前耗尽） | 通过 | FR-10.4 / 9.3 |
| **AC-73** | **整帧**（`20 + tlv_len + payload_len`）超过 `max_message_size`：同步发送返回 `TOO_LARGE`；异步经 `on_done(TOO_LARGE)` 且不入队；入站超大帧关闭连接并产生 `DROPPED(reason=TOO_LARGE)`。边界用例：payload 恰好使整帧等于上限时**成功**，多 1 字节即失败 | 通过 | FR-4.3 |
| **AC-74** | `conn_send_async` 带 `ICOMM_SEND_CLOSE_AFTER`：对端收到完整数据后观测到优雅 FIN，发送方 `on_done(OK)` 之后句柄为 `STALE_HANDLE`；对 `endpoint_send*`（扇出）使用该标志返回 `INVALID_ARGUMENT` | 通过 | FR-8.8 / FR-8.9 |
| **AC-75** | accept 回调内 `conn_send_async` 既未带 `CLOSE_AFTER`、也未先 `conn_retain`/`conn_subscribe`、**且该端点未启用端点级订阅/拉取** → 返回 `INVALID_STATE`；回调内 `conn_subscribe` 后不 retain，连接保持打开并能持续收数据 | 通过 | FR-8.8 |
| **AC-76** | 连接上有在途 `send_async` 时调用 `conn_destroy`：每条未完成发送的 `on_done` 恰好触发一次且 `code = CANCELLED`，连接随后关闭，无泄漏（AC-E3 口径） | 通过 | FR-8.9 |
| **AC-77** | `queue_timeout_ms=N` 的异步发送在队列长期写不出去时：`on_done(ICOMM_ERR_TIMEOUT)` **恰好一次**、产生一条 `DROPPED(TIMEOUT)`；`queue_timeout_ms=0` 时同场景不超时；**开始写之后不再超时**（注入慢传输，写的中途不发生超时） | 通过 | FR-6.3 / FR-10.3 |
| **AC-78** | 异步发送同步返回非 `OK`（含 `TOO_LARGE`、句柄失效）时 `on_done` **不被调用**；返回 `OK` 时 `on_done` 恰好一次。**边界**：`TOO_LARGE` 走同步返回，绝不走 `on_done` | 通过 | FR-6.1 / C ABI §6.2 |
| **AC-79** | `iocomm_runtime_node_id()` 返回的值与重启后一致；`runtime_config.node_name` 设置的字符串在 `iocomm_runtime_node_name()` 取回一致，且出现在对端发现快照的 `node_info.name` 中；未配置名字时为空串 | 通过 | FR-9.4 / FR-9.1 |
| **AC-80** | 同一进程内两个 Runtime 以 `inproc` 建连并双向收发，字节完全一致；接收回调**不在发送者的调用栈上执行**（回调内读取线程 id 校验） | 通过 | FR-3.5 / FR-3.7 |
| **AC-81** | 同进程内重复 `inproc` 名字 → `ALREADY_EXISTS`；两个进程用同一名字互不可见 | 通过 | FR-3.6 |
| **AC-82** | inproc 上**整帧**超 `max_message_size` 的发送返回/回调 `TOO_LARGE`（与 tcp 同口径）；`publish_local=1` + `inproc` → `INVALID_ARGUMENT` | 通过 | FR-3.8 / FR-3.9 |
| **AC-83** | owned 模式：主线程**从不调用** `run_once` 也能完成一次建连 + 往返收发；IO 线程恒为 1（子进程内枚举线程数验证） | 通过 | FR-6.5 |
| **AC-84** | `max_handles = 1` 时，第二次 `endpoint_create` 返回 `RESOURCE_EXHAUSTED`（不崩溃、不静默失败） | 通过 | FR-1.7 |
| **AC-85** | `discovery_lease_ms = 3000`：正常心跳续期只产生一次 `JOINED`；停掉对端后 ≤ lease 产生一次 `LEFT`，且快照中该节点被移除 | 通过 | FR-2.3 |
| **AC-86** | `FR-5.1` 四条件（**仅在已建立连接的句柄上观测**）：建连成功后 `connected = TRUE`、`lively = TRUE`；`healthy` 在**未满一个心跳判定周期前为 `UNKNOWN`**、满后变 `TRUE`；注入一次 `ERROR` 帧后 `healthy` 变 `FALSE`；`runtime_reconfigure` 后 `config_current` 由 `FALSE` 变 `TRUE`。**`connected = UNKNOWN` 的建连前/重连期观测已移出本 AC**——`iocomm_conn_status` 需要一个 conn 句柄，而 `connect*()` 在双向 HELLO 完成后才产出句柄（N-03）。重连期该子项已在 **AC-105**（N-06 定案：句柄复用）覆盖 | 通过 | FR-5.1 |
| **AC-87** | 发现快照：空快照 `count == 0` 且 `get(0)` 返回 `NOT_FOUND`；`index` 越界返回 `NOT_FOUND`；`release` 后再次 `release` 或任意 `get` 返回 `STALE_HANDLE` | 通过 | FR-2.8 |
| **AC-88** | 对端进程被 `kill -9`：≤ N 秒产生断开事件；随后对端重启并重新 `listen` 同一 pathname socket / 管道名，**无需人工删除残留文件即成功** | 通过 | FR-3.3 / FR-3.4 |
| **AC-89** | 两进程同时注册同名端点：**第二实例 `create` 返回 `CONFLICT` 且未注册**（本机查不到该端点——`endpoint_lookup` 返回 `NOT_FOUND`；`endpoint_name_state(<原名>)` 仍报 `HELD_BY_OTHER`，由第一实例持有）；同进程内重名 → `ALREADY_EXISTS`，同样不注册。两种情形第二实例都拿不到可用端点句柄 | 通过 | FR-1.4 / FR-1.5 |
| **AC-90** | **TLV 前向兼容**：测试用 `FakeTransport` 向接收方注入一帧，帧内带一个 v1 未定义的 tag（如 `0x00FF`，长度非 0）：接收方**正常投递**该消息、payload 与该帧里的一致、连接**不关闭**；同一帧去掉未知 tag 后结果完全相同（对照组）。再把该 tag 的 `len` 改成越界值 → 连接关闭并报帧损坏 | 通过 | [线格式 §3](api/wire-format.md#3-tlv-扩展区) / FR-4.3 |
| **AC-91** | 一个**未产生 `SENT`** 的报错路径（`TOO_LARGE`、句柄无效）留有环空位：`poll` **取不到任何记录**，`monitor_stats.emitted` 不变；对照组（同样的消息在队列未满时正常发送）产生 `SENT` | 通过 | FR-10.15 / 线格式 §3 |
| **AC-92** | `HELLO` 握手：① 双方互发后连接可用；② 未发 `HELLO` 直接发 `DATA` → 关闭且不投递；③ `min_version` 不满足 → `ERROR(VERSION_UNSUPPORTED)` 后关闭；④ `HELLO` 带 TLV → `ERROR(MALFORMED)`；⑤ **接收尺寸协商**：A 配 1 MiB、B 配 64 KiB，A 发 100 KiB → A 侧 `TOO_LARGE`（**不是** `on_done(OK)`）；⑥ 握手超时 → `ERROR(HANDSHAKE_TIMEOUT)` 后关闭；⑦ **交付时点**：`accept` 回调只在双向 HELLO 完成后触发——延迟对端发 `HELLO`（或故意只发 TCP 不握手）期间 `conn_count(ep)` 为 0、`accept` 未被调用；对端补发 `HELLO` 后 `accept` 触发一次且 `peer->peer_node_id == 对端 node_id`；握手超时/版本不兼容路径 `accept` **一次都不触发**（对照正常路径） | 通过 | [线格式 §2.1 / §5](api/wire-format.md) / FR-8.5 |
| **AC-93** | 发现报文编解码：对端以组播信标上报的节点表，`discovery_snapshot` 里的 `node_id` / `name` / 端点列表与发送端一致；单播 seed 路径与组播路径得到相同结果；未知字段（TLV）被跳过 | 通过 | FR-2.1 / FR-2.4 / FR-2.9 / [线格式 §8](api/wire-format.md) |
| **AC-94** | `iocomm_diagnostic_dump` 返回的 JSON：顶层含 `"version"` 与 `"connections"` 数组；每条连接至少含 `conn` / `peer_node_id` / `connected` / `send_queue_depth` / `recv_queue_depth`；`version` 与实际实现一致 | 通过 | FR-5.5 |
| **AC-95** | 头文件静态检查：导出的**每个** `iocomm_*` 函数都能在 [C ABI §3.2.1 矩阵](api/c-abi.md) 中找到对应行（无遗漏），且表中列出的码都在 `iocomm_error_code` 内定义。**排除** 6 个无错误通道的函数：`runtime_destroy` / `message_release` / `free_text` / `strerror` / `version_string` / `abi_version` | 通过 | [C ABI §3.2](api/c-abi.md) |
| **AC-96** | UDP 传输：两个 Runtime 经 UDP 互发有界消息，字节一致；**超过 MTU 的消息返回 `TOO_LARGE`**（不静默分片）；无连接时 `endpoint_send` 返回 `NO_RECEIVER`（v1.1） | 通过 | FR-4.2 | 〔v1.1〕 |
| **AC-97** | `iocomm_diagnostic_dump` 含 `"errors"` 数组（最近 **64** 条，v1.1 固定容量），每条含 `code` / `ts_ns` / `context`；满 64 条后环形覆盖（v1.1） | 通过 | FR-5.5b | 〔v1.1〕 |
| **AC-98** | 同机两进程共享同一 `node_id`（FR-9.3）：发现表按 `(node_id, process_epoch)` 区分出**两条**记录，各自 `JOINED`；同进程重启后 `process_epoch` 变化而 `node_id` 不变（v1.1） | 通过 | FR-9.3 | 〔v1.1〕 |
| **AC-100** | 队列双上限：注入 1 MiB 消息填满端点队列 → 在 **64 条**（64 MiB 字节上限）时按策略丢弃，而不是 1024 条；注入 1 KiB 消息 → 在 **1024 条**时丢弃（条数上限先到） | 通过 | FR-4.7 |
| **AC-102** | `endpoint_destroy` 时存在 `ep_owner == ep` 的出站连接且有未发消息：连接**仍存活**（`conn_status` 可查），未发消息在其连接队列里继续发出、对端收齐；该连接不再计入 `conn_count(ep)` | 通过 | FR-8.10 |
| **AC-101** | `monitor_ttl_ms > 24h` → `monitor_open` 返回 `INVALID_ARGUMENT`；`monitor_ttl_ms = 0` 不自动关闭；到期后 `poll` 返回 `CLOSED`（**v1 行为**，不含载荷捕获） | 通过 | FR-10.4 / C8 / C11 |
| **AC-99** | 协议级错误帧：对端收到超限帧 / 畸形帧时回 `ERROR(reason, detail)` 再关闭。**接收方的观测面**：① 该连接在途 `on_done` 为 `DISCONNECTED`；② `log_fn` 的 ERROR 级别输出含 `reason` 与 `detail`；③ `iocomm_stats.protocol_errors` 递增 | 通过 | FR-5.4 / [线格式 §2.1](api/wire-format.md) / NFR-3 |
| **AC-103** | **服务端扇出（N-01）**：纯服务端（不调 `connect*`）注册端点 A，3 个客户端分别连入并在 accept 回调内 `conn_subscribe`；随后 `endpoint_send(A, …)` 返回 `ICOMM_OK` 且 `out_delivered == 3`，3 个客户端均收到字节一致的消息；`conn_count(A) == 3`。对照组：3 条连接全部 `ep_owner == 0` 的出站连接时，对 A 扇出返回 `NO_RECEIVER` | 通过 | FR-8.6 / FR-8.11 |
| **AC-104** | **端点级订阅（N-02）**：`endpoint_create` 后**不注册** `endpoint_accept`，只调 `iocomm_subscribe(ep, on_msg)`；客户端 `connect` 并发送 3 条消息 → `on_msg` 收到 3 条、`conn_count(ep) == 1`（入站连接被端点隐式持有，未被 FIN）。对照组改用 `endpoint_recv(ep)`（prompt 拉取）得到同样结果；再对照：同一 `ep` 上先 `endpoint_recv` 再 `endpoint_accept` → 后者返回 `INVALID_STATE`（§6.4 互斥） | 通过 | FR-8.11 / FR-6.8 |
| **AC-105** | **重连语义（N-06）**：客户端 `connect` 后对端 `kill -9`，再用**同一** endpoint/地址重启。① **句柄复用**：断开前后及重连成功后 `iocomm_conn_t` 不变（`conn_status` 在重连窗口内仍可调用）；重连窗口内 `connected = FALSE`（不是 `UNKNOWN`——句柄已存在且确知未连通），`lively` / `healthy` 在心跳窗口未满前为 `UNKNOWN`，重连成功且窗口满后均为 `TRUE`；② **在途不重放**：断开前入队的 3 条未发消息在断开时各产生 `DROPPED(PEER_GONE)`、异步 `on_done(DISCONNECTED)` 各一次，重连成功后对端**一条也收不到**；③ **序号重置**：重连后首条消息的 `sequence` 从 1 重新开始（不接续断开前的值）；④ **订阅保持**：断开前已 `conn_subscribe` 的回调在重连后**无需重新订阅**即继续收到消息，`conn_status.peer_node_id` 更新为新对端的 `node_id`、`reconnect_count` 递增 | 通过 | FR-4.4 / FR-5.1 |
| **AC-106** | **端点级套接字参数（N-12）**：① `endpoint_config.tcp_nodelay = 0`（默认）与 `= 1` 时，`getsockopt(TCP_NODELAY)` 为 1、`= 2` 时为 0；非 0/1/2 → `endpoint_create` 返回 `INVALID_ARGUMENT`。② 同一参数在 `endpoint_config` 显式设 `2`、`tune_config.tcp_nodelay = 1` 时，按 §5.0「端点级 > tune」生效为端点值；`tune_config.tcp_nodelay` 只改**未被端点显式设置**的端点。③ `listen_backlog = 0` 时监听 socket 的 backlog 为 128（Linux `ss -lnt` 的 Send-Q 列），显式设 1 时同一时刻只允许 1 个已建立未 accept 的连接（第 2 个在 backlog 满后被拒/排队超时）；`tune_config.listen_backlog` 只对**新建**监听 socket 生效，已监听端点不变。④ 非 tcp / unix 传输（pipe / inproc）上设置这两个字段不报错（被忽略）；unix 上 `listen_backlog` 生效、`tcp_nodelay` 忽略 | 通过 | FR-4.8 |
| **AC-107** | **`connect_node` 地址解析（N-05）**：服务端以 `listen_addr = "0.0.0.0:0"` 监听（系统分配端口），客户端从发现快照取 `node_info.endpoints` 的 `addr` → **不是** `0.0.0.0:0`，而是实际 IP:实际端口；`connect_node(node_id, 端点名)` 成功往返。失败路径：端点名不存在 → `NOT_FOUND`；`node_id` 不在发现表 → `NOT_FOUND`；端点条目的 `transport` 为未实现值 → `NOT_SUPPORTED` | 通过 | FR-8.2 / FR-8.12 |
| **AC-108** | **端点名格式校验（N-17）**：`endpoint_create` 对以下名字各返回 `INVALID_ARGUMENT` 且**不注册**——① 空名（`name_len = 0`）；② `name_len = 256`（超 255 B）；③ 含 NUL 字节（如 `"a\0b"`，`name_len = 3`）；④ 空段：`"/a"`、`"a/"`、`"a//b"`；⑤ 非法 UTF-8（如孤立续字节 `"\x80"`、过长编码）。成功路径：`name_len = 255` 的 UTF-8 名、含 `/` 的合法层级名（`"plant3/line2/temp"`）均返回 `OK`。**区分度**：255 B 成功 vs 256 B 拒绝，边界两侧各一例 | 通过 | FR-1.8 |

### 5.2 平台验收

| 编号 | 验收项 | 判定 |
|---|---|---|
| AC-P1 | x86_64 Linux（glibc 2.17 基线）构建 + 全量测试通过 | 通过 |
| AC-P2 | ARM64 Linux 构建 + QEMU 全量测试通过；实机冒烟（跨机收发 + 发现） | 通过 |
| AC-P3 | Windows Server 2016：命名管道 IPC + TCP 收发 + 心跳超时判定 | 通过 |
| AC-P4 | 麒麟 V10 SP3 x86_64 / UOS 20 x86_64 实机：启动 + 同机 IPC + 跨机收发 | 通过 |
| AC-P5 | C ABI 头用 `gcc -std=c99` 与 `g++ -std=c++17` 各编译一次 | 通过（覆盖 FR-7.2） |

### 5.3 工程验收

| 编号 | 验收项 | 判定 |
|---|---|---|
| AC-E1 | 所有超时相关测试使用假时钟，单测总耗时 < 10 s | 通过 |
| AC-E2 | 崩溃类测试用子进程探针，只判退出码 `!= 0` | 通过 |
| AC-E3 | 1000 轮连接/断开后，fd / 句柄 / 内存增量有界（阈值待实测后定） | 通过 |
| AC-E4 | 产物 `readelf --version-info` 无高于目标 glibc 的符号 | 通过 |
| **AC-E5** | 24 小时 soak：内存与 fd 曲线斜率 ≈ 0，无未回收连接 | 通过 |
| **AC-E6** | 每个 P0 的 FR 至少对应一条 AC（用表格交叉核对） | 通过 |

---

## 6. 需求演进记录

| 日期 | 变更 |
|---|---|
| 2026-10-16 | 原始需求提出 |
| 2026-10-19 | 确认：独立 IO 库 / Rust 核心 / C ABI / x86_64+ARM64 / 排除国产私有架构 |
| 2026-10-20 | 新增 FR-10 消息级监控；移除 `ICOMM_ENDPOINT_SECRET`（监控改为独立对象） |
| 2026-10-22 | 同行对比后的修复：**HELLO 增加 `max_frame_bytes` 接收尺寸协商**（两端取较小值，避免「A 报成功、B 断连」）；新增 **`ERROR` 帧**（5 种 reason）+ AC-99；补**握手超时**；修正 TLV 固定开销 40 B → **73 B/帧**；写明共享队列的三条代价（慢 peer 挤占、队头阻塞、AC-8 只保证「不阻塞」）；队列增加 **64 MiB 字节上限**（默认 1024 条 × 1 MiB 最坏是 1 GiB）；定义此前空白的 `Healthy` 条件；统一 `timeout_ms = 0` 的两处歧义 |
| 2026-10-22 | 两轮独立审计（跨文档一致性 32 条 / 契约完整性 33 条）后的修复：补 §3.1 错误出参通用契约、§3.2 `@errors` 书写规则 + AC-95、§3.3 枚举/配置值合法性、§3.4 `hdr.size` 读写规则；定义 `endpoint_destroy` 完整语义与 Runtime 状态机；把发送队列明确为「端点共享队列 + 队列项携带目标连接」使 AC-76 可实现；定义 `endpoint_send_async` 部分失败与 `send_cancel` 的整组语义；补齐父子对象销毁表、回调内逐 API 的允许/禁止；修正丢弃原因分界（按**策略**而非方向，`QUEUE_FULL` 不再限接收侧）；`PEER_GONE` 分入队前/后两形态；统一 `max_message_size` 的**整帧**口径；修 `capture_set` 的 v1 返回码；配置优先级改为「越具体越优先」；loop 线程记录时机改回「首次确定、stop 前不变」；心跳 payload 补 `hb_ts_ns`；发现报文补 §8.1 寻址/MTU/分页并声明 tag 空间与帧 TLV 独立；AC-91 移 M3；M7 产出补 UDP / 错误环 / `process_epoch` |
| 2026-10-22 | 收敛复查修复：① SENT 澄清为「已入队 ≠ 已送达」，同步/异步同口径（FR-10.15 / AC-59）；② 丢弃原因分界先按方向、后改为按**策略**（`QUEUE_FULL` = DROP_* 策略丢消息，`BACKPRESSURE` = ERROR 策略拒绝）；AC-41 最终口径为「按策略 + 接收/发送各一」；③ `HELLO` 握手补 AC-92（M2）；④ 发现报文补线格式 §8 + AC-93（M4）；⑤ `diagnostic_dump` 定 JSON 键名 + AC-94（M3）；⑥ FR-4.2（UDP）降为 **v1.1**；⑦ `stats.audit_events` 明确 v1 计入 `log_fn` 的 AUDIT 事件；新增 AC-91（入队前失败不产生监控记录） |
| 2026-10-22 | 新增 AC-90（TLV 未知 tag 跳过的前向兼容验收，归 M2） |
| 2026-10-22 | 完成任务 C 全部 12 条遗留：FR-3.6 限定语（inproc 隔离只指 `listen_addr`）、FR-5.5 拆分（+FR-5.5b 最后 N 条错误 → v1.1）、FR-9.3 降 v1.1（v1 的 `node_id` 标识 Runtime 实例）、新增 AC-89；新建 `docs/api/wire-format.md`（D-06）；`c-abi.md` §9.0 新增 v1/v1.1 归属表；监控内存模型定稿为「逻辑配额 + 按需分配」；删除 `ICOMM_ENDPOINT_LOCAL`；`max_bytes` 默认值定死 4 MiB；平台矩阵删 MinGW、ARM64 Windows 标为不在产品范围 |
| 2026-10-21 | 完成任务 C 核实：40 条中 **C 37 / R 3**；本轮处置 25 条（其中新增 FR-2.8 / FR-6.8、AC-83–88），12 条仍待处置（D-05/06/07/09/13/16、B-03 残余/08/09/10/13/14）。推翻 D-08、B-06、B-12 |
| 2026-10-21 | 落实 D-11（`registry_plugin` 删除，中心注册表标 v2 评估项） |
| 2026-10-21 | M0 冻结前补三项缺口：① 异步发送补 **`send_options.queue_timeout_ms`**（0 = 无截止），并把 `on_done(OK)` 的完成点定为「**已完整交给传输层**」（同步路径同步对齐该含义；新增 AC-77 / AC-78；FR-10.3 的 `timeout` 口径）；② 补**节点名**（`runtime_config.node_name` + `iocomm_runtime_node_id()` / `iocomm_runtime_node_name()`，FR-9.4 / AC-79）；③ 补 **inproc** 的 FR-3.5–3.10 / AC-80–82，`listen_transport` 加入 `"inproc"`，并写明与 nng 的**有意分歧**（保留出站大小校验）。顺带落 B-01（UDP → v1.1）、B-04（FR-10.17 预算属 v1）、D-15（FR-3.4 措辞）、D-17 / D-19 / D-22 / D-23（AC 覆盖列与 AC 口径） |
| 2026-10-21 | 四项设计收敛（[ADR-002](adr/ADR-002-message-addressing-and-ownership.md)）：① 删除 per-message 路由键 `key`（撤销 **AC-66**，编号不复用）；② 删除 `delivery_class` 三档，溢出策略改为按端点（FR-4.5 加「按端点」；AC-26 重写；溢出策略枚举值改为 1–4、0 = 默认；`ICOMM_DROP_FILTERED` 撤销后 `iocomm_drop_reason` **紧凑重编号为 1–6**，并补哨兵 `ICOMM_DROP_NONE = 0`）；③ `accept` 改为借用语义 + 唯一 `conn_retain` + `SEND_CLOSE_AFTER`（新增 FR-8.8 / FR-8.9 / AC-74–76；AC-29 / AC-33 重写）；④ 审计由独立句柄/环改为创建期 `audit_fn`（FR-10.13 措辞；AC-56 / AC-61 / AC-70 / AC-71 调整）。同时修正 AC-48 的「M8」、AC-68 的「M11」两处不存在的里程碑引用 |
| 2026-11-03 | **N-01/N-02 裁决（方案 A：入站连接归监听端点）**：废止「入站连接不归属端点、不参与端点扇出」（`d8156aa` 引入，与 `architecture.md` endpoint 表、`c-abi.md`「所有已建立的连接」自相矛盾，导致纯服务端 `endpoint_send` 必返 `NO_RECEIVER`）。改为：**入站连接被持有后即成为监听端点的成员**——参与 `endpoint_send` 扇出、`conn_count(ep)`、与出站成员共用发送队列。持有动作扩为三种，新增**端点级持有**（FR-8.11）：启用 `iocomm_subscribe(ep)` / `endpoint_recv(ep)` 即隐式持有此后接入的入站连接，不注册 `endpoint_accept` 也能收消息；入站消息默认进端点接收队列，被 `conn_subscribe`/`conn_retain` 单独接管的连接改进连接队列（不双投）。同步修订：FR-8.6 / FR-8.8、AC-30（N 定义）/ AC-33（豁免）/ AC-39（入站计入）、新增 AC-103 / AC-104；`c-abi.md` §5.2 / §6.1 / §6.3 / §6.4、`architecture.md` §5.2、`README.md` 第 3 步注释 |
| 2026-11-03 | **N-03 裁决（accept 交付时点 = 双向 HELLO 完成，方案 1）**：tcp/unix/pipe 上 `accept` 回调在双向 `HELLO` 完成后才触发，`peer_node_id` 必有真实值，回调内 `CLOSE_AFTER` 发首条 DATA 合法；握手期连接是内部会话（不分配句柄、不占 `max_handles`、应用不可见）；握手失败/超时不产生 `accept`。inproc 无 HELLO，交付时点 = 建立即交付，`peer_node_id` 取对端 Runtime `node_id`（竞态下才为 0）。同步修订：FR-8.5、AC-92 新增第 ⑦ 项；`c-abi.md` §5.2 / §6.0 / §6.1、`wire-format.md` §5 / §7、`architecture.md` §5.2 / §5.2b、`README.md` 第 3 步注释 |
| 2026-11-04 | **N-04 / N-05 / N-06 / N-07 / N-12 处置**：① **N-04**：`node_id` 自动模式**只做 `state_dir` 持久化**，v1 **不派生**（machine-id / 主机名 / MAC 会违反「每 Runtime 独立」，掺随机盐会违反 FR-9.1）；`state_dir` 为空/不可写 → `INVALID_ARGUMENT`；FR-9.2 补充口径。② **N-05**：新增 **FR-8.12**（端点地址的**通告值**：通配地址/端口 0 替换为实际值，`endpoint_local_addr()` 仍返回原始监听值）与 FR-8.2 的解析规则（`name` 精确匹配 → `transport`+`addr`；`NOT_FOUND` / `NOT_SUPPORTED`）；新增 **AC-107**（归 M4）。③ **N-06**：FR-4.4 定四件事——句柄复用 / 断开即清空并 `DROPPED(PEER_GONE)` 不重放 / `sequence` 随连接重置 / 订阅保持且 `peer_node_id` 更新（架构新增 §5.2c）；新增 **AC-105**（归 M3），并回写 AC-86 的重连子项指向 AC-105。④ **N-07**：`heartbeat_ms = 2000`、`heartbeat_miss_limit = 3` 定为具体默认值（架构 §6.2 与 Healthy 定义、c-abi 注释同步，删除悬空引用）。⑤ **N-12**：新增 **FR-4.8** + `endpoint_config` / `tune_config` 尾部 `tcp_nodelay` / `listen_backlog` 字段（默认开 / 128；0 = 默认或保持）；**新增 AC-106**（归 M2）；v1 不暴露内核 keepalive（进非目标） |
| 2026-11-04 | **N-16 处置（废止「允许第二实例 + 自动改名」，依据见 [ADR-003](adr/ADR-003-endpoint-name-uniqueness.md)）**：跨进程同名端点改为 **fail-fast**——`endpoint_create` 返回 **`CONFLICT` 且不注册**；同进程同名仍 `ALREADY_EXISTS`。**理由**：`<name>#<pid>` 是远端无法预测的寻址身份（`connect_node` 按 `name` 精确匹配），自动改名既未实现「第二实例可被发现」的初衷，又让 `connect_node` 可能连到错误进程；且与 FR-1.4（P0「重名注册被拒绝」）直接冲突。删除 `ICOMM_ENDPOINT_UNIQUE` 宏（`flags` 改为 v1 保留字段，非 0 → `INVALID_ARGUMENT`）；保留 `endpoint_name_state()` 三态查询（仅注册前探测/诊断，权威是 `create()` 返回值）。同步修订：FR-1.4 / FR-1.5、AC-89、架构 §6.4、c-abi §5.1 / §3.2.1 / §10 |
| 2026-11-04 | **N-17 处置（端点名格式与长度上限）**：新增 **FR-1.8** + **AC-108**（归 M1）——端点名 UTF-8 编码后 **1–255 B**、不得含 NUL、合法 UTF-8、`/` 层级无空段，违反 → `INVALID_ARGUMENT`。补 [C ABI §5.1a](api/c-abi.md)（含与 `iocomm_endpoint_info.name_len`（`u16`）及 1400 B 发现分页的关系）。 |
