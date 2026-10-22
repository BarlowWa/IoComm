# IoComm 架构设计

> 状态：设计阶段 ｜ 相关：[需求](requirements.md) · [C ABI](api/c-abi.md) · [平台支持](platform-support.md) · [ADR-001](adr/ADR-001-language-and-platform.md)

---

## 1. 分层

```
┌──────────────────────────────────────────────────────────┐
│  应用（C / C++ / Python / Rust / 任意语言）                │
└───────────────────────┬──────────────────────────────────┘
                        │  纯 C ABI
┌───────────────────────▼──────────────────────────────────┐
│  iocomm-capi          C ABI 层：类型、版本协商、错误映射、  │
│                       panic 拦截、句柄翻译                  │
├──────────────────────────────────────────────────────────┤
│  iocomm               门面：Runtime / Handle / Subscription │
│                       同步壳 · 事件分发 · 生命周期           │
├──────────────┬──────────────┬────────────────────────────┤
│  iocomm-     │  iocomm-     │  iocomm-monitor             │
│  transport   │  discovery   │  心跳 · 指标 · 诊断快照       │
│  tcp/unix/   │  组播/单播    │                             │
│  pipe/inproc │  seed/本机    │                             │
├──────────────┴──────────────┴────────────────────────────┤
│  iocomm-core         事件循环（mio）· 计时器 · 缓冲区 ·     │
│                      句柄表 · 会话状态机 · 错误码            │
└──────────────────────────────────────────────────────────┘
```

**依赖方向单向向下**。`capi` 依赖 `iocomm`；`iocomm` 依赖各域 crate；所有域 crate 依赖 `core`。**`core` 不依赖任何域 crate。**

---

## 2. Crate 划分

| Crate | 职责 | 依赖 |
|---|---|---|
| `iocomm-core` | 事件循环、计时器、缓冲、句柄表、错误码 | `mio` |
| `iocomm-net` | 传输抽象 trait（`Transport` / `Listener` / `Conn`）+ 地址模型 | `core` |
| `iocomm-transport` | 传输实现（tcp / unix / pipe / inproc；udp 为 v1.1）。Windows 管道优先用 `mio::windows::NamedPipe`，自研为备选。地址解析可直接用 `socket2`（ADR-001 依赖清单） | `core`, `net` |
| `iocomm-discovery` | 发现策略 trait + 实现（可复用 `net` 的 socket 封装） | `core`, `net` |
| `iocomm-monitor` | 心跳、指标、诊断、**消息监控环形缓冲**、审计事件产生点（纯回调 sink，无环、无句柄） | `core` |
| `iocomm` | 门面、会话、同步壳、事件分发、**远端寻址与连接管理** | 上面全部 |
| `iocomm-capi` | C ABI，产出 `staticlib` / `cdylib` | `iocomm` |

> **修正**：`discovery` 与 `monitor` 原先只依赖 `core`，不闭合。发现需要 socket 封装（`net`）；监控需要读取会话/传输计数，因此由 `iocomm` 在装配时注入一个 `MetricsSource` trait（定义在 `core`），`monitor` 只依赖 trait 而非具体传输。

### 2.1 监控子系统

```
消息路径（loop 线程）
  send/recv → 会话 → [信封事件打点] → 环形缓冲（每监控者一份）
                                      ↑ 无锁 SPSC，满则丢并计数
  DROP 路径  → [丢弃事件打点] ────────┘

poll（任意线程，同一 monitor 串行）→ 取记录 → 调用方消费
```

| 约束 | 实现 |
|---|---|
| 不反压主链路 | 入队用 `try_push`，失败只计数 |
| 零同步 I/O | 热路径只写定长记录 + 可选 memcpy 进 arena |
| 独立队列 | 每监控者一个 SPSC 环，生产端 loop 线程 |
| 载荷捕获 | 深拷贝进监控自有 arena（不共享传输缓冲） |
| 监控内存模型 | **逻辑配额 + 按需分配**：`max_bytes` 是**记账上限**，不是预留量；`monitor_budget_bytes` 是各 monitor **已提交配额之和**。记录与槽位按需分配、离开 `retain_window` 时归还（AC-72 的前提）。v1.1 的载荷 arena 仍按工作集预分配。超预算（配额之和）返回 `RESOURCE_EXHAUSTED`；热路径不分配 |
| 事件来源 | `core` 定义 `MonitorSink` trait；会话/传输在打点处调用它，**`core` 不依赖域 crate** |
| poll 线程 | 只读私有环、不依赖 loop 推进，故 loop 线程也允许 `timeout_ms=0` 的非阻塞 poll |
| 视图保留 | 记录被 poll 取出后，其**槽位与 arena 块**在 `retain_window` 次 poll 内不复用（消费端持有引用计数） |
| TTL 释放 | `monitor_ttl_ms` 到期时 loop 线程**只置 expired 标志**；资源由消费线程在下次 `poll` 中释放 |
| 监控自监控 | 丢记录时 `stats.lost++`、`degraded=1`；每 1024 次由生产端聚合写一条 `LOST` |
| 审计 | **创建期固定的回调 sink**（`runtime_config.audit_fn`），事件产生点在各 API 入口，**在生产线程上同步调用**。无环、无句柄、无 poll；`audit_fn == NULL` 时回退 `log_fn` 的 AUDIT 类别。回调必须线程安全且不得阻塞、不得重入（见 C ABI §9.5） |

**可插拔点**（运行期 trait 对象）：

- `Transport`：tcp / unix-socket / named-pipe / inproc（udp 为 v1.1）
  > `inproc` 不参与发现：`publish_local = 1` 时 `endpoint_create` 返回 `INVALID_ARGUMENT`（见 [需求 FR-3.9](requirements.md)）
- `Discovery`：multicast / unicast-seed / local-registry
- `Clock`：生产用稳态时钟；测试用假时钟
- `Transport` 的测试实现：`FakeTransport`（内存队列 + 故障注入）

---

## 3. 线程模型

### 3.1 两种运行模式

| 模式 | 谁驱动 | 适用 |
|---|---|---|
| **托管**（`Runner`） | 库自带 **1 个** IO 线程 | 普通应用、快速上手 |
| **调用方驱动**（`run_once` / `run_for`） | 宿主线程 | 工业单线程控制循环、确定性测试 |

两种模式**共享同一实现**。这是硬要求：只有托管模式的库写不出确定性测试。

> **IO 线程数固定为 1。** 所有 IO、定时器、回调都在该线程上执行。不做 work-stealing 多线程——那会让「回调无锁」的承诺失效（见 3.3）。
> **`iocomm_runtime_config.owned_threads` 已移除**：它允许多 IO 线程，与本节契约冲突。

### 3.2 线程归属与「谁在驱动 loop」

- **一个事件循环线程**处理所有 IO、定时器、回调。
- 回调**只在事件循环线程**上执行 —— 用户无需在回调里加锁。
- 同步 API（`send`/`recv`/`unsubscribe`）阻塞**调用者线程**，**不占用事件循环线程**。

#### manual 模式的硬约束

manual 模式下**只有一个宿主线程**在驱动 loop。因此：

| 情形 | 行为 |
|---|---|
| 在 **loop 驱动线程**上调用同步 API | **返回 `ICOMM_ERR_WOULD_DEADLOCK`**，不阻塞 |
| 在**其他线程**上调用同步 API | 允许；该线程阻塞等待，loop 线程继续推进 |
| manual 模式下 `runtime_drain` | **不接受阻塞调用**——传入 `timeout_ms = 0` 并在外部循环调用 `run_once` 直到返回 `ICOMM_OK` |
| **manual 模式建连** | **必须用 `iocomm_connect_async` / `iocomm_connect_node_async`**；同步 `iocomm_connect` 在 loop 线程上会返回 `WOULD_DEADLOCK` |

> **`iocomm_runtime_drain` 的「返回时保证已排空」只对 owned 模式成立**；manual 模式改为「drain 返回 `ICOMM_ERR_WOULD_BLOCK` 表示仍有在途操作，调用方应继续 `run_once`」。

### 3.3 线程安全契约

| 对象 | 线程安全 |
|---|---|
| `Runtime` / 端点 / 连接 / 订阅的**创建与销毁** | 否（调用方串行化） |
| `run_once` / `run_for` | 否（仅 loop 线程） |
| 端点/连接/订阅的 `count/get` | 否（loop 线程或串行化） |
| `*_send_async` / `connect*_async` / `runtime_wakeup` | **是**（内部投递到 loop） |
| `conn_send` / `endpoint_send` / `*_recv` / `unsubscribe`（同步） | 否（一句柄一线程；loop 线程调用返回 `WOULD_DEADLOCK`） |
| `runtime_reconfigure` | **是**（内部投递到 loop，异步生效） |
| `subscribe` / `conn_subscribe` / `discovery_start` / `discovery_stop` | 否（调用方串行化，或经 `run_once` 线程调用） |
| 指标快照 `iocomm_stats_snapshot` / `conn_status` / `monitor_get_stats` | **是**（返回拷贝） |
| `monitor_poll` / 载荷查询 / `monitor_dump` / `monitor_close` | 否（同一 monitor 单线程串行；SPSC 消费端） |
| `monitor_open` / `capture_set` | **是**（内部加锁或投递到 loop） |

> **异步发送与句柄销毁的竞态**：异步发送只接收**连接句柄或端点句柄**，内部先做代际校验再入队；调用方必须保证「不再对某对象发起异步操作之后」才销毁它。文档写死这条顺序，**不做隐式同步**——与 ZeroMQ / Asio 的惯例一致。

> **线程检测的生产语义**：`WOULD_DEADLOCK` 是**生产行为**，不是调试断言。实现方式是：Runtime 在首次 `run_once`（manual）或启动 IO 线程（owned）时记录 loop 线程 ID；该 ID 在 `stop` 前保持不变，所有同步入口比对它。首次 `run_once` 之前 loop 线程未确定，同步 API 允许调用（此时不可能有在途操作）。

---

## 4. 事件循环

```
mio::Poll
  ├─ 注册的 socket（读/写就绪）
  ├─ 唤醒机制（eventfd / 跨线程 task 队列）
  └─ 最近到期时间（决定 poll 超时）

每轮 run_once：
  1. 从跨线程队列取出待执行任务，执行
  2. poll(timeout = min(下一计时器, 队列为空则阻塞))
  3. 处理就绪事件 → 会话状态机 → 分发
  4. 执行到期计时器
```

- **不绑 tokio**：tokio 会拥有线程与调度器，与本库「调用方驱动」的要求冲突。
- 跨线程投递用**无锁队列 + 唤醒 fd**（Windows 用 `IOCP` 的 post 机制或 event）。
- **计时器**：最小堆 + 单调时钟。所有超时经 `Clock` trait，测试可注入。

---

## 5. 核心数据结构

### 5.1 句柄表（索引 + 代际）

```
Handle = u64
  ├─ 低 32 位：索引（从 1 起，0 保留为无效句柄）
  └─ 高 32 位：代际（从 1 起，0 保留）
```

- 创建：索引从 1 分配、代际从 1 开始。**第一个合法句柄是 `(1<<32)|1`，绝不为 0。**
- 销毁：`generation += 1`，对象释放。
- 查找：**先校验句柄种类**，再比对代际；任一不符 → `STALE_HANDLE`。
  > 六类对象（Runtime / endpoint / conn / subscription / snapshot / monitor）共用同一张表，但**种类是句柄的一部分**：把 `conn` 句柄传给 `endpoint_*` 函数会被拒绝，而不是被当成同号对象误用。**审计没有句柄**（回调 sink）。
- **绝不传裸指针**，跨 FFI 只传 `u64`。

> 槽位记录 `{kind, generation, object}`；`kind` 区分 Runtime / endpoint / conn / subscription / snapshot / **monitor**。C ABI 中**不出现 `void*` 型的不透明对象**。

### 5.1b 节点身份（NodeId）

节点身份必须**跨进程重启保持稳定**，否则「重启后被识别为同一逻辑节点」（AC-9）无法成立。

```
NodeId = u64
  ├─ 落盘持久化：首次运行生成随机 64 位，写入配置目录
  └─ 不可写时（只读文件系统）：从 machine-id / 主机名 / MAC 派生稳定哈希
```

- 配置入口：`iocomm_runtime_config.node_id`（0 = 自动）。
- 自动模式下，库在 `state_dir` 下读写 `node_id` 文件；`state_dir` 通过配置指定。
- **v1 语义：`NodeId` 唯一标识一个 Runtime 实例**，同机多进程各自拥有独立 NodeId（不共享）。
  「同机多进程共享主机身份、用 `(NodeId, process_epoch)` 区分」是 **v1.1** 的扩展（FR-9.3），v1 不实现 `process_epoch`，任何 C 结构体里也没有这个字段。

### 5.2 对象模型：端点 / 连接 / 订阅

这三个概念**必须分开**，否则「发给谁」无法表达：

```
                     ┌──────────────────────────────┐
   本地监听端点       │ iocomm_endpoint_t             │
   （具名、可发现）    │  name / listen_addr / flags   │
                     └───────┬──────────────┬────────┘
                             │ accept       │ connect
                             ▼              ▼
                     ┌──────────────────────────────┐
   连接（双向）        │ iocomm_conn_t                 │
   （入站 or 出站）    │  peer / 状态 / 收发队列        │
                     └───────┬──────────────────────┘
                             │ subscribe / recv
                             ▼
                     ┌──────────────────────────────┐
   订阅                │ iocomm_subscription_t         │
                     └──────────────────────────────┘
```

| 对象 | 语义 | 发送目标 | 接收来源 |
|---|---|---|---|
| **endpoint** | 本地具名监听者 | **扇出**到它的所有连接 | 它的所有入站连接 |
| **conn** | 一条双向连接 | **点对点** | 该连接 |
| **subscription** | 推送回调的注册 | — | — |

**入站连接**由 `iocomm_endpoint_accept()` 注册的回调交付。回调内的句柄是**借用**：只在回调期间有效。持有动作只有两种——**显式 `conn_retain`**（拉取）与**隐式 `conn_subscribe`**（推送，订阅即所有权）；两者都不调则回调返回时自动收回并以 FIN 优雅关闭。「发完即关」用发送选项 `ICOMM_SEND_CLOSE_AFTER`，`conn_send_async` 本身不是所有权开关。完整契约见 C ABI §5.2 与 [ADR-002](adr/ADR-002-message-addressing-and-ownership.md)。

> **连接由 `connect*()`（出站）或 `accept`（入站）创建**，状态迁移在 `iocomm_conn_t` 上发生。关闭有四条路：`conn_destroy`（取消在途、丢弃缓冲、FIN）、`conn_close_graceful(linger_ms)`（flush 后关）、`ICOMM_SEND_CLOSE_AFTER`（发完即关）、`conn_abort`（RST 异常中止）。

### 5.2b 连接状态机

> 连接由 `connect*()`（出站）或 `accept`（入站）创建，状态迁移在 `iocomm_conn_t` 上发生。

```
        ┌──────────────┐
        │ Disconnected │
        └──────┬───────┘
               │ iocomm_connect() / iocomm_connect_async()
        ┌──────▼───────┐
        │  Connecting  │
        └──────┬───────┘
    失败 │      │ 成功
        │   ┌──▼────────┐
        │   │ Connected  │
        │   └──┬────┬───┘
        │      │    │ 心跳超时 / 断开
        │      │    ▼
        │      │ ┌──────────────┐
        └──────┴▶│ Reconnecting  │── 退避 ──┐
                 └──────────────┘◀──────────┘
```

> **入站连接**由 `accept` 直接进入 `Connected`（不需要 Connecting）。重建由对端发起。

**状态是条件集，不是单一枚举**（见 [需求 FR-5.1](requirements.md)）：

| 条件 | 取值 |
|---|---|
| `Connected` | True / False / Unknown |
| `Lively` | True / False / Unknown |
| `Healthy` | True / False / Unknown —— **定义**：最近一次心跳判定周期（`heartbeat_ms × max(heartbeat_miss_limit,1)`，默认 3 个心跳周期）内既**没有重连**、也**没有收到 `ERROR` 帧**；`Unknown` = 该连接尚未经历满一个周期 |
| `ConfigCurrent` | True / False |

上层按需查询，新增条件不破坏既有判断。**状态变化通过 `iocomm_condition_fn` 回调推送**（见 C ABI §8），同时保留拉取式查询。

### 5.3 消息

```
Message {
    from                // 来源连接 → C ABI: iocomm_conn_t
    source_node         // 来源节点 NodeId
    sequence            // per-source 单调序号（排序与检漏的权威）
    timestamp           // 发送方事件时间（附时钟同步状态）
    correlation_id      // 请求-应答关联
    payload             // 不透明字节
}

**发送成功 ≠ 对端收到**

`send` / `on_done(OK)` 的完成点统一定义为「**消息已完整交给传输层**」（OS 已接受），不是「对端已收到」。
本库没有 ACK / 重传 / 去重 / 会话恢复，端到端确认属于应用层。异步发送另有 `send_options.queue_timeout_ms`
约束「入队 → 开始写」这一段（超时产生 `DROPPED(TIMEOUT)`）；**开始写之后不再超时**——字节流中途放弃只能 RST 整条连接。
```

> **没有 per-message 路由键**：v1 删除 `key`（ADR-002）。「消息类型」不是通信层的概念——需要时放进 payload 或拆成不同端点；v2 若要做 pub/sub，走**接收侧层级过滤**（端点名按 `/` 分段，L2），不引入 per-message 键。

**头部定长 + TLV 扩展区**：实时路径一次定长解析即可决策，新字段前后兼容。

> **ABI 映射**：`from`、`sequence`、`timestamp`、`correlation_id` 必须全部出现在 `iocomm_message` 中，否则请求-应答与「收到后回发」无法跨越 FFI（见 C ABI §6）。

---

## 6. 关键机制

### 6.1 帧与背压

- 有界消息：长度前缀，库内分帧，**不暴露字节流**。
- **溢出策略按端点配置，不是全局一个开关**：一个端点 = 一条发送队列 + 一条接收队列 + 一个策略（ADR-002）。

| 业务类别 | 表达方式 | 典型策略 |
|---|---|---|
| 过程数据 | 一个专门端点 | 丢最旧（keep-latest） |
| 事件 / 报警 | 一个专门端点 | 阻塞（同步发送）/ 报错 |
| 命令 | 一个专门端点 | 报错 |

- **没有「投递类别」**：本库没有 ACK / 重传 / 去重 / 会话恢复，`send` 成功只表示**已完整交给传输层**（at-most-once）。`AT_LEAST_ONCE` / `RELIABLE` 这类名字会让上层误以为「不会丢」，已删除。队列满策略与投递保证是两回事（MQTT 的 QoS 与 Receive Maximum、DDS 的 RELIABILITY 与 HISTORY 也是分开的）。
- **`BLOCK` 只在同步发送上真阻塞**（至 `timeout_ms`）；异步发送与接收侧入队发生在「必须立即返回」或 loop 线程上，`BLOCK` 自动退化为 `ERROR` 并计数——否则唯一的事件循环线程会自锁。
- **丢弃必须计数并可读** ——「丢了但没人知道」比「丢了并报警」危险得多。

### 6.2 心跳与存活

- 应用层心跳（**不依赖内核 keepalive**，其默认 2 小时且 Windows Server 2016 缺 `TCP_KEEPIDLE`）。
- 心跳带**序号 + 时间戳 + 双向确认**（消除单向故障盲区）。
- 判定：连续 N 次未收到 → `Lively = False`；N 可配，默认 ≥ 3。
- 重连：**Full jitter 退避**（`random(0, min(cap, base*2^n))`），cap 10–30s。

### 6.3 发现

**两阶段**（借鉴 DDS）：

1. 阶段一：节点存在性（轻量心跳 + 地址）
2. **阶段二：端点能力**（事件驱动，单播）——节点上报自己**注册了哪些句柄**，供远端 `connect` 使用

**三件套 + 一档**：

| 机制 | 用途 | 节点规模 |
|---|---|---|
| 组播信标 | 默认 | < 20 |
| 单播 seed 列表 | 组播不可用 / 跨网段兜底 | < 200 |
| **中心注册表（v2 评估项）** | 可配置的外部 discovery server | **≥ 200** |
| 本机注册表 | 同机进程 | 任意 |

> `inproc`（同一进程内的 Runtime 之间）**不进任何发现表**——它已经在同一地址空间里，没有「发现」可言。

> **20 节点是分水岭**（调研结论）。v1 **不提供**中心注册表，也不保留加载语义未定义的 `registry_plugin` 字段（D-11 / E-3：空操作字段会让调用方误以为生效）。v2 视需求引入，属新增入口而非 ABI 变更。

**必须做对**：出接口选择（`IP_MULTICAST_IF` / 接口索引）、源地址校验、幂等去重（元信息未变不触发事件）。

> **快照枚举**：除事件回调外，提供 `iocomm_discovery_snapshot_take/count/get/release` 四个函数，供晚加入者一次性获取当前节点表。

### 6.4 跨进程名表（FR-1.5 三态查询）

`iocomm_endpoint_name_state()` 要区分「空闲 / 本进程持有 / 他进程持有」，必须有**跨进程协调机制**：

| 平台 | 机制 |
|---|---|
| **Linux** | 以端点名派生一个**抽象命名空间 socket**（`@iocomm/<hash>`）。bind 成功 = 抢到；`EADDRINUSE` = 他进程持有。本进程自持的名字先查本地表。抽象命名空间**零残留**（进程死亡自动释放） |
| **Windows** | 命名内核对象 `Global\iocomm_<hash>`（`CreateMutexW` + `ERROR_ALREADY_EXISTS`）。进程退出时内核自动回收句柄 |
| **本机 IPC（unix/pipe）** | 复用同一套名字锁；实际 socket 文件放 `/run/iocomm/` 或命名管道，不在 `/tmp` |

**规则**：
- **默认所有具名端点都做跨进程唯一性检查**（不要求 `UNIQUE` 标志），**与传输后端无关**——inproc 端点同样参与（inproc 的「跨进程隔离」只针对它自己的 `listen_addr`，见 [FR-3.6](requirements.md)）；`UNIQUE` 只影响「重复注册时是拒绝还是允许第二实例」。若允许第二实例，第二实例收到 `CONFLICT` 但可改名为 `<name>#<pid>` 继续。
- 名字 → 锁的映射用**稳定哈希**（同一名字在同一机器上恒定）。
- **残留处理**：Linux 抽象命名空间与 Windows 命名对象都由内核在进程退出时回收，**不需要手工清理**；pathname socket 的残留清理见 [平台支持 §3.2](platform-support.md)。
- 判定结果不是原子的：`name_state()` 查询与随后 `create()` 之间存在 TOCTOU 窗口。**`create()` 的返回值才是权威**，`name_state()` 仅用于诊断与友好提示。

### 6.5 时间

| 用途 | 时钟 |
|---|---|
| 超时 / 心跳 / RTT / 退避 | **单调时钟**（`steady_clock` 语义） |
| 事件时间戳 / 日志 | 挂钟（附同步状态标志） |

**排序以序号为权威，不以时间戳为权威**（跨机挂钟不可信）。

---

## 7. 可测试性设计（反向约束接口）

这些不是测试技巧，而是**接口要求**：

| # | 要求 | 接口表现 |
|---|---|---|
| T1 | 事件循环可手动驱动 | `run_once()` / `run_for()` / `run_until()` |
| T2 | 时间可注入 | 所有超时经 `Clock` trait；内核零处直接读时钟 |
| T3 | 传输可替换 | `Transport` trait；`FakeTransport` 做测试；`inproc` 让 M1 不碰 socket 也能验完整个模型 |
| T4 | 端口可协商 | `listen(0)` 后 `local_port()` 可读 |
| T5 | 线程归属可校验 | 调试构建下检查归属线程，违反返回错误 |
| T6 | 定时器可枚举 | `pending_timer_count()` |
| T7 | 故障可注入 | 丢包 / 乱序 / 重复 / 分配失败 |
| T8 | 指标可读 | 从**公开** API 读，不做后门 |
| T9 | 无内部线程模式 | 与托管模式共享实现 |

---

## 8. 错误模型

```rust
// 内部名 → ABI 值映射。**`C ABI §3` 是唯一权威**，此处必须逐值对齐。
enum ErrorCode {
    Ok              = 0,
    InvalidArgument = 1,
    NotFound        = 2,
    AlreadyExists   = 3,
    Conflict        = 4,   // 端点名被其他进程占用
    StaleHandle     = 5,
    WouldDeadlock   = 6,
    NotSupported    = 7,
    InvalidState    = 8,
    Timeout         = 10,
    WouldBlock      = 11,
    Closed          = 12,
    Disconnected    = 13,
    Cancelled       = 14,
    NoReceiver      = 15,
    ResourceExhausted = 20,
    TooLarge        = 21,
    Internal        = 100,
}
```

- **超时是正常结果，不是错误**（独立码）。
- 运行期通信错误走返回码；构造/配置错误也走返回码（**C ABI 不抛异常**）。
- 错误码是 ABI 的一部分：**只追加，不改值**。

---

## 9. 已决问题（原未决项的处理）

原列出的 4 个未决问题，在 API 冻结前必须定，否则会造成「先冻结接口、后讨论」的倒挂：

| # | 原问题 | 处理 |
|---|---|---|
| Q1 | 拉取式 `recv` 与推送式 `subscribe` 是否并存 | **并存，但同一接收对象上互斥**（C ABI §6.4） |
| Q2 | 零拷贝的借用期形态 | **v1 不提供**：`send_async` 立即拷贝入队。零拷贝留到 v2 作为 `loan` API |
| Q3 | 是否兼容 mDNS | **v1 不做**；作为独立 discovery 插件后置 |
| Q4 | 控制面是否独立通道 | **v1 不独立**；控制面与数据面共用按端点的队列。v2 视需要再分 |
| Q5 | 是否提供 per-message 路由键（`key`） | **v1 删除**（ADR-002）。控制用端点名；v2 若需过滤，走接收侧层级过滤 |
| Q6 | 溢出策略按「投递类别」还是按端点 | **按端点**（ADR-002）。三类业务用三个端点表达；删 `delivery_class` 三档 |
| Q7 | `accept` 的所有权模型 | **借用 + 唯一 `conn_retain`（subscribe 隐式持有）+ `CLOSE_AFTER`**（ADR-002）。不用「四选一接管」，也不用返回值枚举 |
| Q8 | 审计是否给独立句柄 / 环 | **不**。创建期不可变的 `audit_fn` 回调 sink；计数并入 `stats.audit_events`（ADR-002） |

> **控制面落点**：`iocomm_runtime_start/stop/reconfigure/drain` 已在 C ABI §4 定义。

---

## 10. 实施顺序、里程碑与工作量

### 10.1 里程碑（每个里程碑都有可验收产出）

| # | 里程碑 | 产出 | 验收 |
|---|---|---|---|
| **M0** | 骨架 | C ABI 头（C99 可编译）+ crate 划分 + CI 三平台构建 | AC-P1 / AC-P5 / AC-18 / AC-24 / AC-35 / AC-95 |
| **M1** | inproc 闭环 | 句柄表（代际）+ Runtime + 端点/连接模型 + **跨进程名字表（§6.4）** + `inproc` 传输（FR-3.5–3.10） | AC-4 / AC-11 / AC-25 / AC-32 / AC-33 / AC-36 / AC-40 / AC-80 / AC-81 / AC-82 / AC-83 / AC-84 / AC-89 |
| **M2** | TCP + 双向 | tcp 传输 + accept + connect + send/recv/subscribe + 异步排队超时 + **[线格式](api/wire-format.md)（含 HELLO 握手）** | AC-1 / AC-2 / AC-10 / AC-29 / AC-30 / AC-31 / AC-33b / AC-39 / AC-73 / AC-74 / AC-75 / AC-76 / AC-77 / AC-78 / AC-90 / AC-92 / AC-99 |
| **M3** | 状态与监控 | 心跳 + 条件集 + 指标 + 诊断（JSON 结构见 AC-94）+ **消息监控（信封级）** | AC-3 / AC-5 / AC-6 / AC-12 / AC-13 / AC-15 / AC-20 / AC-27 / AC-28 / AC-37 / AC-41 / AC-42 / AC-43 / AC-44 / AC-45 / AC-53 / AC-55 / AC-57 / AC-58 / AC-59 / AC-64 / AC-68 / AC-71 / AC-72 / AC-86 / AC-91 / AC-94 |
| **M4** | 发现 | 组播 + 单播 seed + 节点身份 + 阶段二端点能力 + **[发现线格式](api/wire-format.md#8-发现报文阶段一--阶段二)** | AC-7 / AC-9 / AC-14 / AC-16 / AC-21 / AC-22 / AC-23 / AC-34 / AC-38 / AC-79 / AC-85 / AC-87 / AC-93 |
| **M5** | 本机 IPC | Linux unix socket + Windows 命名管道 | AC-P3 / AC-8 / AC-17 / AC-19 / AC-26 / AC-88 |
| **M6** | 平台与加固 | 麒麟/UOS 实机 + glibc 2.17 基线 + soak | AC-P1 / AC-P2 / AC-P3 / AC-P4 / AC-P5 / AC-E1 / AC-E2 / AC-E3 / AC-E4 / AC-E5 / AC-E6 |
| **M7** | **v1.1** 载荷捕获与审计 | arena / 限速 / 双 TTL / dump / 审计 sink 回调（`audit_fn`）/ SLOW / **UDP 传输** / 错误环（FR-5.5b）/ `process_epoch`（FR-9.3） | AC-46 / AC-47 / AC-48 / AC-49 / AC-50 / AC-51 / AC-52 / AC-54 / AC-56 / AC-60 / AC-61 / AC-62 / AC-63 / AC-65 / AC-67 / AC-69 / AC-70 / AC-71b / AC-96 / AC-97 / AC-98 |

### 10.2 关键路径

```
M0 ──► M1 ──► M2 ──┬──► M3
                   └──► M4
                          └──► M5 ──► M6
```

**M2 是关键路径的瓶颈**：同时依赖「连接/端点模型」与「传输抽象」，任何一处返工都会顺延 M3–M6。

### 10.3 SPIKE（先于实现，用于消除不确定性）

| Spike | 目的 | 判据 | 失败则 |
|---|---|---|---|
| **S1 工具链** | x86_64 / aarch64 / WS2016 上编出 C ABI 的 staticlib + cdylib | 三平台跑通最小 TCP echo | 重评语言（ADR-001 翻转条件） |
| **S2 Windows 命名管道** | 验证 `mio::windows::NamedPipe` 可用性（**首选**）或自研 overlapped IO（备选） | 能完成 pipe 收发并接入同一 loop | 回退 loopback TCP（约 2× 延迟） |
| **S3 发现** | 组播/多网卡/单播兜底 | 1 s 内发现、无假阳性、切网卡能恢复 | 单播 seed 成为默认路径 |

### 10.4 工作量估算（人日，1 名熟悉 Rust 的工程师）

| 模块 | 估算 | 说明 |
|---|---|---|
| C ABI 层 + 版本协商 + 测试 | 8–12 | 含坏对端矩阵 |
| core（loop / 计时器 / 句柄表 / 缓冲） | 15–25 | mio 之上自研 |
| 端点 / 连接 / 会话状态机 | 20–30 | 含 accept、重连、条件集 |
| transport: inproc | 2–3 | 进程内名字表 + 队列投递；**复用消息抽象，不走线格式**（[线格式 §7](api/wire-format.md)） |
| **跨进程名字表（§6.4）** | **3–5** | Linux 抽象 socket / Windows 命名对象；归 M1 |
| transport: tcp | 8–12 | |
| transport: unix socket | 4–6 | |
| **transport: Windows 命名管道** | **2–5**（若 mio 可用）/ **10–18**（自研） | 风险项，S2 先验证 |
| discovery（组播 + seed + 节点身份） | 12–20 | |
| monitor（心跳 / 指标 / 诊断 / 环境指纹） | 7–12 | |
| **消息监控（信封级 P0）** | **4–6** | 环形缓冲 + 丢弃事件 + 隔离 |
| **载荷捕获（P1）** | **5–8** | arena / 限速 / 双 TTL / dump 格式 |
| **审计 sink（P1）** | **1–2** | `audit_fn` 回调 + 事件产生点（无环、无句柄） |
| **SLOW / 采样 / direction（P1）** | **1–2** | 配对表 + 采样 |
| 测试基建（fake clock / fake transport / 探针） | 8–12 | |
| 平台验证（麒麟 / UOS / WS2016 / ARM64） | 15–25 | |
| 小计：**v1（M0–M6）** | **108–173** | 不含 v1.1 项（mio 命名管道） |
| 小计：**v1.1（M7）** | **17–26** | 载荷捕获 5–8 + 审计 1–2 + SLOW/采样 1–2 + **UDP 4–6 + 错误环 2–3 + `process_epoch` 2–3 + 其余 2** |
| **合计（mio 提供命名管道）** | **125–199** | 不含 soak 与认证 |
| **合计（自研命名管道）** | **133–212** | 同上 |
| **小计：v1（自研命名管道）** | **116–186** | |

> 估算为**工程判断**，非实测。S1/S2 Spike 完成后应据此修正。
