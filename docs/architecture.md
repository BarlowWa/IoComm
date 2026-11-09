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
| 监控内存模型 | **逻辑配额 + 按需分配**：`max_bytes` 是**记账上限**，不是预留量；`monitor_budget_bytes` 是各 monitor **已提交配额之和**。记录与槽位按需分配、离开 `retain_window` 时归还（AC-72 的前提）。超预算（配额之和）返回 `RESOURCE_EXHAUSTED` |
| 环与槽位的预分配 | **环的存储**（`ring_capacity × sizeof(record)`）在 `monitor_open` 时**一次性分配**，不是逐条分配；热路径只做写槽位，**零分配** |
| 载荷 arena（v1.1） | 在 `monitor_open` 时按工作集预分配；热路径只做 memcpy |
| 事件来源 | `core` 定义 `MonitorSink` trait；会话/传输在打点处调用它，**`core` 不依赖域 crate** |
| poll 线程 | 只读私有环、不依赖 loop 推进，故 loop 线程也允许 `timeout_ms=0` 的非阻塞 poll |
| 视图保留 | 记录被 poll 取出后，其**槽位与 arena 块**在 `retain_window` 次 poll 内不复用（消费端持有引用计数） |
| TTL 释放 | `monitor_ttl_ms` 到期时 loop 线程**只置 expired 标志**；资源由消费线程在下次 `poll` 中释放 |
| 监控自监控 | 丢记录时 `stats.lost++`、`degraded=1`；每 1024 次由生产端聚合写一条 `LOST` |
| 审计 | **创建期固定的回调 sink**（`runtime_config.audit_fn`），事件产生点在各 API 入口，**在生产线程上同步调用**。无环、无句柄、无 poll；`audit_fn == NULL` 时回退 `log_fn` 的 AUDIT 类别。回调必须线程安全且不得阻塞、不得重入（见 C ABI §9.5） |

**可插拔点**（运行期 trait 对象）：

- `Transport`：tcp / unix-socket / named-pipe / inproc（udp 为 v1.1）
  > `inproc` 不参与发现：`publish_local = 1` 时 `endpoint_create` 返回 `INVALID_ARGUMENT`（见 [需求 FR-3.9](requirements.md)）
- `Discovery`：multicast / unicast-seed / local-registry（本机注册表的机制见 §6.4b）
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
| 在 **loop 驱动线程**上调用**阻塞型**同步 API | **返回 `ICOMM_ERR_WOULD_DEADLOCK`**，不阻塞。**非阻塞的所有权 / 注册类调用不受此限**（`conn_retain` / `conn_subscribe` / `endpoint_accept` / 两个 `*_condition_subscribe` / `runtime_wakeup` 在 loop 线程上合法）——见 §3.3 与 C ABI §6.4 `@special` |
| 在**其他线程**上调用同步 API | 允许；该线程阻塞等待，loop 线程继续推进 |
| manual 模式下 `runtime_drain` | **不接受阻塞调用**——传入 `timeout_ms = 0`，在外部循环里交替调 `run_once` 与 `drain`，**直到 `drain` 返回 `ICOMM_OK`**（判据是 `drain` 的返回值；`run_once` 空闲返回 `TIMEOUT`，不能拿它当完成信号） |
| **manual 模式建连** | **必须用 `iocomm_connect_async` / `iocomm_connect_node_async`**；同步 `iocomm_connect` 在 loop 线程上会返回 `WOULD_DEADLOCK` |

> **`iocomm_runtime_drain` 的「返回时保证已排空」只对 owned 模式成立**；manual 模式改为「drain 返回 `ICOMM_ERR_WOULD_BLOCK` 表示仍有在途操作，调用方应交替 `run_once` 与 `drain`，**直到 `drain` 返回 `ICOMM_OK`**」。

> **尺寸协商与热更新的关系**：连接生效的 `max_frame_bytes` 在**握手完成时冻结**；之后 `tune_config.max_message_size`
> 只影响**新建连接**与**尚未握手完成**的连接。这与 §5.0「热更新作用于全部端点」是**显式例外**，理由：
> 中途改变已建连接的上限会让「同一连接上的前一条能发、后一条不能发」，且对端无从得知。

### 3.3 线程安全契约

| 对象 | 线程安全 |
|---|---|
| `Runtime` / 端点 / 连接 / 订阅的**创建与销毁** | 否（调用方串行化）。**注意**：本行指**对象生命周期**；下文单独列出的注册类入口（`endpoint_accept` / 两个 `*_condition_subscribe`）另有属性 |
| `run_once` / `run_for` | 否（仅 loop 线程）。**`run_once` 返回 `TIMEOUT` = 本轮空闲**（正常事件，非故障，C ABI §4） |
| 端点/连接/订阅的 `count/get` | 否（loop 线程或串行化） |
| `*_send_async` / `connect*_async` / `runtime_wakeup` | **是**（内部投递到 loop） |
| `conn_send` / `endpoint_send` / `*_recv` / `unsubscribe`（同步） | 否（一句柄一线程；loop 线程调用返回 `WOULD_DEADLOCK`。**唯一例外**：在**本订阅自己的回调内**用 `unsubscribe` 取消本订阅 → `ICOMM_OK`，见 C ABI §6.4 `@special` 与 AC-5） |
| `runtime_reconfigure` | **是**（内部投递到 loop，异步生效） |
| `subscribe` / `conn_subscribe` / `endpoint_accept` / `conn_condition_subscribe` / `endpoint_condition_subscribe` / `discovery_start` / `discovery_stop` | 否（调用方串行化，或经 `run_once` 线程调用——**含回调内**；见下方「注册类入口」）——2026-11-05，N-39 |
| `conn_retain` | **是**（只改所有权表，不等待、不投递）——2026-11-05，N-36 |
| 指标快照 `iocomm_stats_snapshot` / `conn_status` / `monitor_get_stats` / `diagnostic_dump` | **是**（返回拷贝） |
| `monitor_poll` / 载荷查询 / `monitor_dump` / `monitor_close` | 否（同一 monitor 单线程串行；SPSC 消费端） |
| `monitor_open` / `capture_set` | **是**（内部加锁或投递到 loop） |

> **默认规则**（2026-11-05，N-39）：**本表未列出的入口默认非线程安全**（与 libuv 的惯例一致）。
> 「**是**」表示内部投递到 loop 或加锁，「否」表示须调用方串行化或仅在 loop 线程调用。
> **例外**：若某函数的头文件注释**明确写了**「任意线程可调用」（如 `runtime_node_id` / `conn_destroy` /
> `endpoint_destroy` / `monitor_get_stats`），**以注释为准**——本默认规则只覆盖「既未在本表、注释也没写」的入口。
>
> **注册类入口（`endpoint_accept` / 两个 `*_condition_subscribe`）为什么是「否」而不是「是」**（2026-11-05，N-39 复核）：
> 它们要求**同步生效**（返回时订阅已登记，随后的 `connect` 不会漏交付），这与「内部投递到 loop」矛盾。
> 若改为「内部加锁 + 同步生效」，则**在 loop 线程（含回调内）调用会自己取到自己持有的锁**——
> 要么自锁，要么返回矩阵未列的码。故归入与同族 `subscribe` / `conn_subscribe` **完全一致**的口径：
> **调用方串行化，或在 loop 线程上调用**（loop 线程调用合法且是内联执行，不会自锁）。
> 代价是「另一线程注册」不可用——与 `subscribe` 的既有代价相同，不是新增限制。
> `conn_count` / `conn_get` 属「否」——外部监控线程若需枚举连接，应把枚举放进 loop 线程
> （manual 模式下就是驱动 `run_once` 的那个线程），或按 `open-questions.md` **N-46** 的裁决改用快照 API。

> **异步发送与句柄销毁的竞态**：异步发送只接收**连接句柄或端点句柄**，内部先做代际校验再入队；调用方必须保证「不再对某对象发起异步操作之后」才销毁它。文档写死这条顺序，**不做隐式同步**——与 ZeroMQ / Asio 的惯例一致。

> **线程检测的生产语义**：`WOULD_DEADLOCK` 是**生产行为**，不是调试断言。实现方式是：Runtime 在首次 `run_once`（manual）或启动 IO 线程（owned）时记录 loop 线程 ID；该 ID 在 `stop` 前保持不变。
> **比对范围 = 矩阵里列了 `WOULD_DEADLOCK` 的那些入口**（阻塞型同步 API：`conn_send` / `endpoint_send` / `*_recv` / `connect` / `conn_close_graceful` / `unsubscribe` / `monitor_poll` / `runtime_stop` / `runtime_drain`（后两者仅 `timeout_ms > 0`）/ `*_destroy` / `conn_abort` 等）。
> **不比对**的是非阻塞注册类入口（`endpoint_accept` / 两个 `*_condition_subscribe` / `conn_subscribe` / `subscribe`）与 `conn_retain`——
> 它们标「否」的含义是「**调用方须串行化**」：违反时行为**未定义**——库不保证检测、不保证崩溃、不保证返回某个码（与 libc 的非线程安全函数同口径）。
> 注意这与 FR-1.6「句柄失效绝不 UB」**不冲突**：那条讲的是**句柄有效性**（库必须返回 `STALE_HANDLE`），
> 这里讲的是**线程亲和性**（调用方违反了 `@thread` 约定，库无义务兜底）。
> 而不是「在 loop 线程外调用会返回 `WOULD_DEADLOCK`」。**本表未列 `WOULD_DEADLOCK` 的，就不要指望库替你检测。**
> 首次 `run_once` 之前 loop 线程未确定，同步 API 允许调用（此时不可能有在途操作）。

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
  > 六类对象（Runtime / endpoint / conn / subscription / snapshot / monitor）共用同一张表——其中 **Runtime 是表的主人，不占 `max_handles`**；计入名额的是**五类对象句柄**（endpoint / conn / subscription / snapshot / monitor）。**种类是句柄的一部分**：把 `conn` 句柄传给 `endpoint_*` 函数会被拒绝，而不是被当成同号对象误用。**审计没有句柄**（回调 sink）。
- **绝不传裸指针**，跨 FFI 只传 `u64`。

> 槽位记录 `{kind, generation, object}`；`kind` 区分 Runtime / endpoint / conn / subscription / snapshot / **monitor**。C ABI 中**不出现 `void*` 型的不透明对象**。

### 5.1b 节点身份（NodeId）

节点身份必须**跨进程重启保持稳定**，否则「重启后被识别为同一逻辑节点」（AC-9）无法成立。

```
NodeId = u64
  ├─ 显式配置：runtime_config.node_id != 0，原样使用（稳定性由调用方保证）
  └─ 自动：node_id == 0 时，在 state_dir 下持久化一个随机 64 位值
```

- 配置入口：`iocomm_runtime_config.node_id`（0 = 自动）。
- **自动模式要求 `state_dir` 非空（`state_dir != NULL` 且 `state_dir_len > 0`）且可写**。
  不满足（`state_dir` 为空、路径不存在、不是目录、创建/读取/写入文件失败）→
  `iocomm_runtime_create` 返回 `INVALID_ARGUMENT`，`err.message` 指明「自动 `node_id` 需要可写的 `state_dir`，
  或显式配置 `node_id`」。
- 落盘文件（两个，职责不同）：
  - **`<state_dir>/iocomm.nodeid`** —— 持久化的 NodeId，内容为 16 位小写十六进制 + `\n`。首次以**原子创建**
    （`O_CREAT | O_EXCL` / `CREATE_NEW`）写入；已存在则读取。文件内容不合法（长度/字符不符）→
    `INVALID_ARGUMENT`（**不自动重新生成**——静默换号会破坏 FR-9.1）。**重启后 NodeId 稳定靠它**。
  - **`<state_dir>/iocomm.owner`** —— 属主标记，内容为 `<node_id>` + `<pid>` + 进程启动时间（N-25）。
    同样以**独占创建**占住；用于判断「同一 `state_dir` 是否已被另一存活进程使用」。
    **与 `iocomm.nodeid` 分开是必须的**：前者要跨重启保持不变，后者每次 `runtime_create` 都要反映**当前**属主，
    两者的生命周期相反，合并会导致「重启后仍判旧 pid 存活」或「丢 NodeId」。
- **v1 不提供任何宿主级派生**（2026-11-04 定，N-04）：**不读** machine-id / `MachineGuid` / 主机名 / MAC。
  理由（两约束夹逼，唯一解）：
  - 主机级纯函数（machine-id / 主机名 / MAC 哈希）在**同机多进程必然同值**，直接违反本节 v1 语义；
  - 在派生值上掺「每进程随机盐」会让**重启后 `node_id` 变化**，违反 FR-9.1；
  - 因此「无持久化又要求跨重启稳定 + 每 Runtime 独立」不可能同时成立。v1 的结论是：
    **只读文件系统 / 无 `state_dir` 的场景一律要求调用方显式配置 `node_id`**（库拒绝自动模式，不猜测）。
  - **Windows 与 Linux 同规则**：v1 不做 Windows 派生，不存在「Windows 派生源」的规定。
- **v1 语义：`NodeId` 唯一标识一个 Runtime 实例**，同机多进程各自拥有独立 NodeId（不共享）。
  **含 `state_dir` 的情况也一样**：多个进程配置**同一个** `state_dir` 时，先创建者以独占创建占住目录内的
  **属主标记 `iocomm.owner`**（记 `<node_id>` + `<pid>` + 启动时间）；后创建者发现**属主进程仍存活** →
  `runtime_create` 返回 **`ICOMM_ERR_CONFLICT`**（`message` 指明目录），因此**不会**共享同一 NodeId。
  属主进程已退出（`destroy` 或崩溃）时目录可复用，残留标记按「进程不存在」判失效。
  **每个 Runtime 仍应使用独立的 `state_dir`**（这是推荐部署，不是唯一正确方式）。
  「同机多进程共享主机身份、用 `(NodeId, process_epoch)` 区分」是 **v1.1** 的扩展（FR-9.3），v1 不实现 `process_epoch`，任何 C 结构体里也没有这个字段。

> **N-04 的取舍（2026-11-05 已闭环，保留作决策记录）**：把「只读 / 无 `state_dir`」从「库自动派生」改为
> 「要求显式 `node_id`」是**产品取舍**——它把部署负担推给调用方，换取 v1 语义自洽。若产品要求
> 「无 `state_dir` 也能自动建号」，唯一自洽的替代是**放宽 v1「每 Runtime 独立」语义**（提前采用
> v1.1 的 `process_epoch` 方案），那属需求变更，不在本项处置范围内。

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
| **endpoint** | 本地具名监听者 | **扇出**到它的全部**成员连接**（入站 + `ep_owner == ep` 出站） | 它的所有入站连接（默认进入端点接收队列） |
| **conn** | 一条双向连接 | **点对点** | 该连接 |
| **subscription** | 推送回调的注册 | — | — |

**入站连接**由 `iocomm_endpoint_accept()` 注册的回调交付（**双向 HELLO 完成后才触发**，见 §5.2b）。同一端点可注册**多个** accept 回调，按注册顺序各触发一次；持有动作只需在**任一**回调内完成，生命周期判定在**全部**回调跑完后进行（2026-11-05，N-37；见 C ABI §6.4 与 AC-33）。回调内的句柄是**借用**：只在回调期间有效。持有动作有**三种**——**显式 `conn_retain`**（拉取）、**隐式 `conn_subscribe`**（推送，订阅即所有权），以及**端点级持有**（该端点已启用 `iocomm_subscribe(ep)` / `endpoint_recv(ep)` 时，入站连接在**交付的同一时刻**由端点接管，回调内无需再表态）；三者都不做则回调返回时自动收回并以 FIN 优雅关闭。「发完即关」用发送选项 `ICOMM_SEND_CLOSE_AFTER`，`conn_send_async` 本身不是所有权开关。完整契约见 C ABI §5.2 与 [ADR-002](adr/ADR-002-message-addressing-and-ownership.md)。

> **成员资格（2026-11-03，N-01 / N-03）**：入站连接**在交付（双向 HELLO 完成）时**被持有即成为监听端点的**成员**，参与 `endpoint_send` 扇出与 `conn_count(ep)`，与 `ep_owner == ep` 的出站成员连接地位相同。**握手期的内部会话不在此列**（无句柄、不计入扇出与计数）。**纯服务端（只 accept 不 connect）因此可以对全部入站连接做一次扇出广播。** 此前「入站连接不归属端点、不参与扇出」的规定已废止——它使服务端广播不可用，且与本节 `endpoint` 行自相矛盾。

> **连接句柄由 `connect*()`（出站成功）或 `accept`（入站交付）创建**；**句柄产生后**的状态迁移在 `iocomm_conn_t` 上发生。入站在交付前先经历内部 `Handshaking` 会话（无句柄，见 §5.2b）。关闭有四条路：`conn_destroy`（取消在途、丢弃缓冲、FIN）、`conn_close_graceful(linger_ms)`（flush 后关）、`ICOMM_SEND_CLOSE_AFTER`（发完即关）、`conn_abort`（RST 异常中止）。

### 5.2b 连接状态机

> 连接由 `connect*()`（出站）或 `accept`（入站交付）产生；**句柄产生后**的状态迁移在 `iocomm_conn_t` 上发生。**出站同样经历 `Handshaking`**：`iocomm_connect` 成功返回 / `connect_async` 的 `on_done(OK)` 都发生在双向 HELLO 完成之后，因此不存在「拿到句柄却还不能发 DATA」的半可用窗口（2026-11-03，N-03）。

```
   Disconnected ──首次 connect*()──► Connecting ──TCP 失败──► [仅首次调用] 返回 DISCONNECTED
                                       │ TCP 建立成功
                                       ▼
                                    Handshaking ──握手失败/超时──► [仅首次调用] 返回 DISCONNECTED / TIMEOUT
                                       │ 双向 HELLO 完成
                                       ▼
                                    Connected ──[仅首次调用] connect 返回 / on_done(OK)
                                       │ 心跳超时 / 断开
                                       ▼
                                    Reconnecting ──退避后重试──► Connecting
                                       ▲                         │
                                       └─────────────────────────┘（重试失败则继续退避）
```

> **图的读法（唯一口径，2026-11-03 N-03）**：`[仅首次调用]` 的三处出口（TCP 失败、握手失败/超时、成功）只发生在**调用方发起的那次 `connect*()`**；
> 自动重连再次走 `Connecting → Handshaking → Connected` 时**没有**返回值，也**不再触发** `on_done`（AC-27「恰好一次」）。
> **重连成功后复用同一个 `iocomm_conn_t` 句柄**（2026-11-04，N-06，见 §5.2c）——`Reconnecting → Connected`
> 期间句柄始终有效，`iocomm_conn_status` 可查询；应用不需要（也不能）重新 `connect*()` 再换句柄。


> **入站连接**不经 `Connecting`，但要经过 `Handshaking`（双向 HELLO）：
>
> ```
>   Disconnected ──监听 socket 接受──► Handshaking ──双向 HELLO 完成──► Connected
>                                          │                          （此刻交付：触发 accept 回调）
>                                          └──失败 / 超时 / 版本不兼容──► Disconnected（不产生 accept 回调）
> ```
>
> `Handshaking` 是**内部会话**：还没有 `iocomm_conn_t` 句柄、不占 `max_handles`、对应用不可见（§5.2、[线格式 §5](api/wire-format.md)）。
> 它只在**交付时**（双向 HELLO 完成后）进入 `Connected` 并触发 `accept` 回调——「`Connected` = 应用可见」对入站同样成立。
> **握手失败 / 超时路径不触发 `accept`**（只产生日志/计数）。重建由对端发起；inproc 没有握手，接受后直接 `Connected` 并交付（[线格式 §7](api/wire-format.md)）。

**状态是条件集，不是单一枚举**（见 [需求 FR-5.1](requirements.md)）：

| 条件 | 取值 |
|---|---|
| `Connected` | True / False / Unknown |
| `Lively` | True / False / Unknown |
| `Healthy` | True / False / Unknown —— **定义**：最近一次心跳判定周期（`heartbeat_ms × max(heartbeat_miss_limit, 1)`，**默认 `2000 ms × 3 = 6 s`**）内既**没有重连**、也**没有收到 `ERROR` 帧**；`Unknown` = 该连接尚未经历满一个周期 |
| `ConfigCurrent` | True / False |

上层按需查询，新增条件不破坏既有判断。**状态变化通过 `iocomm_condition_fn` 回调推送**（见 C ABI §8），同时保留拉取式查询。

### 5.2c 自动重连语义（2026-11-04 定，N-06）

自动重连（FR-4.4）只适用于**出站连接**（`connect*` 产出）；入站连接断开后由对端重连，本端不主动重拨。
重连过程中确定四件事（对应的验收见 [需求 AC-105](requirements.md)）：

1. **句柄复用**：重连成功前后是**同一个 `iocomm_conn_t`**。`Connecting / Handshaking / Reconnecting` 期间句柄
   一直有效（可 `conn_status`、可查询条件集），应用不必观察重连过程。
   `conn_destroy` / `conn_abort` 在重连窗口内同样可用，取消重连并关闭。
2. **在途消息不跨重连保留**：连接断开的那一刻，该连接的发送队列中被摘除的项（`conn_send` 的点对点项、
   以及该连接的扇出项）**逐条产生 `DROPPED(PEER_GONE)`**（若有监控者），对应的异步 `on_done` 报
   `DISCONNECTED`（§5.2b 裁决表第 4 行）；**重连成功后不重放**。重连窗口内的新发送按 §6.1
   「入队**前**已断开」处理（立即失败、不入队、不排队等重连）。理由：本库无 ACK/重传/去重/会话恢复
   （§5.3），「跨重连保留」等于发明一套重放协议，且无法区分「对端已收到但没回 ACK」与「没收到」。
3. **`sequence` 随连接重置**：`sequence` 是**连接级**序号（不是 `(source_node)` 全局序号）。新连接从 1 重新开始，
   因此断开前后的序号**不可比**。跨重连的应用级顺序只能靠应用自己的 `correlation_id`（或 payload 内的业务序号）；
   本库不做 `SEQ` 空洞检测的跨连接推断。
4. **订阅保持、`peer_node_id` 更新**：订阅（`conn_subscribe` / `conn_retain` / `conn_condition_subscribe`）
   挂在**连接对象**上，不是挂在 socket 上，重连后**自动恢复**，应用无需重新订阅。`peer_node_id` 在新握手
   完成后**以对端 `HELLO` 的新值更新**（同一 `(addr, endpoint_name)` 可能被不同 `node_id` 的进程接管）；
   `conn_status.reconnect_count` 与 `stats.reconnects` 各递增一次。

> **为什么句柄复用而不是「重连后换新句柄 + 回调通知」**：换句柄会把「稳定句柄」变成一个需要应用维护
> 代际映射的易错对象，且与 AC-27 的 `on_done` 生命周期（句柄由首次 `connect*` 产出、销毁时回收）不自洽。
> 复用句柄的代价是：句柄在「断开→重连」窗口内仍可用，`connected` 条件必须能表达中间态（FR-5.1 的 `UNKNOWN/False`）。

### 5.3 消息

```
Message {
    from                // 来源连接 → C ABI: iocomm_conn_t
    source_node         // 来源节点 NodeId
    sequence            // per-source 单调序号（排序与检漏的权威）；按连接计，重连后从 1 重计（§5.2c）
    timestamp           // 发送方事件时间（附时钟同步状态；v1 恒不同步，见 §6.5）
    correlation_id      // 请求-应答关联
    payload             // 不透明字节
}

**发送成功 ≠ 对端收到**

`send` / `on_done(OK)` 的完成点统一定义为「**消息已完整交给传输层**」（OS 已接受），不是「对端已收到」。
本库没有 ACK / 重传 / 去重 / 会话恢复，端到端确认属于应用层。异步发送另有 `send_options.queue_timeout_ms`
约束「入队 → 开始写」这一段（超时产生 `DROPPED(TIMEOUT)`）；**开始写之后不再超时**——理由见 C ABI §6.2b（部分写出时放弃只能 RST；未写出时窗口不可观测）。
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

- 应用层心跳（**不依赖内核 keepalive**，其默认 2 小时且 Windows Server 2016 缺 `TCP_KEEPIDLE`）。v1 **不暴露**内核 keepalive 开关（见 [c-abi §5.1](api/c-abi.md) 非目标口径）。
- 心跳带**序号 + 时间戳 + 双向确认**（消除单向故障盲区）。
- **默认值（唯一权威）**：`heartbeat_ms = 2000`、`heartbeat_miss_limit = 3`。两个字段都可配
  （`tune_config` 热更新），但**默认即 3**，不是「≥ 3」的下界。
- 判定：连续 `heartbeat_miss_limit` 次未收到对端心跳 → `Lively = False`；默认 3 次（= 6 s）。
- 重连：**Full jitter 退避**（`random(0, min(cap, base*2^n))`），cap 10–30s。

### 6.3 发现

> **v1 是单发现域**（2026-11-05，N-44）：组播组 `239.255.73.77` + 端口 `47377` 硬编码，**同网段内所有启用发现的
> Runtime 互相可见**。需要两个互不可见的通信域时，请在部署层用 **VLAN / 交换机 ACL / 独立网卡 / netns**，
> 不要依赖「分组播组」（不可配置）。**域 ≠ 安全边界**——v1 无认证无加密（需求 §4.1）。
> 本机名字锁（§6.4）是机器级的，同样不构成网络边界。DDS / ROS 2 的 `domain_id` 方案可作为 v2 的参考。

**两阶段**（借鉴 DDS）：

1. 阶段一：节点存在性（轻量心跳 + 地址）
2. **阶段二：端点能力**（事件驱动，单播）——节点上报自己**注册了哪些句柄**，供远端 `connect` 使用。
   上报的 `addr` 是**通告值**（通配监听地址 / 端口 0 已替换为可拨号值）；`connect_node` 的「`node_id` + 端点名 → 地址」解析规则见 [C ABI §5.2a](api/c-abi.md) 与 [FR-8.12](requirements.md)（2026-11-04，N-05）。

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

> **为什么是拒绝，而不是改名或接管**：与 ZeroMQ / nng 的「注册失败」、MQTT 的「会话接管」、mDNS 的「改名 + 持久化 + 告警」做过横向对照（Windows 命名管道作为「独占需显式声明」的旁证），结论见 [ADR-003](adr/ADR-003-endpoint-name-uniqueness.md)。

`iocomm_endpoint_name_state()` 要区分「空闲 / 本进程持有 / 他进程持有」，必须有**跨进程协调机制**：

| 平台 | 机制 |
|---|---|
| **Linux** | 以端点名派生一个**抽象命名空间 socket**（`@iocomm/<hash>`）。bind 成功 = 抢到；`EADDRINUSE` = 他进程持有。本进程自持的名字先查本地表。抽象命名空间**零残留**（进程死亡自动释放） |
| **Windows** | 优先 `Global\iocomm_<hash>`（`CreateMutexW` + `ERROR_ALREADY_EXISTS`，跨会话可见）；创建失败（`SeCreateGlobalPrivilege` 不足，普通用户默认没有）时回退 `Local\iocomm_<hash>`（同会话可见，**同机跨会话的端点名唯一性不保证**），并在 `log_fn` 写 WARN。进程退出时内核自动回收句柄 |
| **本机 IPC（unix/pipe）** | 复用同一套名字锁；实际 socket 文件放 `/run/iocomm/` 或命名管道，不在 `/tmp` |

**规则**：
- **所有具名端点都做跨进程唯一性检查**，**与传输后端无关**——inproc 端点同样参与（inproc 的「跨进程隔离」只针对它自己的 `listen_addr`，见 [FR-3.6](requirements.md)）。
- **注册判定（fail-fast，唯一口径）**：
  | 情形 | `endpoint_create` 结果 | 是否注册 |
  |---|---|---|
  | 首次注册 | `OK` | 是 |
  | 他进程已持有同名 | **`CONFLICT`** | **否**（不自动改名） |
  | 本进程已持有同名 | `ALREADY_EXISTS` | 否 |
  - 跨进程同名**一律拒绝**：端点名是远端寻址身份（`connect_node` 按 `name` 精确匹配，见 [C ABI §5.2a](api/c-abi.md)），若自动改名为 `<name>#<pid>`，远端无法预测该身份，`connect_node` 可能连到错误进程。与 [FR-1.4](requirements.md)（P0「重名注册被拒绝」）一致；见 [§6 演进记录](requirements.md#6-需求演进记录) 2026-11-04。
  - 没有「单实例 / 可多实例」的开关——所有端点名都按上表处理。
- 名字 → 锁的映射用**稳定哈希**（同一名字在同一机器上恒定）。
- **残留处理**：Linux 抽象命名空间与 Windows 命名对象都由内核在进程退出时回收，**不需要手工清理**；pathname socket 的残留清理见 [平台支持 §3.2](platform-support.md)。
- 判定结果不是原子的：`name_state()` 查询与随后 `create()` 之间存在 TOCTOU 窗口。**`create()` 的返回值才是权威**，`name_state()` 仅用于**注册前探测**与诊断/友好提示（三态：`FREE` / `HELD_BY_SELF` / `HELD_BY_OTHER`）。

### 6.4b 本机注册表（`publish_local`，FR-2.6）

> 2026-11-04 定（N-13）。§6.4 的名字锁只能回答「这个名字是否被占」，**承载不了端点能力表与上下线事件**，
> 因此本机发现需要独立机制。

**机制：每 Runtime 一个单元文件（unit file）+ 原子 rename**

| 项 | 规则 |
|---|---|
| 目录 | **本机固定的每用户目录**（**不是** `state_dir`）：Linux `$XDG_RUNTIME_DIR/iocomm/local/`，无该变量时 `$HOME/.iocomm/local/`；Windows `%LOCALAPPDATA%\iocomm\local\`。所有 Runtime 共用这一个目录——"互相发现"与"`state_dir` 各自独立"（[§5.1b](#51b-节点身份nodeid) 要求每个 Runtime 用自己的 `state_dir`）本来就不该绑在一起 |
| 文件名 | `<node_id>-<pid>.bin`（十六进制）。**不用 `process_epoch`**——它是 v1.1 的扩展（FR-9.3），v1 的任何 C 结构体里都没有；`pid` 在进程存活期内唯一，进程退出后的残留由租约清理。**同进程内两个 Runtime 被显式配成同一 `node_id`** 属配置错误，文件名相同 → 后写者覆盖，库不检测（与「跨进程共用 `state_dir`」不同：后者由 §5.1b 的属主标记检出并返回 `CONFLICT`） |
| 内容 | **与 `BEACON` 的报文体同构**（[线格式 §8](api/wire-format.md)）：节点自述 TLV（`NODE_ID` / `NODE_NAME` / `WIRE_VERSION` / `LEASE_MS`）+ `ENDPOINTS` 条目（`name` + `transport` + **通告 `addr`**，取值规则与网络发现完全一致，见 [线格式 §8 规则 6](api/wire-format.md)）。**`NODE_NAME` 因此有明确来源**——就是 `runtime_config.node_name`，与组播路径的 `iocomm_node_info.name` 取值规则相同；不引入第二套格式 |
| 写入 | **整文件重写 + rename 原子替换**（读者永远看不到半个文件）。触发点：端点创建 / 销毁 / 地址变化、以及**每个发现心跳周期**（刷新 mtime） |
| 读取 | **每个发现心跳周期**扫描目录（不只启动时）：把每个**非本 Runtime** 的单元文件按 `BEACON` 的解析规则组装成**一条 `iocomm_node_info`**（`name` 取 `NODE_NAME` tag，`endpoints` 取 `ENDPOINTS` tag），并入同一节点表（与组播 / seed 的结果走同一条合并路径，`JOINED` / `UPDATED` / `LEFT` 语义不变）。**读取侧三道校验**：① 文件 ≤ `max_message_size`（防损坏或被恶意放大），超限视为无效并删除；② 文件内的 `NODE_ID` 必须与文件名中的 `<node_id>` 一致，不一致视为无效；③ **`NODE_ID` 相同的另一个单元文件**（同进程被配成同一 `node_id`，或显式 `node_id` 重复）→ 只保留 **mtime 较新**的那条，并在 `log_fn` 写一条 WARN（否则 `connect_node` 按 `node_id` 查找会歧义） |
| 崩溃清理 | 进程 `kill -9` 后文件残留：**按 `lease_ms`（默认 6000 ms）判陈旧**——mtime 超过租约的文件被视作 `LEFT` 并删除（只由 `node_id` 最小的存活 Runtime 执行删除，避免多进程同时删同一文件的竞争；删失败无害）。与网络节点的租约语义同口径，不引入新概念 |
| 停止 | `discovery_stop` 删除本 Runtime 的单元文件（等价一次 `LEFT`） |
| 可见性 | **同一用户下的全部 Runtime 互相可见**，与各自的 `state_dir` 无关。跨用户不可见（目录在每用户命名空间内）——这与内核对命名管道的默认隔离同量级 |
| 前置条件 | 目录**可写**。目录创建 / 首次写失败 → `discovery_start` 返回 `INTERNAL`。**与 `state_dir` 无关**：显式 `node_id` 且 `state_dir == NULL` 的 Runtime 同样可以 `publish_local` |

**`discovery_start` 是不是前置条件：不是，但发布在它之后才开始**

- `publish_local = 1` 的端点可以**先于** `discovery_start` 创建。`endpoint_create` **不因此失败**，也**不静默丢失**：
  发布状态由 `discovery_start` 时**扫描现有端点**补齐（此后端点增删实时写文件）。
- 理由：启动顺序天然是「创建 Runtime → 创建端点 → 启动发现」，强制 `discovery_start` 在前会让最常见的顺序报错；
  而「本机发现」在 `discovery_start` 之前**本来就不存在**（没有发现就没有快照、没有事件），延迟发布于语义无损。
- `discovery_stop` 之后新建的 `publish_local` 端点同样只是「未发布」，直到下次 `discovery_start`。

**为什么是文件而不是共享内存段 / 命名对象**：

- 共享内存段需要跨进程的**生命周期与并发写**协调（谁是 owner、崩溃后谁回收、读者如何避免撕裂），
  而单元文件用 **rename 原子替换**把并发写问题直接消掉，生命周期由 mtime 租约兜底。
- 同机进程数是**十几到几十**量级（<200 的 seed 档位），每周期读几十个小文件的开销可忽略；
  发现本身已按 `heartbeat_ms`（默认 2000 ms）轮询，不需要额外引入 `inotify` / `ReadDirectoryChangesW` 两套平台事件 API。
- 失败面收敛：唯一的外部依赖是**单元文件目录可写**（`$XDG_RUNTIME_DIR/iocomm/local/` 等），
  与 `state_dir`（自动 `node_id` 的持久化目录）**互不依赖**——纯显式 `node_id` 部署同样能用本机发现。

**失败处理（不做静默空操作）**：

- `discovery_start` 无法创建目录 / 写入单元文件 → **返回 `INTERNAL`**（`message` 指明目录），发现不启动。
- `discovery_start` **之后**的写入失败（磁盘满等）→ `log_fn` 的 **ERROR** 级记录，并**继续尝试下一次心跳写**
  （瞬时失败可自愈）；此时持久失败会让本机对端看到该 Runtime 在 `lease_ms` 后 `LEFT`——这是可观测的正确降级。
- `publish_local = 0` 的端点**不进入**单元文件（本机对端也看不到它）——与网络中「不参与发现」一致。

### 6.5 时间

| 用途 | 时钟 |
|---|---|
| 超时 / 心跳 / RTT / 退避 | **单调时钟**（`steady_clock` 语义） |
| 事件时间戳 / 日志 | 挂钟（附同步状态标志） |

**排序以序号为权威，不以时间戳为权威**（跨机挂钟不可信）。

> **`clock_synced` 在 v1 恒为 0**（2026-11-04，N-11）：本库不提供时间同步——PTP / NTP 不在范围，
> 平台对 PTP 硬件时间戳的支持本身也在 [platform-support.md](platform-support.md) §7 的**待核实**清单里。
> 该标志与线格式 `CLOCK_SYNCED` tag **保留但恒发 0**（而不是删除）：`iocomm_message` 是库写出的
> 公开结构体，删字段要动 ABI 布局；而保留的成本只是一个恒 0 字节。线格式侧两种做法都合法
> （删 tag 后再在 v2 追加同号也符合「只追加」规则），此处置与 ABI 对齐，避免两处不一致。
> 调用方**必须**按 0 处理——「两端时间可比」在 v1 永远不成立。

---

## 7. 可测试性设计（反向约束接口）

这些不是测试技巧，而是**接口要求**：

| # | 要求 | 接口表现 |
|---|---|---|
| T1 | 事件循环可手动驱动 | `iocomm_runtime_run_once()` / `iocomm_runtime_run_for()`（**没有 `run_until`**，D-10） |
| T2 | 时间可注入 | 所有超时经 `Clock` trait；内核零处直接读时钟 |
| T3 | 传输可替换 | `Transport` trait；`FakeTransport` 做测试；`inproc` 让 M1 不碰 socket 也能验完整个模型 |
| T4 | 端口可协商 | `listen(0)` 后 `local_port()` 可读 |
| T5 | 线程归属可校验 | 调试构建下检查归属线程，违反返回错误 |
| T6 | 定时器可枚举 | **v1 不提供公开入口**（D-10：C ABI 无此函数）；测试用 `FakeClock` 推进行为断言 |
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
| Q7 | `accept` 的所有权模型 | **借用 + 持有动作三选一**：`conn_retain`（唯一显式）/ `conn_subscribe`（隐式）/ **端点级订阅（`iocomm_subscribe(ep)` / `endpoint_recv(ep)`，2026-11-03 增补）**；「发完即关」用 `CLOSE_AFTER`（**不是持有**）（ADR-002）。不用「四选一接管」，也不用返回值枚举 |
| Q8 | 审计是否给独立句柄 / 环 | **不**。创建期不可变的 `audit_fn` 回调 sink；计数并入 `stats.audit_events`（ADR-002） |

> **控制面落点**：`iocomm_runtime_start/stop/reconfigure/drain` 已在 C ABI §4 定义。

---

## 10. 实施顺序、里程碑与工作量

### 10.1 里程碑（每个里程碑都有可验收产出）

| # | 里程碑 | 产出 | 验收 |
|---|---|---|---|
| **M0** | 骨架 | C ABI 头（C99 可编译）+ crate 划分 + CI 三平台构建 | AC-P1 / AC-P5 / AC-18 / AC-24 / AC-35 / AC-95 |
| **M1** | inproc 闭环 | 句柄表（代际）+ Runtime + 端点/连接模型 + **跨进程名字表（§6.4）** + **端点名格式/长度校验（§c-abi 5.1a）** + **手动驱动语义（`run_once` / `run_for`）** + `inproc` 传输（FR-3.5–3.10） | AC-4 / AC-11 / AC-25 / AC-32 / AC-33 / AC-36 / AC-40 / AC-80 / AC-81 / AC-82 / AC-83 / AC-84 / AC-89 / AC-100 / AC-102 / **AC-108** / **AC-109** / **AC-111** / **AC-114** / **AC-115** / **AC-116** / **AC-120** |
| **M2** | TCP + 双向 | tcp 传输 + accept + connect + send/recv/subscribe + 异步排队超时 + **[线格式](api/wire-format.md)（HELLO 握手 · ERROR 帧 · 尺寸协商）** + **端点级套接字参数（`TCP_NODELAY` / backlog）** | AC-1 / AC-2 / AC-10 / AC-29 / AC-30 / AC-31 / AC-33b / AC-39 / AC-73 / AC-74 / AC-75 / AC-76 / AC-77 / AC-78 / AC-90 / AC-92 / AC-99 / AC-103 / AC-104 / **AC-106** / **AC-110** / **AC-112** / **AC-113** / **AC-117 / AC-118 / AC-119** |
| **M3** | 状态与监控 | 心跳 + 条件集 + 指标 + 诊断（JSON 结构见 AC-94）+ **消息监控（信封级）** + **自动重连语义** | AC-3 / AC-5 / AC-6 / AC-12 / AC-13 / AC-15 / AC-20 / AC-27 / AC-28 / AC-37 / AC-41 / AC-42 / AC-43 / AC-44 / AC-45 / AC-53 / AC-55 / AC-57 / AC-59 / AC-64 / AC-68 / AC-71 / AC-72 / AC-86 / AC-91 / AC-94 / AC-101 / **AC-105** / **AC-121** |
| **M4** | 发现 | 组播 + 单播 seed + 节点身份 + 阶段二端点能力 + **[发现线格式](api/wire-format.md#8-发现报文阶段一--阶段二)** + **`connect_node` 地址解析** | AC-7 / AC-9 / AC-14 / AC-16 / AC-21 / AC-22 / AC-23 / AC-34 / AC-38 / AC-79 / AC-85 / AC-87 / AC-93 / **AC-107** |
| **M5** | 本机 IPC | Linux unix socket + Windows 命名管道 | AC-P3 / AC-8 / AC-17 / AC-19 / AC-26 / AC-88 |
| **M6** | 平台与加固 | 麒麟/UOS 实机 + glibc 2.17 基线 + soak | AC-P1 / AC-P2 / AC-P3 / AC-P4 / AC-P5 / AC-E1 / AC-E2 / AC-E3 / AC-E4 / AC-E5 / AC-E6 |
| **M7** | **v1.1** 载荷捕获与审计 | arena / 限速 / 双 TTL / dump / 审计 sink 回调（`audit_fn`）/ SLOW / **UDP 传输** / 错误环（FR-5.5b）/ `process_epoch`（FR-9.3） | AC-46 / AC-47 / AC-48 / AC-49 / AC-50 / AC-51 / AC-52 / AC-54 / AC-56 / AC-60 / AC-61 / AC-62 / AC-63 / AC-65 / AC-67 / AC-69 / AC-58 / AC-70 / AC-71b / AC-96 / AC-97 / AC-98 |

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
