# ADR-002：消息寻址、溢出策略、入站连接所有权与审计通道

- **状态**：已接受
- **日期**：2026-10-21
- **修订**：2026-10-22 —— 修正「v2 预留」的版本归属（UDP 实为 v1.1）、补「`on_done(OK)` = 已交给传输层」的澄清（决策本身未变）
- **修订**：2026-11-03 —— 决策 3 补充第三类持有动作「**端点级持有**」：启用 `iocomm_subscribe(ep)` / `endpoint_recv(ep)` 即隐式持有此后接入的入站连接（N-02）。**不改变**「数据面 API 不是所有权开关」与「未持有即回收」两条原则——端点级订阅是有意的、显式的持有声明，不是把 `send` 当所有权开关
- **决策者**：项目负责人
- **影响**：`api/c-abi.md`（§5.0 / §5.2 / §6.1 / §6.2 / §9）· `architecture.md`（§6.1 / §9）· `requirements.md`（FR-4.5 / FR-8 / FR-10，AC-26 / 29 / 33 / 41 / 56 / 61 / 65 / 66 / 70 / 71，新增 AC-74–76）。**2026-11-03 补**：新增 FR-8.11 / AC-103 / AC-104（端点级持有与服务端扇出）

---

## 背景

M0 冻结前，四项设计在文档中各自存在内部矛盾或缺少需求支撑：

1. `send_options.key` 路由键：名义上是 L3 投递选择，实现上只是透传元数据（L1），库不做任何匹配。
2. `delivery_class` 三档（`BEST_EFFORT` / `AT_LEAST_ONCE` / `RELIABLE`）：命名复用了「投递保证」，但本库没有 ACK / 重传 / 去重 / 会话恢复。
3. `accept` 回调的「四选一接管」：调用了 `conn_subscribe` / `conn_send_async` / `conn_retain` / `conn_destroy` 之一即视为接管，导致「发一条拒绝就走」永久持有连接；且头文件同时写了「归调用方所有」与「未调用则自动回收」。
4. 独立审计通道（句柄 + 环 + poll + dump）：库内几 MB 环无法满足现场留存；运行期 `audit_open/close` 与防篡改方向相反。

决定依据来自 2026-10-20 的四份行业调研（OPC UA / DDS / gRPC / nng / ZeroMQ / libuv / POSIX / MQTT 的官方文档与源码），结论是：**「在工业局域网 + 不含数据格式 + 纯 C ABI」三约束下，四项都应删繁就简。**

---

## 决策

| # | 决策 |
|---|---|
| 1 | **删除 per-message 路由键 `key`**。端点名承担寻址；消息类型由调用方放进 payload 或拆成不同端点。 |
| 2 | **删除 `delivery_class` 三档**，只保留**每端点一个 `overflow_policy`**（4 种）。「过程数据 / 报警 / 命令」用三个端点表达。 |
| 3 | **`accept` 改为借用语义**：回调内句柄只在回调期间有效；持有动作有**显式 `conn_retain`**、**隐式 `conn_subscribe`**、以及 **2026-11-03 增补的「端点级持有」**（启用 `iocomm_subscribe(ep)` / `endpoint_recv(ep)` 即隐式持有此后接入的入站连接）；「发完即关」用发送选项 **`ICOMM_SEND_CLOSE_AFTER`**。 |
| 4 | **审计不做独立句柄 / 环**，改为**创建期不可变的 `audit_fn` 回调 sink**；计数并入 `iocomm_stats.audit_events`。 |

---

## 理由

### 1. 删除 `key`

- 路由键的语义强度分四层：L3 投递选择（broker 消费）/ L2 分派 / L1 透传元数据 / L0 名字即路由。ZeroMQ SUB 是库内真正的前缀过滤；NATS 的过滤在 server 侧。**本库的具名端点已经占了 L0**。
- 当前的 `key` = 名义 L3、实现 L1、把 L3 判断外包给应用的三不像：它等价于「payload 的第一个字段」，却带来 4 KiB 截断、arena 预算、独立视图 API 与验收项。
- 仓库内唯一提到 `key` 的需求是 FR-10.2 的监控视图，且已移入 v1.1 → **v1 没有需求支撑**。
- 发布后再删是 major 变更；头文件尚未发布，现在删成本最低且可逆（将来作为新字段尾部追加只需升 minor）。

### 2. 删除 `delivery_class`

- 行业严格区分「投递保证」（需 ACK / 重传 / 会话：MQTT QoS、DDS RELIABILITY）与「队列满策略」（MQTT Receive Maximum、DDS HISTORY、Kafka acks vs buffer.memory）。ZeroMQ / nng / .NET Channels **只提供 overflow mode** —— 「只提供溢出策略」是成熟系统的正常选择。
- 本库没有 ACK / 重传 / 去重 / 会话恢复，`send` 成功只表示**已完整交给传输层**（at-most-once）。`AT_LEAST_ONCE` / `RELIABLE` 与 `BEST_EFFORT` 的唯一差别就是队列满策略。复用这些名字会让 SDK 封装层假设「不会丢」。
- **per-message 类别 + 共享队列无法保持 per-class 语义**：`DROP_OLDEST` 可能丢掉一条 `RELIABLE` 命令。三端点可以在行为上等价，前提是队列与接收按端点隔离、跨类顺序不要求、连接/故障独立。

### 3. `accept` 借用语义

- 行业只有两条轴：**借用 + 显式 retain**（GObject `GSocketService`、nng、Qt、httpd、nginx）或**送出即泄漏**（POSIX `accept`、libuv、libevent、AcceptEx）。**「四选一接管」没有同类先例。**
- 「调了某个数据面 API 就算接管」是反模式：`conn_send_async` 被拿来当所有权开关 → 「发一条拒绝就走」永久持有连接，而这恰好是最常见的用法。
- 借用语义让库的默认行为安全：**什么都不做的连接会被收回**，而不是泄漏。
- `u64` 代际句柄保留：保存但未持有的误用**安全失败为 `STALE_HANDLE`**，而不是 GObject 那样的 UAF。

### 4. 审计 sink

- 标准只要求**稳定事件 schema + 可插拔 sink**：OPC UA 用 Event Notification + Subscription；DDS Security 是 Logging Plugin；gRPC 是 `AuditLogger` 回调；nng 是 `nng_log_auth`。ZeroMQ / libuv / Asio 都没有「handle + poll 环」式审计。
- 库内几 MB 环最多覆盖几分钟到几小时，远不够现场留存；`subject` 只是句柄，v1 无认证 → 没有真正的「谁」；运行期 `audit_open/close` 与防篡改方向相反（DDS Security 明确日志选项在 `enable_logging` 之后不可运行期修改）。
- 删除面：5 个函数 + `iocomm_audit_t` 句柄类型 + `audit_stats`。保留：`audit_kind` / 固定大小 POD 记录 / 计数（并入 `iocomm_stats`）。

---

## 被否决的方案

| 方案 | 否决理由 |
|---|---|
| 保留 `key` 但改名 `tag`（64–256 B） | 提供的能力与「payload 第一个字节」完全等价，却多出 arena 计费、截断标志、独立视图 API 与 AC |
| v1 做 `key` 接收侧过滤（pub/sub） | 真要做应走**端点名层级过滤**（L2），不需要 per-message 键；且不在 v1 范围 |
| 保留 `delivery_class`，把 `RELIABLE` 配成 `DROP_*` 时记 Warning | per-class 语义仍然无法在共享队列上保持；Warning 不能弥补可能丢命令 |
| 接收侧单独一个 `recv_overflow_policy` | 一键一端点、一对收发队列，两个旋钮反而让人不知道调哪个；接收侧 `BLOCK` 永不生效 |
| 异步 `BLOCK` 加隐藏的有界 pending 缓冲 | 多一层隐藏队列，内存与延迟不可估；`on_done` 触发时间变得无界；行业里异步发布不阻塞调用方 |
| accept 返回 `ACCEPT` / `REJECT` 枚举表达所有权 | 行业返回值枚举只用于**准入门禁**（`WSAAccept` 的 `CONDITIONPROC`、`MHD_AcceptPolicyCallback` 根本不接触 fd）；无法表达「接受并订阅」/「接受并回发一条」 |
| 无持有 `send_async` 时隐式 retain | 正是「数据面 API 当所有权开关」的反模式 |
| 无持有 `send_async` 时隐式 `CLOSE_AFTER` | 发送后静默关闭，用户下一次用句柄才发现 `STALE_HANDLE` |
| `conn_destroy` = flush 后关闭 | destroy 变成阻塞调用；在回调内调用会死锁，还得再加超时 |
| `retain` 与 `subscribe` 互斥 | `retain` 之后订阅是合法需求；互斥只会制造 `INVALID_STATE` |
| 审计保留「runtime 创建时即存在、always-on 的小环」 | 只有合同硬性要求 pull 式时才考虑；当前无此需求，见「后果」 |
| 审计 `audit_fn` 经 `tune_config` 运行期重设 | 与防篡改方向相反 |
| 审计事件投递到 loop / 独立线程 | loop 模型需要队列 + 丢事件策略（等于把删掉的环请回来）、loop 阻塞时审计停摆；独立线程违反「owned 模式恰好 1 个 IO 线程」 |

---

## 后果

### 正面

- v1 的发送语义只有一条：**入队或失败**（`on_done(OK)` 进一步表示「已完整交给传输层」）。不存在「这个类别保证不丢」的错觉。
- 入站连接的默认行为安全（未持有即回收），「发完即关」有单条原子表达。
- 审计事件在任何线程都能送达宿主，库不承担留存职责，内存占用为零。
- 头文件少一个枚举、两个字段、一个句柄类型与五个函数；验收项减少 2 条（AC-66 撤销、AC-71 收敛）。

### 负面 / 需要说明

- **异步 `BLOCK` 不阻塞**：调用方若需要「满队列时等待」，必须改用同步发送（自带 `timeout_ms`）或在应用层重试。
- **逐消息「类型」信息不在信封里**：需要时放进 payload 或按消息类型拆分端点；对「监控时不解析 payload 就能看类型」有硬需求的客户，须在 v1.1 评估。
- **审计无法回放**：`audit_fn` 之后的事件无处查找；需要留存时由宿主的回调写盘 / 送入 SIEM。
- **版本归属**：UDP 传输排在 **v1.1**（FR-4.2）；不可靠传输上的投递保证仍留到 v2，届时以真正的 `delivery_guarantee` 与**端点名层级过滤**引入，均属尾部追加或新入口。

---

## 相关文档

- [需求](../requirements.md) · [架构](../architecture.md) · [C ABI](../api/c-abi.md) · [ADR-001](ADR-001-language-and-platform.md)
