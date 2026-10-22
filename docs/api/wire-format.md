# IoComm 线格式（v1）

> 状态：设计阶段 ｜ 相关：[架构](../architecture.md) · [C ABI](c-abi.md) · [需求](../requirements.md)
>
> **定位**：本文件只定义**帧的边界与头部**，不定义 payload 的含义。
> M2 开始前必须冻结；任何字段宽度的改动都会影响 `sequence` / `timestamp` 的编码，越晚改代价越大。

---

## 1. 帧布局

```
+----------------+----------------+--------------------------+
|  帧头 (20 B)    |  TLV 扩展区     |  payload（不透明字节）      |
+----------------+----------------+--------------------------+
```

| 偏移 | 宽度 | 字段 | 说明 |
|---|---|---|---|
| 0 | 4 | `magic` | `0x49 0x4F 0x43 0x4D` = `"IOCM"` |
| 4 | 2 | `version` | `1`（本文件的版本） |
| 6 | 1 | `frame_type` | 见 §2 |
| 7 | 1 | `flags` | bit0 = little-endian，其余保留为 0 |
| 8 | 4 | `tlv_len` | TLV 扩展区字节数 |
| 12 | 4 | `payload_len` | payload 字节数（**不含**头与 TLV） |
| 16 | 4 | `reserved` | 必须为 0；读方忽略 |

- **整帧长 = 20 + `tlv_len` + `payload_len`**，没有冗余的长度字段（冗余 = 两处可能不一致）。
- 读方的解码顺序：读满 20 B → 校验 `magic` / `version` / `reserved` → 按 `tlv_len` 读扩展区 → 按 `payload_len` 读载荷。
- **所有多字节整数按 `flags.bit0` 指定端序**；发送方固定写 little-endian（`bit0 = 1`），读方必须支持两种。
- **上限**：`20 + tlv_len + payload_len ≤ max_message_size`（默认 1 MiB）。超限的处理见 C ABI §9.3「消息尺寸上限」。

> **这是线格式，不是内存里的结构体**：禁止把 `iocomm_*` 结构体直接 `memcpy` 到线上，
> 也禁止用 `#pragma pack` 去「对齐」线格式（C ABI 反例清单第 10 条）。编码/解码是显式逐字段的。

---

## 2. `frame_type`

| 值 | 类型 | 含义 |
|---|---|---|
| `0x01` | `DATA` | 用户消息（payload 为调用方的字节） |
| `0x02` | `HEARTBEAT` | 心跳（payload 见 §4） |
| `0x03` | `HEARTBEAT_ACK` | 心跳确认 |
| `0x0A` | `HELLO` | **连接上的第一帧**，携带线格式版本与节点身份（见 §5） |
| `0x0B` | `HELLO_ACK` | 对 `HELLO` 的应答 |
| `0x0C` | `ERROR` | **协议级错误**：发送后关闭连接（见 §2.1） |

> `frame_type` **不进入 ABI**。它只在线格式里有意义；应用层永远看不到它。
### 2.1 `ERROR` 帧

payload 固定 6 B：`reason(u16)` + `reserved(u16)` + `detail(u32)`。

| reason | 名称 | 触发 |
|---|---|---|
| `0x0001` | `FRAME_TOO_LARGE` | 收到整帧超过本端 `max_frame_bytes` |
| `0x0002` | `HANDSHAKE_TIMEOUT` | 握手超时（§5 规则 5） |
| `0x0003` | `VERSION_UNSUPPORTED` | `wire_version` 不兼容 |
| `0x0004` | `MALFORMED` | magic / 长度 / TLV 校验失败 |
| `0x0005` | `PROTOCOL_STATE` | 未握手就收到 `DATA` 等 |

- `detail` 携带**附加信息**（如 `FRAME_TOO_LARGE` 时为实际帧长，`VERSION_UNSUPPORTED` 时为本端版本）。
- 发送 `ERROR` 后**必须**关闭连接。
- **发送侧观测面**：发出 `ERROR` 的一方自己就是判定者，不需要额外通知——返回值 / `on_done` 已给出结论。
  `stats.protocol_errors` **只统计接收侧**（收到 `ERROR` 或判定帧损坏的次数）。
- **各 reason 的触发点**：
  | reason | 由谁发 | 同时产生的本地结果 |
  |---|---|---|
  | `FRAME_TOO_LARGE` | 接收方：入站整帧 > `max_frame_bytes` | `DROPPED(TOO_LARGE)` + 计数 |
  | `HANDSHAKE_TIMEOUT` | 双方各自计时，先到者发 | 该连接在途 `on_done(DISCONNECTED)` |
  | `VERSION_UNSUPPORTED` | 收到不兼容 `HELLO` 的一方 | 同上 |
  | `MALFORMED` | 接收方：magic / 长度 / TLV 校验失败 | 同上 |
  | `PROTOCOL_STATE` | 接收方：**握手后**再收到 `HELLO` / `HELLO_ACK`，或收到 `ERROR` 后再收到任何帧 | 同上 |
- **接收方的观测面（唯一口径）**：收到 `ERROR` 属于**异步事件**，不挂在任何一次调用上。
  因此它固定映射为：
  1. 该连接上所有在途 `on_done` → `code = ICOMM_ERR_DISCONNECTED`（**不是** `CLOSED`；
     与 `PEER_GONE → DISCONNECTED` 同口径，见 C ABI §9）；
  2. `log_fn` 的 **ERROR** 级别输出一条含 `reason` 与 `detail` 的文本；
  3. `iocomm_stats` 对应连接/端点的诊断计数递增（`protocol_errors`，v1 新增计数）。
  **`iocomm_error.message` 不承载该信息**——接收侧没有哪次调用的 `err` 能对上这个事件。
- `ERROR` 帧本身**不参与** `max_frame_bytes` 检查（固定 26 B）。
- `ERROR` 帧**豁免** §3 规则 5 的必填 tag 要求（与 `HELLO` 同）：`tlv_len = 0` 是合法的，
  因为此时对端可能已处于无法解析 TLV 的状态。

> **未知 `frame_type` → 关闭连接**（`DISCONNECTED`）。不「跳过未知帧」：跳过它等于跳过一段可能改变会话状态的语义，
> 前向兼容靠 **TLV 未知 tag 跳过**（§3）实现，而不是靠跳过整帧。

---

## 3. TLV 扩展区

```
+--------+--------+---------------------+
| tag(2) | len(2) | value (len B)        |
+--------+--------+---------------------+
```

| tag | 名称 | 编码 | 说明 |
|---|---|---|---|
| `0x0001` | `SEQ` | `u64` | per-source 单调序号（C ABI 的 `message.sequence`） |
| `0x0002` | `TS_SEND` | `u64` | 发送方事件时间（纳秒，挂钟） |
| `0x0003` | `CLOCK_SYNCED` | `u8` | 0 / 1 |
| `0x0004` | `CORRELATION_ID` | `u64` | 0 = 无 |
| `0x0005` | `SOURCE_NODE` | `u64` | 来源 NodeId |

**规则**：

1. **未知 tag 必须跳过**（按 `len` 前移），**不得报错**——这是 **TLV 层**唯一的前向兼容手段
   （帧外的兼容靠 `HELLO` 版本协商；帧类型层的未知值是关闭连接，见 §2）。验收项：AC-90。
2. tag 值**只追加、不复用**；`0x0000` 保留为无效。
3. 同一 tag 重复出现：**后者覆盖前者**（不报错），便于「重发/合并」场景。
4. TLV 区总长 `tlv_len` 必须与逐项解析的结果**严格相等**，否则视为帧损坏 → 关闭连接。
5. `SEQ`、`TS_SEND`、`SOURCE_NODE` 三个 tag **必须存在**；缺失视为帧损坏。

> **为什么这些字段在 TLV 里，而不在定长头里**：头只放**分帧必需**的信息（要能跳过 payload）；
> 语义字段放 TLV，才能在不升 `version` 的前提下追加。代价是实时路径多一次扫描——
> TLV 区 5 项实际开销 **53 B**（每项 `tag 2 + len 2 + 值`：`SEQ` 12、`TS_SEND` 12、
> `CLOCK_SYNCED` 5、`CORRELATION_ID` 12、`SOURCE_NODE` 12），**加 20 B 头 = 每帧固定 73 B**。
> 以 128 B payload 为例：`20 + 53 + 128 = 201 B`，其中协议开销 73 B ≈ **36%**；
> 以 64 B payload 为例：`20 + 53 + 64 = 137 B`，开销 ≈ **53%**。这是「可演进」的代价，不是缺陷。

---

## 4. 心跳帧的 payload

`HEARTBEAT` / `HEARTBEAT_ACK` 的 payload 固定 16 B（"序号 + 时间戳 + 双向确认"三项在此落齐）：

| 偏移 | 宽度 | 字段 |
|---|---|---|
| 0 | 4 | `hb_seq`（u32，自增，**不是**消息 `SEQ`） |
| 4 | 4 | `hb_ack`（u32，应答中回填对端最近一次 `hb_seq`；心跳帧填 0） |
| 8 | 8 | `hb_ts_ns`（u64，发送方事件时间，纳秒挂钟） |

`hb_ts_ns` 用于让接收方把心跳计入「最后活动时间」并做单向延迟估计；
**RTT 只用 `hb_seq`/`hb_ack` 配对计算**，不用跨机时间戳相减（跨机挂钟不可信，见架构 §6.5）。

双向确认靠 `hb_ack` 回填实现：只收到 `HEARTBEAT` 而从未收到回填了自己序号的 `HEARTBEAT_ACK`，判为单向故障。

---

## 5. HELLO 的 payload

`HELLO` / `HELLO_ACK` 的 payload 固定 20 B（多字节整数按 `flags.bit0` 端序）：

| 偏移 | 宽度 | 字段 | 说明 |
|---|---|---|---|
| 0 | 2 | `wire_version` | 发送方实现的线格式版本（v1 = 1） |
| 2 | 2 | `min_version` | 发送方能接受的最低版本 |
| 4 | 4 | `max_frame_bytes` | 发送方**能接收**的最大整帧字节数 |
| 8 | 8 | `node_id` | 发送方 NodeId |
| 16 | 4 | `abi_major` | 仅供诊断；**不参与**线格式协商 |

> **接收尺寸协商（唯一口径）**：双方各自上报 `max_frame_bytes`（= 本端 `max_message_size`），
> 连接生效上限 = **`min(本端配置, 对端上报)`**。**发送侧 `TOO_LARGE` 以此为准**——
> 否则会出现「A 报成功、B 断连」。该值在握手完成时**定死**；之后任一端热改 `max_message_size`
> **不影响已建立连接**（要生效需重连）。

**握手规则**：

1. 连接建立后，**双方都必须以 `HELLO` 作为第一帧**（可以同时发，无先后）。
2. 收到 `HELLO` 后校验**区间交集非空**：`max(本端 min_version, 对端 min_version) ≤ min(本端 wire_version, 对端 wire_version)`。
   不满足 → 发 `ERROR(VERSION_UNSUPPORTED)` 后关闭连接。
   （写成 `本端 ≤ 对端 ≤ 本端` 的三项链是错的：v2 对端 `(wire=2, min=1)` 与 v1 本端 `(wire=1, min=1)` 明明可互通，三项链会判 `1≤2≤1` 为假。）
3. 双方都收到合法 `HELLO` 后，连接才进入「可发 DATA」状态；在此之前收到的 `DATA` 帧一律丢弃并**直接关闭**
   （不发 `ERROR`——此时对端可能根本不懂 `ERROR` 帧，发了也白发）。
4. `HELLO` / `HELLO_ACK` / `ERROR` **不携带 TLV 区**（`tlv_len = 0`）；带 TLV 的 `HELLO` 是格式错误，
   回 `ERROR(MALFORMED)` 后关闭（§3 规则 5 的必填 tag 要求对这三类帧**不适用**）。
5. **握手超时**：连接建立后 **5000 ms**（v1 固定；不分出入站——入站侧没有 `connect_timeout_ms`
   这样的调用参数，用参数派生会让一半连接无值可依）内未完成双向 `HELLO`
   → 发 `ERROR(HANDSHAKE_TIMEOUT)` 后关闭。
6. 连接上限只在握手时计算一次（见上方「接收尺寸协商」）；之后热改 `max_message_size` 不改变它。

> 没有 `HELLO` 就无从知道对端版本——「未知 tag 跳过」只能处理**同一 major 内**的追加。
> 提前握手把「版本不匹配」变成一条明确的 `DISCONNECTED`，而不是解析到一半才发现。

---

## 6. 版本协商

| 场景 | 行为 |
|---|---|
| `wire_version` 兼容（见 §5 规则 2） | 正常解析；额外 TLV tag 按 §3 规则 1 跳过 |
| `wire_version` 不兼容 | `HELLO` 后关闭连接；**不做尽力兼容** |
| 未收到 `HELLO` 就收到其他帧 | 关闭连接 |
| `magic` 不匹配 / `version` 不在 {1} 内 | 帧损坏 → 关闭连接。**`reserved != 0` 不作为关闭条件**（前向兼容：读方忽略） |
| `tlv_len` 或 `payload_len` 使整帧 > 本端 `max_frame_bytes` | **立即**判帧损坏 → 关连接（长度字段一读完就能判，不需要等数据） |
| 长度合法但数据未到齐 | **等待**：读满 `20 + tlv_len + payload_len` 字节（流式传输受连接读超时约束，超时 → 关连接） |

> **不要在读到长度字段时就拿它和「当前缓冲区剩余字节」比**：TCP 是字节流，大帧必然跨段到达，
> 那样会把合法帧误判为损坏。唯一能立即判定的越界是「整帧超过 `max_frame_bytes`」。

> 与 C ABI 的 `abi_major` 无关：**线格式版本与 ABI 版本是两套独立编号**。
>
> **两个 `version` 的分工**：帧头的 `version` 是**逐帧**的解析版本（v1 只有 `1`，其他值直接判帧损坏）；
> `HELLO` 里的 `wire_version` / `min_version` 是**协商用**的区间。二者在 v1 必须都为 1；
> 未来加新的帧头版本时，`HELLO` 的协商先于任何非 1 帧头的出现——即**帧头 version 的兼容性由 HELLO 协商结果决定**。
> 理由：线格式约束的是「两个运行时怎么对话」，ABI 约束的是「宿主怎么调库」；同一 ABI 下可以跑不同线格式（例如将来 inproc 用内存直传），反之亦然。

---

## 7. inproc 与线格式的关系

**inproc 不走本文件定义的线格式**（同一地址空间，直接移交编解码后的缓冲）。

- 它**不跑 `HELLO` 握手**：没有版本协商的必要——两端必然链接同一个库。
- 「复用帧层」在架构文档里指的是**复用同一套消息抽象**（消息边界、`sequence`、`correlation_id`、`original_len`、监控打点），
  **不是**逐字节走 `IOCM` 帧。
- 因此 inproc 的跨版本兼容性问题不存在；`wire_version` 只在 tcp / unix / pipe 上协商。
- **尺寸校验仍生效**：inproc 两端直接比较各自的 `max_message_size`（不协商），
  若本端大于对端，超出对端上限的消息在**本端发送时**已通过校验、在**对端入站时**被判 `TOO_LARGE` 并关闭连接。
  这是 inproc 与 TCP 的唯一行为差异（TCP 有 §5 的协商可避免），属已知瑕疵，v1 不做额外协商。

> 这也是为什么 `wire-format.md` 与 ABI 版本是两套编号（§6 末尾）：inproc 可以完全不产生线格式。

---

## 8. 发现报文（阶段一 / 阶段二）

发现报文**是 UDP 数据报**，不套用 §1 的帧头（没有连接，没有流分帧）。统一前缀：

| 偏移 | 宽度 | 字段 | 说明 |
|---|---|---|---|
| 0 | 4 | `magic` | `0x49 0x4F 0x43 0x44` = `"IOCD"` |
| 4 | 1 | `version` | `1` |
| 5 | 1 | `kind` | 见下 |
| 6 | 2 | `reserved` | 0 |
| 8 | … | 报文体 | 逐 `kind` 定义 |

| `kind` | 名称 | 方向 | 报文体 |
|---|---|---|---|
| `0x01` | `BEACON` | 组播 / 单播发送 | **节点自述 + 端点列表**（不含端点时对端无法 `connect_node`） |
| `0x02` | `CAP_Q` | 单播 | 阶段二查询：目标 `node_id`（8 B） |
| `0x03` | `CAP_A` | 单播 | 节点自述 + 端点列表（与 `BEACON` 同构；用于主动查询晚加入者） |

**节点自述**（TLV 区，**编码规则同 §3，但 tag 数值空间与 §3 完全独立**——
`0x0001` 在连接内帧里是 `SEQ`，在这里是 `NODE_ID`，两者互不影响）：

> **必须实现的校验**：解析时先按 `magic` 区分「连接内帧」与「发现报文」，再套用对应的 tag 表。
> 用错表会被 §3 规则 5（必填 tag 缺失）判为帧损坏，导致所有发现流量被丢弃。

| tag | 名称 | 编码 |
|---|---|---|
| `0x0001` | `NODE_ID` | `u64` |
| `0x0002` | `NODE_NAME` | UTF-8 字节串 |
| `0x0003` | `WIRE_VERSION` | `u16` |
| `0x0004` | `ENDPOINTS` | 重复项：`name_len(u16) + name + transport_len(u16) + transport + addr_len(u16) + addr` |
| `0x0005` | `LEASE_MS` | `u64`（与 `c-abi` 的 `uint64_t` 一致） |
| `0x0006` | `PAGE_NO` | `u8`（从 1 起；无分页时为 1） |
| `0x0007` | `PAGE_TOTAL` | `u8`（无分页时为 1） |

**规则**：

1. **未知 `kind` → 直接丢弃**（不是关闭连接——发现没有连接）。
2. **未知 TLV tag 跳过**（与 §3 同一规则）。
3. 报文体总长必须与逐项解析严格相等，否则丢弃该数据报。
4. 单条报文必须 ≤ **1400 B**（§8.1 的 UDP 数据报上限，**不是** `max_message_size`）；超长按 §8.1 的分页规则处理。
5. 同一节点重复 `BEACON` 且元信息未变 → **不触发 `UPDATED`**（FR-2.7），由接收方比对。

> 阶段一（`BEACON`）回答「有谁在」，阶段二（`CAP_Q` / `CAP_A`）回答「它能连什么」。
> **`BEACON` 也携带端点列表**（否则晚加入者无法 `connect_node`）；`CAP_Q` 用于节点表已过期时的按需刷新。
> 端点列表过大时靠 §8.1 的分页解决，不靠「不放进信标」。

### 8.1 寻址、MTU 与节奏

| 项 | 值 | 说明 |
|---|---|---|
| 组播组地址 | `239.255.73.77` | v1 **不可配置**（无对应字段）；改动属 v2 新增入口 |
| UDP 端口 | `47377` | v1 **不可配置**；同机多 Runtime 需共用同一端口（见下） |
| 单播 seed 字符串格式 | `"<host>:<port>"`，IPv4 字面量或主机名 | 与 `listen_addr` 同格式 |
| 发现 socket 绑定 | `0.0.0.0:<port>`；发送组播时用 `iface_index` 指定的网卡 | 多网卡必须显式指定（FR-2.5） |
| 信标周期 | `discovery_config.heartbeat_ms`（默认 **2000 ms**），±10% 抖动 | 抖动避免节点同步风暴 |
| 租约 | `discovery_config.lease_ms`（默认 **6000 ms**，即 3 个信标周期） | 超时剔除 |
| **单个数据报上限** | **1400 B**（保守取以太网 MTU 1500 减 IPv6/UDP 头） | **不是** `max_message_size`（1 MiB） |

**同机多 Runtime（按收发路径分别处理）**：

| 路径 | 机制 | 依据 |
|---|---|---|
| **组播接收** | 所有 Runtime 加入同一组播组、绑同一端口，内核按**组播语义把数据报复制给每个 socket** | 组播天然是一对多 |
| **单播接收**（`CAP_Q` / `CAP_A` / seed） | **每个 Runtime 用独立端口**：在 `47377..47476` 内取第一个可用端口绑定；向对端查询时，目标端口取对端 `BEACON` 里上报的**实际源端口** | 单播 UDP 在 `SO_REUSEADDR`/`SO_REUSEPORT` 下**不会**复制给所有 socket，会被同机另一个 Runtime 吞掉 |

- `BEACON` 的**源端口**因此必须被记录（`iocomm_node_info` 的地址里带端口）。
- 接收方**忽略 `NODE_ID == 本机任一 Runtime` 的信标**，避免自我发现。
- `SO_REUSEADDR` 只用于组播 socket；单播 socket **不**设该选项，靠端口区间分配保证互不冲突。

**MTU 与分页**：

- `BEACON` / `CAP_A` 的报文体超过 1400 B 时，**端点列表按条目边界分页**：同一节点的多页报文带相同的
  `NODE_ID` 与递增的 `PAGE_NO` / `PAGE_TOTAL`（tag `0x0006` / `0x0007`），接收方按页组装后才更新节点表。
- 单条**端点条目**本身超过 1400 B → 该条目**不发送**并计入诊断计数（端点名 + 地址的理论上限足够小，正常不会触发）。
- `CAP_Q` 永远不超过 16 B，不需要分页。
- **收不到全部页时不更新节点表**（宁可慢，不可出现半张表）；已有条目在租约到期后自然淘汰。

> 与连接内帧的 `max_message_size` 是**两套上限**：UDP 受 MTU 约束，TCP/unix/pipe 受 `max_message_size` 约束。
> 把 1 MiB 的端点表直接塞进一个 UDP 包在现场必然会被分片或丢弃。

---

## 9. 与其他文档的边界

| 内容 | 归属 |
|---|---|
| 帧边界、头、TLV tag、心跳 payload | **本文件** |
| `sequence` / `timestamp` / `correlation_id` 在 ABI 里的类型 | [C ABI §6.3](c-abi.md) |
| 队列、溢出策略、`TOO_LARGE` 的判定点 | [C ABI §6.1 / §9.3](c-abi.md) |
| 组播地址、端口、信标节奏 | **本节 §8.1** |
| 发现报文 `magic` / 节点自述 / 端点列表 | **§8** |
| inproc 是否走线格式 | **§7**（不走） |

**不在此文件定义**：载荷编码、消息类型、业务语义——那是应用层的职责（需求红线）。
