# IoComm — 工业局域网 IO 通信库

> 工业局域网通信基础设施。提供句柄注册、发现、终端内/终端间通信、状态监控与控制，**同步与异步**双接口，**不定义任何应用层数据格式**。

**状态**：设计阶段（未开始实现）
**决策**：Rust 核心 + 纯 C ABI ｜ x86_64 + ARM64 ｜ [ADR-001](docs/adr/ADR-001-language-and-platform.md)

---

## 这个库是什么

一个**通信基础设施库**，负责把字节送到对端并管理端点，不关心字节的含义。

```
┌──────────────────────────────────────────────┐
│  应用（C / C++ / Python / 任意语言）           │
└───────────────────┬──────────────────────────┘
                    │  纯 C ABI（唯一稳定边界）
┌───────────────────▼──────────────────────────┐
│  IoComm                                       │
│  ┌───────────┬───────────┬───────────────┐   │
│  │ 句柄注册   │  发现      │ 状态监控/控制  │   │
│  ├───────────┴───────────┴───────────────┤   │
│  │        会话 / 消息 / 同步·异步          │   │
│  ├───────────────────────────────────────┤   │
│  │  传输：TCP / Unix socket / 命名管道 /   │   │
│  │        进程内（可插拔；UDP 属 v1.1）    │   │
│  └───────────────────────────────────────┘   │
└──────────────────────────────────────────────┘
```

---

## 这个库不做什么

明确边界，避免被要求实现不擅长或不该做的事：

| 不做 | 原因 |
|---|---|
| **任何数据格式 / 序列化 / schema** | 需求红线。载荷对库不透明 |
| **硬实时**（PROFINET IRT / EtherCAT / TOWERLINK 等） | 确定性来自专用硬件，软件层做不到 |
| **TSN 特性** | 配置入口在 OS / 网卡，不在应用库 |
| **PRP/HSR 零切换冗余** | 需以太网层帧复制，TCP 之上的库做不到 |
| **私有协议**（S7comm 等） | 法律与范围风险 |
| **证书签发 / PKI 生命周期** | 运维职责；只提供接入钩子 |
| **业务语义的控制操作**（启动/校准/配方） | 一旦理解业务语义就不再是数据格式无关的层 |
| **传输加密 / 认证（v1）** | v1 只面向受控局域网；跨不可信网段须外部加隧道。见 [安全边界](docs/requirements.md#41-安全边界必须显式声明) |
| **跨进程 / 集中式监控** | 监控作用域 = **本 Runtime**。管理进程要观测子进程须各自嵌入 Runtime 由应用汇总，库不提供中心守护进程。见 [非目标](docs/requirements.md#4-非目标明确不做) |
| **多通信域 / 网络级分区** | v1 是**单发现域**；需要互不可见请用 **VLAN / ACL / 独立网卡 / netns**。名字锁是机器级，**域 ≠ 安全边界** |
| **事件循环投递入口（`post` 类）** | 回调内只做异步发送 + 置标志，数据处理放 `run_once` 之后即可；v1 也不提供定时器公开入口 |
| **国产私有指令集**（LoongArch / MIPS64 / SW64） | 见 ADR-001；保持代码可移植，按合同评估 |

---

## 快速开始（设计目标，尚未实现）

```c
#include "iocomm/iocomm.h"

/* 1. 创建运行时（owned 模式：库自带 1 个 IO 线程） */
iocomm_runtime_t rt = 0;
iocomm_runtime_config cfg = ICOMM_RUNTIME_CONFIG_INIT;
cfg.node_id      = 0;                 /* 0 = 自动生成并持久化 */
cfg.node_name     = "plc-3";           /* 展示用，随发现上报 */
cfg.node_name_len = 5;
cfg.state_dir     = "/var/lib/iocomm";
cfg.state_dir_len = 15;
iocomm_error err = ICOMM_ERROR_INIT;

if (iocomm_runtime_create(&cfg, &rt, &err) != ICOMM_OK) { /* err.message */ }
iocomm_runtime_start(rt, &err);

/* 2. 创建本地端点（监听 + 具名） */
iocomm_endpoint_t ep = 0;
iocomm_endpoint_config ep_cfg = ICOMM_ENDPOINT_CONFIG_INIT;
ep_cfg.name                 = "plant3/line2/temp";
ep_cfg.name_len             = 17;            /* 名字 UTF-8 1–255 B，'/'-分层不得空段（c-abi §5.1a） */
ep_cfg.listen_transport     = "tcp";
ep_cfg.listen_transport_len = 3;
ep_cfg.listen_addr          = "0.0.0.0:0";   /* 0 = 系统分配 */
ep_cfg.listen_addr_len      = 9;
if (iocomm_endpoint_create(rt, &ep_cfg, &ep, &err) != ICOMM_OK) { /* ... */ }
/*    同进程重名 → ALREADY_EXISTS；他进程已持有同名 → CONFLICT（均不注册，不自动改名） */

/* 3. 接收入站连接（服务端角色） */
iocomm_subscription_t accept_sub = 0;
iocomm_endpoint_accept(rt, ep, on_new_connection, user_data, &accept_sub, &err);

/*    在 on_new_connection 里，连接句柄是**借用**的——只在回调期间有效。
 *    **回调在双向 HELLO 完成后才触发**（tcp/unix/pipe）：此时对端身份已知
 *    （peer_node_id 有真实值）、连接已可发 DATA，所以下面的「发一条就关」是合法的；
 *    握手失败/超时不会走到这个回调。inproc 无握手，连接建立即回调。
 *    要持有它必须三选一，否则回调返回时连接会被优雅关闭（视为拒绝）：
 *      iocomm_conn_subscribe(rt, conn, on_message, user, &sub, &err);      // 推送收（订阅即持有）
 *      iocomm_conn_retain(rt, conn, &err);                                 // 拉取收（显式持有）
 *      端点级：先前已调 iocomm_subscribe(rt, ep, ...) / endpoint_recv(rt, ep, ...)
 *              → 入站连接在**交付时**即由端点接管，回调内**无需再表态**
 *                （此模式下甚至可以不注册 endpoint_accept）
 *    「发一条就关」不是 conn_send_async + 什么都不做，而是显式带关闭标志：
 *      iocomm_send_options opt = ICOMM_SEND_OPTIONS_INIT;
 *      opt.flags = ICOMM_SEND_CLOSE_AFTER;
 *      iocomm_conn_send_async(rt, conn, &opt, msg, on_done, u, &op, &err);
 *    显式拒绝用 iocomm_conn_destroy(rt, conn, &err)。
 *    只保存句柄而不持有 = 未持有 → 连接被回收，句柄变 STALE。
 *    入站连接一旦持有，即成为本端点的**成员**，参与 endpoint_send 扇出。 */

/* 4. 连接远端（客户端角色） */
iocomm_conn_t conn = 0;
iocomm_connect(rt, 0 /* ep_owner：0 = 不归属任何端点 */,
               "tcp", 3, "10.0.1.5:5000", 13, 3000, &conn, &err);

/* 5. 发送：连接 = 点对点；端点 = 扇出。队列满策略按端点配置，不按消息分类 */
iocomm_send_options opt = ICOMM_SEND_OPTIONS_INIT;

iocomm_conn_send(rt, conn, &opt, (iocomm_slice){ payload, payload_len },
                 1000 /* ms */, &err);

/* 6. 关闭 */
iocomm_conn_destroy(rt, conn, &err);
iocomm_endpoint_destroy(rt, ep, &err);
iocomm_runtime_drain(rt, 5000 /* ms */, &err);
iocomm_runtime_destroy(rt);
```

> 与 [`docs/api/c-abi.md`](docs/api/c-abi.md) 保持一致；实现后以头文件为准。

---

## 文档

| 文档 | 内容 |
|---|---|
| [产品需求](docs/requirements.md) | 需求原文、功能拆解、验收标准、非目标 |
| [架构设计](docs/architecture.md) | 分层、模块、线程模型、可插拔点 |
| [C ABI 契约](docs/api/c-abi.md) | 类型、句柄、错误码、版本协商、回调规则、消息监控 |
| [线格式](docs/api/wire-format.md) | 帧边界、帧头、TLV 扩展区、心跳 payload、版本协商 |
| [平台支持](docs/platform-support.md) | OS × 架构矩阵、构建基线、平台差异 |
| [待核实问题](docs/open-questions.md) | 文档审计发现的断链与口径矛盾（**未经核实**，处理前先看状态列） |
| [ADR-001](docs/adr/ADR-001-language-and-platform.md) | 语言、平台、边界的决策与依据 |
| [ADR-002](docs/adr/ADR-002-message-addressing-and-ownership.md) | 路由键 / 溢出策略 / accept 所有权 / 审计通道四项决策与依据 |
| [ADR-003](docs/adr/ADR-003-endpoint-name-uniqueness.md) | 端点名唯一性：跨进程同名一律拒绝（含与 ZeroMQ / nng / mDNS / MQTT 的横向对照） |

---

## 平台

| 架构 | Linux | Windows |
|---|---|---|
| **x86_64** | ✅ glibc ≥ 2.17（RHEL 7 best-effort / 麒麟 V10+ / UOS 20+） | ✅ Server 2016+ |
| **ARM64** | ✅ glibc ≥ 2.17（麒麟 / UOS / 飞腾 / 鲲鹏） | 暂不支持 |
| LoongArch / MIPS64 / SW64 | ❌ 软排除（代码保持可移植） | — |

---

## 技术栈

| 项 | 选择 | 理由 |
|---|---|---|
| 核心语言 | **Rust** | 异步生命周期 / 并发状态机 / 缓冲所有权 / 不可信输入 —— 四条都由编译器保证 |
| 事件循环 | **mio + 自研**（不绑 tokio） | 必须支持「调用方驱动」，不能把运行时强加给宿主 |
| 对外边界 | **纯 C ABI** | 跨语言、跨编译器、跨架构的唯一稳定边界 |
| 依赖 | 尽量少，vendor 锁定 | 离线可构建 |

细节见 [ADR-001](docs/adr/ADR-001-language-and-platform.md)。

---

## 许可证

本项目按 Rust 生态惯例**双许可**：任选其一

- [MIT 许可证](LICENSE-MIT)
- [Apache License 2.0](LICENSE-APACHE)（含显式专利授权）

除非另有明确说明，任何有意提交以纳入本项目的贡献，均按上述双许可授权，不附加额外条款。
