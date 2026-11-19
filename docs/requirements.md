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
| FR-2.4 | **单播 seed 列表**（组播不可用/跨网段时的兜底）。seed 格式 `"<host>:0"`（port **必须为 0** = 对端单播端口未知）；`discovery_start` 后向该主机 `23101..23200` 逐个发 `CAP_Q`（通配 `node_id = 0`），收到 `CAP_A` 后记录实际源端口并回落到稳态寻址；seed 派生的节点全部过期后按租约周期重扫；**单向**（只让配置方发现对端）。规则见 [线格式 §8.1](api/wire-format.md)。**2026-11-18 落笔，N-60** | P0 |
| FR-2.5 | 多网卡：显式指定出接口 | P0 |
| FR-2.6 | 本机进程间发现：`endpoint_config.publish_local=1` 时发布到本机注册表，并通过 `JOINED/LEFT` 事件上报。**发布状态在 `discovery_start` 时建立**——之前创建的端点由启动扫描补齐，`endpoint_create` **不因未启动发现而失败**；单元文件放**每用户的固定目录**（与本 Runtime 的 `state_dir` 无关），同用户 Runtime 互相可见、跨用户不可见（机制见 [架构 §6.4b](architecture.md)） | P1 |
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

#### 进程内传输 `inproc`（FR-3.5–3.12）

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-3.5 | **进程内传输**：`listen_transport = "inproc"`，连接**同一进程内的 Runtime**（也允许同一 Runtime 连自己的端点），不走 socket / 管道 | P0 |
| FR-3.6 | inproc 的 `listen_addr` 是**进程内唯一名字**（≤255 B，必填），与端点名是两套独立命名空间；同进程重名返回 `ALREADY_EXISTS`。**「跨进程天然隔离」只指 `listen_addr` 这个名字**——端点名（FR-1.4/1.5）无论用哪种传输都参与跨进程名字表 | P0 |
| FR-3.7 | **inproc 是一个 `Transport` 实现，写入目标 = 接收方的接收队列**（2026-11-13 定）：发送方 loop 从**发送方端点发送队列**取出后，把消息**写入接收方的接收队列**（端点级或连接级，按 §6.1 归属规则；有界，上限 `recv_queue_max`——**per-connection 接收队列无独立配置项**，取 runtime 默认并经全局 `tune_config` 热更新（端点级 `queue_limit` 只作用于端点队列），见 c-abi §5.0）。**接收队列满 → 写入返回 `WouldBlock`**，消息留在发送队列（与 tcp「内核写缓冲满 → `WouldBlock`」同义）；**写入成功后库必须唤醒接收方 loop**。回调只在接收方 loop 线程执行，**绝不在 `send` 调用栈内同步回调**；**不引入额外的库内队列** | P0 |
| FR-3.8 | 与 tcp 保持一致：帧结构（消息边界 / `sequence` / `original_len`）、**出站大小校验**（`TOO_LARGE`）、端点队列与溢出策略、监控打点。**inproc 同样有发送队列与接收队列**——**成员连接共用端点发送队列、`ep_owner == 0` 的出站连接各自一条**（与 §6.1 队列归属一致），两者各自按端点策略独立溢出（与 tcp 同口径，见 c-abi §6.1）：**发送队列满**（对端不消费 → 接收队列满 → 写入 `WouldBlock` → 堆积）→ 发送方按策略丢弃并计**发送方** `queue_dropped`；**接收队列满**（tcp / unix / pipe 上本端消费跟不上）→ 接收方按同一策略丢弃并计**接收方** `queue_dropped`。**inproc 上接收队列只能由发送方 `write` 填充、满即 `WouldBlock`，故该分支在 inproc 上不可达**——inproc 的溢出一律由发送方发送队列承担。**丢弃一律发生在「自己的」loop 线程上**，监控环的生产端约束因此成立 | P0 |
| FR-3.9 | **不参与发现**：`publish_local = 1` 时 `endpoint_create` 返回 `INVALID_ARGUMENT`，不做静默空操作 | P0 |
| FR-3.10 | **有意放宽**：编解码后的缓冲可以以移动代替拷贝交给接收方（零拷贝收益）。**大小校验不在此列**——见 FR-3.8 | P1（**实现约束**：是「允许怎么做」而非可观测行为，不可从 C ABI 观测，**不单独挂 AC**；正确性由 FR-3.8 的帧结构 / 大小校验保证，后者的可观测部分是 **AC-82**） |
| FR-3.11 | **不跑应用层心跳**（2026-11-11，D-5 / N-58）：inproc **不发 `HEARTBEAT` / `HEARTBEAT_ACK`**（它们是线格式帧，[线格式 §7](api/wire-format.md) 已定 inproc 不走线格式），因而**没有心跳周期**、`peer_status.last_heartbeat_ns` **恒为 0**、inproc 连接**不产生 RTT 样本**（`stats.rtt_p50/p99/max_ns` 只在**本 Runtime 仅有 inproc 连接**时为 0，混合传输时照常累计 tcp 样本）。**这不是「因为没有网络所以不需要检测」**——同地址空间能免掉「半开」（对端销毁是直接可观测事件），免不掉「**对端 loop 卡死**」（连接还在、但对端不消费）。**卡死信号与 tcp 同构**：接收方不消费 → 接收队列满 → 发送方**写入 `WouldBlock`** → 消息堆积在**发送方发送队列** → 发送方按端点策略丢弃并计**发送方** `queue_dropped`（FR-4.6）。这与 tcp 上「对端不读 → 内核写缓冲满 → 发送队列堆积」是同一条链路，**不是类比**——inproc 与 tcp 走的是同一段「写不动就回 `WouldBlock`」的代码（[架构 T3](architecture.md)）。**盲区与 tcp 相同**：缓冲尚未填满时无信号（这是所有传输共有的「缓冲未满前不可见窗口」，不是 inproc 特有缺陷）；per-connection 卡死定时器 v1 不做 | P0 |
| FR-3.12 | **断开由直接通知驱动，无重连**（2026-11-11，D-5 / N-58）：inproc **不适用 FR-4.4 的自动重连**——对端 Runtime **销毁** / 对端 / 本端对连接调用 `conn_destroy` / `conn_abort` / `conn_close_graceful` / `CLOSE_AFTER` 时，同地址空间**直接送达**断开，**两端连接对象均终结**（对端先断的一方先入排空窗口、队列取空后才终结；无需等超时推断）。**通知两路**：① **对端先断** → 本端经 loop 任务收到 `connected = FALSE` 推送与断开事件；② **本端先销毁连接** → 本端按既有语义收尾、**不再对自己推一次断开事件**，仅向对端投递通知。**两端同时销毁时各自回收、互不等对方**。连接对象**终结**（不进入 `Reconnecting`、不自动重拨）——**本端销毁立即终结**；**对端先断**则先入排空窗口、**接收队列取空后才终结**。终结后**句柄失效**——断开当下在途异步发送**按 c-abi §5.2 取消表按触发源报码**：本端 `conn_destroy` / `conn_abort` → `CANCELLED`，`runtime_destroy` → `CANCELLED`，`*_close_graceful` → 实际结果或 `CANCELLED`，**对端断开 / 对端 Runtime 销毁 → `DISCONNECTED`**；此后对旧句柄的任何调用返回 `STALE_HANDLE`（FR-1.6 兜底，绝不 UB）。**为何不重连（与 nng 的有意分歧）**：nng 的 inproc dialer **确实会重连**（其 `reconnect_test.c` 四条路径全用 inproc，含「listener 关闭后重开」）；拒绝它是**策略选择而非能力缺失**——本库的重建语义是「应用删连接 → 删对端端点 → 应用重建对端端点 → 应用重连」，这是唯一的已知正确时序，不把它固化成「一个自动重放且会失败的循环」。应用要恢复须**重新 `connect*` 创建新句柄**（与 FR-4.4 的句柄复用是两条路径，不可混用）。**`runtime_stop` 不算断开**——它只停止接受新的写操作，已建立的连接与**其发送队列在继续驱动 loop 时照常中继**，与其它传输同口径。**定序（2026-11-13）**：断开通知经 loop 任务到达、数据在接收队列，**二者不在同一条 FIFO**。故定义**排空窗口**：对端先断时，连接进入「已断开、待排空」——`connected` 的**条件值立即变为 `FALSE`**（`conn_status` 可读），但**断开事件推迟到该连接在当前路由所在接收对象中的「可交付残留」为 0 之后才推送**（连接级 = 自己的接收队列；端点级 = 只算该连接在端点队列中的项；**已取出但尚未完成交付的项仍计入**）；推送模式下先回调完队列内全部已写入消息、拉取模式下**按该连接当前路由取完**（连接级持有用 `conn_recv`；端点级持有时路由在端点队列、`conn_recv` 返回 `INVALID_STATE`，须用 `endpoint_recv`）——**窗口内句柄保持有效**，窗口结束后才推事件、才失效。**本端主动销毁不进入排空窗口**（按销毁语义立即丢弃剩余消息、句柄立即失效）。| P0 |

> **为什么 M1 需要它**：M1 是「只碰句柄表 / 会话 / 队列 / 回调，不碰 socket 与平台差异」的闭环。删掉 inproc 会把 M2 的传输验收整体前移（已否决方案 E-1）。
>
> **与行业的分歧（有意）**：nng 在 inproc 上**忽略** `NNG_OPT_RECVMAXSZ`（理由是同地址空间「implicitly trusted」）。本库保留出站校验，理由是 ① 有界队列（FR-4.6）要求队列占用有上界，否则「有界」只在部分传输上成立；② 同一 payload 在 tcp / inproc 上行为一致。代价只是每消息一次比较。入站超限分支保留同一代码路径——在 inproc 上不可达，不为它单独分叉。

### FR-4 终端间通信

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-4.1 | 跨机 TCP 通信 | P0 |
| FR-4.2 | UDP（含组播/广播） | **v1.1**（v1 的 `listen_transport` 不含 `"udp"`，见 [C ABI §5.1](api/c-abi.md)） |
| FR-4.3 | 帧定界：有界消息，不暴露字节流 | P0 |
| FR-4.4 | 自动重连（指数退避 + 抖动）。**四件确定的语义（2026-11-04，N-06）**：① **复用同一 `iocomm_conn_t` 句柄**（重连窗口内句柄有效）；② 断开时在途未发项**逐条 `DROPPED(PEER_GONE)`**、`on_done(DISCONNECTED)`，**重连不重放**；③ `sequence` **随连接重置**（新连接从 1 起，跨重连顺序只能靠应用层 `correlation_id`）；④ **订阅保持**（挂在连接对象上），`peer_node_id` 以新握手结果更新。详见 [架构 §5.2c](architecture.md)。**作用域（2026-11-11，D-5 / N-58）：仅 tcp / unix / pipe**——inproc 不适用本条的自动重连，断开后连接终结、不重拨，见 FR-3.12 | P0 |
| FR-4.5 | 背压策略可配（阻塞 / 丢最旧 / 丢最新 / 报错），**按端点配置** | P0 |
| FR-4.6 | 有界队列 + 溢出可见（丢弃计数） | P0 |
| FR-4.7 | **队列的三层上限**（2026-11-18 重写，N-62 / N-63）：① 条数 ≤ `queue_max`（默认 1024）；② **单队列字节** ≤ `queue_budget_bytes + max_message_size`（默认 64 MiB + 1 MiB，**可被 `endpoint_config.queue_budget_bytes` 按端点覆盖**）；③ **全部队列字节** ≤ `queue_total_bytes + max_message_size`（默认 256 MiB + 1 MiB，含在途入站帧缓冲，**无端点级、不按端点均分**）。② 是准入阈值、③ 是硬上限，**两者必须同时满足**——端点放宽单队列预算不能突破总量。任一不满足按目标端点策略处理。**字节预算与 `max_message_size` 解耦**——旧公式 `min(queue_max × max_message_size, 64 MiB)` 已废止（它让调大单条上限意外放大队列内存，且反向锁死单条上限）。**空队列无条件接受一条消息**（单条不可分割，否则大消息永远进不了队列）。**按需分配**：三条都是记账上限，不是预留量 | P0 |
| FR-4.8 | **端点级套接字参数（2026-11-04 新增，N-12）**：TCP 的 `TCP_NODELAY` 与监听 `backlog` 可按端点配置（`endpoint_config` 尾部字段）或全局热更新（`tune_config`）。`tcp_nodelay` **默认开**（小消息低延迟优先于带宽）；`listen_backlog` 默认 **128**。0 一律表示「用默认 / 保持当前值」，与其它字段口径一致。v1 **不暴露**内核 keepalive 开关——半开检测依赖应用层心跳（FR-5.3） | P0 |

### FR-5 状态监控与控制

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-5.1 | 连接/节点状态（**条件集**，不是扁平枚举）。**`lively` / `healthy` 的判定语义只适用于 tcp / unix / pipe**（2026-11-11，D-5 / N-58）：inproc 上二者**恒为 `TRUE`**（没有心跳即没有能翻转它们的来源，也不存在 `UNKNOWN` 的「窗口未满」态），对端异常的可观测面由 **FR-3.11**（发送方发送队列堆积，与 tcp 同构）与 **FR-3.12**（直接通知的断开）承担。`connected` / `config_current` 四个传输同义 | P0 |
| FR-5.2 | 状态变化**可订阅**（不只是 `get_state()`）。**两级订阅**：连接级 `iocomm_conn_condition_subscribe` 只报该连接；**端点级 `iocomm_endpoint_condition_subscribe` = 对「当前与未来全部成员连接」条件集变化的聚合**（2026-11-05，N-45）——等价于对每个成员连接各订阅一次但**只产生一个订阅句柄**；新成员**自动纳入**、不需要在 `accept` 回调里补订阅。**成员离开**：其状态变化照常推送（含最后一次 `connected = FALSE`，与逐连接订阅等价，且**推送先于**摘除），摘除后停止投递，但**不额外推送「成员离开」这类独立事件**（上线归 `endpoint_accept`，节点上下线归 `discovery`）。**本端主动销毁例外（通用语义）**：`conn_destroy` / `conn_abort` / `*_close_graceful` 由调用方自己发起，**不向自己推送最后那次 `connected = FALSE`**；对端侧照常收到。**inproc 的排空窗口**：对端先断时该连接**先推送完「可交付残留」、再推 `connected = FALSE`、之后才摘除**（不改变「推送先于摘除」，只是把「最后一次推送」放到数据之后）。**「可交付残留」按该连接当前路由所在的接收对象计**——连接级持有算它自己的队列，**端点级持有只算该连接在端点队列中的项**（不被其他存活连接的消息拖延）；**已取出但尚未完成交付的项仍计入**（订阅模式 = 回调未返回；拉取模式 = `conn_recv` 未写入 `*out`）。**成员定义 = 计数成员**（= FR-8.6 扇出集合 + inproc 排空窗口内的连接）。**carve-out（2026-11-13，仅 inproc）**：排空窗口内的连接**仍计入 `conn_count(ep)`、条件订阅仍覆盖**，但**不计入扇出集合**（`endpoint_send` 视其为不存在）；若端点内再无其他扇出成员，扇出按 **`NO_RECEIVER`** 处理（与「无成员连接」同一条规则），并产生 `DROPPED(NO_SUBSCRIBER)`。端点无自身状态，回调的 `conn` 与 `ep` **恒非 0** | P0 |
| FR-5.3 | 应用层心跳（带序号 + 双向确认）。**作用域（2026-11-11，D-5 / N-58）：仅 tcp / unix / pipe**——inproc 不发心跳，见 FR-3.11 | P0 |
| FR-5.4 | 指标快照：吞吐 / 延迟 / 队列深度 / 丢弃 / 重连次数 / **协议错误数**（`protocol_errors`）。**作用域 = 本 Runtime**（聚合值；无 per-connection 维度）——见 §4 非目标表与 [open-questions N-47](open-questions.md)。**队列水位四个值都是「取 max、不求和」**（2026-11-18，N-55）：条数（`*_depth`）与 **payload 字节**（`*_bytes`）各一对，因为是「条数 + 字节」双约束——大消息下条数会严重低估压力。**分母不随这四个值返回**（最满队列的 `queue_max` / `queue_budget_bytes` 可能是端点级覆盖值），要算精确填充率请用 `iocomm_diagnostic_dump` 的 `endpoints[]`（那里逐端点给出分母） | P0 |
| FR-5.5 | 诊断 dump：**连接表 + 队列水位**，JSON 文本（顶层含 `"version"` 键，供格式演进）。**作用域 = 本 Runtime**；`send_queue_depth` 为端点级（成员连接共用端点发送队列），`recv_queue_depth` 为每连接一条。<br>**同时是 v1 唯一的「跨线程连接枚举」入口**（2026-11-09，D-2）：**任意线程**均可调用，取「当前全部存活连接」及其状态与队列水位，**无需**自行维护句柄表；owned 模式下应用线程不可调 `conn_count` / `conn_get`（仅 loop 线程）。结果允许是**近似一致**——逐条目取自同一次 dump 调用内，但**不承诺跨调用**的一致性。**不做**专用快照句柄 API（`conn_snapshot_take/count/get/release`，业界同族库均无，见 [open-questions N-46](open-questions.md)） | P1 |
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
| FR-6.4 | **库支持「无内部线程、调用方驱动」**（`run_once` / `run_for`）。`run_once(timeout_ms)` 驱动一轮：处理了事件返回 `OK`，纯空闲返回 `TIMEOUT`（**正常事件，非故障**），`timeout_ms = 0` 只轮询一次；`run_for(duration_ms)` = 循环 `run_once` 至累计驱动满 `duration_ms`，`0` 为空操作，**从不返回 `TIMEOUT`**（C ABI §4 为唯一权威） | P0 |
| FR-6.5 | 也可托管运行（自带**单** IO 线程）。**AC 口径**：owned 模式下主线程不调 `run_once` 也能完成收发，且 IO 线程恒为 1。**Stopped 为终态，不可再 `start`（返回 `CLOSED`）；恢复需销毁后重建（见 AC-116）** | P0 |
| FR-6.6 | 取消语义明确（取消后仍回调一次，带 `CANCELLED`）——**由 AC-111⑤ 覆盖**（不另立 AC） | P1 |
| FR-6.7 | 在回调线程 / loop 驱动线程内调用**阻塞型**同步 API → 返回 `WOULD_DEADLOCK`，而不是死锁。**不适用于**非阻塞的所有权 / 注册类调用：`conn_retain`（N-36）、`conn_subscribe`、`endpoint_accept` 与两个 `*_condition_subscribe`（N-39）**在回调内合法**，见 [C ABI §6.4 @special](api/c-abi.md#64-拉取与推送的互斥规则) | P0 |
| FR-6.8 | **同一接收对象上 `subscribe` 与 `recv` 二选一**：先设置者生效，后调用者返回 `INVALID_STATE`（实现依据：[C ABI §6.4](api/c-abi.md#64-拉取与推送的互斥规则)） | P0 |

### FR-8 远端寻址与连接

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-8.1 | 显式连接远端地址（`transport` + `addr`）→ 得到**连接**句柄 | P0 |
| FR-8.2 | 通过发现结果连接（`node_id` + 端点名）。**地址解析规则（2026-11-04，N-05）**：在发现表的 `node_info.endpoints` 中按 `name` **精确匹配** → 取该条目的 `transport` + `addr`（**通告值**，见 FR-8.12）拨号；成员不存在 / 节点不存在 → `NOT_FOUND`；transport 未实现 → `NOT_SUPPORTED` | P0 |
| FR-8.3 | 连接是双向的：出站连接也能接收对端数据 | P0 |
| FR-8.4 | 发现阶段二上报**端点能力**（对端注册了哪些端点） | P0 |
| FR-8.5 | **入站连接必须可被应用拿到**：`endpoint_accept` 回调交付连接句柄（**借用**：仅在回调期间有效）。**交付时点**：tcp/unix/pipe 上为**双向 HELLO 完成后**（此时 `peer_node_id` 必有值、连接已可发 DATA）；inproc 为**连接建立即交付**（无 HELLO，见 FR-3.5 / 线格式 §7）。握手期的连接是内部会话，不分配句柄、不占 `max_handles`；握手失败/超时**不触发** `accept`；**交付时句柄表已满同样不触发**（连接立即 FIN，见 [C ABI §6.0](api/c-abi.md)） | P0 |
| FR-8.6 | 发送目标语义明确：连接 = 点对点；端点 = **扇出到该端点的扇出集合** = 全部成员连接（入站 + `ep_owner == ep` 出站），**但 inproc 排空窗口内的连接除外**（它仍计入 `conn_count(ep)` 且条件订阅仍覆盖，只是不参与扇出，见 FR-5.2） | P0 |
| FR-8.7 | 收到消息时可从 `from` 取得来源连接，用于**回发** | P0 |
| FR-8.8 | **入站连接的持有**：显式 `conn_retain`、隐式 `conn_subscribe`、**端点级持有**（端点已启用 `iocomm_subscribe(ep)` / `endpoint_recv(ep)`）三者之一即持有；都不做则**全部** `accept` 回调返回后自动关闭（**优雅关闭**：tcp / unix / pipe 上为优雅 FIN；inproc 上为断开通知驱动的 `connected = FALSE`，见 c-abi §5.1b；多个 accept 回调时，**任一**完成持有即保留，**任一** `conn_destroy` 则其余回调不再触发——见 AC-33 / AC-33b）。**发送不是所有权开关**：「发完即关」用 `ICOMM_SEND_CLOSE_AFTER`（ADR-002）。**端点既无 `endpoint_accept` 回调、也无端点级订阅/拉取时，入站连接在交付时点即关闭（tcp / unix / pipe 上为 FIN；inproc 上为断开通知），见 AC-114** | P0 |
| FR-8.10 | **端点销毁时的出站连接**：`ep_owner == ep` 的出站连接**继续存活**，未发项原子迁移到各自的连接队列（容量取 runtime 默认），不再计入该端点扇出 | P0 |
| FR-8.9 | **连接的四种关闭**：`conn_destroy`（立即取消在途发送、丢弃缓冲、以**优雅关闭**终止——tcp / unix / pipe 为 FIN；inproc 为断开通知；各回调一次 `CANCELLED`）/ `conn_close_graceful(linger_ms)`（flush 后关）/ `ICOMM_SEND_CLOSE_AFTER`（发完即关）/ `conn_abort`（**异常中止**——tcp / unix / pipe 为 RST；inproc 无 RST，与对端断开观测面相同，见 c-abi §5.1b） | P0 |
| FR-8.11 | **端点级接收（2026-11-03 新增）**：`iocomm_subscribe(ep)` / `iocomm_endpoint_recv(ep)` 一经启用，即**隐式持有**该端点此后的全部入站连接（**全部** accept 回调仍会触发、仅用于观测，不因端点级收消息已启用而被拒——N-37）；不注册 `endpoint_accept` 时同样可正常接收。入站消息默认进入**端点接收队列**；被 `conn_subscribe` / `conn_retain` 单独接管的连接改进入该连接的接收队列，不再参与端点级投递（不双投）。**三项补充（2026-11-05）**：① **`endpoint_accept` 与端点级收消息正交**——两轴可分可合、可任意顺序注册，`endpoint_accept` **不因 `recv` 已启用而返回 `INVALID_STATE`**（N-37 / AC-117）；② **端点级持有的那一刻路由即定死**——此后 `conn_retain` 只做所有权确认、返回 `OK` 但不改路由，对该连接 `conn_recv` 返回 `INVALID_STATE`（N-38 / AC-118）；③ 上述「单独接管」仅指**端点级收消息未启用**时的情形（N-38） | P0 |
| FR-8.12 | **端点地址的通告值（2026-11-04 新增，N-05）**：库在发布端点能力（`ENDPOINTS` tag 与 `iocomm_endpoint_info.addr`）时，若 `listen_addr` 是通配地址（`0.0.0.0` / `[::]`）或端口为 0，则**替换为实际监听地址 + 实际端口**；实际地址仍是通配地址时，用**发送该发现报文所用 socket 的本地地址**替换。`iocomm_endpoint_local_addr()` 返回**原始监听值**（端口 0 时返回系统分配的实际端口，`0.0.0.0` 原样保留）。两者不混用：`endpoint_info.addr` = 可拨号通告值；`endpoint_local_addr()` = 本端监听事实 | P0 |
| FR-8.13 | **监听配置的合法性（2026-11-04 新增，N-14）**：`listen_transport` 与 `listen_addr` 成对使用——**两者皆空 = 纯出站端点（合法）**；**只填 addr（transport 空）→ `INVALID_ARGUMENT`**（不猜默认传输）；**只填 transport（addr 空）→ `INVALID_ARGUMENT`**（无「监听任意地址」简写）；未知传输名 → `NOT_SUPPORTED`。判定发生在注册之前，失败不占用端点名。组合表见 [C ABI §5.1c](api/c-abi.md) | P0 |
| FR-8.14 | **异步操作 ID 与取消（2026-11-04 新增，N-10）**：`op_id` **每 Runtime 单调分配、永不回绕**，耗尽 → `RESOURCE_EXHAUSTED`（与 `capture_id` 同口径）。该取消对已完成 / 从未分配 / **已取消过**的 `op_id` 一律返回 `NOT_FOUND`，且**不再触发** `on_done`。**`op_id` 不可跨 Runtime 使用**：判据只是目标 Runtime 自己的操作表，数值碰巧相同就会误取消对方同号操作 | P0 |

### FR-9 节点身份

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-9.1 | 节点身份（`node_id`）跨进程重启**保持稳定** | P0 |
| FR-9.2 | 支持显式配置或自动持久化（`state_dir`）。**自动模式要求 `state_dir` 非空且可写**；不满足 → `runtime_create` 返回 `INVALID_ARGUMENT`（v1 **不派生**自 machine-id / 主机名 / MAC——见 [架构 §5.1b](architecture.md)）。**自动模式下若 `state_dir` 已被另一仍存活的进程占用（名字文件存活标记有效），`runtime_create` 返回 `CONFLICT`；进程退出后同目录可复用（见 AC-115）** | P0 |
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
| FR-10.3 | **丢弃必带原因**（`queue_full` / `no_subscriber` / `timeout` / `peer_gone` / `backpressure` / `too_large`——`too_large` **仅接收侧**（入站帧超限），发送侧超限走返回值、不产生 `DROPPED`）。**`timeout` 的口径**：异步发送排队超过 `iocomm_send_options.queue_timeout_ms`（从入队成功到开始写传输层；开始写之后不再超时） | P0 |
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
| **per-connection 的指标维度**（2026-11-09，N-47 裁决 / 关闭 N-56 断链） | FR-5.4 的指标快照**作用域 = 本 Runtime**（聚合值），**不提供** per-connection 的吞吐 / 延迟 / 丢弃计数；`iocomm_peer_status` 只带条件集 + `last_rx_ns` / `last_heartbeat_ns` / `reconnect_count`（它同时是 `iocomm_condition_fn` 的回调载荷，加累加值会让每次状态推送变重）。逐连接的**队列水位**可从 `iocomm_diagnostic_dump` 取（FR-5.5）。v2 若确需 per-conn 吞吐再评估 |
| **专用连接快照句柄 API**（`conn_snapshot_take/count/get/release`）（2026-11-09，D-2 / N-46） | 需要从任意线程枚举连接时走 **`iocomm_diagnostic_dump`**（跨线程安全，含状态与队列水位）+ 逐句柄 `conn_status`；loop 线程上仍可直接 `conn_count` / `conn_get`。**不做**专用快照句柄：libuv / Asio / libevent / ZeroMQ / NNG / DDS / iceoryx / ROS 2 均无「任意线程同步枚举」的专用入口（调研见 `open-questions.md` N-46），且快照句柄会占用 `max_handles` 名额、引入新的 `WOULD_DEADLOCK` 情形。v2 若确需再评估 |
| **应用线程同步投递进 loop 并阻塞等待**（2026-11-09，D-2） | 本库只提供**非阻塞**投递原语（`*_send_async` / `connect*_async` / `runtime_wakeup` / `runtime_reconfigure`）。「投递 + 阻塞等结果」需调用方自己用 `runtime_wakeup` + 条件变量搭——库不提供该原语。业界同族库同样如此（libuv `uv_async_send`、Asio `post`、libcurl `curl_multi_wakeup` 均只唤醒不等待） |
| **跨进程 / 集中式监控**（2026-11-05，N-42） | 监控入口全部挂在 `iocomm_runtime_t` 上，**作用域 = 本 Runtime**。管理进程要观测被管子进程，须在每个进程内各嵌一个 Runtime 由应用自己汇总；库不提供中心守护进程或跨进程指标通道。行业先例（iceoryx 的 RouDi、OPC UA 的 `ServerDiagnosticsSummary`、ZeroMQ 的 `inproc://` monitor）均表明这需要一个**中心组件**。v2 评估 |
| **事件循环投递入口（`runtime_post` 类）**（2026-11-05，N-43） | 回调内只做异步发送 + 置标志位，数据处理放 `run_once` 返回后即可覆盖全部「稍后再做」需求；**真正做不到的只有「回调内延迟 N ms」，而 post 也做不到**（v1 无定时器公开入口，见架构 T6）。在 C ABI 上实现需新增 6 条契约（取消语义 / `user` 生命周期 / 队列满策略 / 自我投递 / `run_for` 交互 / 销毁时未执行任务），5–8 人日。v2 评估 |
| **多通信域 / 网络级分区**（2026-11-05，N-44） | v1 组播组 `239.255.73.77` + 端口块 `23100..23200` 硬编码，**同网段 = 单发现域**。硬隔离请用 **VLAN / ACL / 独立网卡 / 网络命名空间**——本库的名字锁是机器级、不构成网络边界，**域 ≠ 安全边界**（v1 无认证无加密，见 §4.1）。DDS / ROS 2 的 Domain ID 方案有明确的端口规划成本（`7400 + 250×domainId`，ROS 2 实测仅 0–101 与 215–232 可用）。v2 与 TLS 同批评估 |
| **发现端口可配置（`discovery_config.listen_port` 类字段）**（2026-11-10，D-4） | v1 **不提供**端口配置入口（[线格式 §8.1](api/wire-format.md) 写明理由）。端口撞车是**宿主机级**问题——同机所有进程共享内核端口池，字段改不了内核会不会先把它分给出站连接；且端口**同时就是发现域**（两机配不同端口 → 静默互不可见），等价于半个 `domain_id`，与 N-44 的「v1 单发现域」裁决冲突。v1 的做法是把默认块迁到 `23100..23200`（Linux `32768–60999` 与 Windows `49152–65535` 两个默认动态段之外）使默认配置下不再冲突。v2 与 `domain_id` / TLS 同批评估 |
| **inproc 的心跳与自动重连**（2026-11-11，D-5 / N-58） | inproc **不发 `HEARTBEAT` 帧、不判定 `lively` / `healthy`、不自动重连**——心跳是线格式帧，inproc 不走线格式（[§7](api/wire-format.md)）；且对端异常在**同地址空间**里无需靠超时推断。**卡死信号与 tcp 同构**：接收方不消费 → 接收队列满 → 写入 `WouldBlock` → **发送方发送队列**堆积 → 按端点策略丢弃并计**发送方** `queue_dropped`；断开改由**直接通知**驱动、句柄在排空窗口后才失效（[FR-3.11 / FR-3.12](requirements.md)）。**盲区与 tcp 相同**：缓冲未满前无信号；per-connection 卡死定时器 v1 不做 |
| **按字节的端点级预算精细分配（如按端点均分总量）**（2026-11-18，N-62 / N-63） | 队列字节预算是**两层**：`queue_budget_bytes`（每队列，**端点级可覆盖**）+ `queue_total_bytes`（Runtime 总量，**无端点级、不均分**）。**不做**「把总量按端点均分」——端点是动态创建的，`max_handles` 只给上界 4096，均分后每端点仅 `256 MiB / 4096 = 64 KiB`，比一条默认消息还小。总量是**先到先得的水位**（与 RabbitMQ 全局内存水位同构），端点级只调「自己的准入阈值」，**不能突破总量**。需要的是「某端点可以多占」时设它的 `queue_budget_bytes` 即可；需要「某端点不得占用过多」时同理设一个较小的值 |
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

> **域隔离边界（2026-11-05，N-44）**：**域 ≠ 安全边界**。v1 是**单发现域**——同一网段内所有启用发现的 Runtime
> 互相可见（见 §4 非目标表）。库提供的名字锁是**机器级**（Linux 抽象 `AF_UNIX` socket / Windows `Global\iocomm_*`，
> 后者在无 `SeCreateGlobalPrivilege` 时回退 `Local\`，见 [平台支持 §2.1](platform-support.md)），
> **不构成网络边界**。需要两个互不可见的通信域时，请在部署层使用 **VLAN / 交换机 ACL / 独立网卡 / 网络命名空间**；
> 不要依赖「不同组播组」——v1 的组播组地址与端口均不可配置。**也不要依赖「同机配不同端口」**——端口字段根本不存在（2026-11-10，D-4）；即便将来加上，端口**同时就是发现域**，配成不同值的两机会**静默**互相看不见。
> **推论**：本库的「隔离」语义只有三条——进程边界（不能直接访问他进程句柄）、`state_dir` 属主标记（同一目录不能有两个自动 `node_id` 的 Runtime）、
> 端点名跨进程唯一性。**没有任何一条是安全意义上的隔离**。

---

## 5. 验收标准

### 5.1 功能验收

| 编号 | 验收项 | 判定 | 覆盖 |
|---|---|---|---|
| AC-1 | 两进程（同机）互发消息，字节完全一致 | 通过 | FR-3.1 |
| AC-2 | 两机（跨网）互发消息，字节完全一致 | 通过 | FR-4.1 |
| AC-3 | 对端被 `kill -9` 后，N 秒内检测到并触发事件 | 通过（检测时间可调） | FR-3.3 / FR-5.3 |
| AC-4 | 句柄失效后再使用返回 `STALE_HANDLE` | 通过 | FR-1.6 |
| AC-5 | **回调内销毁端点/订阅** 返回 `WOULD_DEADLOCK`，进程不崩溃。**例外清单**（见 C ABI §6.4 `@special`）：① 在**本订阅自己的回调内**用 `unsubscribe` 取消本订阅 → `ICOMM_OK`；② `conn_destroy(本回调交付的 conn)` → `ICOMM_OK`。**非阻塞的所有权/注册类调用不受本条约束**（`conn_retain` / `conn_subscribe` / `endpoint_accept` / 两个 `*_condition_subscribe`，见 FR-6.7） | 通过 | FR-6.7 |
| AC-6 | 回调中调用**阻塞型**同步 API（`conn_send` / `endpoint_send` / `*_recv` / `connect` / `conn_close_graceful` 等）返回 `WOULD_DEADLOCK`；`conn_retain` 等非阻塞所有权调用**不返回**该码（FR-6.7 / C ABI §3.2.1） | 通过 | FR-6.7 |
| AC-7 | 组播被禁时，靠单播 seed 仍能发现。**可执行步骤**（2026-11-18，N-60）：双侧 `enable_multicast = 2`；B 正常启动（单播端口由库从 `23101..23200` 分配）；A 配 `seeds = ["<B主机>:0"]` → ① A 的 `discovery_snapshot` 在 **1 s 内**出现 B，且 B 的端点列表、`node_info` 与 B 自述一致；② A 记录的 B 地址端口 **等于 B 的实际单播端口**（不是 `23100`）；③ **B 侧不出现 A**（单向）；④ 对照组：seed 写成 `"<B主机>:23101"`（非 0 端口）→ `discovery_start` 返回 `INVALID_ARGUMENT` 且发现未启动。**对照组 2**：B 重启并换到另一个单播端口 → A 在租约到期后重扫，B 重新出现在 A 的快照里（不永久丢失） | 通过 | FR-2.4 |
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
| **AC-29** | 服务端在 `endpoint_accept` 回调内 `conn_retain`（**端点级收消息未启用**的情形），另一线程用 `conn_send` 回发；客户端能收到（回调内不得用同步 `conn_send`，会返回 `WOULD_DEADLOCK`） | 通过 | FR-8.5 / FR-8.7 / FR-8.8 |
| **AC-30** | `endpoint_send` 扇出到 **N = 该端点参与扇出的成员连接**（入站成员 + `ep_owner == ep` 的出站连接；**inproc 排空窗口内的连接不计入 N**，见 FR-5.2 carve-out），`out_delivered == N`；无扇出成员时返回 `NO_RECEIVER` | 通过 | FR-8.6 |
| **AC-31** | 出站连接上 `conn_subscribe` 能收到对端数据（双向） | 通过 | FR-8.3 |
| **AC-32** | 同一接收对象上 `subscribe` 与 `recv` 同时使用，第二个调用返回 `INVALID_STATE` | 通过 | FR-6.8（实现依据 [C ABI §6.4](api/c-abi.md#64-拉取与推送的互斥规则)） |
| **AC-33** | `accept` 回调返回时既未 `conn_retain` 也未 `conn_subscribe`、**且该端点未启用端点级订阅/拉取**的连接被自动收回（连接数回到 0，对端观测到**优雅关闭**：tcp / unix / pipe 上为**优雅 FIN 而非 RST**；**inproc 上为断开通知驱动的 `connected = FALSE`**，因 inproc 无 FIN / RST，见 c-abi §5.1b）。**多次注册的边界（N-37）**：同一端点上注册了**两个** `endpoint_accept` 回调时，**只要其中任一回调返回时完成了持有**（`conn_retain` / `conn_subscribe` / 端点级持有），连接即被保留；两个都不持有时才回收。**未在任一回调内被 `conn_destroy` 时**，全部回调**按注册顺序**各触发一次，生命周期判定在所有回调跑完后进行；**若某个回调销毁了该连接，其后尚未执行的 accept 回调不再触发**（见 AC-33b 与 C ABI §6.4 `@special`） | 通过 | FR-8.5 / FR-8.8 |
| **AC-33b** | 回调内显式 `conn_destroy` 拒绝同样以 FIN 关闭；`conn_abort` 才产生 RST。**多次注册时（N-37）**：第一个 accept 回调内 `conn_destroy` 后，**其后尚未执行的 accept 回调不再触发** | 通过 | FR-8.8 / FR-8.9 |
| **AC-33c** | **自动收回 / 无消费者的 tcp 观测（覆盖 AC-33 与 AC-114 的 tcp 分支，归 M2）**：AC-33b 测的是「回调内显式 `conn_destroy`」，触发路径不同，不能顶替。(i) `accept` 回调返回且未持有、**且该端点未启用端点级订阅/拉取**时，对端观测到**优雅 FIN（`recv` 返回 0）而非 RST**；(ii) 端点无 `endpoint_accept` / 端点级订阅 / 端点级拉取时（AC-114 场景），对端同样观测到**优雅 FIN 而非 RST**。unix / pipe 见 AC-33d；inproc 分支见 AC-33 / AC-114（断开通知驱动的 `connected = FALSE`，无 FIN / RST） | 通过 | FR-8.5 / FR-8.8 |
| **AC-33d** | **自动收回 / 无消费者的 unix / pipe 观测（覆盖 AC-33 与 AC-114 的 unix/pipe 分支，归 M5）**：同 AC-33c 的两种触发路径——(i) accept 回调返回且未持有、且端点未启用端点级订阅/拉取；(ii) 端点无任何消费者。二者下对端均观测到**优雅关闭（`recv` 返回 0）而非连接重置**。与 AC-33c 的差别仅在传输（unix socket / 命名管道），断言同一可观测结果 | 通过 | FR-8.5 / FR-8.8 |
| **AC-34** | `endpoint_create` 返回非 0 句柄，且 `endpoint_name_state` 为 `HELD_BY_SELF`；按名字查询 / 枚举端点返回正确结果；不存在时返回 `NOT_FOUND` | 通过 | FR-1.1 / FR-1.3 |
| **AC-35** | 三项静态检查全过：① 所有句柄最终 typedef 为 `uint64_t`（经 `iocomm_handle_t` 间接亦算），声明中无 `void*` 句柄；② **声明部分**（结构体字段 + 函数参数 + 返回值，排除注释）无 `long` / `size_t` / `bool`；③ **cdylib** 的公开 API 符号均为 `iocomm_*`（Linux `nm -D`，Windows `dumpbin /exports`；M0 先取实际清单，必要时给白名单）；staticlib 不做此检查 | 通过 | FR-7.1 / FR-7.4 / FR-7.6 |
| **AC-36** | 把 `conn` 句柄传给 `endpoint_*` 函数返回 `STALE_HANDLE`（不误用） | 通过 | FR-1.6 |
| **AC-37** | `log_fn != NULL` 时，`runtime_start` 后环境指纹**恰好输出一次**（P1） | 通过 | FR-5.7 |
| **AC-38** | `publish_local=1` 的端点出现在 discovery 快照（本机注册表条目并入同一节点表）中，并产生 `JOINED/LEFT` 事件。**含四条边界**：① 端点**先于** `discovery_start` 创建时，启动后仍可见（扫描补齐）；② **同一用户、不同 `state_dir`** 的两个 Runtime（其中一个 `state_dir == NULL`、显式配 `node_id`）**互相可见**，且并入的 `node_info.name` **等于**对端 `runtime_config.node_name`；③ **不同用户**的 Runtime 互相看不见；④ 进程被 `kill -9` 后，对端在 **`lease_ms + discovery_heartbeat_ms` 内**（最坏一个扫描周期 + 租约）产生 `LEFT`（P1） | 通过 | FR-2.6 |
| **AC-39** | `connect_async(ep_owner=ep)` 建立的出站连接计入 `endpoint_send` 扇出与 `conn_count(ep)`；`ep_owner=0` 时两者均不计入。**入站成员连接同样计入两者**（N-01 修正） | 通过 | FR-8.6 |
| **AC-40** | 在 accept 回调内 `conn_retain`（**端点级收消息未启用**）后，另一线程可对该入站连接 `conn_recv` 收到数据；**对照组**：端点已启用 `iocomm_subscribe(ep)` 时同一流程下 `conn_recv` 返回 `INVALID_STATE`（N-38 / AC-118） | 通过 | FR-8.5 / FR-6.2 / FR-6.3 |
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
| **AC-73** | **整帧**（`20 + tlv_len + payload_len`）超过 `max_message_size`：同步发送返回 `TOO_LARGE`；异步发送**同步返回** `TOO_LARGE` 且不入队、**不触发** `on_done`（与 AC-78 一致）；入站超大帧关闭连接并产生 `DROPPED(reason=TOO_LARGE)`。边界用例：payload 恰好使整帧等于上限时**成功**，多 1 字节即失败 | 通过 | FR-4.3 |
| **AC-74** | `conn_send_async` 带 `ICOMM_SEND_CLOSE_AFTER`：对端收到完整数据后观测到优雅 FIN，发送方 `on_done(OK)` 之后句柄为 `STALE_HANDLE`；对 `endpoint_send*`（扇出）使用该标志返回 `INVALID_ARGUMENT` | 通过 | FR-8.8 / FR-8.9 |
| **AC-75** | accept 回调内 `conn_send_async` 既未带 `CLOSE_AFTER`、也未先 `conn_retain`/`conn_subscribe`、**且该端点未启用端点级订阅/拉取** → 返回 `INVALID_STATE`；回调内 `conn_subscribe` 后不 retain，连接保持打开并能持续收数据 | 通过 | FR-8.8 |
| **AC-76** | 连接上有在途 `send_async` 时调用 `conn_destroy`：每条未完成发送的 `on_done` 恰好触发一次且 `code = CANCELLED`，连接随后关闭，无泄漏（AC-E3 口径） | 通过 | FR-8.9 |
| **AC-77** | `queue_timeout_ms=N` 的异步发送在队列长期写不出去时：`on_done(ICOMM_ERR_TIMEOUT)` **恰好一次**、产生一条 `DROPPED(TIMEOUT)`；`queue_timeout_ms=0` 时同场景不超时；**开始写之后不再超时**（注入慢传输，写的中途不发生超时） | 通过 | FR-6.3 / FR-10.3 |
| **AC-78** | 异步发送同步返回非 `OK`（含 `TOO_LARGE`、句柄失效）时 `on_done` **不被调用**；返回 `OK` 时 `on_done` 恰好一次。**边界**：`TOO_LARGE` 走同步返回，绝不走 `on_done` | 通过 | FR-6.1 / C ABI §6.2 |
| **AC-79** | `iocomm_runtime_node_id()` 返回的值与重启后一致；`runtime_config.node_name` 设置的字符串在 `iocomm_runtime_node_name()` 取回一致，且出现在对端发现快照的 `node_info.name` 中；未配置名字时为空串 | 通过 | FR-9.4 / FR-9.1 |
| **AC-80** | 同一进程内两个 Runtime 以 `inproc` 建连并双向收发，字节完全一致；接收回调**不在发送者的调用栈上执行**（回调内读取线程 id 校验） | 通过 | FR-3.5 / FR-3.7 |
| **AC-81** | 同进程内重复 `inproc` 名字 → `ALREADY_EXISTS`；两个进程用同一名字互不可见 | 通过 | FR-3.6 |
| **AC-82** | inproc 上**整帧**超 `max_message_size` 的发送**同步返回** `TOO_LARGE`（与 tcp 同口径，无 `on_done`）；`publish_local=1` + `inproc` → `INVALID_ARGUMENT` | 通过 | FR-3.8 / FR-3.9 |
| **AC-83** | owned 模式：主线程**从不调用** `run_once` 也能完成一次建连 + 往返收发；IO 线程恒为 1（子进程内枚举线程数验证） | 通过 | FR-6.5 |
| **AC-84** | `max_handles = 1` 时，第二次 `endpoint_create` 返回 `RESOURCE_EXHAUSTED`（不崩溃、不静默失败）。**Runtime 不占名额**，故 `max_handles = 1` 时首个 `endpoint_create` 成功、第二个才返回 `RESOURCE_EXHAUSTED` | 通过 | FR-1.7 |
| **AC-85** | `discovery_lease_ms = 3000`：正常心跳续期只产生一次 `JOINED`；停掉对端后 ≤ lease 产生一次 `LEFT`，且快照中该节点被移除 | 通过 | FR-2.3 |
| **AC-86** | `FR-5.1` 四条件（**仅在已建立连接的句柄上观测**；**本条为 tcp 连接**——inproc 的退化取值与断开路径见 **AC-124**）：建连成功后 `connected = TRUE`、`lively = TRUE`；`healthy` 在**未满一个心跳判定周期前为 `UNKNOWN`**、满后变 `TRUE`；注入一次 `ERROR` 帧后 `iocomm_condition_fn` **至少推送一次** `healthy = FALSE`（发生在连接关闭前的同一回调序列内，随后的断开按 FR-4.4 处理；不要求关闭后再拉取 `conn_status` 读到 `FALSE`）；`runtime_reconfigure` 后 `config_current` 由 `FALSE` 变 `TRUE`。**`connected = UNKNOWN` 的建连前/重连期观测已移出本 AC**——`iocomm_conn_status` 需要一个 conn 句柄，而 `connect*()` 在双向 HELLO 完成后才产出句柄（N-03）。重连期该子项已在 **AC-105**（N-06 定案：句柄复用）覆盖 | 通过 | FR-5.1 |
| **AC-87** | 发现快照：空快照 `count == 0` 且 `get(0)` 返回 `NOT_FOUND`；`index` 越界返回 `NOT_FOUND`；`release` 后再次 `release` 或任意 `get` 返回 `STALE_HANDLE` | 通过 | FR-2.8 |
| **AC-88** | 对端进程被 `kill -9`：≤ N 秒产生断开事件；随后对端重启并重新 `listen` 同一 pathname socket / 管道名，**无需人工删除残留文件即成功** | 通过 | FR-3.3 / FR-3.4 |
| **AC-89** | 两进程同时注册同名端点：**第二实例 `create` 返回 `CONFLICT` 且未注册**（本机查不到该端点——`endpoint_lookup` 返回 `NOT_FOUND`；`endpoint_name_state(<原名>)` 仍报 `HELD_BY_OTHER`，由第一实例持有）；同进程内重名 → `ALREADY_EXISTS`，同样不注册。两种情形第二实例都拿不到可用端点句柄 | 通过 | FR-1.4 / FR-1.5 |
| **AC-90** | **TLV 前向兼容**：测试用 `FakeTransport` 向接收方注入一帧，帧内带一个 v1 未定义的 tag（如 `0x00FF`，长度非 0）：接收方**正常投递**该消息、payload 与该帧里的一致、连接**不关闭**；同一帧去掉未知 tag 后结果完全相同（对照组）。再把该 tag 的 `len` 改成越界值 → 连接关闭并报帧损坏 | 通过 | [线格式 §3](api/wire-format.md#3-tlv-扩展区) / FR-4.3 |
| **AC-91** | 一个**未产生 `SENT`** 的报错路径（`TOO_LARGE`、句柄无效）留有环空位：`poll` **取不到任何记录**，`monitor_stats.emitted` 不变；对照组（同样的消息在队列未满时正常发送）产生 `SENT` | 通过 | FR-10.15 / 线格式 §3 |
| **AC-92** | `HELLO` 握手：① 双方互发后连接可用；② 未发 `HELLO` 直接发 `DATA` → 关闭且不投递；③ `min_version` 不满足 → `ERROR(VERSION_UNSUPPORTED)` 后关闭；④ `HELLO` 带 TLV → `ERROR(MALFORMED)`；⑤ **接收尺寸协商**：A 配 1 MiB、B 配 64 KiB，A 发 100 KiB → A 侧**同步返回** `TOO_LARGE`（不是 `on_done(OK)`，也**不触发** `on_done`）；⑥ 握手超时 → `ERROR(HANDSHAKE_TIMEOUT)` 后关闭；⑦ **交付时点**：`accept` 回调只在双向 HELLO 完成后触发——延迟对端发 `HELLO`（或故意只发 TCP 不握手）期间 `conn_count(ep)` 为 0、`accept` 未被调用；对端补发 `HELLO` 后 `accept` 触发一次且 `peer->peer_node_id == 对端 node_id`；握手超时/版本不兼容路径 `accept` **一次都不触发**（对照正常路径） | 通过 | [线格式 §2.1 / §5](api/wire-format.md) / FR-8.5 |
| **AC-93** | 发现报文编解码：对端以组播信标上报的节点表，`discovery_snapshot` 里的 `node_id` / `name` / 端点列表与发送端一致；单播 seed 路径与组播路径得到相同结果；未知字段（TLV）被跳过 | 通过 | FR-2.1 / FR-2.4 / FR-2.9 / [线格式 §8](api/wire-format.md) |
| **AC-94** | `iocomm_diagnostic_dump` 返回的 JSON：顶层含 `"version"`（= **2**）与 `"connections"` 数组；每条连接含 `conn` / `ep` / `peer_node_id` / `connected` / `lively` / `healthy` / `config_current` / `last_rx_ns` / `last_heartbeat_ns` / `last_rx_age_ms` / `last_heartbeat_age_ms` / `reconnect_count` / `send_queue_depth` / `recv_queue_depth` / `send_queue_bytes` / `recv_queue_bytes`（2026-11-18，N-55；**时钟口径**：`last_*_ns` 为**系统单调时钟原值**（Linux `CLOCK_BOOTTIME` / Windows QPC，**计挂起**，原点 = 系统 boot），**同机跨进程可比**、不跨机跨重启（见架构 §6.5）；`last_*_age_ms` 是库算好的毫秒差值，仅在对应 `last_*_ns != 0` 时出现——2026-11-09 复核）；**`send_queue_depth` 在 `endpoints[]` 里为端点级字段**（成员连接共用端点发送队列，逐连接无定义，见 C ABI §6.1「队列归属规则」；2026-11-05，N-40），`connections[]` 内的同名字段是**同一队列的读数**，同一端点的成员连接报同一个值；`ep_owner == 0` 的出站连接 `ep == 0` 且报其**自身**队列深度（2026-11-09，D-2 关闭 N-47 盲区）；`"endpoints"` 数组每条含 `ep` / `name` / `conn_count` / `send_queue_depth` / `send_queue_bytes` / `send_queue_max` / `queue_budget_bytes`，后两者是**该端点的生效分母**（已按 `endpoint_config` > `tune_config` > `runtime_config` 解析，2026-11-19 补，gap-66——N-55 / N-63 追加的 `send_queue_bytes` / `send_queue_max` / `queue_budget_bytes` 三键此前只有契约、无验收）；`version` 与实际实现一致 | 通过 | FR-5.5 |
| **AC-95** | 头文件静态检查：导出的**每个** `iocomm_*` 函数都能在 [C ABI §3.2.1 矩阵](api/c-abi.md) 中找到对应行（无遗漏），且表中列出的码都在 `iocomm_error_code` 内定义。**排除 9 个无错误通道的函数**（签名无 `iocomm_error*`）：`runtime_destroy` / `message_release` / `free_text` / `strerror` / `version_string` / `abi_version` / `runtime_wakeup` / `endpoint_count` / `discovery_snapshot_release`。其余**任何带 `err` 的**函数都必须走 `err` 报告失败，不得发明第二套渠道 | 通过 | [C ABI §3.2](api/c-abi.md) |
| **AC-96** | UDP 传输：两个 Runtime 经 UDP 互发有界消息，字节一致；**超过 MTU 的消息返回 `TOO_LARGE`**（不静默分片）；无连接时 `endpoint_send` 返回 `NO_RECEIVER`（v1.1） | 通过 | FR-4.2 | 〔v1.1〕 |
| **AC-97** | `iocomm_diagnostic_dump` 含 `"errors"` 数组（最近 **64** 条，v1.1 固定容量），每条含 `code` / `ts_ns` / `context`；满 64 条后环形覆盖（v1.1） | 通过 | FR-5.5b | 〔v1.1〕 |
| **AC-98** | 同机两进程共享同一 `node_id`（FR-9.3）：发现表按 `(node_id, process_epoch)` 区分出**两条**记录，各自 `JOINED`；同进程重启后 `process_epoch` 变化而 `node_id` 不变（v1.1） | 通过 | FR-9.3 | 〔v1.1〕 |
| **AC-100** | 队列三层上限（2026-11-18 重写，N-62 / N-63）：① **条数先到**——1 KiB 消息 → 在 **1024 条**时按策略丢弃；② **单队列字节先到**——1 MiB 消息、`queue_budget_bytes = 64 MiB`（默认）→ 第 **64** 条入队后，第 65 条被丢弃（队列非空，字节预算已用尽）——**对照**：把队列取空后，同一条 1 MiB 消息**能**入队（「空队列无条件接受」）；③ **总预算先到**——4 个端点、`queue_total_bytes = 8 MiB` 而每队列预算 64 MiB → 4 个端点合计压满 8 MiB 后按策略丢弃，各端点单队列均未超 64 MiB；④ **空队列无条件接受**：`max_message_size = 8 MiB`、`queue_budget_bytes = 1 MiB` → 一条 8 MiB 消息仍能进入空队列（`send` 返回 `OK`），第二条被丢弃；⑤ **端点级覆盖（N-63）**：全局 `queue_budget_bytes = 4 MiB`，端点 A 覆盖为 `16 MiB` → A 的队列可积压到 16 MiB+，端点 B 仍按 4 MiB 拒收；⑥ **总量不可被端点放宽突破（N-63）**：`queue_total_bytes = 8 MiB`、端点 A 覆盖 `queue_budget_bytes = 64 MiB` → A 积压到全局 8 MiB 用尽后**同样被拒**（撞 ③），而非按 64 MiB 继续收 | 通过 | FR-4.7 |
| **AC-125** | **队列水位指标（N-55）**：`iocomm_stats_snapshot` 取四次快照，断言：① 空载时四个值均为 0；② 单个端点发送队列积压 3 条小消息 → `send_queue_depth == 3`（取 max，不求和）；③ **同一端点两条成员连接**、队列积压 3 条 → `send_queue_depth` 仍为 **3**（共享队列不被重复计入），`recv_queue_depth` 按各自连接分别计；④ 1 MiB 消息积压至字节上限附近 → `send_queue_bytes` 接近 `queue_budget_bytes`，而 `send_queue_depth` **远小于** `send_queue_max`（证明大消息下条数指标失真、字节指标不失调）；⑤ `ep_owner == 0` 的无主出站连接积压 → 其队列计入（`send_queue_depth` 非 0） | 通过 | FR-5.4 |
| **AC-126** | **条件订阅不补推初值 + 先订阅后取初值（N-61）**：一条 tcp 连接上，① 在已知状态下调 `iocomm_conn_condition_subscribe` → 返回前与返回后**回调均未被调用**（观察窗口：返回后 `run_once` 驱动一轮仍未触发）；② 按推荐顺序——先订阅、再 `conn_status` 取基线——然后在两次之间注入一次状态变化 → 该变化**至少被推送一次**（可能推两次：既在基线里、又作为变化推送；**重复是允许的、幂等的**）；③ **对照组**：按旧建议顺序（先取基线、后订阅）注入同一次变化 → 该变化**丢失**（用此证明「先订阅」不是任意选择）；④ 端点级同口径：`iocomm_endpoint_condition_subscribe` 建立时对现有成员不推初值，之后新成员的变化照常推送 | 通过 | FR-5.2 |
| **AC-102** | `endpoint_destroy` 时存在 `ep_owner == ep` 的出站连接且有未发消息：连接**仍存活**（`conn_status` 可查），未发消息在其连接队列里继续发出、对端收齐；该连接不再计入 `conn_count(ep)` | 通过 | FR-8.10 |
| **AC-101** | `monitor_ttl_ms > 24h` → `monitor_open` 返回 `INVALID_ARGUMENT`；`monitor_ttl_ms = 0` 不自动关闭；到期后 `poll` 返回 `CLOSED`（**v1 行为**，不含载荷捕获） | 通过 | FR-10.4 / C8 / C11 |
| **AC-99** | 协议级错误帧：对端收到超限帧 / 畸形帧时回 `ERROR(reason, detail)` 再关闭。**接收方的观测面**：① 该连接在途 `on_done` 为 `DISCONNECTED`；② `log_fn` 的 ERROR 级别输出含 `reason` 与 `detail`；③ `iocomm_stats.protocol_errors` 递增 | 通过 | FR-5.4 / [线格式 §2.1](api/wire-format.md) / NFR-3 |
| **AC-103** | **服务端扇出（N-01）**：纯服务端（不调 `connect*`）注册端点 A，3 个客户端分别连入并在 accept 回调内 `conn_subscribe`；随后 `endpoint_send(A, …)` 返回 `ICOMM_OK` 且 `out_delivered == 3`，3 个客户端均收到字节一致的消息；`conn_count(A) == 3`。对照组：3 条连接全部 `ep_owner == 0` 的出站连接时，对 A 扇出返回 `NO_RECEIVER` | 通过 | FR-8.6 / FR-8.11 |
| **AC-104** | **端点级订阅（N-02）**：`endpoint_create` 后**不注册** `endpoint_accept`，只调 `iocomm_subscribe(ep, on_msg)`；客户端 `connect` 并发送 3 条消息 → `on_msg` 收到 3 条、`conn_count(ep) == 1`（入站连接被端点隐式持有，未被 FIN）。对照组改用 `endpoint_recv(ep)`（prompt 拉取）得到同样结果 | 通过 | FR-8.11 / FR-6.8 |
| **AC-105** | **重连语义（N-06）**：客户端 `connect` 后对端 `kill -9`，再用**同一** endpoint/地址重启。① **句柄复用**：断开前后及重连成功后 `iocomm_conn_t` 不变（`conn_status` 在重连窗口内仍可调用）；重连窗口内 `connected = FALSE`（不是 `UNKNOWN`——句柄已存在且确知未连通），`lively` / `healthy` 在心跳窗口未满前为 `UNKNOWN`，重连成功且窗口满后均为 `TRUE`；② **在途不重放**：断开前入队的 3 条未发消息在断开时各产生 `DROPPED(PEER_GONE)`、异步 `on_done(DISCONNECTED)` 各一次，重连成功后对端**一条也收不到**；③ **序号重置**：重连后首条消息的 `sequence` 从 1 重新开始（不接续断开前的值）；④ **订阅保持**：断开前已 `conn_subscribe` 的回调在重连后**无需重新订阅**即继续收到消息，`conn_status.peer_node_id` 更新为新对端的 `node_id`、`reconnect_count` 递增。**`connected` 在重连窗口内为 `FALSE`（不是 `UNKNOWN`）**——句柄尚在且确知未连通，与 AC-86「`connected = UNKNOWN` 只出现在建连前」的口径一致 | 通过 | FR-4.4 / FR-5.1 |
| **AC-106** | **端点级套接字参数（N-12）**：① `endpoint_config.tcp_nodelay = 0`（默认）与 `= 1` 时，`getsockopt(TCP_NODELAY)` 为 1、`= 2` 时为 0；非 0/1/2 → `endpoint_create` 返回 `INVALID_ARGUMENT`。② 同一参数在 `endpoint_config` 显式设 `2`、`tune_config.tcp_nodelay = 1` 时，按 §5.0「端点级 > tune」生效为端点值；`tune_config.tcp_nodelay` 只改**未被端点显式设置**的端点。③ `listen_backlog = 0` 时监听 socket 的 backlog 为 128（Linux `ss -lnt` 的 Send-Q 列），显式设 1 时同一时刻只允许 1 个已建立未 accept 的连接（第 2 个在 backlog 满后被拒/排队超时）；`tune_config.listen_backlog` 只对**新建**监听 socket 生效，已监听端点不变。④ 非 tcp / unix 传输（pipe / inproc）上设置这两个字段不报错（被忽略）；unix 上 `listen_backlog` 生效、`tcp_nodelay` 忽略 | 通过 | FR-4.8 |
| **AC-107** | **`connect_node` 地址解析（N-05）**：服务端以 `listen_addr = "0.0.0.0:0"` 监听（系统分配端口），客户端从发现快照取 `node_info.endpoints` 的 `addr` → **不是** `0.0.0.0:0`，而是实际 IP:实际端口；`connect_node(node_id, 端点名)` 成功往返。失败路径：端点名不存在 → `NOT_FOUND`；`node_id` 不在发现表 → `NOT_FOUND`；端点条目的 `transport` 为未实现值 → `NOT_SUPPORTED` | 通过 | FR-8.2 / FR-8.12 |
| **AC-108** | **端点名格式校验（N-17）**：`endpoint_create` 对以下名字各返回 `INVALID_ARGUMENT` 且**不注册**——① 空名（`name_len = 0`）；② `name_len = 256`（超 255 B）；③ 含 NUL 字节（如 `"a\0b"`，`name_len = 3`）；④ 空段：`"/a"`、`"a/"`、`"a//b"`；⑤ 非法 UTF-8（如孤立续字节 `"\x80"`、过长编码）。成功路径：`name_len = 255` 的 UTF-8 名、含 `/` 的合法层级名（`"plant3/line2/temp"`）均返回 `OK`。**区分度**：255 B 成功 vs 256 B 拒绝，边界两侧各一例 | 通过 | FR-1.8 |
| **AC-109** | **手动驱动语义（N-08）**：manual 模式空闲 Runtime 上 ① `run_once(50)` 连续 5 次均返回 `TIMEOUT` 且 `err.code == ICOMM_ERR_TIMEOUT`（**不是** `OK`；此处的「空闲」= **无就绪 IO、无到期定时器、无内部任务、且无 `runtime_wakeup` 待处理**，见 N-50）；② 有事件待处理时 `run_once(50)` 返回 `OK`；③ `run_once(0)` 在有事件时返回 `OK`、无事件时立即返回 `TIMEOUT`（不等待）；④ `run_for(200)` 在空闲 Runtime 上返回 `ICOMM_OK` 且**从不返回 `TIMEOUT`**，实测耗时 ≥ 200 ms；⑤ `run_for(0)` 立即返回 `ICOMM_OK` 且不驱动任何事件（其后事件仍待处理）；⑥ owned 模式下两者均返回 `INVALID_STATE` | 通过 | FR-6.4 |
| **AC-110** | **监听配置组合（N-14）**：① `listen_transport` 与 `listen_addr` 均空 → `endpoint_create` 返回 `OK`，`endpoint_local_addr()` 返回 `INVALID_STATE`，该端点可作 `ep_owner` 扇出；② 只填 `listen_addr`（transport 空）→ `INVALID_ARGUMENT`；③ 只填 `listen_transport`（addr 空）→ `INVALID_ARGUMENT`；④ 未知传输名 `"quic"` + 非法地址 → `NOT_SUPPORTED`（传输名优先于地址格式）；⑤ 执行 ②③④ 之后，**同名端点仍可成功创建**（失败未占用名字）。**区分度**：三种**不同**的结果各自被断言——`OK`（①）、`INVALID_ARGUMENT`（②③）、`NOT_SUPPORTED`（④）；②③ 同码但走的是不同分支（缺少 transport vs 缺少 addr），各自单独断言 | 通过 | FR-8.13 |
| **AC-111** | **`op_id` 唯一性与取消（N-10）**：① 同一 Runtime 上并发发起 10 路 `conn_send_async` / `endpoint_send_async`，得到的 10 个 `op_id` **两两不同**；② 对已完成的 op 调 `send_cancel` → `NOT_FOUND`，且该 op 的 `on_done` **不再**触发（回调计数不变）；③ 对从未分配的 `op_id`（如 `UINT64_MAX`）→ `NOT_FOUND`；④ 对**已取消过**的同一 `op_id` 再次 `send_cancel` → `NOT_FOUND`（幂等失败，不重复 `on_done`）；⑤ 对未完成 op 取消 → `OK` 且 `on_done(CANCELLED)` 恰好一次。**不测跨 Runtime**：判据只是目标 Runtime 自己的操作表，数值碰巧相同就会误取消对方同号操作——这是 `op_id` 不可跨 Runtime 使用的原因，不是需要验收的行为 | 通过 | FR-8.14 / FR-6.6 |
| **AC-112** | **`clock_synced` 恒 0（N-11）**：tcp 上收到任意 `DATA` 帧时 `iocomm_message.clock_synced == 0`；抓包可见发送方携带 `CLOCK_SYNCED = 0`（线格式 §3 规则 6）；**删除**该 tag 后接收方仍按 0 处理且不判损坏；inproc 上同样为 0。**不应有**任何配置项或状态能把该值变为 1 | 通过 | 线格式 §3 / 架构 §6.5 |
| **AC-113** | **交付时句柄表已满（N-19）**：`max_handles = 3`，Runtime 上建 1 个端点 + 1 个 `endpoint_accept` 订阅（共占 2），**conn 名额只剩 1**。① 客户端 A 完成 TCP 连接与双向 HELLO → `accept` 触发一次，回调内 `conn_retain`（conn 名额用满，3/3）；② 客户端 B 完成同样的建连与双向 HELLO → **`accept` 不触发**（回调计数仍为 1）、连接被 FIN（B 侧 `recv` 返回 0 / 断开）、`log_fn` 出现一条含端点名的 ERROR；`stats.protocol_errors` 与 `queue_dropped` **均不递增**。③ 对照组：`conn_destroy(A 的连接)` 释放 conn 名额后，客户端 C 建连 → `accept` 正常触发（计数变 2）。**句柄名额口径**：`max_handles` 是**五类对象句柄合计**（endpoint / conn / subscription / snapshot / monitor；**Runtime 不占**）——端点、订阅、conn 各占 1，因此 `max_handles = 1` 连订阅都建不起来，本用例必须取 3 | 通过 | FR-1.7 / FR-8.5 |
| **AC-114** | **无消费者端点的入站连接（N-24）**：端点 A 只 `create`，**不注册** `endpoint_accept`、也不启用 `iocomm_subscribe(ep)` / `endpoint_recv(ep)`。对端 `connect` 成功后：① 对端观测到**优雅关闭**——tcp / unix / pipe 上为优雅 FIN（`recv` 返回 0）而非 RST；**inproc 上为断开通知驱动的 `connected = FALSE`**（无 FIN / RST，见 c-abi §5.1b）；② `conn_count(A) == 0`；③ `log_fn` 出现一条含端点名的 WARN；④ `stats.protocol_errors` 与 `queue_dropped` 均不递增。对照组：同一端点在 `connect` 前调 `iocomm_subscribe(ep)` → 连接存活、消息正常投递、`conn_count(A) == 1` | 通过 | FR-8.8 |
| **AC-115** | **共用 `state_dir`（N-25）**：进程 P1 以 `node_id = 0` + 可写 `state_dir = D` 创建 Runtime → `OK`；同机进程 P2 用**同一** `D`、`node_id = 0` 创建 → **`CONFLICT`**，`message` 含 `D`；P2 改用显式 `node_id` 或另一个 `state_dir` → `OK`。对照组：P1 退出（`destroy`）后 P2 用同一 `D` 重新创建 → `OK`（存活探测随进程结束而失效） | 通过 | FR-9.2 |
| **AC-116** | **Stopped 后不可重启（N-22）+ 写操作返回码（N-21）+ 只读可用（N-57）**：`stop` 后：① 对同一 Runtime 调 `runtime_start` → `ICOMM_ERR_CLOSED`；② `endpoint_create` / `iocomm_subscribe` / `conn_send` 各返回 `ICOMM_ERR_CLOSED`（**不是** `INVALID_STATE`）；③ `stop` 重复调用返回 `ICOMM_OK`（幂等）、`drain` 合法；④ `run_once` / `run_for` 仍可调用（**用于排空在途**——`stop` 不取消在途操作，只停止接受新写）；⑤ `destroy` 后重建 Runtime 一切正常；⑥ **只读查询全部返回 `OK`**（2026-11-18 补，N-57）：`stats_snapshot` / `conn_status` / `endpoint_get` / `endpoint_count` / `diagnostic_dump` / **`runtime_node_id`** / **`runtime_node_name`** / `discovery_snapshot_take/count/get/release` 各调一次，均不得返回 `CLOSED`（**调用前提**——本项场景本身就是 `stop` 之后，此时句柄必然有效；要排除的只是「尚未 `create`、没有 Runtime 句柄」这一不可达情形。按 C ABI §4，`runtime_node_id` 自动模式下**`create` 后即有值**，本项不额外要求先 `start`；建 Runtime 之前的版本查询用 `iocomm_abi_version()`。2026-11-19，gap-68） | 通过 | FR-6.5 / FR-8.1 |
| **AC-117** | **`endpoint_accept` 与端点级收消息正交（N-37 / N-51）**：同一 `ep` 上**先** `endpoint_recv(ep)` 再 `endpoint_accept(ep, fn)` → 后者返回 `ICOMM_OK`（**不是** `INVALID_STATE`）；随后客户端 `connect` → `fn` **仍被触发一次**、同时 `endpoint_recv(ep)` 能拉到该连接的消息。反向顺序（先 accept 后 recv）结果相同；同一端点注册**两个** accept 回调 → 两个都按注册顺序各触发一次。**注册与连接并发**：在 `connect` 进行中的同时注册第二个 accept 回调，**不要求**该在途连接被补发交付（§6.4 未规定补发），但要求**不得崩溃、不得重复交付** | 通过 | FR-6.8 / FR-8.11 |
| **AC-118** | **端点级持有后 `conn_retain` 不改路由（N-38）**：端点已启用 `iocomm_subscribe(ep)` 时，在 accept 回调内对 inbound 调 `conn_retain` → 返回 `ICOMM_OK`；此后对同一 `conn_recv(conn)` → 返回 `ICOMM_ERR_INVALID_STATE`，而对端发来的消息仍由 `on_msg` 收到（**不双投**）。对照组：端点**未**启用端点级收消息时，同一流程下 `conn_recv` 能正常收到 | 通过 | FR-8.11 |
| **AC-119** | **`conn_retain` 的线程与订阅顺序（N-36 / N-41）**：① 在 `endpoint_accept` 回调内调 `conn_retain` → 返回 `ICOMM_OK`（**不是** `WOULD_DEADLOCK`）；② 该连接在回调外（另一线程）调 `conn_retain` → 同样 `ICOMM_OK`；**两个线程并发**对同一连接各调一次 `conn_retain` → 均返回 `ICOMM_OK`、连接仍存活（`conn_status` 可调）；③ `conn_retain` 之后在回调外调 `conn_subscribe` → `ICOMM_OK`，此后消息走订阅回调；④ 该连接上再调 `conn_recv` → `INVALID_STATE`（订阅与 recv 二选一照常适用） | 通过 | FR-6.7 / FR-8.5 / FR-8.7 / FR-8.8 |
| **AC-120** | **`runtime_wakeup` 使 `run_once` 返回 `OK`（N-50）**：manual 模式空闲 Runtime 上，主线程阻塞在 `run_once(rt, 5000)`，另一线程 100 ms 后调 `iocomm_runtime_wakeup(rt)` → `run_once` 在 **1 s 内**返回且返回码为 `ICOMM_OK`（**不是** `TIMEOUT`）；无唤醒时同样调用 `run_once(50)` 仍返回 `TIMEOUT` | 通过 | FR-6.4 / FR-6.5 |
| **AC-121** | **端点级条件订阅（N-45）**：端点 `ep` 上先 `iocomm_subscribe(ep, on_msg)`（**必要前置**——只注册条件订阅不构成持有，按 FR-8.8 连接会在交付时点即 FIN，见 AC-114）再 `iocomm_endpoint_condition_subscribe(ep, fn)`；接入 2 条入站连接 → 对第 1 条注入一次 `ERROR` 帧 → `fn` **至少收到一次**且 `conn` **等于该连接句柄**、`ep == ep`（两者均非 0）；对第 2 条调 `conn_destroy` → `fn` **在该连接关闭后不再投递**；`unsubscribe(该订阅)` 一次即覆盖全部成员连接。**变体**：订阅建立时**已存在**的 `ep_owner == ep` 出站连接**同样**进入订阅范围（成员按 **FR-5.2 的「计数成员」** 定义；inproc 排空窗口内的连接仍受覆盖，但不参与扇出）。**不断言**「订阅建立瞬间是否先推一次当前值」——该口径与**连接级** `iocomm_conn_condition_subscribe` **共用同一条规则**（见 C ABI §8 注释），AC 只断言**变化**被推送 | 通过 | FR-5.2 |
| **AC-122** | **跨线程连接枚举（D-2）**：**owned** 模式下建立 1 个监听端点并接入 2 条入站连接 + 1 条 `ep_owner == 0` 的出站连接（共 3 条）。① **应用线程**（非 loop 线程）调 `iocomm_diagnostic_dump` → 返回 `ICOMM_OK`，`"version" == 2`，`"connections"` 含 **3** 条，每条含 `conn` / `ep` / `peer_node_id` / `connected` / `lively` / `healthy` / `config_current` / `last_rx_ns` / `last_heartbeat_ns` / `last_rx_age_ms` / `last_heartbeat_age_ms` / `reconnect_count` / `send_queue_depth` / `recv_queue_depth` / `send_queue_bytes` / `recv_queue_bytes`（`last_*_age_ms` 在对应 `last_*_ns == 0` 时省略）；② 出站那条的 `ep == 0` 且 `send_queue_depth` **可读**（非缺失键）——对应关闭 N-47 登记的盲区；③ 取其中 `conn` 值**从同一应用线程**调 `iocomm_conn_status` → `ICOMM_OK`；④ **对照组**（manual 模式）：同一场景下应用主线程即 loop 线程，`iocomm_conn_count` / `iocomm_conn_get` 返回与 dump 一致的 **3** 条——证明「仅 loop 线程」是可用的合法路径，缺的只是 owned 模式下的跨线程入口 | 通过 | FR-5.5 |
| **AC-123** | **休眠恢复后的心跳超时（时钟口径；本条为 tcp 连接——inproc 没有心跳，见 AC-124）**：用可注入的 `Clock` 模拟「一次前进 N 分钟」（对应系统休眠，架构 §6.5 的计挂起单调钟）。① 建立连接并等心跳窗口正常后，把假时钟**一次前跳**超过 `heartbeat_ms × heartbeat_miss_limit` → `lively` 由 `TRUE` 变 `FALSE`、连接被判定超时并按 FR-4.4 处理（对端恢复后自动重连）；② 对照组：同样前跳量但**分成若干小步**（每步 < 判定窗口）推进 → 不得误判超时；③ **`Clock` 的生产实现不得是 `Instant::now()` 的薄包装**——静态检查：生产实现须在 Linux 绑 `CLOCK_BOOTTIME`、Windows 绑 `QueryPerformanceCounter`（两条都是「计挂起」，见架构 §6.5；Linux `CLOCK_MONOTONIC` 与 `Instant` 均**不计**挂起，用它们本用例①在 Linux 上会失败） | 通过 | FR-5.3 / [架构 §6.5](architecture.md) |
| **AC-124** | **inproc 无心跳、无重连（D-5 / N-58）**：同一进程内两个 Runtime 以 `inproc` 建连。① 驱动假时钟前跳**远超** `heartbeat_ms × heartbeat_miss_limit` → `lively` / `healthy` **仍为 `TRUE`**（既不变 `FALSE` 也不变 `UNKNOWN`）、连接不被判定超时、`reconnect_count == 0`；`peer_status.last_heartbeat_ns == 0`、`stats.rtt_p50_ns / rtt_p99_ns / rtt_max_ns == 0`（**本 Runtime 只有 inproc 连接**时）、`stats.heartbeat_timeouts == 0`。② **卡死信号与 tcp 同构（落在发送方发送队列）**：**接收方不驱动 loop**（manual 模式不再 `run_once`）→ 接收方的**接收队列**被填满 → 发送方写入返回 `WouldBlock` → 消息堆积在**发送方发送队列** → 发送方按端点策略处理，**发送方** Runtime 的 `stats.queue_dropped` 递增，**发送方**所挂监控者产生 `DROPPED`。**逐策略**：`DROP_OLDEST` / `DROP_NEWEST` → `DROPPED(QUEUE_FULL)`、**发送调用不报错**；`ERROR` → 单条 `conn_send_async` 的 `on_done(WOULD_BLOCK)` + `DROPPED(BACKPRESSURE)`，扇出时若有连接成功则报 `OK`（c-abi §6.1「扇出的部分失败」）；`BLOCK` 在**同步**发送上阻塞至超时返回 `TIMEOUT`、**异步**发送退化为 `ERROR`。**丢弃发生在发送方 loop 线程**，监控环生产端约束成立。**对照组**：同一场景在 `tcp` 上也是**发送方**发送队列堆积（对端不读 → 内核写缓冲满），计数位置相同。③ **断开由直接通知驱动**：销毁对端 Runtime → 本端**继续驱动 loop**（无需推进时钟、无需等任何超时）→ 收到 `connected = FALSE` 推送与断开事件（**接收队列本已为空**，故不进入排空窗口、事件直接推送）；`reconnect_count` **仍为 0**（不进入 `Reconnecting`）；**随后在 loop 线程**对旧句柄调 `conn_status` 返回 `STALE_HANDLE`、`conn_count == 0`（`conn_count` 仅 loop 线程可调，见架构 §3.3）；重建对端 Runtime 并在同一 `listen_addr` 重新 `endpoint_create` 后，本端重新 `connect` 得到**新句柄**、可正常收发。④ **排空先于断开（定序）**：**条件**——本端以 `conn_subscribe` 或 `conn_recv` 持有该连接、接收队列中已有 **N（N ≥ 2）** 条待取消息；**动作**——对端以 `CLOSE_AFTER` 关闭。**断言（二选一，按本端持有的接收方式）**：订阅模式下「第 N 条消息的回调**早于**断开事件」；拉取模式下「`conn_recv` 在返回连接终止前能连续取到全部 N 条」。**「已取出未完成交付」的项同样算残留**（见 FR-5.2 / c-abi §5.1b），故事件不会越过任何一条已出队消息。**窗口内 `conn_status` 的 `connected` 已为 `FALSE`**（条件值先变、事件后到）；窗口内句柄仍有效、`conn_count(ep)` 仍计入。**本端主动 `conn_destroy` 不适用本项**（立即丢弃剩余消息） | 通过 | FR-3.11 / FR-3.12 / FR-5.1 |

> **新增验收项的里程碑归属（2026-11-05）**：**AC-117 / AC-118 / AC-119** 归 **M2**（需要真实的入站连接与 accept 交付）；
> **AC-120** 归 **M1**（manual 驱动在 M1 已可用）；**AC-121** 归 **M3**（条件集与心跳判定属 M3）。
> **AC-122**（2026-11-09，D-2）归 **M2**（需 owned 模式 + 真实连接；`conn_status` 与 dump 的字段在 M2 已具备）。
> **AC-123**（2026-11-10，时钟口径）归 **M3**——它断言 `lively` 由 `TRUE` 变 `FALSE` 并按 FR-4.4 重连，而心跳与条件集整体属 M3（见架构里程碑表），M1 的 inproc 闭环里没有心跳。**`Clock` 的生产绑定仍须在 M1 就定**（后续所有超时都依赖它），AC-123 只是验收推迟到 M3。
> **AC-33c**（2026-11-13）归 **M2**——覆盖 AC-33 / AC-114 的 **tcp** FIN 分支；**AC-33d** 归 **M5**——同一断言的 **unix / pipe** 分支。二者不重叠：按传输划分，判据相同（对端 `recv` 返回 0、非 RST）。inproc 分支由 AC-33 / AC-114 本体在 M1 验收。
> **AC-125**（2026-11-18，N-55）归 **M3**——它读 `iocomm_stats_snapshot` 的队列水位，而 **`stats` 快照整体属 M3**（M1 只有 inproc 传输、句柄表、队列与回调，没有 `stats` 快照；见本段末行对 AC-121 / AC-123 的同类说明）。
> **AC-126**（2026-11-18，N-61）归 **M3**——条件订阅在 M3 才有条件集可推；**AC-7** 的 seed 端到端部分归 **M4**（真实 UDP + 两个 Runtime 的单播 socket；其「换端口后重扫」对照可用假时钟或调小 `lease_ms`）。
> **AC-124**（2026-11-11，D-5 / N-58）归 **M3**——它的**四个子项**全部读条件集（`lively` / `healthy`）与 `stats`（RTT 分位 / `heartbeat_timeouts` / `queue_dropped`），或读接收队列的排空顺序（④）。
> 而这两块都属 M3；M1 只有 inproc 传输、句柄表、队列与回调，**没有条件集、也没有 `stats` 快照**，挂在该里程碑上不可执行。
> **注意它验证的恰好是 M3 的「没有」**：M3 实现心跳与自动重连时，**不覆盖 inproc**——AC-124 是那条排除规则的验收（对照 AC-123 验证 tcp 上确实有）。
>
> **既有 AC 的同步改动（2026-11-05，共 9 条）**：AC-5 / AC-6（补 `conn_retain` 等非阻塞调用的例外）、
> **AC-29 / AC-40**（补「端点级收消息未启用」限定；AC-40 另加对照组）、**AC-33 / AC-33b**（补多次注册的持有与销毁边界）、
> AC-94（`send_queue_depth` 改端点级）、AC-104（删 accept/recv 互斥的末位断言）、AC-109（「空闲」排除有 `wakeup` 待处理）。

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
| **AC-E3** | 1000 轮连接/断开后，fd / 句柄 / 内存增量有界（阈值口径见下方补充口径）。**补充口径（2026-11-19，gap-67）**：三者均**不在 C ABI 内**——本库不向调用方暴露 fd（C ABI 原文），内存与 fd 只能从**进程外**量（Linux 读 `/proc/self/fd` 计数与 RSS；Windows 用 `GetProcessMemoryInfo` / 句柄计数）。「句柄」指**五类对象句柄合计**，可由 AC-113 的自查路径（`conn_count(rt, 0)` + `max_handles` 差额）间接约束。阈值须在**首次 soak（AC-E5）执行前**写死（可先取保守值），**不得留空签发**；首跑后按实测复核修订——只有在实测证明原阈值不可达或过松时才改，改后记入变更记录 | 通过 |
| AC-E4 | 产物 `readelf --version-info` 无高于目标 glibc 的符号 | 通过 |
| **AC-E5** | 24 小时 soak：内存与 fd 曲线斜率 ≈ 0，无未回收连接。**「≈ 0」的判定（2026-11-19，gap-67）**：曲线取**后 12 小时**的最小二乘斜率，**不得以整段斜率代替**（启动期的缓存 / 句柄预热会使整段斜率为正）。**通过判据**：内存斜率对应的 24 h 累计增量 ≤ 进程**稳态占用**（后 12 h 自身均值）× **1%**——**用同一段数据自标定，不再需要另一次 soak 的基线**；fd 计数在末 1 小时**无单调上升**（允许常数级波动）。**上述两条判据的容差须在首次 soak 执行前写死**，与 AC-E3 的阈值同批 | 通过 |
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
| 2026-11-04 | **N-08 / N-09 / N-10 / N-11 / N-13 / N-14 处置**：① **N-08**：`run_once` 语义定死——**本轮空闲返回 `TIMEOUT`**（正常事件，非故障，置 `err`），`timeout_ms = 0` 只轮询一次；`run_for` = 循环 `run_once` 至累计驱动满 `duration_ms`，`0` 为空操作，**从不返回 `TIMEOUT`**；FR-6.4 扩写、C ABI §4 补注释、错误码矩阵 `run_once` 增 `TIMEOUT`、新增 **AC-109**。② **N-09**：三个无 `err` 的函数（`runtime_wakeup` / `endpoint_count` / `discovery_snapshot_release`）**统一为「无错误通道」**——矩阵行改标注、AC-95 豁免清单由 6 个扩为 **9 个**、各自写明失败如何体现（返回值 / 0 的歧义）。③ **N-10**：`op_id` **每 Runtime 单调分配、永不回绕**（耗尽 `RESOURCE_EXHAUSTED`），`send_cancel` 对已完成 / 已取消过 / 从未在本 Runtime 分配的 op 一律 `NOT_FOUND`（**判据只查目标 Runtime 自己的操作表**，`op_id` 不可跨 Runtime 使用）；新增 **FR-8.14** + **AC-111**。④ **N-11**：`clock_synced` 与线格式 `CLOCK_SYNCED` tag **保留但 v1 恒 0**（不删——`iocomm_message` 为库写出的公开结构体，删字段要动 ABI 布局），架构 §6.5 写明理由；新增 **AC-112**。⑤ **N-13**：本机注册表定为**每 Runtime 一个单元文件 + 原子 rename**，按 `lease_ms` 判陈旧；`discovery_start` **不是**创建端点的前置条件（启动时扫描补齐）；FR-2.6 / AC-38 补口径，架构新增 **§6.4b**。⑥ **N-14**：新增 **FR-8.13** + C ABI **§5.1c** 四格组合表（两者皆空 = 纯出站端点、只填 addr / 只填 transport → `INVALID_ARGUMENT`、未知传输名 → `NOT_SUPPORTED`）+ **AC-110** |
| 2026-11-04 | **N-18 / N-19 处置（复审新发现，随 N-08–N-14 同批落文档）**：① **N-18**：握手期内部会话「每端点 ≤ `max_handles`」保留为**局部**保护——删去「防止 fd 耗尽」的错标，明写聚合上界 = `端点数 × max_handles` 是**软上界**，全局 fd 由部署侧 `ulimit -n` 兜底；被拒 socket 只写 `log_fn` WARN，不新增计数。② **N-19**：交付时句柄表已满 → **不交付、不触发 `accept`、立即 FIN**、写 `log_fn` ERROR，不计 `protocol_errors` / `queue_dropped`；FR-8.5 补一句；新增 **AC-113**（归 M2）。两项均不占用 §8 原 15 条的计数 |
| 2026-11-04 | **N-17 处置（端点名格式与长度上限）**：新增 **FR-1.8** + **AC-108**（归 M1）——端点名 UTF-8 编码后 **1–255 B**、不得含 NUL、合法 UTF-8、`/` 层级无空段，违反 → `INVALID_ARGUMENT`。补 [C ABI §5.1a](api/c-abi.md)（含与 `iocomm_endpoint_info.name_len`（`u16`）及 1400 B 发现分页的关系）。 |
| 2026-11-05 | **N-20 ～ N-35 收口**（M0 冻结前残留核对，详见 [open-questions §8.8](open-questions.md)）：句柄口径统一为「五类对象句柄，Runtime 不占」；Stopped 为终态、写操作统一返回 `CLOSED`，`runtime_stop` **不取消在途操作**（N-29，与 §5.2 取消表一致）；`TOO_LARGE` 一律同步返回（修正 AC-73/AC-82/AC-92⑤）；`too_large` 丢弃原因仅限接收侧；无消费者端点的入站连接交付即关闭；共用 `state_dir` 检出即 `CONFLICT`；`max_message_size` 下限改为 56 B；AC-86 的「注入 `ERROR` 后 `healthy = FALSE`」改测 `iocomm_condition_fn` 推送（N-34）；Windows 名字锁 `Global\` 失败回退 `Local\` 并写 WARN（N-30，落架构 §6.4 与 `platform-support.md`）。新增 **AC-114 / AC-115 / AC-116**；补 FR-8.8 / FR-9.2 / FR-6.5 口径。N-35（许可证）仅登记、待负责人决策，未改文档（**2026-11-17 已补决**：定为 **MIT OR Apache-2.0 双许可**，新增 `LICENSE-MIT` / `LICENSE-APACHE` 与 `README.md` §许可证；`Cargo.toml` 的 `license` 字段待建仓时写入） |
| 2026-11-05 | **N-36 ～ N-52 用户清单核实与收口**（详见 [open-questions §9](open-questions.md)）：① `conn_retain` 去掉 `WOULD_DEADLOCK`/`TIMEOUT`（N-36）、`endpoint_accept` 与端点级收消息定为正交两轴（N-37）、端点级持有后 `conn_retain` 不改路由且 `conn_recv` 返回 `INVALID_STATE`（N-38）、线程表补注册类入口（N-39）、AC-94 队列深度改端点级（N-40）、`conn_retain` 后订阅合法（N-41）、destroy 矩阵补 `WOULD_DEADLOCK`（N-49）、`run_once` 唤醒返回 `OK`（N-50）、AC-104 删互斥断言（N-51）、`monitor_poll` 去 `TIMEOUT`（N-52）；② 新增非目标三条——跨进程集中监控（N-42）、post 类投递（N-43）、多通信域（N-44）；③ 端点级条件订阅补完整语义（N-45）；④ **新增 AC-117 ～ AC-121**，改动 AC-5/6/29/33/33b/40/94/104/109 |
| 2026-11-09 | **N-46 / N-47 裁决（D-2 / D-3）——零 ABI 增量**：方向定位为「面向普通应用」⇒ owned 是默认主路径 ⇒ `conn_count` / `conn_get` 在应用线程上不可用（UB）。三路独立调研（C/C++ 事件循环 / 工业中间件 / C ABI 惯例）一致表明业界对「off-loop 看连接状态」的答案是**事件流 + 值快照**而非同步枚举 API，故**不新增 `conn_snapshot_*` 句柄 API**，改为补全已有的 `iocomm_diagnostic_dump`。① **N-46**：`connections[]` 条目补 `ep` / `lively` / `healthy` / `config_current` / `last_rx_ns` / `last_heartbeat_ns` / `reconnect_count` / `send_queue_depth` / `recv_queue_depth`，`version` 1→2；把跨线程枚举语义**并进 FR-5.5**（不新增编号）与 **AC-122**（归 M2）；`architecture.md` §3.3 明写 owned 模式跨线程调用 `conn_count` / `conn_get` 为 UB 并指向 dump；§4 非目标补「专用连接快照句柄 API」与「应用线程同步投递进 loop 并阻塞等待」两行。② **N-47**：`iocomm_peer_status` **不追加**计数（它同时是 `iocomm_condition_fn` 的回调载荷）；原登记的无主出站连接发送水位盲区**改由 dump 关闭**（`ep == 0` + 自身 `send_queue_depth`）。③ 顺带**关闭 N-56**：§4 非目标补「per-connection 的指标维度」一行，修复 FR-5.4 的断链。**不改任何 C 结构体、不新增导出函数、不改线格式**。④ **顺带定死 `peer_status` 时间戳的时钟口径**（复核发现此前 `last_rx_ns` / `last_heartbeat_ns` 在声明处**无任何时钟说明**，而本次新写的 dump 注释擅自把「墙钟」写了进去，并与架构 §6.5「心跳/RTT/退避走单调钟」冲突）：改为**单调时钟、原点 = Runtime 创建时刻**，补注释；dump 额外给 `last_rx_age_ms` / `last_heartbeat_age_ms`（库算好的毫秒差值，对应 `last_*_ns == 0` 时省略该键），供人读与诊断。`peer_status` **不加字段**——它是 `iocomm_condition_fn` 的回调载荷，与 N-47 的裁决口径一致 |
| 2026-11-10 | **时钟口径定死（顺带修正 2026-11-09 的越权笔误）**：① 2026-11-09 我给 `peer_status.last_*_ns` 写的是「单调钟、原点 = **Runtime 创建时刻**」，经调研推翻——归一化后调用方**拿不到那个零点**，字段只剩「谁更早」一种用法，而 `last_*_age_ms` 已直接给出该信息，字段变冗余。改为 **系统单调钟原值**（原点 = 系统 boot，不归一化），故**同机跨进程可比**、不跨机跨重启。② **更关键**：`architecture.md` §6.5 原写「单调时钟（`steady_clock` 语义）」**不够**——它没排除「不计挂起」的实现，而这恰是默认行为，且**两平台默认相反**：Linux `CLOCK_MONOTONIC` **不计**挂起（man page 原文），Windows `QueryPerformanceCounter` **计**挂起（2026-11-10 本机实测：QPC 与 `QueryUnbiasedInterruptTime` 相差 4940 秒，与事件日志累计睡眠 83.6 分钟吻合）。**休眠 1 小时后恢复**：计挂起的时钟判出心跳超时→断开重连；不计挂起的误判连接仍活着→**半开连接检测失效**。故定：Linux 用 **`CLOCK_BOOTTIME`**、Windows 用 **QPC**，两者都计挂起。**`Clock` trait 的生产实现不得是 `Instant::now()` 的薄包装**（`std` 文档明言挂起是否计入未规定、随平台与版本变化）。③ 新增 **AC-123**（休眠恢复后心跳超时，**归 M3**——2026-11-11 更正：本行原写「归 M1」，与 AC-123 下方注及架构里程碑表冲突，按后者为准）与架构 §6.5a「单调时间戳的原点」；`mon_record.ts_mono_ns` 补明与 `peer_status` **同一零点**；T2 测试要求补「假时钟须能模拟时间跳跃」；架构 §5 计时器段补实现约束 |
| 2026-11-10 | **N-48 中期裁决（D-4）——发现端口块迁至 `23100..23200`，不加字段**：`47377..47477` 整段落在 Linux 默认 `ip_local_port_range`（`32768–60999`）内，与出站连接的自动源端口分配互相抢——启动顺序不利时 `discovery_start` 的 `bind()` 被内核先一步分给别的进程而出 `RESOURCE_EXHAUSTED`，反方向则挤压同机其它应用的出站端口池。① **改默认块**：组播 `23100` + 单播 `23101..23200`，脱离 Linux 与 Windows（本机 `49152 + 16384`）两个默认动态段；按 IANA 官方 CSV 逐端口核对全段未注册，两端余量充足（紧邻块下方的最近注册端口 `23053` / 上边界 `23272`）。**组播组 `239.255.73.77` 不动**——组播组无内核自动分配问题，与端口编号互相独立。② **否掉加 `listen_port` 字段**：端口撞车是**宿主机级**事实（同机所有进程共享内核端口池），字段改不了内核是否先把该口分给出站连接；且**端口同时就是发现域**（两机配不同端口 → 静默互不可见，唯一症状是 `discovery_snapshot` 空表），等于引入半个 `domain_id`，与 2026-11-05 N-44 的「v1 单发现域、`domain_id` 留到 v2 与 TLS 同批」冲突。③ **否掉维持原端口 + 只靠 sysctl**：要求每台 Linux 机改内核参数，与「面向普通应用」定位冲突。④ 落点：[线格式 §8.1](api/wire-format.md) 寻址表拆为三行并新增「端口块的选择」段（四项核对 + 两条「不做」）；`platform-support.md` §3.3 风险行改为「默认不冲突 + `ip_local_port_range` 被调宽时的核对与 `ip_local_reserved_ports` 保留方法」；`architecture.md` §6.3 首段；`c-abi.md` §7 `discovery_config` 上方注与 §9.8 非目标表；本文 §4 非目标表新增「发现端口可配置」行、§4.1 域隔离注补「不要依赖同机配不同端口」。**不动任何 C 结构体、不新增导出函数、不改线格式**。⑤ **遗留（新登记 N-60，B2）**：`wire-format.md` §8.1 的 seed 端口语义仍为空——seed 格式为 `"<host>:<port>"`，但单播端口由运行时从 `23101..23200` 取首个可用，对端无法预知，故「关组播 + 配 seed」这条 P0 路径（FR-2.4 / AC-7）的寻址规则未定义。**与端口迁移无关**（换不换端口都存在），登记于 [open-questions §10.4](open-questions.md)（**2026-11-18 已收口，N-60**：seed 格式定为 `"<host>:0"` + 逐端口扫描，见 FR-2.4 / AC-7） |
| 2026-11-11 | **N-58 裁决（D-5）——inproc 不跑心跳、不自动重连，零 ABI 增量**：① **判据**：心跳只解决两类问题——「半开」（连接已断但无人告知）与「对端卡死」（连接在、对端不跑）。inproc **免掉前者**（同地址空间内断开是直接可观测事实）、**免不掉后者**。故本条**不是**「因为近所以不需要」，而是「**卡死信号由别处承载**」。② **卡死信号与 tcp 同构（落在发送方发送队列）**：对端 loop 停止消费 → 接收队列满 → 写入 `WouldBlock` → 消息堆积在**发送方发送队列** → 按端点策略丢弃并计入**发送方** `queue_dropped`（FR-4.6）。与 tcp「对端不读 → 内核写缓冲满 → 发送队列堆积」是同一条链路——inproc 与 tcp 共用同一段「写不动回 `WouldBlock`」的代码。**盲区与 tcp 相同**：缓冲未满前无信号；per-connection 卡死定时器 v1 **不做**，写入 §4 非目标。③ **断开改由直接通知驱动**：对端 Runtime **销毁** / 对端或本端对连接销毁/关闭 → 两端连接对象**终结**（**本端销毁立即**；**对端先断**则先入排空窗口、接收队列取空后才终结并失效，见「定序」项）；**对端先断** → 本端经 loop 任务收到 `connected = FALSE` 推送与断开事件，**本端先销毁** → 不再对自己推一次事件、仅通知对端；两端同时销毁各自回收（`runtime_stop` 不算断开，只停新的写操作，发送队列在继续驱动 loop 时照常中继）；**不进入 `Reconnecting`**，应用重建路径是重新 `connect*` 拿**新句柄**。**不重连的理由**：对端 Runtime 一销毁，同一 `listen_addr` 上已无监听者，自动重拨只会对空转（nng 的 dialer 级重连在 inproc 上没有意义）。**否掉「inproc 也跑心跳」**：需把定时器与 `HEARTBEAT` 帧从 M3 提前进 M1，且为「可直接观测的事」付一份推测性检测的成本；**否掉「inproc 上两条件恒 `UNKNOWN`」**：那会让「不适用」与「窗口未满」共用同一个值，监控侧无法区分，且 AC-86 需分叉。④ **落点**：新增 **FR-3.11**（不跑心跳 + 发送侧卡死信号 + 盲区声明）与 **FR-3.12**（直接通知断开 + 句柄失效 + 不重连及其理由）；FR-5.1 补 `lively` / `healthy` 的 transport 作用域；FR-4.4 补「仅 tcp / unix / pipe」；**新增 AC-124**（归 M3）；AC-86 / AC-123 标注为 tcp 连接；架构 §5.2b 条件表、§5.2c 首段、§6.2 心跳别名辨析与 inproc 声明、M3 里程碑行（追加 AC-124 —— 它验证的是 M3 的排除规则）；[线格式 §7](api/wire-format.md) 心跳段；`c-abi.md` §5.1b（第③条含卡死信号方向与断开后句柄语义）、`peer_status` / `stats`（含 `heartbeat_timeouts` / `reconnects`）/ `diagnostic_dump` 注释、端点级 keepalive 非目标注。⑤ **顺带修正**：本文 2026-11-10 行旧文写「AC-123 归 M1」，与 AC-123 下方注（归 M3，M1 的 inproc 闭环里没有心跳）矛盾——按后者为准，旧行已改 |
| 2026-11-13 | **N-58 收尾（第 13 轮复审后）**：① **N1** 意图码引用中误指的『6.2b 节』全数改为'§5.2 取消表'（误指处共 5 点，6.2b 实为超时口径）；② **N2** inproc 接收队列上限补明「per-connection 无独立配置项，固定取 Runtime 默认」；③ **N3** 「可交付残留」定义补「已取出但尚未完成交付的项仍计入」（c-abi 2 处、需求 3 处、架构复述 1 处）；④ **N4** `BLOCK` 在 inproc 上与 tcp 一致（同步真阻塞至 `TIMEOUT`、异步退化 `ERROR`）；⑤ **N5** AC-33 / AC-114 改双传输观测口径，FR-8.8 与 c-abi 自动收回 / 无消费者条文同步；**新增 AC-33c**（tcp-FIN 观测，归 M2）与 **AC-33d**（unix/pipe 观测，归 M5）。**推翻**上一轮 M1 注记中「tcp 版随 AC-33b 验收」的归属——AC-33b 触发路径不同 |
| 2026-11-18 | **P1 三项收口 + N-62 队列预算重构**（详见 [open-questions §10.4 / §10.5](open-questions.md)）。① **N-60 seed bootstrap**：`wire-format.md §8.1` 新增 7 条 bootstrap 规则——seed 格式 `"<host>:0"`（port 必须为 0）、`discovery_start` 后向 `host:23101..23200` 逐端口发 `CAP_Q`（通配 `node_id = 0`）、`CAP_A` **必须从单播 socket 发出**、记录实际源端口后回落稳态、全过期后按租约周期重扫、严格单向、忽略 ICMP 端口不可达噪声。**否决**「seed 只填 host」（改字符串契约）、「用组播口收单播」（同机多 Runtime 被吞 + 防火墙风险）、「固定端口 + `SO_REUSEPORT`」（Windows 无此选项）、「新增 `SEED_QUERY` 报文」（动线格式）。AC-7 改写为 4 步可执行地址构造 + 2 组对照。② **N-55 stats 队列水位**：`send_queue_depth` / `recv_queue_depth` 定义为「**取 max，不求和**」（本库发送队列由成员连接共享，求和会把同一队列重复计入），新增 `send_queue_bytes` / `recv_queue_bytes`（payload 字节，与 depth 一一对应），补 `open_endpoints` / `discovered_peers` 注释；`diagnostic_dump` 的 `endpoints[]` 追加 `send_queue_bytes` / `send_queue_max` / `queue_budget_bytes` 以提供分母。**关键**：条数指标在「平均消息 > 64 KiB」时会把「已满」读成「6%」，故必须同时给字节；**新增 AC-125**（归 M3）。③ **N-61 条件订阅初值**：定「**订阅不补推初值、只推变化**」，且**修正此前注释教反的顺序**——正确姿势是「**先订阅、后取初值**、允许重复投递（条件集全量、幂等）」，因为「先取初值后订阅」会永久漏掉窗口内的变化而本结构体无序号可去重；**新增 AC-126**（归 M3）。**原「在连接级该口径写死之前」一句删除**。④ **N-62 队列字节预算与消息上限解耦**：旧公式 `min(queue_max × max_message_size, 64 MiB)` **废止**（它让调大单条上限意外放大队列内存，且反向把单条上限锁死在 64 MiB；行业无对等物——RabbitMQ/Artemis 的每队列字节上限均默认不设且可配，Kafka/RabbitMQ/OPC UA 的单条与预算都是两个独立旋钮）。新口径：`runtime_config` / `tune_config` 尾部追加 `queue_budget_bytes`（默认 64 MiB，**每队列**）/ `queue_total_bytes`（默认 256 MiB，**全部队列**，含在途入站帧缓冲）；`max_message_size` 硬顶 **64 MiB → 1 GiB**（1 GiB 而非 `uint32_t` 满值：`20 + tlv_len + payload_len` 求和逼近 4 GiB 会越过 `uint32_t`，且 1 GiB 单条在千兆网上已需 8 秒）；**空队列无条件接受一条消息**（Kafka 口径：大消息优先于预算，否则 `max_message_size > queue_budget_bytes` 时大消息永远进不了队列），故每队列实际内存上界 = `queue_budget_bytes + max_message_size`。**明确按需分配**（三条上限都是记账上限，不是预留量；端点创建时不分配 64 MiB，否则 4096 端点会占 256 GiB）；分配失败按端点策略处理 + `log_fn` ERROR，**不新增错误码**。FR-4.7 重写、**AC-100 重写为四子项**（条数先到 / 单队列字节先到 / 总预算先到 / 空队列无条件接受）。**N-63 端点级额度**：`endpoint_config` 尾部追加 `queue_budget_bytes`（0 = 用 runtime 值），形成「端点准入阈值 + Runtime 硬上限」两层——端点可放宽自己的单队列预算，但**不能突破 `queue_total_bytes`**。**否决「按端点均分总量」**：端点数动态，`max_handles` 只给上界 4096，均分后每端点仅 64 KiB。默认值取宽松（64 MiB / 256 MiB），**不改任何已有结构体字段的偏移**（`iocomm_stats` 与三个 config 的追加均在尾部），故 `abi_minor` 不升（发布前定型口径）。**N-64「Runtime 是资源隔离单位、不是线程单位」**：C ABI §6.0 与架构 §3.1 补澄清块——一个 Runtime 用 owned 1 线程 / manual 0 线程，一个线程可驱动任意多个 Runtime，一个进程可有任意多个 Runtime；因此所有 per-Runtime 上限（`max_handles` / `monitor_budget_bytes` / 队列预算）**随 Runtime 数叠加，库不做跨 Runtime 协调**，部署侧核算用 `Runtime 数 × (queue_total_bytes + max_message_size)`。**否决进程级共享配额**（会破坏 §5.1b 的「每 Runtime 独立」） |
| 2026-11-18 | **复核收尾（N-65 + 三处陈旧表述）**：① **N-65**——`wire-format.md` §8.1 「同机多 Runtime」表原写「区间用尽…或关组播改 seed」，该建议**不成立**：seed bootstrap 的 `CAP_Q` 必须从本端单播 socket 发出，**同样占用** `23101..23200` 的一个端口，故 100 是宿主机级上限、关组播不释放端口；已改为「只能拆分主机」（限定在同一 netns 内；Linux 分 netns 可绕过但会切断组播，Windows 无对应机制）。② `open-questions.md` 清理：§5 七行中 5 行已被后续决策作废（M8/M11、`registry_plugin`、UDP 附件、「无工作量」、`monitor_budget_bytes` 是否 v1 执行），标注作废并保留去向；§9.3 N-45 行的「待定：订阅后是否补推初值」回写为 **N-61 已定**；§9.6c 引言「仍未闭合」改为「已全部闭合」。③ **FR-3.10** 标为实现约束（「允许移动代替拷贝」不可观测，不单独挂 AC，正确性由 FR-3.8 覆盖）；**FR-6.6** 补注由 **AC-111⑤** 覆盖、AC-111 覆盖列加 `FR-6.6`（不新增测试）。**不动任何 C 结构体、不新增导出函数、不改线格式** |
| 2026-11-19 | **文档一致性收尾（不增 FR/AC 编号）**：① **AC-94** 的 `"endpoints"` 数组此前无任何字段断言（`send_queue_max` / `queue_budget_bytes` 是 N-55 / N-63 追加的分母，只写在契约里）——补 `ep` / `name` / `conn_count` / `send_queue_depth` / `send_queue_bytes` / `send_queue_max` / `queue_budget_bytes` 七键；② **AC-E3 / AC-E5 的「待实测」「≈ 0」无数值**——补判定口径（AC-E3 的 fd / 内存只能从进程外观测，库不暴露 fd；AC-E5 取后 12 h 最小二乘斜率、内存判据用同一段数据的稳态均值自标定），两阈值的定稿时点统一为**首次 soak 执行前写死**（可先取保守值），**不得留空签发**，首跑后仅在实测证明阈值不可达或过松时修订并记入变更记录；③ **AC-116⑥** 补**调用前提**（要排除的只是「尚未 `create`、没有 Runtime 句柄」这一不可达情形，**不**额外要求先 `start`；建 Runtime 之前的版本查询指向 `iocomm_abi_version()`）；④ 变更记录两处陈旧表述修正：2026-11-05 行的「N-35 待负责人决策」补 2026-11-17 双许可裁决、2026-11-10 行的「N-60 待定口径」补 2026-11-18 收口；⑤ `architecture.md` §9 引言「原列出的 4 个未决问题」改为八项（实际 Q1–Q8）、`README.md` 架构图把 UDP 标出 v1.1；⑥ `open-questions.md` 的行号漂移（§8.4 更正块的 AC-104 引用）、§9.6c 引言、§10.5b 重复表头与缺失空行、文首 `§10` 自引用锚点一并修正。**不动任何 C 结构体、不新增导出函数、不改线格式** |
