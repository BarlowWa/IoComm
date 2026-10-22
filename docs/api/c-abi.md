# IoComm C ABI 契约

> 状态：设计阶段 ｜ 相关：[架构](architecture.md) · [需求](requirements.md)
>
> **这份头文件的规则一旦发布就不能随意更改。** 它是跨语言、跨编译器、跨架构的唯一稳定边界。

---

## 1. 总原则

| 原则 | 说明 |
|---|---|
| **只用 C 类型** | 不出现 Rust 类型、C++ 类型、STL、异常 |
| **C99 可编译** | 头文件必须能被纯 C 编译器编译（CI 守卫） |
| **不透明整数句柄** | 所有对象（Runtime / 端点 / 连接 / 订阅 / 快照 / 监控者，共六类）都是 `uint64_t`；**C ABI 中不出现任何 `void*` 型对象** |
| **定宽整数** | `int32_t` / `uint64_t`；**禁止** `long` / `size_t` / `bool` 上 ABI |
| **枚举只提供符号名** | C 枚举的底层宽度是**实现定义**的（MSVC/GCC 默认 4 字节，`-fshort-enums` 下可变），不能上 ABI。**公开结构体字段与函数出参/入参一律用定宽整数承载枚举值**（`uint8_t` / `uint32_t` / `int32_t`），枚举类型本身只用于定义常量名。0 一律保留为「默认 / 保持当前值」（见 §5.0、§6.1） |
| **版本协商** | 结构体首字段 `size` + 版本号；只允许尾部追加 |
| **无 panic 穿越** | 所有入口 `catch_unwind`，转成错误码 |
| **谁分配谁释放** | 跨边界一律走库提供的 release 函数或 allocator 回调 |
| **显式长度** | 字符串与二进制都是 `(ptr, len)`，不依赖 NUL |

---

## 2. 基础类型

```c
#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

#define ICOMM_ABI_MAJOR 1
#define ICOMM_ABI_MINOR 0

/* 所有句柄的统一编码：高 32 位代际 + 低 32 位索引。
 * 索引与代际均从 1 开始；0 是无效句柄。 */
typedef uint64_t iocomm_handle_t;

typedef iocomm_handle_t iocomm_runtime_t;     /* Runtime */
typedef iocomm_handle_t iocomm_endpoint_t;    /* 本地端点（监听 / 具名） */
typedef iocomm_handle_t iocomm_conn_t;        /* 连接（入站或出站，双向） */
typedef iocomm_handle_t iocomm_subscription_t;/* 订阅 */
typedef iocomm_handle_t iocomm_snapshot_t;    /* 发现快照 */
typedef iocomm_handle_t iocomm_monitor_t;     /* 消息监控者 */
/* 审计没有句柄：v1.1 用创建期固定的 audit_fn 回调（见 §9.5，ADR-002）。 */

/* 前向声明：§5.2 / §9 的函数签名会先用到这里定义于 §8 的类型。 */
struct iocomm_peer_status;
typedef struct iocomm_peer_status iocomm_peer_status;
struct iocomm_stats;
typedef struct iocomm_stats iocomm_stats;
struct iocomm_audit_record;
typedef struct iocomm_audit_record iocomm_audit_record;

/* 字节视图：库不拥有这块内存。 */
typedef struct iocomm_slice {
    const uint8_t* data;
    uint64_t       len;      /* u64 而非 size_t：避免 32/64 位差异 */
} iocomm_slice;

/* 版本 + 尺寸协商头。所有「调用方传给库」的公开结构体首字段必须是它。 */
typedef struct iocomm_abi_header {
    uint32_t size;              /* 生产者看到的 sizeof(该结构体) */
    uint32_t abi_major;
    uint32_t abi_minor;
    uint32_t reserved0;
    uint64_t features;          /* 我支持的能力位（可被对端忽略） */
    uint64_t features_required; /* 我要求对端必须懂的位（不满足则拒绝） */
} iocomm_abi_header;
```

> **首字段规则的例外**：`iocomm_error` 与 `iocomm_message` 是**库写、调用方读**的输出结构体，用裸 `uint32_t size` 开头即可（它们不参与版本协商，只要求调用方预置 `size`）。该例外**仅限输出方向**。

---

## 3. 错误

```c
typedef enum iocomm_error_code {
    ICOMM_OK = 0,

    /* 参数/状态 */
    ICOMM_ERR_INVALID_ARGUMENT  = 1,
    ICOMM_ERR_NOT_FOUND         = 2,
    ICOMM_ERR_ALREADY_EXISTS    = 3,
    ICOMM_ERR_CONFLICT          = 4,   /* 名字被其他进程占用 */
    ICOMM_ERR_STALE_HANDLE      = 5,
    ICOMM_ERR_WOULD_DEADLOCK    = 6,
    ICOMM_ERR_NOT_SUPPORTED     = 7,
    ICOMM_ERR_INVALID_STATE     = 8,

    /* 运行期（预期事件，不是异常） */
    ICOMM_ERR_TIMEOUT           = 10,
    ICOMM_ERR_WOULD_BLOCK       = 11,
    ICOMM_ERR_CLOSED            = 12,
    ICOMM_ERR_DISCONNECTED      = 13,
    ICOMM_ERR_CANCELLED         = 14,
    ICOMM_ERR_NO_RECEIVER       = 15,   /* 扇出时没有任何连接 */

    /* 资源 */
    ICOMM_ERR_RESOURCE_EXHAUSTED = 20,
    ICOMM_ERR_TOO_LARGE          = 21,

    /* 内部 */
    ICOMM_ERR_INTERNAL          = 100,
} iocomm_error_code;

/* 错误详情：固定缓冲，调用方无需释放。 */
typedef struct iocomm_error {
    uint32_t size;               /* 调用方必须预置为 sizeof(iocomm_error) */
    int32_t  code;               /* iocomm_error_code */
    char     message[256];       /* UTF-8，NUL 结尾 */
} iocomm_error;

#define ICOMM_ERROR_INIT { sizeof(iocomm_error), 0, {0} }

const char* iocomm_strerror(int32_t code);  /* 静态存储期，不要 free */
```

**规则**：
- **本枚举是唯一权威**；`architecture.md` 中的 Rust `ErrorCode` 是内部名，必须逐值映射到本枚举。
- **超时是正常结果**，独立码，不折进「失败」。
- 错误码**只追加**，已有值永不改变。
- 错误详情走**出参**，不使用跨模块的 thread-local。
- **函数签名里的错误码一律用 `int32_t`**（返回值与 `iocomm_error.code` 都是），不用 `iocomm_error_code`——它是策略枚举（定宽承载，见 §1）。

---

## 4. 运行时

```c
typedef enum iocomm_driver_mode {
    ICOMM_DRIVER_OWNED  = 0,   /* 库自带 1 个 IO 线程 */
    ICOMM_DRIVER_MANUAL = 1,   /* 调用方驱动 */
} iocomm_driver_mode;

/* 审计 sink：创建期设定、运行期不可改（见 §9.5）。 */
typedef void (*iocomm_audit_fn)(void* user, const iocomm_audit_record* rec);

typedef struct iocomm_runtime_config {
    iocomm_abi_header hdr;

    uint8_t  driver_mode;          /* ICOMM_DRIVER_* */
    uint8_t  reserved8[7];

    /* 节点身份：0 = 自动（在 state_dir 下持久化） */
    uint64_t node_id;
    const char* state_dir;         /* 自动生成 node_id 的落盘目录；可 NULL */
    uint64_t    state_dir_len;

    /* 节点名：展示用，随发现上报（FR-9.4）。NULL 或 len=0 = 不设名，
     * 对端看到空串。**创建期不可变**（改名字请重建 Runtime）。 */
    const char* node_name;
    uint64_t    node_name_len;

    /* 默认队列与溢出策略；端点级覆盖见 endpoint_config */
    uint32_t send_queue_max;       /* 0 = 默认 */
    uint32_t recv_queue_max;       /* 0 = 默认 */
    uint32_t max_message_size;     /* 0 = 默认（1 MiB） */
    uint32_t max_handles;          /* 句柄上限 */

    /* ICOMM_OVERFLOW_*；0 = DROP_OLDEST（见 §6.1） */
    uint8_t  default_overflow_policy;
    uint8_t  reserved1[7];

    /* 监控的全局预分配预算（字节），0 = 默认 64 MiB */
    uint64_t monitor_budget_bytes;

    /* 日志回调（可选）；audit_fn 为 NULL 时审计事件回退到此处的 AUDIT 类别 */
    void (*log_fn)(void* user, int32_t level, const char* msg, uint64_t len);
    void* log_user;

    /* 审计 sink（可选；v1.1）。见 §9.5 */
    iocomm_audit_fn audit_fn;
    void* audit_user;
} iocomm_runtime_config;

/* C99 分部初始化：未列出的成员自动置零。 */
#define ICOMM_RUNTIME_CONFIG_INIT \
  { { sizeof(iocomm_runtime_config), ICOMM_ABI_MAJOR, ICOMM_ABI_MINOR, 0, 0, 0 } }

int32_t iocomm_runtime_create(const iocomm_runtime_config* cfg,
                              iocomm_runtime_t* out_rt,
                              iocomm_error* err);

/* ── 控制面 ── */

int32_t iocomm_runtime_start(iocomm_runtime_t rt, iocomm_error* err);
int32_t iocomm_runtime_stop (iocomm_runtime_t rt, uint64_t timeout_ms, iocomm_error* err);

/* 优雅关闭：owned 模式返回时保证已排空；
 * manual 模式返回 ICOMM_ERR_WOULD_BLOCK 表示仍有在途操作，
 * 调用方应继续 run_once 直到返回 ICOMM_OK。 */
int32_t iocomm_runtime_drain(iocomm_runtime_t rt, uint64_t timeout_ms, iocomm_error* err);

/* 热重配置：只接受**通信参数**，不接受业务参数。
 * 入参为 iocomm_tune_config；创建期参数（driver_mode / node_id / state_dir /
 * node_name / log_fn / audit_fn / max_handles / monitor_budget_bytes）不可热更新。
 * 字段优先级与作用域见 §5.0「配置优先级」。 */
typedef struct iocomm_tune_config {
    iocomm_abi_header hdr;

    /* 0 = 保持当前值；非 0 才生效 */
    uint32_t send_queue_max;
    uint32_t recv_queue_max;
    uint32_t max_message_size;

    uint64_t heartbeat_ms;         /* 0 = 保持当前 */
    uint64_t heartbeat_miss_limit; /* 连续丢 N 次判死；0 = 保持 */

    uint32_t iface_index;          /* 0 = 保持；否则改为指定网卡 */
    uint8_t  overflow_policy;      /* ICOMM_OVERFLOW_*；0 = 保持；作用于全部端点 */
    uint8_t  reserved8[3];

    /* 发现侧参数（0/NULL = 保持） */
    uint64_t discovery_heartbeat_ms;
    uint64_t discovery_lease_ms;
} iocomm_tune_config;

#define ICOMM_TUNE_CONFIG_INIT \
  { { sizeof(iocomm_tune_config), ICOMM_ABI_MAJOR, ICOMM_ABI_MINOR, 0, 0, 0 } }

int32_t iocomm_runtime_reconfigure(iocomm_runtime_t rt,
                                   const iocomm_tune_config* cfg,
                                   iocomm_error* err);

void    iocomm_runtime_destroy(iocomm_runtime_t rt);  /* 强制关闭，取消在途 */

/* ── 事件循环（manual 模式） ── */

int32_t iocomm_runtime_run_once(iocomm_runtime_t rt, uint64_t timeout_ms, iocomm_error* err);
int32_t iocomm_runtime_run_for (iocomm_runtime_t rt, uint64_t duration_ms, iocomm_error* err);
int32_t iocomm_runtime_wakeup  (iocomm_runtime_t rt);   /* 任意线程可调用 */

/* ── 本机身份（FR-9.4） ── */

/* 返回本机实际使用的 node_id（自动模式下在 create/start 后才有值）。
 * 任意线程可调用，返回拷贝。AC-9 用它观测「重启后不变」。 */
int32_t iocomm_runtime_node_id(iocomm_runtime_t rt, uint64_t* out_node_id,
                               iocomm_error* err);

/* 取回本机节点名（来自 runtime_config.node_name）。buf 不足时返回
 * ICOMM_ERR_RESOURCE_EXHAUSTED，并由 out_len 给出所需长度（不含 NUL）；
 * 未配置名字时 out_len = 0。 */
int32_t iocomm_runtime_node_name(iocomm_runtime_t rt, char* buf, uint64_t buf_len,
                                 uint64_t* out_len, iocomm_error* err);

/* ── 版本 ── */

const char* iocomm_version_string(void);
const iocomm_abi_header* iocomm_abi_version(void);
```

> **manual 模式的硬约束**：手动模式下只有一个线程在驱动 loop。在该线程上调用同步 API 会返回 `ICOMM_ERR_WOULD_DEADLOCK`（见 §6）。`runtime_drain` 在 manual 模式下不做阻塞排空。

---

## 5. 端点与句柄

### 5.0 配置优先级（**唯一的权威定义**）

同一个通信参数出现在多个结构体里时，按以下优先级**后者覆盖前者**：

| 参数 | 创建期（runtime_config） | 端点级（endpoint_config） | 运行期热更新（tune_config） | 作用域 |
|---|---|---|---|---|
| `send_queue_max` / `recv_queue_max` | ✅ 默认值 | ✅ `queue_limit` 覆盖 | ✅ 覆盖全部端点 | runtime → 端点 → 热更新 |
| `overflow_policy` | ✅ `default_overflow_policy` | ✅ `overflow_policy` 覆盖 | ✅ 覆盖全部端点 | runtime → 端点 → 热更新 |
| `max_message_size` | ✅ 默认值 | — | ✅ | runtime → 热更新 |
| `max_handles` | ✅ 仅创建期 | — | ❌ | 不可热更新 |
| `heartbeat_ms` / `heartbeat_miss_limit` | — | — | ✅ 仅运行期 | 热更新 |
| `iface_index` | — | ✅ 作用：**端点监听 + 该端点的发送/组播** | ✅ 作用：**全部端点 + 发现** | 见下 |
| `discovery_heartbeat_ms` / `discovery_lease_ms` | — | — | ✅ | 热更新（**发现配置的单一权威**） |

**规则**：
1. `tune_config` 的 `iface_index` 作用于**全部端点与发现**；`endpoint_config.iface_index` 与 `discovery_config.iface_index` 只作用于各自对象。**若同时设置，以更具体的那个为准**（端点 > 全局）。
2. **发现的心跳/租约只有一处权威**：`iocomm_discovery_start` 时用 `discovery_config.heartbeat_ms/lease_ms` 初始化；之后的 `tune_config.discovery_heartbeat_ms/lease_ms` 覆盖它。`discovery_config` 的这两个字段**不参与版本协商**以外的任何逻辑。
3. `tune_config` 中值为 0 表示「保持当前值」；**没有「恢复默认」的语义**（要恢复请重建 Runtime）。
4. `runtime_config` 中 `driver_mode` / `node_id` / `state_dir` / `node_name` / `log_fn` / `audit_fn` / `max_handles` / `monitor_budget_bytes` 是**创建期参数**，传给 `iocomm_runtime_reconfigure` 不适用（它只收 `iocomm_tune_config`）。

### 5.1 本地端点

```c
typedef struct iocomm_endpoint_config {
    iocomm_abi_header hdr;

    const char* name;            /* 端点名（可带 '/' 分层），UTF-8 */
    uint64_t    name_len;

    /* 监听地址：NULL = 不监听（仅用于连接远端） */
    const char* listen_transport;  /* "tcp" / "unix" / "pipe" / "inproc"（v1）；"udp" 为 v1.1 */
    uint64_t    listen_transport_len;
    const char* listen_addr;       /* "0.0.0.0:0" / "/run/x.sock" / "\\\\.\\pipe\\x" / inproc 名 */
    uint64_t    listen_addr_len;

    uint32_t flags;              /* ICOMM_ENDPOINT_* */
    uint32_t queue_limit;        /* 0 = 默认 */

    uint32_t iface_index;        /* 0 = 自动；否则只在该网卡监听/发送 */
    uint8_t  overflow_policy;    /* ICOMM_OVERFLOW_*；0 = 用 runtime 默认 */
    uint8_t  publish_local;      /* 1 = 同时发布到本机注册表（FR-2.6） */
    uint8_t  reserved8[2];
} iocomm_endpoint_config;

#define ICOMM_ENDPOINT_CONFIG_INIT \
  { { sizeof(iocomm_endpoint_config), ICOMM_ABI_MAJOR, ICOMM_ABI_MINOR, 0, 0, 0 } }

#define ICOMM_ENDPOINT_UNIQUE  0x0001u  /* 单实例排他 */
#define ICOMM_ENDPOINT_LOCAL   0x0002u  /* 仅本机可见 */
/* （原 ICOMM_ENDPOINT_SECRET 已移除：监控改为独立的 iocomm_monitor_*，见 §9） */

int32_t iocomm_endpoint_create(iocomm_runtime_t rt,
                               const iocomm_endpoint_config* cfg,
                               iocomm_endpoint_t* out_ep,
                               iocomm_error* err);

int32_t iocomm_endpoint_destroy(iocomm_runtime_t rt, iocomm_endpoint_t ep,
                                iocomm_error* err);

/* 按名字查询本地端点 */
int32_t iocomm_endpoint_lookup(iocomm_runtime_t rt,
                               const char* name, uint64_t name_len,
                               iocomm_endpoint_t* out_ep, iocomm_error* err);

/* 枚举本地端点 */
uint32_t iocomm_endpoint_count(iocomm_runtime_t rt);
int32_t  iocomm_endpoint_get  (iocomm_runtime_t rt, uint32_t index,
                               iocomm_endpoint_t* out_ep, iocomm_error* err);

/* 唯一性三态（FR-1.5）：区分「空闲 / 本进程持有 / 他进程持有」 */
typedef enum iocomm_name_state {
    ICOMM_NAME_FREE           = 0,
    ICOMM_NAME_HELD_BY_SELF   = 1,
    ICOMM_NAME_HELD_BY_OTHER  = 2,
} iocomm_name_state;

/* 返回值为 iocomm_name_state；用 int32_t 承载（见 §1），负数 = 错误码 */
int32_t iocomm_endpoint_name_state(iocomm_runtime_t rt,
                                   const char* name, uint64_t name_len,
                                   iocomm_error* err);

/* 查询本端点实际监听的地址（端口 0 时用于取回系统分配的端口）。
 * inproc 端点返回它的进程内名字。 */
int32_t iocomm_endpoint_local_addr(iocomm_runtime_t rt, iocomm_endpoint_t ep,
                                   char* buf, uint64_t buf_len,
                                   uint64_t* out_len, iocomm_error* err);
```

### 5.1b inproc 传输（进程内）

`"inproc"` 连接**同一进程内的 Runtime**（也允许同一 Runtime 连自己的端点），不走 socket / 管道。

| 维度 | 契约 |
|---|---|
| `listen_addr` | 进程内唯一的任意 UTF-8 名字，≤ 255 B，**必填**。与端点名是**两套独立命名空间** |
| 冲突 | 同进程内重名 → `ALREADY_EXISTS`；**跨进程天然隔离**（两个进程可用同一名字而互不相通） |
| 投递 | 经接收方 loop 的跨线程任务队列；**绝不在 `send` 调用栈内同步回调** |
| 与 tcp 一致 | 帧结构（消息边界、`sequence`、`original_len`）、**出站大小校验**（`TOO_LARGE`）、端点队列与溢出策略、监控打点 |
| 有意不同 | ① 没有网络地址，`endpoint_local_addr` 返回名字；② **不参与发现**：`publish_local = 1` 时 `endpoint_create` 返回 `INVALID_ARGUMENT`（不做静默空操作） |
| 分配 | 编解码后的缓冲**可以移动代替拷贝**交给接收方（零拷贝的主要收益） |

> **大小校验为什么不在 inproc 上放宽**：nng 在 inproc 上忽略 `NNG_OPT_RECVMAXSZ`（理由是同地址空间「implicitly trusted」）。
> 本库**有意不同**——保留校验的理由不是安全，而是 ① 有界队列（FR-4.6）要求队列占用有上界，否则「有界」只在部分传输上成立；
> ② 同一 payload 在 tcp / inproc 上行为一致。代价只是每消息一次比较。
> **出站强制；入站超限分支保留同一代码路径**（在 inproc 上不可达），不为 inproc 单独增加分叉。

### 5.2 连接（入站与出站）

**连接与端点分离**：`iocomm_endpoint_t` 是本地具名端点（监听者）；`iocomm_conn_t` 是一条**双向连接**，可能来自 `accept`（入站）或 `connect`（出站）。两者是**独立的句柄空间**。

```c
/* 入站连接回调。在 loop 线程上调用。
 *
 * **inbound 是借用句柄，只在本次回调期间有效**（借用语义，见 ADR-002）：
 *   - 什么都不做              → 回调返回时库自动收回并以 FIN 优雅关闭（= 拒绝）
 *   - iocomm_conn_subscribe   → **隐式持有**（订阅即所有权），连接保持打开
 *   - iocomm_conn_retain      → 唯一显式持有，用于拉取模式（之后可在别的线程 conn_recv）
 *   - iocomm_conn_send_async  → **仅在 send_options.flags 含 ICOMM_SEND_CLOSE_AFTER 时合法**：
 *                               数据 flush 后优雅关闭，on_done 之后句柄失效；
 *                               未设 CLOSE_AFTER 且未 subscribe/retain → ICOMM_ERR_INVALID_STATE
 *   - iocomm_conn_destroy     → 立即关闭（= 显式拒绝），重复调用返回 STALE_HANDLE
 *
 * 「什么都不做」与「保存句柄」都会导致回调返回后回收——库无法观测外部变量。
 * 同步 iocomm_conn_send 在回调内会返回 WOULD_DEADLOCK，需在别的线程调用。 */
typedef struct iocomm_peer_info {
    uint32_t size;                 /* 库填写实际 sizeof；调用方读取 */
    uint32_t reserved0;
    uint64_t peer_node_id;         /* 0 = 未知 */
    iocomm_slice address;          /* 对端地址文本，回调期间有效 */
} iocomm_peer_info;

typedef void (*iocomm_accept_fn)(void* user, iocomm_endpoint_t local_ep,
                                 iocomm_conn_t inbound,
                                 const iocomm_peer_info* peer);

int32_t iocomm_endpoint_accept(iocomm_runtime_t rt, iocomm_endpoint_t ep,
                               iocomm_accept_fn fn, void* user,
                               iocomm_subscription_t* out_sub,
                               iocomm_error* err);

/* 出站连接（同步）：阻塞调用者线程；loop 线程上返回 WOULD_DEADLOCK。
 * ep_owner 指定该连接归属哪个本地端点（用于 endpoint_send 扇出与
 * iocomm_conn_count 过滤）；传 0 表示不属于任何端点（只能点对点使用）。 */
int32_t iocomm_connect(iocomm_runtime_t rt, iocomm_endpoint_t ep_owner,
                       const char* transport, uint64_t transport_len,
                       const char* addr, uint64_t addr_len,
                       uint64_t connect_timeout_ms,
                       iocomm_conn_t* out_conn, iocomm_error* err);

/* 出站连接（异步）：**manual 模式的唯一建连路径**。
 * 立即返回；连接建立、失败、超时、或 Runtime stop/destroy 时，
 * on_done **恰好触发一次**（销毁路径下 code = ICOMM_ERR_CANCELLED）。
 * 成功时 out_conn 有效；其余情况为 0，库内已回收所有资源。 */
int32_t iocomm_connect_async(iocomm_runtime_t rt, iocomm_endpoint_t ep_owner,
                             const char* transport, uint64_t transport_len,
                             const char* addr, uint64_t addr_len,
                             uint64_t connect_timeout_ms,
                             void (*on_done)(void* user, int32_t code,
                                             iocomm_conn_t conn),
                             void* user,
                             iocomm_error* err);

/* 通过发现信息连接（同步 / 异步），语义同上。 */
int32_t iocomm_connect_node(iocomm_runtime_t rt, iocomm_endpoint_t ep_owner,
                            uint64_t node_id,
                            const char* endpoint_name, uint64_t name_len,
                            uint64_t connect_timeout_ms,
                            iocomm_conn_t* out_conn, iocomm_error* err);

int32_t iocomm_connect_node_async(iocomm_runtime_t rt,
                                  iocomm_endpoint_t ep_owner,
                                  uint64_t node_id,
                                  const char* endpoint_name, uint64_t name_len,
                                  uint64_t connect_timeout_ms,
                                  void (*on_done)(void* user, int32_t code,
                                                  iocomm_conn_t conn),
                                  void* user, iocomm_error* err);

/* 接管一条连接但**不安排任何收发**（拉取模式）。
 * 这是**唯一**的显式持有动作（subscribe 是推送侧的等价持有）：
 * 在 accept 回调内调用后，该连接不再被自动回收，调用方可在其他线程
 * 对它调用 iocomm_conn_recv。**幂等**：对同一连接重复调用返回 ICOMM_OK，
 * 连接只有一个「C 侧所有权」。持有不与订阅冲突——但订阅与 recv 的
 * 二选一规则（§6.4）照常适用。 */
int32_t iocomm_conn_retain(iocomm_runtime_t rt, iocomm_conn_t conn,
                           iocomm_error* err);

/* 立即关闭一条连接（入站或出站均可）。
 * **在途异步发送一律取消**：每条未完成的 send_async 仍恰好触发一次
 * on_done(code = ICOMM_ERR_CANCELLED)（与 AC-27 的 Runtime 销毁路径一致）。
 * 发送缓冲中尚未交给传输层的数据直接丢弃；随后以 FIN 关闭。
 * 不阻塞、任意线程可调用。重复调用返回 STALE_HANDLE。
 * 「先把缓冲 flush 出去再关」用 conn_close_graceful；
 * 「发完这一条就关」用 ICOMM_SEND_CLOSE_AFTER；
 * 「异常中止」用 conn_abort。 */
int32_t iocomm_conn_destroy(iocomm_runtime_t rt, iocomm_conn_t conn,
                            iocomm_error* err);

/* 优雅关闭：先把发送队列里的数据 flush 给传输层，再以 FIN 关闭；
 * 最多等待 linger_ms。**在 loop 线程/回调内调用返回 WOULD_DEADLOCK**。
 * 返回时句柄失效；在途异步发送的 on_done 按实际结果或 CANCELLED 报告。 */
int32_t iocomm_conn_close_graceful(iocomm_runtime_t rt, iocomm_conn_t conn,
                                   uint64_t linger_ms, iocomm_error* err);

/* 立即断开（RST）：取消在途发送、丢弃全部缓冲、不等 FIN 握手。
 * **异常中止专用**（例如协议层已无法恢复）；正常拒绝入站连接请用
 * conn_destroy（同是立即取消，但以 FIN 关闭），避免对端把 RST 误判为网络故障。 */
int32_t iocomm_conn_abort(iocomm_runtime_t rt, iocomm_conn_t conn,
                          iocomm_error* err);

/* 连接状态（条件集） */
int32_t iocomm_conn_status(iocomm_runtime_t rt, iocomm_conn_t conn,
                           iocomm_peer_status* out, iocomm_error* err);

/* 枚举当前存活连接（可选：按端点过滤，ep=0 表示全部） */
uint32_t iocomm_conn_count(iocomm_runtime_t rt, iocomm_endpoint_t ep,
                           iocomm_error* err);  /* 出错返回 0 并置 err */
int32_t  iocomm_conn_get  (iocomm_runtime_t rt, iocomm_endpoint_t ep,
                           uint32_t index, iocomm_conn_t* out_conn,
                           iocomm_error* err);
```

**发送目标的语义**（消除歧义）：

| 目标 | 语义 |
|---|---|
| `iocomm_conn_t` | **点对点**，发给这一条连接 |
| `iocomm_endpoint_t`（本地监听端点） | **扇出**：发给该端点当前所有已建立的连接；没有连接时返回 `NO_RECEIVER` |

> **入站连接的所有权：借用语义**（完整理由见 [ADR-002](../adr/ADR-002-message-addressing-and-ownership.md)）。
> `accept` 回调拿到的 `inbound` **只在回调期间有效**；回调返回时若库没有观测到任何持有动作，
> 连接被自动收回并以 FIN 优雅关闭。持有动作只有两种：**显式 `conn_retain`** 与 **隐式
> `conn_subscribe`**。`conn_send_async` 不是所有权开关——「发一条拒绝就走」用
> `send_options.flags = ICOMM_SEND_CLOSE_AFTER` 表达；不带 `CLOSE_AFTER` 的 `send_async`
> 若同时未持有，返回 `INVALID_STATE`，强制在回调内表态。
> **仅保存句柄不算持有**（库无法观测外部变量），该连接会被回收并返回 `STALE_HANDLE`。

> **manual 模式的建连路径**：`iocomm_connect_async` / `iocomm_connect_node_async`。同步版本在 loop 驱动线程上一律返回 `WOULD_DEADLOCK`。
> **`endpoint` 与 `conn` 是两个独立句柄空间**，不能互相替代。

---

## 6. 发送与接收

### 6.1 溢出策略（每端点一个队列）

```c
/* 一个端点 = 一条发送队列 + 一条接收队列 + 一个策略（ADR-002）。
 * 「过程数据 / 报警 / 命令」需要不同策略时，用**三个端点**表达。
 * 枚举从 1 开始：0 表示「用默认 / 保持当前值」，zero-init 不会静默变成 BLOCK。
 * 值在 ABI 上由 uint8_t 承载（见 §1），枚举本身只提供符号名。 */
typedef enum iocomm_overflow_policy {
    ICOMM_OVERFLOW_BLOCK       = 1,  /* 同步发送真阻塞至 timeout_ms；异步/接收路径退化为 ERROR 策略（返回/回调 WOULD_BLOCK） */
    ICOMM_OVERFLOW_DROP_OLDEST = 2,  /* 丢最旧（keep-latest，过程数据常用） */
    ICOMM_OVERFLOW_DROP_NEWEST = 3,  /* 丢最新 */
    ICOMM_OVERFLOW_ERROR       = 4,  /* 报错 / 丢弃并计数（命令、报警常用） */
} iocomm_overflow_policy;

/* 运行期设置某端点的策略（等价于 endpoint_config.overflow_policy，
 * 用于创建后调整）。0 = 恢复为 runtime 默认。 */
int32_t iocomm_endpoint_set_overflow(iocomm_runtime_t rt, iocomm_endpoint_t ep,
                                     uint8_t policy, iocomm_error* err);
```

> **`BLOCK` 只在同步发送的调用者线程上真阻塞**（最多到发送的 `timeout_ms`，超时返回 `ICOMM_ERR_TIMEOUT`，见下方 §6.2b）。
> 在**异步发送**与**接收侧入队**上，`BLOCK` 一律自动退化为 `ERROR`：本库的异步卖点是「立即返回」，
> 在调用方线程阻塞等于把异步用成同步；接收侧入队发生在 loop 线程，真阻塞会让唯一的事件循环自锁。
> 这是**运行时保护**，不是配置错误。
>
> **`ERROR` 的返回码与计数**：入队失败返回 `ICOMM_ERR_WOULD_BLOCK`；每次丢弃/拒绝都计入 `iocomm_stats.queue_dropped`。
> 同步发送直接返回该码；异步发送通过 `on_done(code = ICOMM_ERR_WOULD_BLOCK)` 报告。
>
> **接收侧**共用同一端点的策略；`BLOCK` 永不生效，`ERROR` 的语义固定为「丢弃 + 计数 + 产生
> `DROPPED(reason = QUEUE_FULL)`」，**不关闭连接**（接收侧没有可返回失败的调用方）。
>
> **扇出的部分失败**：`iocomm_endpoint_send` 若只有部分连接入队成功，**返回 `ICOMM_OK`**，
> 由 `out_delivered < N` 表达部分成功；若全部失败则返回 `ICOMM_ERR_WOULD_BLOCK`。
> 异步 `endpoint_send_async` 同样以 `on_done(ICOMM_OK)` + 计数表达部分失败。

### 6.2 发送

```c
typedef struct iocomm_send_options {
    iocomm_abi_header hdr;
    uint8_t  flags;              /* ICOMM_SEND_* */
    uint8_t  reserved8[7];
    uint64_t correlation_id;     /* 可选，0 = 无 */
    /* 排队超时（**仅异步发送**）：从入队成功到开始写传输层的上限。
     * 0 = 无截止（默认）。开始写之后不再受此超时约束——
     * 字节流中途截断只能 RST 掉整条连接，那属于 conn_abort 的职责。
     * 超时 → 消息出队 → on_done(ICOMM_ERR_TIMEOUT) + DROPPED(TIMEOUT)。
     * 同步发送的截止时间由函数参数 timeout_ms 给出，本字段被忽略。 */
    uint64_t queue_timeout_ms;
} iocomm_send_options;

#define ICOMM_SEND_OPTIONS_INIT \
    { { sizeof(iocomm_send_options), ICOMM_ABI_MAJOR, ICOMM_ABI_MINOR, 0, 0, 0 }, \
      0, {0}, 0, 0 }

/* 全部数据交给传输层后以 FIN 优雅关闭连接。
 * 只对 conn_send / conn_send_async 有效：扇出（endpoint_send*）返回 INVALID_ARGUMENT。
 * 与 conn_retain 冲突时**关闭优先**：数据 flush 后连接即关闭，持有者随后拿到 STALE_HANDLE。
 * 关闭发生在 on_done 之后——on_done 报告的是「数据已交给传输层」，不等待对端确认。 */
#define ICOMM_SEND_CLOSE_AFTER 0x01u

/* 异步发送到一条连接（点对点）。
 * payload 在调用返回时立即拷贝入队，调用方可在返回后释放。
 * **完成点**：on_done(OK) 表示该消息**已完整交给传输层**（OS 已接受），
 * 不表示对端已收到。同步发送的成功返回是同一含义（FR-6.1）。 */
int32_t iocomm_conn_send_async(iocomm_runtime_t rt, iocomm_conn_t conn,
                               const iocomm_send_options* opt,
                               iocomm_slice payload,
                               void (*on_done)(void* user, int32_t code,
                                               uint64_t op_id),
                               void* user, uint64_t* out_op_id,
                               iocomm_error* err);

/* 异步扇出到一个本地端点当前的所有连接。无连接时以 NO_RECEIVER 回调。 */
int32_t iocomm_endpoint_send_async(iocomm_runtime_t rt, iocomm_endpoint_t ep,
                                   const iocomm_send_options* opt,
                                   iocomm_slice payload,
                                   void (*on_done)(void* user, int32_t code,
                                                   uint64_t op_id),
                                   void* user, uint64_t* out_op_id,
                                   iocomm_error* err);

/* 取消一个未完成的异步发送。on_done 仍会被调用一次，code = CANCELLED。 */
int32_t iocomm_send_cancel(iocomm_runtime_t rt, uint64_t op_id,
                           iocomm_error* err);

/* 同步发送（点对点）：阻塞调用者线程；loop 线程上返回 WOULD_DEADLOCK。 */
int32_t iocomm_conn_send(iocomm_runtime_t rt, iocomm_conn_t conn,
                         const iocomm_send_options* opt,
                         iocomm_slice payload,
                         uint64_t timeout_ms,   /* 0 = 只尝试一次 */
                         iocomm_error* err);

/* 同步扇出。out_delivered = **已完整交给传输层**的连接数（不等于对端已收到）；
 * N=0 时返回 ICOMM_ERR_NO_RECEIVER。 */
int32_t iocomm_endpoint_send(iocomm_runtime_t rt, iocomm_endpoint_t ep,
                             const iocomm_send_options* opt,
                             iocomm_slice payload,
                             uint64_t timeout_ms,
                             uint32_t* out_delivered, iocomm_error* err);
```

### 6.2b 超时口径（同步 / 异步）

| 路径 | 计时起点 | 计时终点 | 超时结果 |
|---|---|---|---|
| **同步**（`conn_send` / `endpoint_send`） | 调用进入 | 数据**完整交给传输层**（或返回） | 返回 `ICOMM_ERR_TIMEOUT` |
| **异步**（`*_send_async`） | 入队成功 | **开始写**传输层 | `DROPPED(TIMEOUT)` + `on_done(ICOMM_ERR_TIMEOUT)` |

- `opt->queue_timeout_ms` **只对异步生效**；同步的截止时间只由参数 `timeout_ms` 给出（`0` = 只尝试一次）。
- **开始写之后不再超时**：帧已部分写入字节流，中途放弃只能 RST 整条连接，那属于 `conn_abort`；发送路径不做隐式 abort。
- **两个 `timeout_ms` 不同名**：同步参数 `timeout_ms = 0` 是「只尝试一次」，异步字段 0 是「无截止」。所以字段叫 `queue_timeout_ms`，不叫 `timeout_ms`。
- `on_done(OK)` 的完成点与同步成功返回**相同**——都是「已交给传输层」，不是「对端已收到」。

### 6.3 接收

```c
typedef struct iocomm_message {
    uint32_t size;               /* 库填写实际 sizeof；调用方读取 */
    uint32_t reserved0;

    iocomm_slice payload;        /* 仅在回调期间 / 下一次 recv 前有效 */

    iocomm_conn_t from;          /* **来源连接**（可用来回复） */
    uint64_t source_node;        /* 来源 NodeId */
    uint64_t sequence;           /* per-source 单调序号 */
    uint64_t timestamp_ns;       /* 发送方事件时间 */
    uint64_t correlation_id;     /* 0 = 无 */

    uint8_t  clock_synced;       /* 时间戳所在时钟是否已同步 */
    uint8_t  reserved1[7];
} iocomm_message;

#define ICOMM_MESSAGE_INIT { sizeof(iocomm_message), 0, {NULL,0}, \
                             0, 0, 0, 0, 0, 0, {0} }

/* 订阅推送。ep 是**本地监听端点**，接收其所有入站连接的消息。 */
typedef void (*iocomm_message_fn)(void* user, iocomm_endpoint_t ep,
                                  const iocomm_message* msg);

int32_t iocomm_subscribe(iocomm_runtime_t rt, iocomm_endpoint_t ep,
                         iocomm_message_fn fn, void* user,
                         iocomm_subscription_t* out_sub, iocomm_error* err);

/* 订阅**单条连接**的入站数据（入站或出站均可；双向通信）。 */
int32_t iocomm_conn_subscribe(iocomm_runtime_t rt, iocomm_conn_t conn,
                              iocomm_message_fn fn, void* user,
                              iocomm_subscription_t* out_sub,
                              iocomm_error* err);

/* 取消订阅：带超时（FR-6.3）。**返回时该订阅的回调不再执行（join 语义）**。
 * loop 线程上调用返回 WOULD_DEADLOCK。 */
int32_t iocomm_unsubscribe(iocomm_runtime_t rt, iocomm_subscription_t sub,
                           uint64_t timeout_ms, iocomm_error* err);

/* 拉取式接收（与 subscribe 二选一，见 §6.4）。 */
int32_t iocomm_endpoint_recv(iocomm_runtime_t rt, iocomm_endpoint_t ep,
                             iocomm_message* out, uint64_t timeout_ms,
                             iocomm_error* err);
int32_t iocomm_conn_recv(iocomm_runtime_t rt, iocomm_conn_t conn,
                         iocomm_message* out, uint64_t timeout_ms,
                         iocomm_error* err);

/* 释放 recv 返回的消息。可重复调用（幂等）。 */
void iocomm_message_release(iocomm_message* msg);
```

### 6.4 拉取与推送的互斥规则

同一个接收对象（端点或连接）上，`subscribe` 与 `recv` **二选一**：

| 情形 | 行为 |
|---|---|
| 先 `subscribe` 再 `recv` | `recv` 返回 `ICOMM_ERR_INVALID_STATE` |
| 先 `recv` 再 `subscribe` | `subscribe` 返回 `ICOMM_ERR_INVALID_STATE` |
| 两者都未设置 | 消息进入**端点/连接的接收队列**，直到队列满后按溢出策略处理 |

> 这条规则消除了「谁消费、是否双投、背压如何合并」的歧义。若确实需要两种消费方式，请使用**两个不同的端点/连接**。

**回调规则（**对所有回调类型**通用，必须写进头文件注释）**：

适用于：`iocomm_message_fn`、`iocomm_accept_fn`、`iocomm_condition_fn`、`iocomm_discovery_fn`、`iocomm_connect_async.on_done`、`iocomm_conn_send_async.on_done`、`iocomm_endpoint_send_async.on_done`。

```
@thread  在 Runtime 的事件循环线程上调用（不是调用方线程）。
         每次回调前 Runtime 会记录当前线程为 loop 线程，供同步入口检测。
@lifetime 回调参数中的指针/切片只在本次回调期间有效
         （例外：明确标注「静态存储期」的字符串可长期缓存）。
@forbid  回调内禁止：阻塞、销毁 Runtime/端点、销毁**非本回调交付的**连接/订阅
         （违反返回 ICOMM_ERR_WOULD_DEADLOCK，而不是死锁）
@except  `iocomm_accept_fn` 的 inbound 句柄**可以**在回调内 conn_destroy
         （用于拒绝入站连接），不返回 WOULD_DEADLOCK
@allow   回调内允许：读取快照、发起异步操作、创建新的端点/连接
@on_destroy
         Runtime 销毁时，所有尚未触发的异步回调**恰好以 CANCELLED 触发一次**。
         已在执行中的回调会先跑完，再销毁。
```

> **`on_done` 的触发语义**（`send_async` / `connect_async`）：**恰好一次**——成功、失败、超时、取消、Runtime 销毁，五种路径都算。

> **「谁负责报告」的分界**（`send_async`）：同步返回值只报告**不可能再回调**的错误——句柄无效 / 参数非法 / 在 accept 回调内未表态 / 端点未监听等。
> 一旦操作已登记（返回 `ICOMM_OK`），**后续一切结果都走 `on_done`**：`OK` / `ICOMM_ERR_TOO_LARGE` / `WOULD_BLOCK` / `TIMEOUT` / `CANCELLED` / `DISCONNECTED`。
> 因此 **`on_done` 恰好一次**只对「登记成功」成立；同步返回非 `OK` 时 `on_done` **不会**被调用。

---

## 7. 发现
```c
typedef struct iocomm_discovery_config {
    iocomm_abi_header hdr;

    uint8_t  enable_multicast;     /* 默认 1 */
    uint8_t  reserved8[3];
    uint32_t iface_index;          /* 0 = 自动；否则只在该网卡上收发组播 */
    uint32_t reserved0;

    uint64_t heartbeat_ms;
    uint64_t lease_ms;             /* 超时即判定离线 */

    /* 单播 seed 列表（组播不可用/跨网段兜底） */
    const char* const* seeds;
    const uint64_t*    seed_lens;
    uint32_t           seed_count;
} iocomm_discovery_config;

#define ICOMM_DISCOVERY_CONFIG_INIT \
  { { sizeof(iocomm_discovery_config), ICOMM_ABI_MAJOR, ICOMM_ABI_MINOR, 0, 0, 0 } }

/* 阶段二：节点上报的端点能力 */
typedef struct iocomm_endpoint_info {
    const char* name;          /* 端点名，**静态存储期**，可长期缓存 */
    uint64_t    name_len;
    const char* transport;     /* **静态存储期** */
    uint64_t    transport_len;
    const char* addr;          /* **静态存储期** */
    uint64_t    addr_len;
} iocomm_endpoint_info;

typedef struct iocomm_node_info {
    uint64_t node_id;
    const char* name;              /* 对端的 runtime_config.node_name；未配置时为空串 */
    uint64_t    name_len;          /* 均为 **静态存储期** */
    uint32_t endpoint_count;
    const iocomm_endpoint_info* endpoints;  /* 数组，指针有效至下次快照失效 */
} iocomm_node_info;

typedef enum iocomm_discovery_event_kind {
    ICOMM_DISCOVERY_JOINED  = 0,
    ICOMM_DISCOVERY_LEFT    = 1,
    ICOMM_DISCOVERY_UPDATED = 2,
} iocomm_discovery_event_kind;

typedef struct iocomm_discovery_event {
    uint32_t kind;                 /* iocomm_discovery_event_kind */
    uint32_t reserved0;
    iocomm_node_info node;
} iocomm_discovery_event;

typedef void (*iocomm_discovery_fn)(void* user, const iocomm_discovery_event* ev);

int32_t iocomm_discovery_start(iocomm_runtime_t rt,
                               const iocomm_discovery_config* cfg,
                               iocomm_discovery_fn fn, void* user,
                               iocomm_error* err);
int32_t iocomm_discovery_stop(iocomm_runtime_t rt, uint64_t timeout_ms, iocomm_error* err);

/* 快照：晚加入者一次性获取当前节点表（含跨机组播/seed 与**本机注册表**条目）。
 * 快照对象也是代际句柄（iocomm_snapshot_t，定义见 §2），
 * release 后再次使用返回 STALE_HANDLE。 */

int32_t iocomm_discovery_snapshot_take(iocomm_runtime_t rt,
                                       iocomm_snapshot_t* out,
                                       iocomm_error* err);
/* 出错返回 0 并置 err；空快照也返回 0（调用方据 err.code 区分）。 */
uint32_t iocomm_discovery_snapshot_count(iocomm_runtime_t rt,
                                         iocomm_snapshot_t s,
                                         iocomm_error* err);
int32_t  iocomm_discovery_snapshot_get(iocomm_runtime_t rt,
                                       iocomm_snapshot_t s,
                                       uint32_t index, iocomm_node_info* out,
                                       iocomm_error* err);
/* 非幂等：重复释放返回 STALE_HANDLE（与 FR-1.2 一致）。 */
int32_t  iocomm_discovery_snapshot_release(iocomm_runtime_t rt, iocomm_snapshot_t s);
```

> **所有字符串均为静态存储期**（库持有），**不使用「紧随其后的变长区」**——那会破坏 `hdr.size` 的版本模型。

---

## 8. 状态与指标

```c
typedef enum iocomm_condition_status {
    ICOMM_COND_UNKNOWN = 0,
    ICOMM_COND_TRUE    = 1,
    ICOMM_COND_FALSE   = 2,
} iocomm_condition_status;

typedef struct iocomm_peer_status {
    uint32_t size;                 /* 调用方预置 = sizeof(iocomm_peer_status) */
    uint32_t reserved0;

    uint64_t peer_node_id;
    /* 条件集（FR-5.1）：值为 iocomm_condition_status */
    uint8_t connected;
    uint8_t lively;
    uint8_t healthy;
    uint8_t config_current;
    uint32_t reserved1;

    uint64_t last_rx_ns;
    uint64_t last_heartbeat_ns;
    uint64_t reconnect_count;
} iocomm_peer_status;

#define ICOMM_PEER_STATUS_INIT { sizeof(iocomm_peer_status), 0 }

/* FR-5.2：状态变化可订阅（适用于 conn 或 endpoint） */
typedef void (*iocomm_condition_fn)(void* user, iocomm_conn_t conn,
                                    iocomm_endpoint_t ep,
                                    const iocomm_peer_status* st);

int32_t iocomm_conn_condition_subscribe(iocomm_runtime_t rt, iocomm_conn_t conn,
                                        iocomm_condition_fn fn, void* user,
                                        iocomm_subscription_t* out_sub,
                                        iocomm_error* err);
int32_t iocomm_endpoint_condition_subscribe(iocomm_runtime_t rt,
                                            iocomm_endpoint_t ep,
                                            iocomm_condition_fn fn, void* user,
                                            iocomm_subscription_t* out_sub,
                                            iocomm_error* err);

typedef struct iocomm_stats {
    uint32_t size;                 /* 调用方预置 = sizeof(iocomm_stats) */
    uint32_t reserved0;

    uint64_t bytes_sent, bytes_received;
    uint64_t messages_sent, messages_received;
    uint64_t queue_dropped;
    uint64_t retransmits;          /* TCP 层重传（可读时）；否则 0 */
    uint64_t heartbeat_timeouts;
    uint64_t reconnects;
    uint64_t audit_events;         /* 已送交 audit_fn（或回退 log_fn）的审计事件数 */

    int64_t  send_queue_depth, recv_queue_depth;
    int64_t  open_endpoints, discovered_peers;

    /* 延迟（FR-5.4）：基于心跳 RTT 的直方图分位 */
    uint64_t rtt_p50_ns, rtt_p99_ns, rtt_max_ns;
} iocomm_stats;

#define ICOMM_STATS_INIT { sizeof(iocomm_stats), 0 }

/* 快照非原子一致：各值可能来自不同时刻。 */
int32_t iocomm_stats_snapshot(iocomm_runtime_t rt, iocomm_stats* out,
                              iocomm_error* err);

/* 诊断 dump：返回 JSON 文本，调用方用 iocomm_free_text 释放。 */
int32_t iocomm_diagnostic_dump(iocomm_runtime_t rt, char** out_text,
                               uint64_t* out_len, iocomm_error* err);
void    iocomm_free_text(char* text, uint64_t len);
```

---

---

## 9. 消息监控（信封级 + 可选载荷）

> **定位**：状态监控回答「链路健康吗」，消息监控回答「**这一条消息去哪了**」。
> 默认只记**信封元数据**；载荷捕获是显式、限时、限速、限量的调试能力。

### 9.1 事件与丢弃原因

```c
typedef enum iocomm_mon_kind {
    ICOMM_MON_SENT      = 1,   /* **成功入队**后才产生；入队失败只产生 DROPPED */
    ICOMM_MON_RECEIVED  = 2,   /* 从传输收到（帧解码完成） */
    ICOMM_MON_DELIVERED = 3,   /* 已交付应用（推给回调 / 进入 recv 队列） */
    ICOMM_MON_DROPPED   = 4,   /* 被丢弃，原因见 drop_reason */
    ICOMM_MON_SLOW      = 5,   /* 见下方「SLOW 的配对规则」 */
    ICOMM_MON_LOST      = 6,   /* **聚合**：监控环满导致的丢失（见 C4） */
} iocomm_mon_kind;

typedef enum iocomm_drop_reason {
    ICOMM_DROP_NONE          = 0,  /* 非 DROPPED 记录使用（`kind != DROPPED` 时 drop_reason 恒为 0） */
    ICOMM_DROP_QUEUE_FULL    = 1,  /* 本端发送/接收队列满且策略为丢弃 */
    ICOMM_DROP_NO_SUBSCRIBER = 2,  /* 端点扇出时无已建立连接 */
    ICOMM_DROP_TIMEOUT       = 3,  /* 异步发送排队超过 send_options.queue_timeout_ms */
    ICOMM_DROP_PEER_GONE     = 4,  /* 连接已断开时仍有待发消息 */
    ICOMM_DROP_BACKPRESSURE  = 5,  /* 上游显式施加背压（策略为 ERROR 且队列满） */
    ICOMM_DROP_TOO_LARGE     = 6,  /* 帧超过 max_message_size（入站关闭连接） */
} iocomm_drop_reason;
```

> **枚举值约定（本条枚举与 `iocomm_overflow_policy` 同口径）**：0 一律保留为哨兵（「无 / 默认 /
> 保持当前值」），**合法取值在 C 与 Rust 两侧都写显式 discriminant**，并由静态断言锁死
> （C 侧 `_Static_assert`；Rust 侧 `const _: () = assert!(...)`；C99 下用负数组尺寸的等价技巧）。`drop_reason` 不进入**节点间的帧格式**，
> 只作为监控记录字段出现（dump 快照按 `sizeof(iocomm_mon_record)` 原样导出，该格式同样未发布）；
> 因此值可以整体更换。**首次发布后**本枚举按「只追加、不复用、不重排」执行。

> **SLOW 的配对规则（唯一权威）**：只有当 ① `direction == BOTH`、② 该消息 `correlation_id != 0`、
> ③ SENT 与 RECEIVED 落在**同一连接** 时，才计算 `RECEIVED.ts_mono - SENT.ts_mono`；
> 超过 `slow_threshold_ms` 则产生**一条** `SLOW` 记录（携带 `correlation_id`，`ts_mono_ns` 取 RECEIVED 的值）。
> **无法配对的消息不产生 SLOW**（宁可少报，不可错配）。`direction` 为 `IN` 或 `OUT` 时不产生 SLOW。
>
> **`DROPPED` 是「业务消息被丢」**，与 `LOST`（**监控自己的记录**没写进去）是两回事。
> **环满时的规则**：业务消息的 `DROPPED` 记录**只在环有空位时写入**；环满时业务丢弃仍计入
> `stats.business_dropped`，监控自身的丢失由**一条聚合的 `LOST` 记录**表达（见 C4），**不递归**。

### 9.2 记录

```c
typedef struct iocomm_mon_record {
    uint32_t size;              /* = sizeof(iocomm_mon_record) */
    uint16_t kind;              /* iocomm_mon_kind */
    uint16_t drop_reason;       /* iocomm_drop_reason；非 DROPPED 时为 0 */

    uint64_t capture_id;        /* **本记录在监控环中的唯一 ID，永不复用** */
    uint64_t seq;               /* 每来源发送操作单调（扇出时同一 send 的多条记录共享该 seq） */
    uint64_t ts_mono_ns;        /* 单调时钟：时延与排序 */
    uint64_t ts_wall_ns;        /* 墙钟：仅用于人读与本地对齐，**不可跨机比较** */

    uint64_t src_node;
    iocomm_conn_t conn;

    uint32_t original_len;      /* 原始载荷长度 */
    uint32_t captured_len;      /* 实际捕获字节数；0 = 未捕获。区分看 flags：
                                 * SAMPLED_OUT 置位 = 未捕获；未置位且 original_len==0 = 捕获了空载荷 */
    uint64_t correlation_id;

    uint8_t  flags;             /* ICOMM_MON_FLAG_* */
    uint8_t  reserved[7];
    uint32_t lost_count;        /* **仅 kind==LOST**：本批聚合条数（≤1024）；其余为 0 */
} iocomm_mon_record;

#define ICOMM_MON_FLAG_TRUNCATED   0x01  /* captured_len > 0 且 < original_len */
#define ICOMM_MON_FLAG_SAMPLED_OUT 0x02  /* 未捕获：捕获关闭 / 采样略过 / capture_ttl 到期 */
```

**`flags` 的判定规则（唯一权威）**：

| 情形 | `captured_len` | `TRUNCATED` | `SAMPLED_OUT` |
|---|---|---|---|
| 捕获关闭（`max_payload_bytes == 0`） | 0 | ❌ | ✅ |
| 采样略过 | 0 | ❌ | ✅ |
| 完整捕获 | == `original_len` | ❌ | ❌ |
| 截断捕获 | 0 < `captured_len` < `original_len` | ✅ | ❌ |
| 零长载荷 | 0 且 `original_len == 0` | ❌ | ❌ |

> **`TRUNCATED` 只在 `captured_len > 0` 时才可能置位。** 未捕获一律用 `SAMPLED_OUT`。

**载荷不在记录内**：库在记录产生时把捕获的载荷**深拷贝进 arena**，
通过 §9.4 的 `iocomm_mon_record_payload()` 取得视图（生命周期见 `retain_window`）。
**arena 保留规则**：载荷的 arena 块与所属记录同寿命——记录离开 `retain_window` 时一并释放并回收。

### 9.3 监控者配置

```c
/* 〔v1.1〕载荷捕获相关字段（max_payload_bytes 及以下四项）在 v1 中恒按「捕获关闭」处理：
 * 即使传入非 0 也视为 0，且 capture_set 一律返回 INVALID_STATE。 */
typedef struct iocomm_monitor_config {
    iocomm_abi_header hdr;

    /* 作用域（0 = 全部） */
    iocomm_endpoint_t ep;
    iocomm_conn_t     conn;
    uint8_t  direction;          /* 0=BOTH 1=IN 2=OUT */
    uint8_t  reserved8[7];

    /* 环形缓冲 */
    uint32_t ring_capacity;      /* 条数上限，默认 1024 */
    uint32_t retain_window;      /* 记录被 poll 取出后仍可查视图的 poll 次数，默认 64 */
    uint64_t max_bytes;          /* 字节上限，统计口径见下 */

    /* 采样与阈值 0–1000 / ms */
    uint32_t sample_per_mille;   /* 元数据采样，默认 1000 */
    uint32_t slow_threshold_ms;  /* 端到端时延阈值，0 = 关闭 SLOW 事件 */

    /* 载荷捕获 —— max_payload_bytes == 0 表示完全关闭 */
    uint32_t max_payload_bytes;  /* 单条截断上限 */
    uint32_t capture_per_mille;  /* 载荷采样，默认 1000 */
    uint64_t max_bytes_per_sec;  /* 速率上限，0 = 不限 */
    uint64_t max_total_bytes;    /* 累计上限，0 = 不限 */
    uint64_t capture_ttl_ms;     /* **仅**结束载荷捕获；0 = 不自动结束；到期后 SAMPLED_OUT。
                                    * 再次 capture_set(on=1) 会重新开始捕获并重置该 TTL */

    uint64_t monitor_ttl_ms;     /* 整个监控者的寿命；0 = 不自动关闭 */
    uint8_t  reserved1[7];
} iocomm_monitor_config;

#define ICOMM_MONITOR_CONFIG_INIT \
  { { sizeof(iocomm_monitor_config), ICOMM_ABI_MAJOR, ICOMM_ABI_MINOR, 0, 0, 0 }, \
    0, 0, 0, {0}, 1024, 64, 4u << 20, 1000, 0, \
    0, 1000, 0, 0, 0, 0, {0} }
```

**默认值与语义**

| 字段 | 默认 | 语义 |
|---|---|---|
| `ring_capacity` | 1024 | 条数上限 |
| `retain_window` | 64 | 记录被 poll 取出后，其载荷视图在接下来多少次 poll 内仍有效；期间对应槽位不被复用。**0 = 视图立即失效**（相当于不保留，仅返回记录本身） |
| `max_bytes` | 4 MiB | 0 = 使用默认 4 MiB（与 `ring_capacity` 不同，0 不报错）。**口径 = 该监控者的监控内存总量**：`现存记录数 × sizeof(iocomm_mon_record) + 已捕获载荷字节`。**记录离开 `retain_window` 后一并释放**，字节归还；**实际生效的是与 `ring_capacity` 中先到者** |
| `sample_per_mille` | 1000 | 元数据全量进环 |
| `slow_threshold_ms` | 0 | 关闭 `SLOW` 事件 |
| `max_payload_bytes` | **0** | **载荷捕获关闭** |
| `capture_per_mille` | 1000 | 仅捕获开启时生效 |
| `max_bytes_per_sec` | 0 | 不限速（不推荐）。>0 时按 **1 秒滑动窗口**限速：窗口内捕获字节达上限后，**本次消息不捕获载荷**（仍记元数据，置 `SAMPLED_OUT`，`capture_throttled++`），窗口滚动后恢复 |
| `max_total_bytes` | 0 | 不设累计上限（不推荐） |
| **`capture_ttl_ms`** | 0 | 到期后**停止捕获载荷**，元数据继续记录 |
| **`monitor_ttl_ms`** | 0 | 到期后**关闭整个监控者**；上限 24 h |

> **预分配上限**：`monitor_open` 预留 `max_bytes + sizeof(iocomm_mon_record)`（工作集 + 1 条 LOST 槽）。
> **`max_bytes` 覆盖记录 + 载荷**，见上表；`max_total_bytes` 是**累计**配额，不参与预分配。
> **v1（载荷捕获关闭）**：`max_bytes` 只计记录，默认 4 MiB 可容纳约 4 万条；若要更省的默认值，v1 可将默认改为
> `ring_capacity × sizeof(iocomm_mon_record)`（约 90 KB）——**库按此自动收紧，不预留未使用的 arena**。
> **预分配失败** → `RESOURCE_EXHAUSTED`。
> 该**工作集**总量不得超过库全局预算 `runtime_config.monitor_budget_bytes`（0 = 默认 64 MiB）；
> 超预算或系统分配失败 → `RESOURCE_EXHAUSTED`。
> **`max_total_bytes` 不受预算限制**：它是累计配额，可在远大于工作集时配置（如 512 MiB），
> 达到后按 §9.4 的 `RESOURCE_EXHAUSTED` 规则停止捕获。
>
> **消息尺寸上限**：`max_message_size`（默认 1 MiB）在发送侧**先于入队**检查——
> 同步 `conn_send` / `endpoint_send` 返回 `TOO_LARGE`；异步经 `on_done(code=TOO_LARGE)`，**不入队**。
> 接收侧超限：关闭该连接（`DISCONNECTED`）并产生一条 `DROPPED(reason=TOO_LARGE)` 记录。
> **发送侧超限不产生 DROPPED**（消息从未入队，只返回错误码）。
> 监控记录中 `original_len` 仍为实际长度。
>
> **参数校验**：`max_bytes` 非 0 时须 ≥ `sizeof(iocomm_mon_record)`；`sample_per_mille` / `capture_per_mille` > 1000、`ep` 与 `conn` 同时非 0、
> `direction > 2`、`ring_capacity == 0`、`max_bytes` 非 0 时小于 `sizeof(iocomm_mon_record)` 均返回 `INVALID_ARGUMENT`。
> **`retain_window` 的规模约束**：它按 poll 次数计，但其实际占用 = `retain_window × 单次 poll 的最大条数`。
> 实现须保证「被保留的记录数」不超过 `ring_capacity`，超出时**提前回收最旧的保留记录**（视图随之失效，返回 `NOT_FOUND`）。
> 这是资源保护，不是配置错误。
> `iocomm_monitor_poll` 的 `cap == 0` 或 `buf == NULL` → `INVALID_ARGUMENT`（`timeout_ms` 仍生效）。
>
> **两个 TTL 必须分开**：载荷捕获要能自动收手（防「忘了关」），但元数据监控不应因此中断。

### 9.4 监控 API

```c
int32_t iocomm_monitor_open(iocomm_runtime_t rt,
                            const iocomm_monitor_config* cfg,
                            iocomm_monitor_t* out, iocomm_error* err);

/* 拉取事件（不使用回调）。
 * - timeout_ms == 0：非阻塞，返回 OK + out_n（可为 0）
 * - timeout_ms  > 0：阻塞至有记录 / 超时（OK + out_n=0）/ 监控者关闭（CLOSED）
 * - 若 monitor_ttl_ms 已到期：**在本次 poll 中释放资源并返回 CLOSED**
 * - loop 线程上：**仅允许 timeout_ms == 0**；>0 时返回 WOULD_DEADLOCK。
 *   （poll 只读私有环、不需要 loop 推进，所以 manual 单线程必须能非阻塞 poll。） */
int32_t iocomm_monitor_poll(iocomm_runtime_t rt, iocomm_monitor_t mon,
                            iocomm_mon_record* buf, uint32_t cap,
                            uint32_t* out_n, uint64_t timeout_ms,
                            iocomm_error* err);

/* 取得记录的载荷视图。用 capture_id 定位（**不要用 seq**：扇出会让
 * 一条 send 产生 N 条同 seq 记录，且 seq 会随环回绕复用）。
 * 有效期：**在该记录被 poll 取出后的 retain_window 次 poll 内有效**
 * （retain_window 见 §9.3，默认 64）；窗口结束或 monitor close 后失效。
 * 窗口内对应的环槽位**不会被生产端复用**。 */
int32_t iocomm_mon_record_payload(iocomm_runtime_t rt, iocomm_monitor_t mon,
                                  uint64_t capture_id, iocomm_slice* out,
                                  iocomm_error* err);

/* 导出**当前快照**（不清空环）。
 * **不与 poll 并发**：须由同一 monitor 的消费线程串行调用（见 §9.4 线程规则）。
 * 导出内部拷贝一份一致快照，调用方用 iocomm_free_text 释放。 */
int32_t iocomm_monitor_dump(iocomm_runtime_t rt, iocomm_monitor_t mon,
                            char** out, uint64_t* out_len, iocomm_error* err);

typedef struct iocomm_monitor_stats {
    uint32_t size;
    uint32_t reserved0;
    uint64_t emitted;            /* 成功写入环的记录数 */
    uint64_t lost;               /* 因环满丢失的记录数 */
    uint64_t business_dropped;   /* 业务消息丢弃数（含未写入记录的） */
    uint64_t capture_bytes;
    uint64_t capture_throttled;
    uint64_t capture_truncated;
    uint8_t  degraded;           /* 1 = 最近发生过丢失 */
    uint8_t  reserved1[7];
} iocomm_monitor_stats;

#define ICOMM_MONITOR_STATS_INIT { sizeof(iocomm_monitor_stats), 0 }

/* 〔v1.1〕运行时开关载荷捕获（FR-10.14）。v1 下恒返回 ICOMM_ERR_NOT_SUPPORTED。
 *
 * 整定的状态机：
 *
 *   初始状态（monitor_open 后）：
 *     - max_payload_bytes > 0  → 捕获**已开启**（打开监控即捕获）
 *     - max_payload_bytes == 0 → 捕获**永久关闭**（无可用上限）
 *
 *   capture_set(on=1)：
 *     - max_payload_bytes == 0        → ICOMM_ERR_INVALID_STATE，不产生审计
 *     - 已开启                         → ICOMM_OK，不重复产生审计
 *     - max_total_bytes 已达上限       → ICOMM_ERR_RESOURCE_EXHAUSTED，不产生审计
 *     - 否则（含 capture_ttl 到期后）  → 开启，产生 CAPTURE_ON 审计；
 *                                       若之前因 capture_ttl 到期而关闭，**重置该 TTL**
 *   capture_set(on=0)：
 *     - 已关闭                         → ICOMM_OK，不产生审计
 *     - 否则                           → 关闭，产生 CAPTURE_OFF 审计
 *
 *   自动停止（capture_ttl_ms 到期 / max_total_bytes 达到）**都视为「关闭」，
 *   各产生一次 CAPTURE_OFF 审计**（若此前为开启态）。
 *
 * 线程：任意线程可调用（内部加锁）。**在 loop 线程 / 回调内同样允许**——
 * 这是对 FR-6.7「回调/loop 线程上调用同步 API 返回 WOULD_DEADLOCK」的**显式例外**，
 * 因为该操作不依赖 loop 推进。若加锁不可即时取得，返回 ICOMM_ERR_WOULD_BLOCK。
 * 生效时机：返回时状态已可见（同一 monitor 后续记录立即按新状态处理）。 */
int32_t iocomm_monitor_capture_set(iocomm_runtime_t rt, iocomm_monitor_t mon,
                                   uint8_t on, iocomm_error* err);

int32_t iocomm_monitor_get_stats(iocomm_runtime_t rt, iocomm_monitor_t mon,
                                 iocomm_monitor_stats* out, iocomm_error* err);

int32_t iocomm_monitor_close(iocomm_runtime_t rt, iocomm_monitor_t mon,
                             iocomm_error* err);
```

**线程安全**：**同一 `monitor` 同一时刻只允许一个线程 `poll` / 查载荷 / `close`**
（内部为 SPSC：生产端 loop 线程，消费端调用方）。多个 `monitor` 互不影响。
`iocomm_monitor_get_stats` 可任意线程调用（返回拷贝）。

### 9.5 审计 sink（回调）

```c
typedef enum iocomm_audit_kind {
    ICOMM_AUDIT_ENDPOINT_CREATE = 1,
    ICOMM_AUDIT_ENDPOINT_DESTROY,
    ICOMM_AUDIT_CONNECT,
    ICOMM_AUDIT_DISCONNECT,
    ICOMM_AUDIT_SUBSCRIBE,
    ICOMM_AUDIT_UNSUBSCRIBE,
    ICOMM_AUDIT_RECONFIGURE,
    ICOMM_AUDIT_CONTROL,        /* runtime_start / stop / drain / endpoint_set_overflow；detail = 子类型 */
    ICOMM_AUDIT_MONITOR_OPEN,
    ICOMM_AUDIT_MONITOR_CLOSE,
    ICOMM_AUDIT_MONITOR_CAPTURE_ON,
    ICOMM_AUDIT_MONITOR_CAPTURE_OFF,
} iocomm_audit_kind;

typedef enum iocomm_ctrl_subtype {
    ICOMM_CTRL_START = 1, ICOMM_CTRL_STOP, ICOMM_CTRL_DRAIN, ICOMM_CTRL_SET_OVERFLOW,
} iocomm_ctrl_subtype;

typedef struct iocomm_audit_record {
    uint32_t size;
    uint32_t kind;               /* iocomm_audit_kind */
    uint64_t seq;                /* runtime 内单调分配；并发回调的到达顺序可能与之不同，按 seq 排序与检漏 */
    uint64_t ts_wall_ns;
    uint64_t subject;            /* 相关句柄或节点 */
    uint64_t detail;             /* 低基数细节：CONTROL 时为 ICOMM_CTRL_* 子类型；其余为 0 */
    int32_t  result;             /* ICOMM_OK 或错误码 */
    uint32_t reserved0;
} iocomm_audit_record;

#define ICOMM_AUDIT_RECORD_INIT { sizeof(iocomm_audit_record), 0, 0, 0, 0, 0, 0, 0 }
```

> **形态**：v1.1 的审计是**创建期固定、运行期不可改的回调 sink**（`runtime_config.audit_fn`），
> **不是**独立句柄 / 环 / poll。行业做法一致：OPC UA 用 Event Notification + Subscription、
> DDS Security 用 Logging Plugin、gRPC 用 `AuditLogger` 回调、nng 用 `nng_log_auth`——
> 共性都是「稳定事件 schema + 可插拔 sink」，留存与存储交给宿主或 SIEM。
> 库内的几 MB 环最多覆盖几分钟到几小时，远不够现场留存；v1 无认证，`subject` 只是句柄，
> 没有真正的「谁」。完整取舍见 [ADR-002](../adr/ADR-002-message-addressing-and-ownership.md)。
>
> **回调契约**（实现与调用方都必须遵守）：
> 1. **在生产线程上同步调用**——`endpoint_create`、`connect`、`subscribe`、`reconfigure`、
>    `monitor_open` 等入口的执行线程。审计事件只出现在**控制面**（每秒最多几次），不在逐消息热路径。
> 2. **可能被多线程并发调用** → `audit_fn` 必须线程安全。
> 3. **禁止阻塞**（不做 I/O、不等待、不睡眠）。
> 4. **禁止在回调内调用任何 `iocomm_*` 函数**（重入）。
> 5. 未设置时（`audit_fn == NULL`）回退到 `log_fn` 的 AUDIT 类别；
>    `log_fn` 也为 NULL 时事件直接丢弃（不缓存、不补发）。
>
> **事件计数**并入 `iocomm_stats.audit_events`（见 §8），没有独立的 `audit_stats`。
> **审计记录不含业务载荷**。参照 OPC UA `AuditEventType`：谁 × 做了什么 × 何时 × 结果。
> **库只提供机制**：记录策略、留存时长、访问控制属于上层。
> **版本**：`audit_fn` 属 v1.1（M7）；v1 由 `log_fn` 的结构化 AUDIT 事件承担。

### 9.6 硬性契约（编号 C1–C12，避免与里程碑 M1–M7 混淆）

| # | 契约 |
|---|---|
| **C1** | 监控**永不反压主链路**：入队失败只丢记录并计数，生产者不受影响。**`monitor_ttl_ms` 到期后到达的事件直接跳过，不计入 `lost`/`degraded`**（那是「有意关闭」，不是丢失） |
| **C2** | 每个监控者**独立有界队列**（条数 + 字节双上限，先到者生效）；一个慢监控者不影响另一个 |
| **C3** | **热路径零同步 I/O、零分配**：只写定长记录 + 可选 memcpy 进**预分配** arena |
| **C4** | 环满时：新记录**写入失败**（不覆盖旧记录）→ `stats.lost++`、`degraded=1`。**LOST 槽位在 `ring_capacity` 之外额外分配 1 条**（有效业务容量仍是 `ring_capacity`，`max_bytes` 之外另计 1 条 LOST 槽）。每满 1024 次丢失就更新该槽位（`lost_count` 存本批条数，`capture_id` 每次**重新分配**）。**in-band LOST 是 best-effort，`stats.lost` / `stats.degraded` 才是权威信号**。poll **只读**，不写环 |
| **C5** | 载荷捕获**默认关闭**；开启后受 `max_payload_bytes` / `max_bytes_per_sec` / `max_total_bytes` / `capture_ttl_ms` 四重约束 |
| **C6** | `flags` 的置位规则见 §9.2 表；**`TRUNCATED` 仅当 `captured_len > 0`** |
| **C7** | 开启/关闭载荷捕获、打开/关闭监控者**必须**产生审计事件。顺序固定为：`monitor_open` →（`max_payload_bytes > 0` 时）`CAPTURE_ON` → 之后每次状态迁移按 §9.4 产生 `CAPTURE_ON` / `CAPTURE_OFF` → `monitor_close` 时若捕获仍开启，先产生一条 `CAPTURE_OFF`，再产生 `MONITOR_CLOSE`。**每次迁移恰好一条；重复设置同一状态不产生** |
| **C8** | `monitor_ttl_ms > 24h` → `monitor_open` 返回 `INVALID_ARGUMENT` |
| **C9** | `runtime_destroy` 时所有监控者自动关闭，未送出的记录丢弃（不阻塞）。**该路径不产生 `MONITOR_CLOSE`** |
| **C10** | 同一 monitor 的 `poll` / 载荷查询 / `close` **必须由同一线程串行调用** |
| **C11** | `iocomm_monitor_close` 有两条路径，各产生**恰好一条** `ICOMM_AUDIT_MONITOR_CLOSE`：① **显式关闭**——在被调用线程上同步产生；② **`monitor_ttl_ms` 到期**——由 loop 线程在标记 expired 时产生。**`runtime_destroy` 路径不产生**（与 C9 一致） |
| **C12** | `audit_fn == NULL` 时**回退 `log_fn` 的 AUDIT 类别**（v1 行为）；两者都为 NULL 时事件直接丢弃（不缓存、不补发） |

### 9.7 dump 线格式

```
[8]  magic = "IOCMON\0\1"
[4]  version = 1
[4]  flags   (bit0 = little-endian)
[8]  record_count
[8]  payload_bytes
--- 记录区（record_count × sizeof(iocomm_mon_record)）---
--- 载荷区（变长，按 capture_id 升序，每条为 [4]len + bytes）---
```

- 所有多字节整数按 `flags.bit0` 指定端序；读取方必须先解头再解记录。
- 版本升级只允许**尾部追加**字段，读方按 `size` 判断。
- dump 是环的忠实快照；载荷只在捕获开启时存在，此时其长度随记录写入，字节进 payload 区。

### 9.8 明确不做

| 不做 | 理由 |
|---|---|
| 全量载荷默认落盘 | 隐私/带宽/存储；违反「载荷不透明」前提 |
| 在收发线程执行监控回调 | 延迟与故障耦合 |
| 无界缓冲 | 内存耗尽 |
| 库内字段级过滤 / 内容审计 | 没有数据格式 |
| 替代 Wireshark / PRONETA | 超出通信层职责 |
| 宣称「满足 IEC 62443」 | 标准要求的是安全事件可审计，不是业务载荷留存 |

> **信任模型（v1）**：任何持有 `iocomm_runtime_t` 的调用方都可以用 `ep=0` 打开监控读取全部消息元数据。
> v1 **信任同进程调用方**；跨进程/多租户隔离留到 v2。


## 10. 版本协商算法（宿主侧）

```
1. 取得对端的 iocomm_abi_header
2. hdr->size < sizeof(iocomm_abi_header)      → 拒绝（头部不完整）
3. hdr->abi_major != ICOMM_ABI_MAJOR          → 拒绝（不做「尽力兼容」）
4. minor 允许任意方向差异，不做拒绝；正确性由第 6 步的 size 检查保证
5. (hdr->features_required & ~host_features)   → 拒绝并列出缺失能力位
6. 访问任何字段前：
   offsetof(field) + sizeof(field) <= hdr->size 才读，否则按默认值
```

| 变更类型 | 版本动作 |
|---|---|
| 尾部追加字段 / 函数指针 | `minor + 1` |
| 改变已有字段语义/布局、删除 | `major + 1`，入口名换 `_v2` |
| 新增能力但不改布局 | feature 位 |
| 仅实现修复 | 都不动 |

> **发布前的一次性布局调整**：本头文件**尚未发布**，没有需要兼容的宿主。2026-10-21 的四项设计收敛
> **（删 `key` / 删 `delivery_class` / accept 借用语义 / 审计改 `audit_fn`，见 [ADR-002](../adr/ADR-002-message-addressing-and-ownership.md)）
> 在发布前直接改布局，**不升 `abi_minor`**——它们不是「向后兼容的追加」，升 minor 会误导。
> **首次发布后**再按上表执行。

> **发布前的同批调整（2026-10-21，同样不升 `abi_minor`）**：`send_options` 尾部追加 `queue_timeout_ms`；
> `runtime_config` 追加 `node_name` / `node_name_len`；新增 `iocomm_runtime_node_id()` / `iocomm_runtime_node_name()`；
> `listen_transport` 文档化 `"inproc"`；删除 `discovery_config.registry_plugin`。理由与上一段相同——尚无需要兼容的宿主，
> 升 minor 会把「发布前定型」误报成「向老宿主向后兼容」。

> **发布前的枚举值调整**：同理，**首次发布前**枚举成员可整体重编号（2026-10-21：撤销 `ICOMM_DROP_FILTERED`
> 后 `iocomm_drop_reason` 由 1–7 紧凑为 1–6，并补哨兵 `ICOMM_DROP_NONE = 0`）。
> Protobuf 的「不重用编号」规则其限定词是 *in use*——「从未发布」不在其保护范围内；
> 空洞在 C 里也没有强制力（C99 §6.7.2.2 允许重复值，误填编译器不报错）。
> **首次发布后**，所有 ABI 可见枚举一律「只追加、不复用、不重排」，且 0 始终保留为哨兵。
> 一旦满足下列任一条件即视为「已发布」：打过 tag / 有 release 产物 / 外部方拿到过头文件 /
> dump 或日志在外部留存 / 下游有 fork 或生成的绑定 / 枚举值进入网络线格式 /
> 正式承诺 ABI 稳定（**与版本号是否 1.0 无关**）。

> **第 4 步的关键修正**：只有当**老宿主读到的新对端结构体**在 `hdr->size` 范围内时才是安全的——由第 6 步统一保证。因此 `minor` 只用于**诊断与能力位**，不用于拒绝。旧版此处的「`abi_minor >` 即拒绝」与「尾部追加只升 minor」直接矛盾，已修正。

---

## 11. 反例清单（明确不要做）

| # | 反例 | 后果 |
|---|---|---|
| 1 | 跨边界传 `std::string` / `rust::String` | 分配器/析构归属不明 |
| 2 | 跨边界传异常 | UB |
| 3 | 用 `long` / `size_t` 上 ABI | LLP64/LP64 差异 |
| 4 | 用裸指针作句柄 | 无法检测悬垂 |
| 5 | 结构体不加 `size` 字段 | 无法向前/向后兼容 |
| 6 | 跨模块 thread-local 存错误 | 每个模块一份 TLS |
| 7 | 回调抛异常 | 杀掉宿主 |
| 8 | 回调内同步调库 API | 死锁 |
| 9 | 返回内部指针但不说明生命周期 | UAF |
| 10 | 用 `#pragma pack` 改线格式 | 跨架构布局不一致 |
| 11 | 结构体尾部放变长数据 | 破坏 `size` 协商 |
| 12 | 句柄 0 作为合法值 | 无法区分「未初始化」 |
| 13 | 监控环满时递归写 `LOST` 记录 | 无限递归 / 栈溢出 |
| 14 | 用 `seq` 定位载荷 | 扇出产生同 seq 多条、环回绕后复用 |
| 15 | 在收发线程格式化/写文件 | 直接抬高抖动与尾延迟 |
| 16 | 监控者满时反压生产者 | 违反 M1；监控故障拖垮业务 |
| 17 | 用枚举类型声明 ABI 结构体字段 / 函数出参 | 枚举宽度实现定义（`-fshort-enums` 下变窄），`hdr.size` 校验仍通过但字段错位；改用 `uint8_t` / `uint32_t` / `int32_t` 承载 |
| 18 | 把「入队成功」当作 `on_done(OK)` 的完成点 | 排队超时（`DROPPED(TIMEOUT)`）将永远不可达；同步与异步对「成功」的含义也会分叉（见 §6.2） |

```c
#ifdef __cplusplus
}
#endif
```
