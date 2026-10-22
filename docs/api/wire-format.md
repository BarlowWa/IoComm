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

> `frame_type` **不进入 ABI**。它只在线格式里有意义；应用层永远看不到它。
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

1. **未知 tag 必须跳过**（按 `len` 前移），**不得报错**——这是唯一的前向兼容手段。验收项：AC-90。
2. tag 值**只追加、不复用**；`0x0000` 保留为无效。
3. 同一 tag 重复出现：**后者覆盖前者**（不报错），便于「重发/合并」场景。
4. TLV 区总长 `tlv_len` 必须与逐项解析的结果**严格相等**，否则视为帧损坏 → 关闭连接。
5. `SEQ`、`TS_SEND`、`SOURCE_NODE` 三个 tag **必须存在**；缺失视为帧损坏。

> **为什么这些字段在 TLV 里，而不在定长头里**：头只放**分帧必需**的信息（要能跳过 payload）；
> 语义字段放 TLV，才能在不升 `version` 的前提下追加。代价是实时路径多一次扫描——但 TLV 区通常只有 5 项、约 40 B。

---

## 4. 心跳帧的 payload

`HEARTBEAT` / `HEARTBEAT_ACK` 的 payload 固定 8 B：

| 偏移 | 宽度 | 字段 |
|---|---|---|
| 0 | 4 | `hb_seq`（u32，自增，**不是**消息 `SEQ`） |
| 4 | 4 | `hb_ack`（u32，应答中回填对端最近一次 `hb_seq`；心跳帧填 0） |

双向确认靠 `hb_ack` 回填实现：只收到 `HEARTBEAT` 而从未收到回填了自己序号的 `HEARTBEAT_ACK`，判为单向故障。

---

## 5. HELLO 的 payload

`HELLO` / `HELLO_ACK` 的 payload 固定 16 B（多字节整数按 `flags.bit0` 端序）：

| 偏移 | 宽度 | 字段 | 说明 |
|---|---|---|---|
| 0 | 2 | `wire_version` | 发送方实现的线格式版本（v1 = 1） |
| 2 | 2 | `min_version` | 发送方能接受的最低版本 |
| 4 | 8 | `node_id` | 发送方 NodeId |
| 12 | 4 | `abi_major` | 仅供诊断；**不参与**线格式协商 |

**握手规则**：

1. 连接建立后，**双方都必须以 `HELLO` 作为第一帧**（可以同时发，无先后）。
2. 收到 `HELLO` 后校验：`min_version ≤ 本端 wire_version ≤ 对端 wire_version`。不满足 → 回 `HELLO_ACK` 后**关闭连接**（`DISCONNECTED`）。
3. 双方都收到合法 `HELLO` 后，连接才进入「可发 DATA」状态；在此之前收到的 `DATA` 帧一律丢弃并关闭连接。
4. `HELLO` / `HELLO_ACK` **不携带 TLV 区**（`tlv_len = 0`）。

> 没有 `HELLO` 就无从知道对端版本——「未知 tag 跳过」只能处理**同一 major 内**的追加。
> 提前握手把「版本不匹配」变成一条明确的 `DISCONNECTED`，而不是解析到一半才发现。

---

## 6. 版本协商

| 场景 | 行为 |
|---|---|
| `wire_version` 兼容（见 §5 规则 2） | 正常解析；额外 TLV tag 按 §3 规则 1 跳过 |
| `wire_version` 不兼容 | `HELLO` 后关闭连接；**不做尽力兼容** |
| 未收到 `HELLO` 就收到其他帧 | 关闭连接 |
| `magic` 不匹配 / `version` 不在 {1} 内 / `reserved != 0` | 帧损坏 → 关闭连接 |
| `tlv_len` 或 `payload_len` 超出剩余数据 | 帧损坏 → 关闭连接（不等待，防止半帧挂死） |

> 与 C ABI 的 `abi_major` 无关：**线格式版本与 ABI 版本是两套独立编号**。
> 理由：线格式约束的是「两个运行时怎么对话」，ABI 约束的是「宿主怎么调库」；同一 ABI 下可以跑不同线格式（例如将来 inproc 用内存直传），反之亦然。

---

## 7. 与其他文档的边界

| 内容 | 归属 |
|---|---|
| 帧边界、头、TLV tag、心跳 payload | **本文件** |
| `sequence` / `timestamp` / `correlation_id` 在 ABI 里的类型 | [C ABI §6.3](c-abi.md) |
| 队列、溢出策略、`TOO_LARGE` 的判定点 | [C ABI §6.1 / §9.3](c-abi.md) |
| 组播地址、端口、信标节奏 | [架构 §6.3](../architecture.md) |

**不在此文件定义**：载荷编码、消息类型、业务语义——那是应用层的职责（需求红线）。
