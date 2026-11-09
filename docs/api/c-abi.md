# IoComm C ABI 契约

> 状态：设计阶段 ｜ 相关：[架构](../architecture.md) · [需求](../requirements.md)
>
> **这份头文件的规则一旦发布就不能随意更改。** 它是跨语言、跨编译器、跨架构的唯一稳定边界。

---

## 1. 总原则

| 原则 | 说明 |
|---|---|
| **只用 C 类型** | 不出现 Rust 类型、C++ 类型、STL、异常 |
| **C99 可编译** | 头文件必须能被纯 C 编译器编译（CI 守卫） |
| **不透明整数句柄** | 所有对象（Runtime / 端点 / 连接 / 订阅 / 快照 / 监控者，共六类）都是 `uint64_t`，共用同一张句柄表；**Runtime 是表的主人，不占 `max_handles`**（名额只计五类对象句柄，见 §6.0）。**C ABI 中不出现任何 `void*` 型对象** |
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

/* 前向声明（§5.2 / §9 的签名先用到 §8 的类型）。
 * 正确写法：此处 `typedef struct X X;`，后面的**定义处只写 `struct X { ... };`**
 * （不再带尾部 typedef）——否则 C99 `-pedantic-errors` 报 `redefinition of typedef`（已实测）。
 * 注意：`struct X;` + `typedef struct X X;` 与 `typedef struct X X;` + `typedef struct X {…} X;`
 * **两种写法都会报错**，唯一通过的是「typedef 一次 + struct 定义不带 typedef」。 */
typedef struct iocomm_peer_status iocomm_peer_status;
typedef struct iocomm_stats       iocomm_stats;
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

> **首字段规则的例外**：`iocomm_error` 与 `iocomm_message` 是**库写、调用方读**的输出结构体，用裸 `uint32_t size` 开头即可。
> **调用方无需预置 `size`**——库无条件写完整结构体（见 §3.1）。该例外**仅限输出方向**；输入结构体必须用 `iocomm_abi_header`。

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
    uint32_t size;               /* 库写入 sizeof(iocomm_error)；调用方**无需预置**（见 §3.1） */
    int32_t  code;               /* iocomm_error_code */
    char     message[256];       /* UTF-8，NUL 结尾 */
} iocomm_error;

#define ICOMM_ERROR_INIT { 0, 0, {0} }   /* 全部置零即可；size 由库写 */

const char* iocomm_strerror(int32_t code);  /* 静态存储期，不要 free */
```

**规则**：
- **本枚举是唯一权威**；`architecture.md` 中的 Rust `ErrorCode` 是内部名，必须逐值映射到本枚举。
- **超时是正常结果**，独立码，不折进「失败」。
- 错误码**只追加**，已有值永不改变。
- 错误详情走**出参**，不使用跨模块的 thread-local。
- **函数签名里的错误码一律用 `int32_t`**（返回值与 `iocomm_error.code` 都是），不用 `iocomm_error_code`——它是策略枚举（定宽承载，见 §1）。

### 3.1 错误出参的通用契约（**对全部 `iocomm_error* err` 参数生效**）

| 情形 | 行为 |
|---|---|
| 调用返回 `ICOMM_OK` | `err` **不被写入**（调用方不应读取其内容） |
| 调用返回非 `OK` | `err` **必然被完整填充**：`code` = 返回值、`message` = 非空且 NUL 结尾的 UTF-8（截断到 255 B）、`size` = 库写入的 `sizeof(iocomm_error)` |
| `err == NULL` | 允许。库**不写**任何内容，只返回错误码；调用方拿不到 `message` |
| `err != NULL` 但 `err->size < sizeof(iocomm_error)` | **不读取 `size`**（本结构体不做版本协商），按完整结构体写入 |
| 库捕获到 panic | 返回值 `ICOMM_ERR_INTERNAL`，`message` 含 `"panic"` 前缀 |

> **没有例外**（2026-11-05，N-38 复核）：本表对全部 `iocomm_error*` 参数无一例外地生效。
> 曾经考虑过让「端点级持有后的 `conn_recv`」返回 `TIMEOUT` 且不写 `err`，**已否决**——
> 那会给全库开一个先例，并迫使调用方同时检查返回值与 `err.code` 才能区分「真超时」与「路由在别处」。
> **现口径**：该情形返回 **`ICOMM_ERR_INVALID_STATE`**（与 §6.4「先 subscribe 再 recv」同码，`err` 照常填充），见 §5.2 与矩阵 `iocomm_conn_recv` 行。

> **`size` 字段在 `iocomm_error` 上不做协商**：它是库写、调用方读的输出结构体（§2 首字段规则的例外）。
> 调用方**不必**预置 `size`；库无条件写完整结构体。

### 3.2 错误码集合的书写规则

每个公开函数**必须**在其头文件注释中以 `@errors` 列出**全部可能返回码**（`ICOMM_OK` 除外），例如：

```c
 * @errors ICOMM_ERR_INVALID_ARGUMENT  ep == 0 / cfg 为 NULL / 端点名格式或长度非法（§5.1a）
 * @errors ICOMM_ERR_ALREADY_EXISTS    同进程已有同名端点
 * @errors ICOMM_ERR_CONFLICT          端点名已被他进程占用（不注册、不自动改名）
 * @errors ICOMM_ERR_RESOURCE_EXHAUSTED 句柄数已达 max_handles
```

- **未列入 `@errors` 的码视为实现缺陷**，由 AC-95 静态检查。

#### 3.2.1 函数族 × 错误码矩阵（**权威**，优先于逐函数注释）

**本表取代 §3.2 首段的「每个函数必须逐条 `@errors`」要求**——只需在头文件中注明
`/* @errors 见 c-abi.md §3.2.1 */`，无需逐函数重复。AC-95 检查的是：
**每个导出函数都能在本表中找到对应行**（按函数族匹配），且表中列出的码都在 `iocomm_error_code` 内定义。
**本表一律用全限定名**（`iocomm_` 前缀），不用简称——避免「`snapshot_get` 到底是哪个函数」的歧义。

| 函数族 | 可能的错误码（`OK` 除外） |
|---|---|
| `iocomm_runtime_create` | `INVALID_ARGUMENT`（`cfg` 为 NULL / `max_message_size > 64 MiB` 或 **< 56 B**（见 §6.0）/ 枚举非法 / **`node_id == 0` 时 `state_dir` 为空或不可写**）、`CONFLICT`（`node_id == 0` 时 `state_dir` 的名字文件已被**另一存活进程**占用，见 `runtime_config.node_id` 注释）、`RESOURCE_EXHAUSTED`、`INTERNAL` |
| `iocomm_runtime_start` | `STALE_HANDLE`、`INTERNAL`（Running 上重复调用幂等 `OK`）；**Stopped 下见下行**（`CLOSED`）。**无 `WOULD_DEADLOCK`、无 `TIMEOUT`、无 `WOULD_BLOCK`**——它不等待任何东西（manual 下只做状态迁移、不启动线程，见 §4） |
| `iocomm_runtime_drain` | `STALE_HANDLE`、`WOULD_BLOCK`（**manual 模式**下仍有在途操作，见下方注释）、`TIMEOUT`（**owned 模式**等满 `timeout_ms` 仍未收敛；此时**不保证已排空**）、`WOULD_DEADLOCK`（**`timeout_ms > 0` 且在 loop 线程或回调内**——owned 下它要等 IO 线程收敛，等待即自锁；`timeout_ms == 0` 不等待，**不返回此码**）、`INTERNAL`（Stopped 下合法） |
| `iocomm_runtime_stop` | `STALE_HANDLE`、`TIMEOUT`、`WOULD_DEADLOCK`（**loop 线程或回调内**且 `timeout_ms > 0`——它要等 IO 收敛，等待即自锁；`timeout_ms == 0` 不等待，**不返回此码**）、`INTERNAL`（Stopped 下幂等） |
| **Stopped 下的其余写操作**（`runtime_start` / `endpoint_create` / `connect*` / `subscribe` / `*_send*` / `discovery_start` / `monitor_open` 等） | `CLOSED`（Runtime 已停止接受写；Stopped 不可重启，恢复需重建 Runtime；见 §4 状态机）。**只读查询不受影响**（`conn_status` / `stats_snapshot` / `endpoint_count` / `endpoint_get` / `discovery_snapshot_*` / `diagnostic_dump` 等照常） |
| `iocomm_runtime_run_once` / `iocomm_runtime_run_for` | `STALE_HANDLE`、`INVALID_STATE`（**owned 模式**下调用）、`INTERNAL`；**`run_once` 另有 `TIMEOUT` = 本轮空闲**（正常事件，非故障，见下方注释）。**与 Runtime 状态无关**——manual 模式下 Created / Running / Stopped 均可调用（Stopped 下用于排空） |
| `iocomm_runtime_reconfigure` | `STALE_HANDLE`、`INVALID_ARGUMENT`（含 `max_message_size` 非 0 时越出 56 B–64 MiB）、`CLOSED`（Stopped 后）、`INTERNAL` |
| `iocomm_runtime_node_id` | `STALE_HANDLE`、`INVALID_ARGUMENT`（`out_node_id` 为 NULL，按 §3.2 通用出参规则）、`CLOSED`（Runtime 已 Stopped）、`INTERNAL` |
| `iocomm_runtime_node_name` | `STALE_HANDLE`、`INVALID_ARGUMENT`（`buf` / `out_len` 为 NULL）、`RESOURCE_EXHAUSTED`（缓冲不足，`out_len` 给所需长度）、`INTERNAL` |
| `iocomm_endpoint_create` | `STALE_HANDLE`、`INVALID_ARGUMENT`、`ALREADY_EXISTS`（**同进程**已持有同名端点）、`CONFLICT`（端点名已被**他进程**占用）、`RESOURCE_EXHAUSTED`、`NOT_SUPPORTED`（未知 transport / 平台不支持）、`INTERNAL` |
| `iocomm_endpoint_destroy` / `iocomm_conn_destroy` / `iocomm_conn_abort` | `STALE_HANDLE`、`WOULD_DEADLOCK`（**两种情况**：① 回调内调 **`iocomm_endpoint_destroy`**——`@forbid` 无条件禁止，`@special` 无对应例外；② 回调内销毁**非本回调交付的**连接 / 订阅。销毁**本回调交付的**连接是 `@special` 允许的，不返回此码。见 §6.4 回调规则）、`INTERNAL` |
| `iocomm_runtime_wakeup` | **无错误通道**（AC-95 豁免）；返回值为错误码，无 `err` 出参 |
| `iocomm_endpoint_lookup` / `iocomm_endpoint_get` / `iocomm_conn_get` / `iocomm_discovery_snapshot_get` | `STALE_HANDLE`、`NOT_FOUND`、`INVALID_ARGUMENT`、`INTERNAL`（`snapshot_get` 另有 `NOT_FOUND` = index 越界） |
| `iocomm_conn_count` / `iocomm_discovery_snapshot_count` | `STALE_HANDLE`、`INTERNAL`（走 `err`；出错返回 0 并置 `err`） |
| `iocomm_endpoint_count` | **无错误通道**（AC-95 豁免）：签名无 `err`；`rt` 无效时返回 **0**，与「该 Runtime 没有端点」不可区分——调用方若需区分，用 `iocomm_endpoint_get` 或任何带 `err` 的入口探测 |
| `iocomm_endpoint_name_state` | `STALE_HANDLE`、`INVALID_ARGUMENT`、`INTERNAL`（错误码仍走 `err`，返回值恒为 0） |
| `iocomm_endpoint_local_addr` | `STALE_HANDLE`、`INVALID_ARGUMENT`、`INVALID_STATE`（**纯出站端点**没有监听地址，见 §5.1c 规则 1）、`RESOURCE_EXHAUSTED`、`INTERNAL` |
| `iocomm_endpoint_set_overflow` | `STALE_HANDLE`、`INVALID_ARGUMENT`（枚举非法）、`INTERNAL` |
| `iocomm_endpoint_accept` | `STALE_HANDLE`、`INVALID_ARGUMENT`（**纯出站端点**——`listen_transport` 与 `listen_addr` 均空，§5.1c 规则 1——没有可交付的入站连接）、`RESOURCE_EXHAUSTED`、`INTERNAL`。**无 `INVALID_STATE`**——它与端点级收消息（`iocomm_subscribe(ep)` / `iocomm_endpoint_recv(ep)`）是**两条正交的轴**，可任意顺序注册（2026-11-05，N-37，见 §6.4 开头的「正交性」段） |
| `iocomm_subscribe` / `iocomm_conn_subscribe` | `STALE_HANDLE`、`INVALID_ARGUMENT`、`INVALID_STATE`（`recv` 已启用，§6.4 二选一；`conn_subscribe` 另有「该连接已由端点级订阅 / 拉取持有」，见 §5.2）、`RESOURCE_EXHAUSTED`、`INTERNAL` |
| `iocomm_conn_condition_subscribe` / `iocomm_endpoint_condition_subscribe` | `STALE_HANDLE`、`INVALID_ARGUMENT`、`RESOURCE_EXHAUSTED`、`INTERNAL`。**无 `INVALID_STATE`**——状态订阅与消息接收是两条独立的通道，不受 §6.4 的 `subscribe` / `recv` 二选一约束 |
| `iocomm_unsubscribe` / `iocomm_conn_close_graceful` | `STALE_HANDLE`、`INVALID_STATE`、`WOULD_DEADLOCK`（loop 线程；`unsubscribe` 本订阅回调内除外）、`TIMEOUT`、`INTERNAL` |
| `iocomm_conn_retain` | `STALE_HANDLE`、`INTERNAL`。**任意线程可调**（含 loop 线程与 accept 回调内）——它只改所有权表，不等待、不投递、不阻塞，因此**没有 `WOULD_DEADLOCK`、没有 `TIMEOUT`**（2026-11-05，N-36：此前与 `unsubscribe` 同行的写法会使 AC-29 / AC-40 的用法直接失败） |
| `iocomm_connect` | `STALE_HANDLE`、`INVALID_ARGUMENT`、`NOT_SUPPORTED`、`TIMEOUT`、`DISCONNECTED`、`NO_RECEIVER`、`WOULD_DEADLOCK`、`RESOURCE_EXHAUSTED`、`INTERNAL` |
| `iocomm_connect_node` | 同 `iocomm_connect`，另加 `NOT_FOUND`（节点或端点成员不在发现表中，见 §5.2a） |
| `iocomm_connect_async` / `iocomm_connect_node_async` | 同步返回：`STALE_HANDLE`、`INVALID_ARGUMENT`、`NOT_SUPPORTED`、`NOT_FOUND`（仅 `connect_node_async`，见 §5.2a）、`WOULD_DEADLOCK`、`RESOURCE_EXHAUSTED`、`INTERNAL`；其余结果走 `on_done` |
| `iocomm_conn_send` / `iocomm_endpoint_send` | `STALE_HANDLE`、`INVALID_ARGUMENT`、`INVALID_STATE`、`TOO_LARGE`、`NO_RECEIVER`、`WOULD_BLOCK`、`DISCONNECTED`、`TIMEOUT`、`WOULD_DEADLOCK`、`CLOSED`、`INTERNAL` |
| `iocomm_conn_send_async` / `iocomm_endpoint_send_async` | 同步返回：`STALE_HANDLE`、`INVALID_ARGUMENT`、`INVALID_STATE`、`TOO_LARGE`、`WOULD_DEADLOCK`、`CLOSED`、`RESOURCE_EXHAUSTED`（`op_id` 空间耗尽，见 §6.2）、`INTERNAL`；其余走 `on_done` |
| `iocomm_send_cancel` | `STALE_HANDLE`、`NOT_FOUND`（op 已完成）、`INVALID_ARGUMENT`、`INTERNAL` |
| `iocomm_endpoint_recv` / `iocomm_conn_recv` | `STALE_HANDLE`、`INVALID_ARGUMENT`、`INVALID_STATE`（已 subscribe；**`conn_recv` 另有「该连接已由端点级订阅 / 拉取持有」——此时路由在端点队列，且该情形 `err` 照常填充**，见 §6.4）、`TIMEOUT`、`WOULD_DEADLOCK`、`CLOSED`、`INTERNAL` |
| `iocomm_discovery_start` | `STALE_HANDLE`、`INVALID_ARGUMENT`、`ALREADY_EXISTS`（已启动）、`NOT_SUPPORTED`、`RESOURCE_EXHAUSTED`、`INTERNAL` |
| `iocomm_discovery_stop` | `STALE_HANDLE`、`INVALID_STATE`（未启动）、`WOULD_BLOCK`、`TIMEOUT`、`INTERNAL` |
| `iocomm_discovery_snapshot_take` | `STALE_HANDLE`、`RESOURCE_EXHAUSTED`、`INTERNAL` |
| `iocomm_discovery_snapshot_release` | **无错误通道**（AC-95 豁免）：返回值承载——`0` = 成功，`ICOMM_ERR_STALE_HANDLE` = 重复释放或快照句柄已失效，`ICOMM_ERR_INTERNAL` = 内部错误 |
| `iocomm_monitor_open` | `STALE_HANDLE`、`INVALID_ARGUMENT`、`RESOURCE_EXHAUSTED`、`INTERNAL` |
| `iocomm_monitor_poll` | `STALE_HANDLE`、`INVALID_ARGUMENT`、`CLOSED`（ttl 到期）、`WOULD_DEADLOCK`（loop 线程 `timeout_ms > 0`）、`INTERNAL`。**无 `TIMEOUT`**：超时以 `ICOMM_OK` + `out_n == 0` 报告（见 §9.4 注释；2026-11-05 修正此前矩阵与注释的矛盾） |
| `iocomm_monitor_close` | `STALE_HANDLE`、`INVALID_STATE`、`WOULD_BLOCK`、`INTERNAL` |
| `iocomm_monitor_capture_set` / `iocomm_mon_record_payload` / `iocomm_monitor_dump` | `STALE_HANDLE`、`INVALID_STATE`、`NOT_SUPPORTED`（v1）、`RESOURCE_EXHAUSTED`、`NOT_FOUND`、`WOULD_BLOCK`、`INTERNAL` |
| `iocomm_monitor_get_stats` / `iocomm_stats_snapshot` / `iocomm_conn_status` | `STALE_HANDLE`、`INVALID_ARGUMENT`、`INTERNAL` |
| `iocomm_diagnostic_dump` | `STALE_HANDLE`、`RESOURCE_EXHAUSTED`、`INTERNAL`。**线程属性**：与 `stats_snapshot` 同属「返回拷贝的安全入口」，**可跨线程**（2026-11-05；此前未在架构 §3.3 列出，已补） |
| `iocomm_message_release` / `iocomm_free_text` / `iocomm_strerror` / `iocomm_version_string` / `iocomm_abi_version` / `iocomm_runtime_destroy` | **无错误通道**（AC-95 豁免） |

> **AC-95 的判定口径**：头文件注释中的 `@errors` **或**其指向的本表，二者取其一即可。
> 这样既保证「调用方知道可能返回什么」，又不强制逐函数重复同一张表。
- **出参（`out_*` 指针）不得为 NULL**：所有 `out_*` / `err` 之外的输出指针传入 NULL → `INVALID_ARGUMENT`，
  唯一的例外是 `err`（可 NULL，见 §3.1）。
- **豁免**：**没有错误通道**的函数不要求 `@errors`——`iocomm_runtime_destroy`、`iocomm_message_release`、
  `iocomm_free_text`、`iocomm_strerror`、`iocomm_version_string`、`iocomm_abi_version`、
  `iocomm_runtime_wakeup`、`iocomm_endpoint_count`、`iocomm_discovery_snapshot_release`（共 **9** 个；
  签名中都没有 `iocomm_error*`，失败只以返回值体现。见 §3.2.1 对应行的「无错误通道」标注）。
  AC-95 的检查范围**排除这九个函数**（见 requirements.md AC-95 正文）。
- 通用的「句柄无效」路径（`ICOMM_ERR_STALE_HANDLE`）与「参数为 NULL / 0」（`ICOMM_ERR_INVALID_ARGUMENT`）对**所有**接受句柄的函数默认成立，可在注释中统一省略，由本节兜底。

### 3.3 枚举与配置值的合法性

| 输入类别 | 非法值时的行为 |
|---|---|
| 定宽整数承载的枚举（`driver_mode` / `overflow_policy` / `direction` / `flags` 等） | 返回 `ICOMM_ERR_INVALID_ARGUMENT`，**不静默截断、不取默认值** |
| **三态开关**（`tcp_nodelay`：0 = 默认/保持、1 = 开、2 = 关；`discovery_config.enable_multicast` 同构） | 非 0/1/2 → `INVALID_ARGUMENT`。**注意 0 不是 1 的同义词**——0 的含义是「用默认/保持」，本库默认值是「开」，因此 0 与 1 生效结果相同但语义不同；tune_config 里 0 = 保持当前（可能是 2 = 关） |
| `listen_backlog` | `0` = 默认 / 保持；非 0 且 ≥ 1 合法；负数在 `uint16_t` 上不可表示 |
| `flags` 中的**未定义位** | 同上：`INVALID_ARGUMENT`（未知位无法安全忽略——它可能改变语义） |
| 数值字段超出范围（如 `max_message_size` 小于 56 B——`20` 帧头 + `SEQ`/`TS_SEND`/`SOURCE_NODE` 三项必填 TLV 共 36 B；低于此值则**任何 `DATA` 帧都无法通过校验**） | `INVALID_ARGUMENT` |
| 0 值 | 按该字段注释的约定（默认 / 保持 / 关闭 / 无截止），**不是错误** |

### 3.4 结构体尺寸（`hdr.size`）的读写规则

| 方向 | 规则 |
|---|---|
| **调用方 → 库**（输入结构体） | `hdr.size < offsetof(末个必填字段)+sizeof` → `ICOMM_ERR_INVALID_ARGUMENT`；`hdr.size` 大于本端 `sizeof` 时**只读本端已知的前缀**，忽略尾部 |
| **库 → 调用方**（输出结构体，裸 `size` 开头） | 库写入 `sizeof(本端结构体)`；调用方按此值判断可读字段 |
| `hdr.abi_major != ICOMM_ABI_MAJOR` | `ICOMM_ERR_NOT_SUPPORTED`（不做尽力兼容） |
| `(hdr.features_required & ~支持的位) != 0` | `ICOMM_ERR_NOT_SUPPORTED`，`message` 列出缺失位的十六进制掩码 |

---

## 4. 运行时

```c
typedef enum iocomm_driver_mode {
    ICOMM_DRIVER_OWNED  = 0,   /* 库自带 1 个 IO 线程 */
    ICOMM_DRIVER_MANUAL = 1,   /* 调用方驱动 */
} iocomm_driver_mode;

/* 审计 sink：创建期设定、运行期不可改（见 §9.5）。 */
typedef void (*iocomm_audit_fn)(void* user, const iocomm_audit_record* rec);

/* 日志级别（log_fn 的 level 参数）。0 保留；非法值不产生日志。 */
#define ICOMM_LOG_ERROR 1
#define ICOMM_LOG_WARN  2
#define ICOMM_LOG_INFO  3
#define ICOMM_LOG_DEBUG 4
#define ICOMM_LOG_AUDIT 5   /* audit_fn 为 NULL 时的审计回退类别 */

typedef struct iocomm_runtime_config {
    iocomm_abi_header hdr;

    uint8_t  driver_mode;          /* ICOMM_DRIVER_* */
    uint8_t  reserved8[7];

    /* 节点身份（2026-11-04，N-04，见架构 §5.1b）：
     *  node_id != 0 → 显式配置，原样使用（稳定性由调用方保证）；
     *  node_id == 0 → 自动：在 state_dir 下原子创建/读取 `<state_dir>/iocomm.nodeid`
     *    （16 位小写十六进制）；**要求 state_dir 非空且可写**；为空 / 路径不可用 /
     *    文件内容不合法 → runtime_create 返回 INVALID_ARGUMENT。
     *    另以独占创建占住 `<state_dir>/iocomm.owner`（记 `<node_id>` + `<pid>` + 启动时间）：
     *    若已被**另一个仍存活的进程**占用（属主 pid 存活、启动时间相符），
     *    runtime_create 返回 **CONFLICT**，message 指明该 state_dir；属主已退出则接管并重写。
     *  **v1 不做任何主机级派生**（machine-id / MachineGuid / 主机名 / MAC 均不参与）：
     *  主机级纯函数会让同机多进程得到同一 NodeId（违反「每 Runtime 独立」），
     *  掺随机盐又会让重启后 NodeId 变化（违反 FR-9.1）。只读文件系统请显式配置 node_id。 */
    uint64_t node_id;
    const char* state_dir;         /* 自动 node_id 的落盘目录；node_id == 0 时**不可为 NULL**（见上） */
    uint64_t    state_dir_len;

    /* 节点名：展示用，随发现上报（FR-9.4）。NULL 或 len=0 = 不设名，
     * 对端看到空串。**创建期不可变**（改名字请重建 Runtime）。 */
    const char* node_name;
    uint64_t    node_name_len;

    /* 默认队列与溢出策略；端点级覆盖见 endpoint_config */
    uint32_t send_queue_max;       /* 0 = 默认（1024 条） */
    uint32_t recv_queue_max;       /* 0 = 默认（1024 条） */
    uint32_t max_message_size;     /* 0 = 默认（1 MiB） */
    uint32_t max_handles;          /* 0 = 默认（4096）；本 Runtime 内**五类对象句柄合计**上限（不含 Runtime 自身，见 §6.0） */

    /* ICOMM_OVERFLOW_*；0 = DROP_OLDEST（见 §6.1） */
    uint8_t  default_overflow_policy;
    uint8_t  reserved1[7];

    /* 监控的全局**已提交配额**上限（字节），0 = 默认 64 MiB；不是预分配量，见 §9.3 */
    uint64_t monitor_budget_bytes;

    /* level 取值见下方 ICOMM_LOG_* 常量 */
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

/* ── Runtime 状态机（唯一权威） ──
 *
 *   Created ──start()──► Running ──stop()──► Stopped ──destroy()──► (无效)
 *
 * | 状态 | 允许的操作 |
 * |---|---|
 * | **Created**（create 后、start 前） | 创建端点 / 连接 / 订阅 / 监控者 / 启动发现；消息可入队但**不会发出** |
 * | **Running** | 全部操作 |
 * | **Stopped**（stop 后） | 只能 `stop`（幂等）/ `drain` / `destroy` / **`run_once` / `run_for`** / 只读查询；**其余写操作**返回 `ICOMM_ERR_CLOSED`；句柄仍然有效。**自动重连属于写操作 → 停止**；已登记的 `on_done` 仍会触发。**`run_once` 在 Stopped 下合法**——manual 模式的 `drain` 正需要继续驱动 loop 才能排空 |
 * | 已销毁 | 任意入口返回 `ICOMM_ERR_STALE_HANDLE` |
 *
 * - `start` 在 Running 上重复调用返回 `ICOMM_OK`（幂等）；在 Stopped 上调用返回 **`ICOMM_ERR_CLOSED`**
 *   （Stopped 不可重启，恢复需重建 Runtime）。`stop` 仍**幂等**（重复调用返回 `ICOMM_OK`）。
 * - manual 模式下 `start` 只做状态迁移，**不启动线程**；loop 由 `run_once` 驱动。
 * - manual 模式下 loop 从未被驱动时，同步 `connect` / `send` 会等满各自的超时后返回
 *   `ICOMM_ERR_TIMEOUT`（它们等的是 loop 推进，不是对端）。`connect` 的超时口径见 §5.2：
 *   `connect_timeout_ms` 管 TCP 建立，握手段固定 5000 ms 窗口。
 * - `destroy` 在任意状态可用；销毁后所有句柄失效。 */

/* ── 控制面 ── */

int32_t iocomm_runtime_start(iocomm_runtime_t rt, iocomm_error* err);
/* `runtime_stop(timeout_ms)` 等待在途操作完成至多 `timeout_ms` 后返回；
 * 超时返回 `ICOMM_ERR_TIMEOUT` 且 **Runtime 已进入 Stopped**（不再接受新写）。
 * **在途操作不被取消**（与 `runtime_destroy` 不同，见 §5.2 的取消表与 `on_done` 码表）：已登记的 `on_done` 仍会在
 * `run_once` / IO 线程上触发，manual 模式须继续驱动 loop 排空。
 * `timeout_ms = 0` = 不等待，立即进入 Stopped。
 * **manual 模式怎么等**（2026-11-05）：`timeout_ms > 0` 时要等 loop 收敛，因此在 **loop 线程上调用会自锁** ——
 *   返回 `WOULD_DEADLOCK`（矩阵见 §3.2.1）。两种正确用法：① loop 线程上 `stop(rt, 0)`，随后用 `run_once` / `drain` 排空；
 *   ② **另一线程** `stop(rt, timeout_ms > 0)`，loop 线程同时继续驱动 `run_once`。
 *   **`drain` 同受此限**（`timeout_ms > 0` 且 loop 线程 → `WOULD_DEADLOCK`）；但 manual 模式本就要求
 *   传 `timeout_ms = 0` 在 loop 线程上交替 `run_once` 调用（见下），故 `drain(0)` 正常可用。 */
int32_t iocomm_runtime_stop (iocomm_runtime_t rt, uint64_t timeout_ms, iocomm_error* err);

/* 优雅关闭：owned 模式返回时保证已排空；
 * manual 模式返回 ICOMM_ERR_WOULD_BLOCK 表示仍有在途操作——
 * 调用方在**外部循环**里交替调 `run_once` 与 `drain`，**直到 `drain` 返回 `ICOMM_OK`**
 * （判据是 `drain` 的返回值，不是 `run_once` 的——`run_once` 空闲时返回 `TIMEOUT`，见 §4）。
 *
 * **`timeout_ms` 的两种口径**（2026-11-05，N-53）：
 *  - **owned 模式**：等待至多在途操作完成，等满仍不收敛返回 `ICOMM_ERR_TIMEOUT`（此时**不保证已排空**）。
 *    在 loop 线程 / 回调内且 `timeout_ms > 0` 会自锁，返回 `WOULD_DEADLOCK`（矩阵见 §3.2.1）。
 *  - **manual 模式**：`timeout_ms` **不推进 loop**——loop 只由调用方的 `run_once` 推进，
 *    `drain` 无法自己让它前进。**按架构 §3.2 传 `0`**，由调用方的外部循环决定总时长；传非 0 不报错
 *    （不返回 `INVALID_ARGUMENT`）。
 *    **注意（2026-11-09 复核）**：`timeout_ms > 0` 在 loop 线程上**仍按矩阵返回 `WOULD_DEADLOCK`**
 *    （统一口径：等待即自锁；库不区分「等待能否产生效果」）。故 manual 模式的唯一可行形态是
 *    **`drain(0)` + loop 线程**。 */
int32_t iocomm_runtime_drain(iocomm_runtime_t rt, uint64_t timeout_ms, iocomm_error* err);

/* 热重配置：只接受**通信参数**，不接受业务参数。
 * 入参为 iocomm_tune_config；创建期参数（driver_mode / node_id / state_dir /
 * node_name / log_fn / audit_fn / max_handles / monitor_budget_bytes）不可热更新。
 * **`max_message_size` 与创建期同口径校验**：非 0 时须落在 **56 B – 64 MiB**，越界 →
 * `INVALID_ARGUMENT`（**整次调用被拒，其余字段不生效**；热改只影响此后新建的连接，
 * 已握手连接保持握手时冻结的值，见架构 §3.2）。
 * 字段优先级与作用域见 §5.0「配置优先级」。 */
typedef struct iocomm_tune_config {
    iocomm_abi_header hdr;

    /* 0 = 保持当前值；非 0 才生效 */
    uint32_t send_queue_max;
    uint32_t recv_queue_max;
    uint32_t max_message_size;

    uint64_t heartbeat_ms;         /* 0 = 保持当前；默认 **2000 ms**（架构 §6.2 同一权威值） */
    uint64_t heartbeat_miss_limit; /* 连续丢 N 次未收到心跳判死；0 = 保持当前；默认 **3** */

    uint32_t iface_index;          /* 0 = 保持；否则改为指定网卡 */
    uint8_t  overflow_policy;      /* ICOMM_OVERFLOW_*；0 = 保持；作用于全部端点 */
    uint8_t  reserved8[3];

    /* 发现侧参数（0/NULL = 保持） */
    uint64_t discovery_heartbeat_ms;
    uint64_t discovery_lease_ms;

    /* ── 套接字参数（2026-11-04 尾部追加，N-12 / FR-4.8；0 = 保持当前）──
     * 与 endpoint_config 同义，但 0 表示「保持当前值」（tune 的统一口径），
     * **不是**「默认开」——端点未显式设置时，tune 的值成为它的生效值。
     * **生效边界（避免误读）**：
     *  - `tcp_nodelay`：可对**已建立连接与已监听 socket**立即 `setsockopt`，热更新当场生效；
     *  - `listen_backlog`：`listen()` 已调用后**无法再改**。tune 值只对**此后新建**的监听 socket
     *    （端点重建 / 新端点）生效；已监听端点保持创建时的 backlog（与 `max_message_size`
     *    对已握手连接的冻结属同类「热更新例外」，见 §5.0 规则 5）。 */
    uint8_t  tcp_nodelay;        /* 0 = 保持；1 = 开；2 = 关；非 0/1/2 → INVALID_ARGUMENT */
    uint8_t  reserved9[5];       /* 补齐 8 B 尾块（1 + 5 + 2），避免隐式尾填充 */
    uint16_t listen_backlog;     /* 0 = 保持；否则 ≥ 1 的 backlog（仅对新建监听 socket 生效） */
} iocomm_tune_config;

/* C99 分部初始化：未列出的成员自动置零 → 两个套接字字段均为 0 = 保持当前值。 */
#define ICOMM_TUNE_CONFIG_INIT \
  { { sizeof(iocomm_tune_config), ICOMM_ABI_MAJOR, ICOMM_ABI_MINOR, 0, 0, 0 } }

int32_t iocomm_runtime_reconfigure(iocomm_runtime_t rt,
                                   const iocomm_tune_config* cfg,
                                   iocomm_error* err);

void    iocomm_runtime_destroy(iocomm_runtime_t rt);  /* 强制关闭，取消在途 */

/* ── 事件循环（manual 模式） ──
 *
 * 两者都**只能在 manual 模式**下调用（owned 模式有 IO 线程 → `INVALID_STATE`），
 * 且都**必须在 loop 线程上调用**（与 `run_once` 同属非线程安全入口，架构 §3.3）。
 *
 * `iocomm_runtime_run_once(rt, timeout_ms)`：驱动一轮 loop，等待至多 `timeout_ms`。
 *   - 本轮处理了至少一件事（就绪 IO / 到期定时器 / 内部任务 / **被 `runtime_wakeup` 唤醒**）→ `ICOMM_OK`；
 *     **唤醒的处理优先级低于就绪 IO 与到期定时器**——若同一轮既有唤醒又有 IO，仍按「处理了事件」计；
 *     只有当唤醒是本轮**唯一**的处理对象时才因唤醒返回 `OK`。
 *     **纯唤醒也返回 `OK`**（2026-11-05，N-50）：`runtime_wakeup` 存在的意义就是「有外部状态需要本轮立刻看一眼」，
 *     若返回 `TIMEOUT` 则调用方无法把它与「真的空闲」区分，`while (rc == OK)` 型的循环也无法在唤醒后重新进入工作态。
 *     注意这与「唤醒不携带数据」并不矛盾——唤醒只保证本轮**从等待中返回**，数据仍由调用方自己的数据结构承载。
 *   - `timeout_ms` 内一件事都没有 → `ICOMM_ERR_TIMEOUT`，并**置 `err`**
 *     （与本文件其余函数「非 OK 必置 err」一致，§3.1）。
 *     **这是正常的空闲，不是故障**：不写日志、不计数、不产生审计事件。
 *   - `timeout_ms = 0` = **只轮询一次不等待**：有就绪事件返回 `OK`，否则立即 `TIMEOUT`。
 *   - 因此「本轮是否干了活」是**可观测的**——典型的单线程控制循环是
 *       for (;;) {
 *           (void)iocomm_runtime_run_once(rt, 100);   /* 空闲返回 TIMEOUT，无害 */
 *           do_my_work();                             /* 空闲也要执行，故不能用 while(rc == OK) */
 *           if (my_shutdown_requested) break;
 *       }
 *
 * **没有 `post`，怎么把回调里的事推到下一轮？**（2026-11-05，N-43 —— v1 的推荐形态）
 * 本库 v1 **不提供**「投递一段代码到 loop 下一轮」的入口（§9.8）。正确做法是**回调内只做三件事**：
 *   ① 把要保留的数据**拷贝出来**（`msg->payload` 只在本轮回调内有效）；
 *   ② 置一个**由应用自己拥有**的标志位；
 *   ③ 需要立刻回应的，用**异步**发送（内部投递到 loop，回调内合法）。
 * 数据处理放到 `run_once` 返回之后：
 *
 *     static void on_message(void* user, iocomm_endpoint_t ep, const iocomm_message* m) {
 *         app* a = user;
 *         memcpy(a->buf, m->payload.data, m->payload.len);  /* ① 拷贝出来（iocomm_slice 字段是 data/len） */
 *         a->len = m->payload.len;
 *         a->pending = 1;                                   /* ② 置标志 */
 *     }
 *     for (;;) {
 *         (void)iocomm_runtime_run_once(rt, 5);             /* 至多 5 ms */
 *         if (a->pending) { a->pending = 0; do_app_work(a->buf, a->len); }   /* ③ 在此做业务 */
 *         do_periodic_control();                            /* 控制周期本体 */
 *     }
 *
 * 需要句柄的（例如「新连接来了要记下来」）：在 accept 回调内 `conn_retain`，下一轮用 `conn_get` 枚举。
 * **唯一做不到的是「在回调内延迟 N ms」**——而 `post` 同样做不到：v1 本就没有定时器公开入口
 * （架构 §7 T6）。需要在应用侧延迟，就用你自己的控制周期计数器。
 *
 * `iocomm_runtime_run_for(rt, duration_ms)`：**循环 `run_once`**，直到**累计**运行时长达到 `duration_ms`。
 *   - 它不是新的等待语义，只是 `run_once` 的循环外壳：单次 `run_once` 的等待不超过剩余时长。
 *   - `duration_ms == 0` → **一次都不跑**，直接返回 `ICOMM_OK`（空操作）。
 *   - 正常跑满 → `ICOMM_OK`；**单次 `run_once` 的空闲 `TIMEOUT` 不向外传播**
 *     （它只用来决定「继续循环」，否则空闲 Runtime 上 `run_for` 永远返回 `TIMEOUT`）。
 *   - 中途出错（`STALE_HANDLE` / `INVALID_STATE` / `INTERNAL`）→ 立即返回该错误码，
 *     不再跑满剩余时长。**`run_for` 从不返回 `TIMEOUT`**。
 *   - `duration_ms` 用**单调时钟**累计（含 `run_once` 内部的空闲等待），不是墙钟差。
 *
 * 两者在 Runtime 为 **Stopped** 时同样合法（manual 模式的 `drain` 要靠它们排空，见上方状态机）。 */

int32_t iocomm_runtime_run_once(iocomm_runtime_t rt, uint64_t timeout_ms, iocomm_error* err);
int32_t iocomm_runtime_run_for (iocomm_runtime_t rt, uint64_t duration_ms, iocomm_error* err);
/* 唤醒 loop 使其从等待中返回（用于跨线程投递后促成立即处理）。
 * **无错误通道**：返回 0 = 成功，非 0 即错误码（`STALE_HANDLE` / `INTERNAL`），
 * 没有 `err` 出参——因为调用方（任意线程）只需要「有没有生效」这一个事实（AC-95 豁免）。 */
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

> **manual 模式的硬约束**：手动模式下只有一个线程在驱动 loop。在该线程上调用**阻塞型**同步 API 会返回 `ICOMM_ERR_WOULD_DEADLOCK`（见 §6）。**非阻塞的所有权 / 注册类调用不受此限**——`conn_retain` / `conn_subscribe` / `endpoint_accept` / 两个 `*_condition_subscribe` / `runtime_wakeup` 在该线程上**合法**（见 §3.2.1 矩阵与 §6.4 `@special`）。`runtime_drain` 在 manual 模式下不做阻塞排空。

---

## 5. 端点与句柄

### 5.0 配置优先级（**唯一的权威定义**）

同一个通信参数出现在多个结构体里时，按以下优先级生效。**总规则：越具体的作用域优先**
（端点级 > runtime 默认），运行期 `tune_config` 是**作用域最宽的覆盖**：
它作用于「未被端点级显式设置」的全部端点。

| 参数 | 创建期（runtime_config） | 端点级（endpoint_config） | 运行期热更新（tune_config） | 作用域 |
|---|---|---|---|---|
| `send_queue_max` / `recv_queue_max` | ✅ 默认值 | ✅ `queue_limit` 覆盖 | ✅ 只改**未被子端点级显式设置**的端点 | 端点级 > tune |
| `overflow_policy` | ✅ `default_overflow_policy` | ✅ `overflow_policy` 覆盖 | ✅ 只改**未被端点级显式设置**的端点 | 端点级 > tune |
| `max_message_size` | ✅ 默认值 | — | ✅ 全部端点 | runtime → tune |
| `max_handles` | ✅ 仅创建期 | — | ❌ | 不可热更新 |
| `heartbeat_ms` / `heartbeat_miss_limit` | — | — | ✅ 仅运行期 | 热更新 |
| `iface_index` | — | ✅ 作用：**端点监听 + 该端点的发送/组播** | ✅ 作用：**全部端点 + 发现** | 见下 |
| `tcp_nodelay` | — | ✅ `tcp_nodelay`（0 = 默认**开**） | ✅ `tcp_nodelay`（0 = 保持）只改**未被端点级显式设置**的端点 | 端点级 > tune |
| `listen_backlog` | — | ✅（0 = 默认 **128**） | ✅（0 = 保持）只改**未被端点级显式设置**的端点 | 端点级 > tune |
| `discovery_heartbeat_ms` / `discovery_lease_ms` | — | — | ✅ | 热更新（**发现配置的单一权威**） |

**规则**：
1. `tune_config` 的 `iface_index` 作用于**全部端点与发现**；`endpoint_config.iface_index` 与 `discovery_config.iface_index` 只作用于各自对象。**若同时设置，以更具体的那个为准**（端点 > 全局）。
2. **发现的心跳/租约的生效顺序**：`iocomm_discovery_start` 时以 `discovery_config.heartbeat_ms/lease_ms` 为**初值**；之后 `tune_config.discovery_heartbeat_ms/lease_ms` 覆盖它（0 = 保持）。`discovery_config` 的这两个字段**只在 `discovery_start` 这一刻生效**，不参与运行期的后续覆盖判断。
3. `tune_config` 中值为 0 表示「保持当前值」；**没有「恢复默认」的语义**（要恢复请重建 Runtime）。
4. `runtime_config` 中 `driver_mode` / `node_id` / `state_dir` / `node_name` / `log_fn` / `audit_fn` / `max_handles` / `monitor_budget_bytes` 是**创建期参数**，传给 `iocomm_runtime_reconfigure` 不适用（它只收 `iocomm_tune_config`）。
5. **热更新的作用对象**：`tcp_nodelay` 对已建立连接与已监听 socket 立即生效；`listen_backlog`
   **只对新建监听 socket 生效**（`listen()` 之后不可改）——与「`max_message_size` 对已握手连接冻结」
   （架构 §3.2）同属显式例外，理由相同：已生效的参数不可能追溯修改。

### 5.1 本地端点

```c
typedef struct iocomm_endpoint_config {
    iocomm_abi_header hdr;

    const char* name;            /* 端点名。格式与长度见 §5.1a：UTF-8 编码后 **1–255 B**、
                                  * 不得含 NUL、不含空段（`/` 为层级分隔符，不以 `/` 开头/结尾、无 `//`）；
                                  * 违反任一项 → INVALID_ARGUMENT */
    uint64_t    name_len;

    /* 监听地址。**`listen_transport` 与 `listen_addr` 的四格组合（唯一口径）见 §5.1c**：
     * 只填 addr 不填 transport → INVALID_ARGUMENT（不猜默认传输）；两者都不填 = 纯出站端点（不监听）。 */
    const char* listen_transport;  /* "tcp" / "unix" / "pipe" / "inproc"（v1）；"udp" 为 v1.1 */
    uint64_t    listen_transport_len;
    const char* listen_addr;       /* "0.0.0.0:0" / "/run/x.sock" / "\\\\.\\pipe\\x" / inproc 名 */
    uint64_t    listen_addr_len;

    uint32_t flags;              /* v1 **保留字段，无已定义位**；任何非 0 位 → INVALID_ARGUMENT
                                  * （与 §3.3「flags 中的未定义位」同口径）。原 ICOMM_ENDPOINT_UNIQUE 已删除 */
    uint32_t queue_limit;        /* 0 = 用 runtime 默认；同时作用于该端点的发送与接收队列 */

    uint32_t iface_index;        /* 0 = 自动；否则只在该网卡监听/发送 */
    uint8_t  overflow_policy;    /* ICOMM_OVERFLOW_*；0 = 用 runtime 默认 */
    uint8_t  publish_local;      /* 1 = 同时发布到本机注册表（FR-2.6） */
    uint8_t  reserved8[2];

    /* ── 套接字参数（2026-11-04 尾部追加，N-12 / FR-4.8）──
     * 语义按传输：tcp 上两者均生效；unix 上仅 `listen_backlog` 有意义（`TCP_NODELAY` 忽略）；
     * 其余传输（pipe / inproc）上两者均忽略、不报错。 */
    uint8_t  tcp_nodelay;        /* 0 = 用默认（**开**，不是「关」）；1 = 明确开；2 = 明确关；
                                  * 非 0/1/2 → INVALID_ARGUMENT。默认开的理由：工业 IO 是小消息低延迟，
                                  * Nagle 会引入数十毫秒。0 与其它字段一样表「默认」，而本字段的默认值是开 */
    uint8_t  reserved9[5];       /* 补齐 8 B 尾块（1 + 5 + 2），避免隐式尾填充 */
    uint16_t listen_backlog;     /* 0 = 默认 **128**；否则为该监听 socket 的 backlog。
                                  * backlog 溢出表现为连接被拒（对端 connect 超时/被拒），本端无计数可观测 */
} iocomm_endpoint_config;

/* C99 分部初始化：未列出的成员自动置零
 * → tcp_nodelay = 0（默认开）、listen_backlog = 0（默认 128）。 */
#define ICOMM_ENDPOINT_CONFIG_INIT \
  { { sizeof(iocomm_endpoint_config), ICOMM_ABI_MAJOR, ICOMM_ABI_MINOR, 0, 0, 0 } }

/* **端点级套接字参数的非目标（2026-11-04，N-12）**：v1 **不暴露**内核 TCP keepalive 开关
 * （`SO_KEEPALIVE` / `TCP_KEEPIDLE` / `SIO_KEEPALIVE_VALS`）。半开检测由**应用层心跳**承担
 * （FR-5.3，默认 2000 ms × 3）：内核 keepalive 默认 2 小时，且 WS2016 缺 `TCP_KEEPIDLE`，
 * 把它做成配置项只会给调用方一个「以为是快速检测」的假旋钮。需要内核级保活时不在本库范围：
 * 本库不向调用方暴露 fd，无法逐连接设置。 */

/* （原 ICOMM_ENDPOINT_UNIQUE 已移除：跨进程同名一律 CONFLICT，同进程同名 ALREADY_EXISTS，
 *   见架构 §6.4 与 FR-1.4；不再有「可多实例 + 自动改名」的开关。
 *   决策依据见 [ADR-003](../adr/ADR-003-endpoint-name-uniqueness.md)。
 *   原 ICOMM_ENDPOINT_SECRET 已移除：监控改为独立的 iocomm_monitor_*，见 §9） */

int32_t iocomm_endpoint_create(iocomm_runtime_t rt,
                               const iocomm_endpoint_config* cfg,
                               iocomm_endpoint_t* out_ep,
                               iocomm_error* err);

/* 销毁本地端点。语义完整定义如下（此前为空缺）：
 *  1. **名字锁**：立即释放跨进程名字锁（§architecture 6.4），其他进程可马上注册同名端点；
 *     本 Runtime 内同名端点也可立即重建。
 *  2. **入站连接**（本端点的**成员连接**）：全部以 FIN 优雅关闭（不是 RST）；这些连接上的订阅失效，
 *     **接收队列**中未取走的消息直接丢弃（**不产生 `DROPPED` 记录**——它们在入站时已记过
 *     `RECEIVED`，且销毁端点不是「丢弃事件」）。正在执行的 `accept` 回调会先跑完，之后不再触发。
 *     仍在**握手期**（尚未交付、因而尚无 `accept` 回调）的入站会话一并以 FIN 关闭，不产生回调。
 *  3. **出站连接**（`ep_owner == ep` 的连接）：**转为独立队列后继续存活**。销毁时把它们的未发项
 *     迁入各自的连接队列（容量取 runtime 默认），之后照常发出；它们不再计入本端点扇出与
 *     `conn_count(ep)`。要一并关闭请先 `conn_destroy`。
 *     迁移是**原子**完成的，调用方无感知，不会出现「有连接无队列」的中间态。
 *     **迁移后若连接队列已满**（迁移项数 > 默认容量）：超出部分按**该连接所属端点**的溢出策略处理
 *     （仍用原端点的策略，不切换到 runtime 默认）；在返回前完成——`endpoint_destroy` 不因迁移而阻塞。
 *  4. **在途异步发送**：该端点扇出的 `endpoint_send_async` **按 op_id 整组取消**
 *     （与 `send_cancel` 同口径，见 §6.2）：每组 `on_done(code = ICOMM_ERR_CANCELLED)` 恰好一次。
 *     **第 3 条的迁移与取消的先后（唯一口径）**：先迁移、后取消——
 *     已迁到出站连接独立队列的项**不取消**（它们会照常发出）；仍在端点队列里的项整组取消。
 *     一个组同时含两类项时，`on_done` 仍**只触发一次**（整组计）：
 *     **只要有项仍会发出 → `OK`**（部分成功，丢失数见 `queue_dropped`）；**全部项都被取消 → `CANCELLED`**。
 *     这与 §6.1「部分失败报 `OK`」一致，不构成两套口径。
 *  5. **阻塞中的同步发送**（`BLOCK` 策略，§6.1）：被唤醒并返回 `ICOMM_ERR_CLOSED`。
 *  6. **订阅 / 监控者**：挂在**本端点**上的订阅与监控者一并回收（等同 unsubscribe / monitor_close，
 *     但**不产生**审计事件）。连接到它们的回调不再触发。
 *  7. **发送队列**：**未被第 3 条迁移的**剩余消息（即属于**入站成员连接**或已无法投递的项）丢弃，
 *     逐条产生 `DROPPED(PEER_GONE)`（若有监控者）。出站成员连接的消息已随第 3 条迁移，**不在此列**。
 *  8. 函数返回后句柄立即失效；重复调用返回 `STALE_HANDLE`。
 *  **不阻塞**；线程要求与 `conn_destroy` 相同——任意线程可调用，但同一对象的创建/销毁
 *  由调用方串行化（架构 §3.3）。
 *  **「任意线程」不含回调内**（2026-11-09 复核）：回调内调用返回 `WOULD_DEADLOCK`（`@forbid`
 *  无条件禁止销毁端点，见 §6.4）。二者不冲突——前者讲**线程**，后者讲**回调上下文**。 */
int32_t iocomm_endpoint_destroy(iocomm_runtime_t rt, iocomm_endpoint_t ep,
                                iocomm_error* err);

/* 按名字查询本地端点 */
int32_t iocomm_endpoint_lookup(iocomm_runtime_t rt,
                               const char* name, uint64_t name_len,
                               iocomm_endpoint_t* out_ep, iocomm_error* err);

/* 枚举本地端点。
 * `iocomm_endpoint_count` **无错误通道**（AC-95 豁免）：`rt` 无效时返回 **0**，
 * 与「没有端点」不可区分——需要区分时改用带 `err` 的 `iocomm_endpoint_get` 探测。 */
uint32_t iocomm_endpoint_count(iocomm_runtime_t rt);
int32_t  iocomm_endpoint_get  (iocomm_runtime_t rt, uint32_t index,
                               iocomm_endpoint_t* out_ep, iocomm_error* err);

/* 唯一性三态（FR-1.5）：区分「空闲 / 本进程持有 / 他进程持有」。
 * **仅用于注册前探测与诊断**——`create()` 的返回值才是权威（架构 §6.4）。 */
typedef enum iocomm_name_state {
    ICOMM_NAME_FREE           = 0,
    ICOMM_NAME_HELD_BY_SELF   = 1,
    ICOMM_NAME_HELD_BY_OTHER  = 2,
} iocomm_name_state;

/* 返回值为 iocomm_name_state（0/1/2）；用 int32_t 承载（见 §1）。
 * **错误时不返回负数**：错误码全部为正（`INVALID_ARGUMENT = 1` …），负数会与之混淆。
 * 因此错误一律通过 `err` 出参报告，返回值为 `0`（= `ICOMM_NAME_FREE`），调用方**必须先检查 err**。
 * **`err` 传 NULL 时无法区分错误与 `NAME_FREE`** —— 传 NULL 前请确认参数已校验。 */
int32_t iocomm_endpoint_name_state(iocomm_runtime_t rt,
                                   const char* name, uint64_t name_len,
                                   iocomm_error* err);

/* 查询本端点实际监听的地址（端口 0 时用于取回系统分配的端口）。
 * inproc 端点返回它的进程内名字。
 *
 * **返回的是「原始监听值」，不是发现表里的「通告值」**（2026-11-04，N-05 口径统一）：
 *  - 通配地址原样保留（`0.0.0.0:<实际端口>`）；端口 0 替换为实际分配端口；
 *  - 发现表 `endpoint_info.addr` 上报的是**可拨号通告值**（通配地址已替换为具体地址，见 FR-8.12 与 §5.2a「地址解析」）。
 * 两者用途不同：排障/自检用本函数，`connect_node` 用通告值。
 * **纯出站端点**（`listen_transport` / `listen_addr` 均空，§5.1c 规则 1）没有监听地址 → `INVALID_STATE`。 */
int32_t iocomm_endpoint_local_addr(iocomm_runtime_t rt, iocomm_endpoint_t ep,
                                   char* buf, uint64_t buf_len,
                                   uint64_t* out_len, iocomm_error* err);
```

### 5.1a 端点名格式与长度上限（2026-11-04 定，N-17）

`endpoint_config.name` 是**远端可寻址的身份**（`connect_node` 按 `name` 精确匹配，§5.2a），
也是发现报文 `ENDPOINTS` 的条目内容（[线格式 §8](wire-format.md)）。因此必须给死上限：

| 规则 | 判定 |
|---|---|
| 长度 | **1–255 字节**（`name_len` 计**UTF-8 编码后的字节数**，不是字符数）。`name_len == 0` 或 > 255 → `INVALID_ARGUMENT` |
| NUL 字节 | **不得包含**（`name_len` 范围内出现 `0x00` → `INVALID_ARGUMENT`）。调用方用 `name_len` 定界，库不依赖 `name` 的 NUL 结尾 |
| 层级分隔符 | `/` 供 v2 的层级过滤（ADR-002）预留；**不允许空段**——不得以 `/` 开头或结尾、不得出现 `//` → 否则 `INVALID_ARGUMENT` |
| 编码 | 必须是**合法 UTF-8**（过长编码 / 代理项等非法序列 → 拒绝）→ 否则 `INVALID_ARGUMENT` |
| 大小写 / 规范化 | **不做**：名字按**字节**比较，不做 Unicode NFC/NFD 归一化、不做大小写折叠。由调用方保证一致 |

**为什么是 255 B**：

- 发现线格式 `ENDPOINTS` 的条目用 `name_len(u16)` 编码（[线格式 §8](wire-format.md)），`u16` 上限 65535 远大于 255；255 B 让 `name_len` 永不逼近 `u16` 上限。
- 发现报文单包 ≤ **1400 B**、按条目边界分页（[线格式 §8.1](wire-format.md)）。255 B 的名字 + 传输名（≤ 8 B）+ 可拨号地址（IPv6 字面量 ≤ 45 B；unix socket 路径与 Windows 管道名通常更短，若超长则由 §8.1「单条条目超限不发送」的既有降级路径处理）组成的**单条端点条目远小于 1400 B**，不会触发「单条条目超限 → 不发送并计入 `stats.discovery_oversize`」的降级路径。
- 与 `inproc` 的 `listen_addr`（≤ 255 B，§5.1b）取同一上限，避免调用方在两套命名空间间来回换算。

> **适用范围**：本节的字节规则同时适用于 `iocomm_connect_node*` 的 `endpoint_name` 参数与
> `iocomm_endpoint_lookup` / `iocomm_endpoint_name_state` 的 `name` 参数（它们引用同一个名字空间）。
> 查询类函数收到不合规名字时同样返回 `INVALID_ARGUMENT`（而不是 `NOT_FOUND`）——格式错误与「查无此名」是两类事。

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

### 5.1c `listen_transport` / `listen_addr` 的组合语义（2026-11-04 定，N-14）

两个字段是**成对**的。「空」的口径与 §1「显式长度」原则一致：**`NULL` 与 `len == 0` 都算空**
（库一律用 `len` 定界，不看 NUL；`ptr != NULL && len == 0` 视同 `NULL`）。

| # | `listen_transport` | `listen_addr` | `endpoint_create` 结果 |
|---|---|---|---|
| 1 | **空** | **空** | **成功，纯出站端点**——只作 `connect*` 的 `ep_owner` 与 `endpoint_send` 扇出宿主，不监听。`endpoint_local_addr()` 返回 `INVALID_STATE`（没有监听地址可报） |
| 2 | **空** | 非空 | `INVALID_ARGUMENT`——**不猜默认传输**。`listen_addr` 的语法随 transport 而变（`"0.0.0.0:0"` / `/run/x.sock` / `\\.\pipe\x` / inproc 名），无法从字符串可靠推断 |
| 3 | 非空 | **空** | `INVALID_ARGUMENT`——监听地址必填，没有「监听任意地址」的简写；要监听全部网卡就显式写 `"0.0.0.0:0"`。`"inproc"` 同样必填（§5.1b），规则一致 |
| 4 | 非空 | 非空 | 按 transport 校验 `listen_addr` 格式 → 合法则监听；**未知传输名**（不是 v1 的四种）→ `NOT_SUPPORTED`；传输名合法但地址格式非法 → `INVALID_ARGUMENT` |

补充规则：

- 规则 4 中「未知传输名」优先于地址格式校验：非法传输名 + 非法地址 → `NOT_SUPPORTED`，不报 `INVALID_ARGUMENT`。
- 规则 1 的纯出站端点**仍然注册端点名**（参与[架构 §6.4](../architecture.md) 的跨进程唯一性），也仍然可被 `endpoint_lookup` 查到、
  可被 `endpoint_send` 扇出到其 `ep_owner` 连接；只是**不监听**，因此 `connect_node` 解析到它时无 `addr` 可用 →
  发现报文里**不上报**（没有可拨号地址的端点不进入 `ENDPOINTS`）。
- 上述判定全部发生在**注册之前**：任何一格返回错误时，端点名**不会被占用**（与[架构 §6.4](../architecture.md) 的 fail-fast 一致——
  参数非法不会留下需要清理的半个注册）。调用方修正参数后可直接重试。
- `iocomm_connect*` 的 `transport` / `addr` **都是必填**（没有「不监听」的对偶概念）：
  任一为空 → `INVALID_ARGUMENT`；未知传输名 → `NOT_SUPPORTED`。
- inproc 的 `publish_local = 1` → `INVALID_ARGUMENT`（§5.1b）与本表正交：规则 2/3 失败时 `publish_local` 不参与判定。

### 5.2 连接（入站与出站）

**连接与端点分离**：`iocomm_endpoint_t` 是本地具名端点（监听者）；`iocomm_conn_t` 是一条**双向连接**，可能来自 `accept`（入站）或 `connect`（出站）。两者是**独立的句柄空间**。

```c
/* 入站连接回调。在 loop 线程上调用。
 *
 * **交付时点（唯一口径，2026-11-03 N-03）：双向 HELLO 完成后才触发本回调**（tcp / unix / pipe）。
 *   因此：
 *   - peer->peer_node_id 必有真实值（HELLO 携带的对端 node_id），不会为 0；
 *   - 回调内用 conn_send_async(CLOSE_AFTER) 发出的首条 DATA 一定落在双方「可发 DATA」之后，
 *     不会被对端按「未握手 DATA」断链；
 *   - 握手期的连接是库的**内部会话占位**：不分配 iocomm_conn_t 句柄、不占 max_handles 名额、
 *     对应用完全不可见（conn_count / conn_get / 扇出都看不到它）；
 *   - **以下路径不产生 `accept` 回调**：
 *     | 原因 | 连接被关闭 | 是否计入 `protocol_errors` |
 *     |---|---|---|
 *     | **握手层**：握手超时 | 是 | 本端判定：否 |
 *     | **握手层**：版本不兼容 | 是 | 本端判定：否 |
 *     | **握手层**：帧损坏（`MALFORMED`） | 是 | **是**（§2.1） |
 *     | **握手层**：整帧超限（`FRAME_TOO_LARGE`，线格式 §5 规则 3 的长度检查先于帧类型判断） | 是 | 否（本端发出 `ERROR`，§2.1）；入站丢弃计入 `queue_dropped` |
 *     | **握手层**：每端点握手会话数超限（§6.0，N-18） | 是（接受即关） | 否（WARN 日志） |
 *     | **交付层**：交付时句柄表已满（§6.0，N-19） | 是（FIN） | 否（ERROR 日志） |
 *     | **本地动作**：`endpoint_destroy` 关掉仍在握手期的会话（`endpoint_destroy` 规则 2） | 是（FIN） | 否 |
 *     前六行是**对端的连接尝试**被拒；最后一行是**本端主动拆掉自己的端点**，与对端行为无关。
 *     **`protocol_errors` 一律按线格式 §2.1 的唯一口径**：**收到** `ERROR`，或**判定收到的帧**损坏，才计入；
 *     本端**发出** `ERROR` 不计入。因此「握手超时 / 版本不兼容」两行写「本端判定：否」只描述本端先判定并
 *     发送 `ERROR` 的情形；对端先判定并回 `ERROR` 时，本端收到即计入——同一连接两端**各自**计数，不算重复。
 *     日志级别以各出处为准：握手层见 [线格式 §2.1](wire-format.md) / §5 规则 7，交付层与本地动作见 §6.0 与本文 `endpoint_destroy` 规则 2。
 *     **计数口径**：本表「是否计入 `protocol_errors`」一列之外，入站帧被判**超限 / 畸形 / 长度校验失败**一律同时计入
 *     `queue_dropped`（见 §8 `iocomm_stats.queue_dropped`）；本地资源保护（握手表满、句柄表满）两个计数**都不计**。
 *   inproc **不跑 HELLO**，交付时点 = 连接建立即交付；peer_node_id 取对端 Runtime 的 node_id
 *   （同地址空间直接读取，仅在对端 Runtime 已销毁的竞态下为 0）。详见 [线格式 §5 / §7](wire-format.md)。
 *
 * **inbound 是借用句柄，只在本次回调期间有效**（借用语义，见 ADR-002）：
 *   - 什么都不做              → **全部** accept 回调返回后若仍无任何持有动作，库自动收回并以 FIN 优雅关闭（= 拒绝）
 *                               （多次注册时「任一回调完成持有即保留」，见 AC-33；2026-11-05，N-37）
 *   - iocomm_conn_subscribe   → **隐式持有**（订阅即所有权），连接保持打开
 *   - iocomm_conn_retain      → 显式持有。**对未被端点级收消息持有的连接**：用于拉取模式
 *                               （之后可在别的线程 conn_recv），并把投递切到该连接的接收队列；
 *                               **对已由端点级推送/拉取持有的连接**：只做所有权确认（见下方「端点级持有」）。
 *                               **可在回调内调用**，不返回 WOULD_DEADLOCK（矩阵见 §3.2.1）。
 *   - iocomm_conn_send_async  → **仅在 send_options.flags 含 ICOMM_SEND_CLOSE_AFTER 时合法**：
 *                               数据 flush 后优雅关闭，on_done 之后句柄失效；
 *                               未设 CLOSE_AFTER 且未 subscribe/retain → ICOMM_ERR_INVALID_STATE
 *                               （**例外**：本端点已启用端点级订阅/拉取时连接已被持有，不返回该错误）
 *   - iocomm_conn_destroy     → 立即关闭（= 显式拒绝），重复调用返回 STALE_HANDLE
 *
 * **端点级持有**（2026-11-03，N-02）：该端点上已启用 `iocomm_subscribe(ep)` 或
 * `endpoint_recv(ep)` 时，端点在**交付的同一时刻**接管入站连接（交付前它是库的内部会话，
 * 无句柄、不计入扇出与 `conn_count(ep)`——见下方交付时点），回调内无需再调任何持有动作；
 * 此时回调仍会触发（用于观测新连接，**2026-11-05 N-37：这与端点级收消息正交，不构成互斥**），
 * 但回调内对该连接调 `conn_subscribe` 返回 `INVALID_STATE`（已由端点持有）。
 *
 * **此时 `conn_retain` 只做所有权确认、不改投递路由**（2026-11-05，N-38）：返回 `OK`（幂等），
 * 消息**继续进入端点接收队列**，对该连接调 `conn_recv` 返回 **`ICOMM_ERR_INVALID_STATE`**
 * （与 §6.4「先 subscribe 再 recv」同码：这条连接已被端点订阅持有，连接级拉取不可用）。
 * 路由在「端点级持有」成立的那一刻就已定死——若需要连接级拉取，应在端点持有**之前**就选定，
 * 或另开一个不启用端点级收消息的端点（§6.4 末段）。
 *
 * 「什么都不做」与「保存句柄」都会导致回调返回后回收——库无法观测外部变量。
 * 同步 iocomm_conn_send 在回调内会返回 WOULD_DEADLOCK，需在别的线程调用。 */
typedef struct iocomm_peer_info {
    uint32_t size;                 /* 库填写实际 sizeof；调用方读取 */
    uint32_t reserved0;
    uint64_t peer_node_id;         /* tcp/unix/pipe：必有真实值（HELLO 后交付）；inproc：见 §5.2；仅竞态下为 0 = 未知 */
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
 * **返回时点与入站交付对称（2026-11-03，N-03）**：成功返回时**双向 HELLO 已完成**——
 * `out_conn` 立即可收可发（含首条 DATA），`peer_node_id` 必有真实值。**超时口径（唯一）——两段相加**：
 * TCP 建立段最多 `connect_timeout_ms`，握手段固定 5000 ms
 * （线格式 §5 规则 5），**总等待上限 = `connect_timeout_ms + 5000`**。因此调用方设的短超时
 * 只会缩短 TCP 段，**不会**掐断一个可能成功的握手。任一段超时 → 返回 `ICOMM_ERR_TIMEOUT`；
 * 握手失败 / 版本不兼容 → `ICOMM_ERR_DISCONNECTED`。
 * 因此不存在「返回了但不能用」的半可用连接。
 * ep_owner 指定该连接归属哪个本地端点（用于 endpoint_send 扇出与
 * iocomm_conn_count 过滤）；传 0 表示不属于任何端点（只能点对点使用）。
 * **入站连接不需要（也无法）指定 ep_owner**：被持有后自动归属监听它的端点，见 §5.2 成员资格。
 * **自动重连（2026-11-04，N-06，见架构 §5.2c）**：断开后库按退避重连，**复用同一 `iocomm_conn_t` 句柄**；
 * 断开时在途未发项逐条 `DROPPED(PEER_GONE)`（异步 `on_done(DISCONNECTED)`），**重连不重放**；
 * `sequence` 随新连接从 1 重置；已登记的订阅保持，`peer_node_id` 以新握手结果更新。 */
int32_t iocomm_connect(iocomm_runtime_t rt, iocomm_endpoint_t ep_owner,
                       const char* transport, uint64_t transport_len,
                       const char* addr, uint64_t addr_len,
                       uint64_t connect_timeout_ms,
                       iocomm_conn_t* out_conn, iocomm_error* err);

/* 出站连接（异步）：**manual 模式的唯一建连路径**。
 * 立即返回；连接建立（**双向 HELLO 完成后**，与同步版同口径）、失败、超时、或 Runtime **销毁**时，
 * on_done **恰好触发一次**（`runtime_destroy` 路径下 code = `ICOMM_ERR_CANCELLED`）。
 * **`runtime_stop` 不取消在途建连**（见 §5.2 取消表）：on_done 仍会在建连完成/失败/超时时照常触发一次，
 * 调用方在 stop 后须继续驱动 loop 才能收到它（manual 模式）。
 * `on_done(OK)` 时交付的 conn 立即可收可发，`peer_node_id` 必有真实值。
 * **超时码以 on_done 为载体**：超时走 `on_done(ICOMM_ERR_TIMEOUT)`，版本不兼容/畸形走
 * `on_done(ICOMM_ERR_DISCONNECTED)`——**不是** [线格式 §2.1](wire-format.md)「接收方的观测面」中的 `on_done(DISCONNECTED)`：
 * 那一条描述的是**已建立连接**上的在途发送被协议错误终止，不覆盖建连阶段。
 * 成功时连接经 `on_done(OK)` 的 `conn` 参数交付；其余情况 `conn` 为 0，库内已回收所有资源。 */
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
```

#### 5.2a `connect_node` 的地址解析规则（2026-11-04 定，N-05）

`iocomm_connect_node*` 只收 `node_id` + 端点名，**不直接接收地址**。由库完成「发现结果 → 可拨号地址」的解析：

| 步骤 | 规则 |
|---|---|
| **0** | **先按 [§5.1a](#51a-端点名格式与长度上限2026-11-04-定n-17) 校验 `endpoint_name`**（1–255 B、合法 UTF-8、无 NUL、`/` 层级无空段）。不合规 → `INVALID_ARGUMENT`，**不进入发现表查找**——格式错误优先于「查无此名」 |
| 1 | 在 discovery 节点表中按 `node_id` 精确查找 `iocomm_node_info`。找不到（未发现 / 已 `LEFT`）→ `NOT_FOUND` |
| 2 | 在该节点的 `endpoints` 数组中按 `name` **精确字节匹配**（区分大小写；不含层级前缀匹配）找成员。没有同名成员 → `NOT_FOUND` |
| 3 | 取该 `iocomm_endpoint_info` 的 `transport` + `addr` 作为拨号目标，等价于调用 `iocomm_connect(ep_owner, transport, addr, …)` |
| 4 | `transport` 是本端未实现的传输（如 v2 对端上报 `"udp"` 而本端为 v1）→ `NOT_SUPPORTED` |
| 5 | 发现条目里的 `addr` **必须是通告值**（见下），库不得在此处再做通配地址替换——替换发生在**发送发现报文的一端**，接收端只使用 |

**`addr` 的语义（唯一口径）**：

- **`iocomm_endpoint_info.addr` = 通告值（可拨号）**，**不是**原始监听值。
  发布端点能力时：若 `listen_addr` 的地址是通配地址（`0.0.0.0` / `[::]`），替换为本端在该报文出口网卡上的具体地址；
  若端口为 0，替换为实际监听端口。组播信标的出口地址取决于 `iface_index`；因此**同一端点在不同网卡上可能通告不同地址**——以最近一次收到的报文为准。
- **`iocomm_endpoint_local_addr()` = 原始监听值**（通配地址原样保留，端口 0 换成实际端口），供本端排障使用。
- 理由：接收端不知道发送端的监听网卡，只有发送端知道「哪些地址能拨通自己」。在接收端做替换需要猜测源地址并额外记录「信标源 IP」，而 `ENDPOINTS` 是多端点共享一个源地址——发送端替换更简单且唯一。

**失败码汇总**（与 §3.2.1 的 `iocomm_connect_node` 行一致）：节点不存在 / 成员不存在 → `NOT_FOUND`；
transport 不支持 → `NOT_SUPPORTED`；其余同 `iocomm_connect`（`INVALID_ARGUMENT` / `TIMEOUT` / `DISCONNECTED` / `NO_RECEIVER` / `WOULD_DEADLOCK` / `RESOURCE_EXHAUSTED` / `INTERNAL`）。

> **异步版的一致性**：`iocomm_connect_node_async` 的同步返回只报「参数/句柄/资源」类错误；
> `NOT_FOUND` / `NOT_SUPPORTED` 若在**查找阶段**就能判定，走同步返回（不入队）；一旦开始拨号，
> 后续结果（`TIMEOUT` / `DISCONNECTED`）走 `on_done`。

```c
/* 接管一条连接但**不安排任何收发**（拉取模式）。
 * 这是**单条连接层面**唯一的显式持有动作（subscribe 是推送侧的等价持有；
 * 端点级 `iocomm_subscribe(ep)` / `endpoint_recv(ep)` 是无须逐连接调用的等价持有，见 §5.2）：
 * 在 accept 回调内调用后，该连接不再被自动回收，调用方可在其他线程
 * 对它调用 iocomm_conn_recv。**幂等**：对同一连接重复调用返回 ICOMM_OK，
 * 连接只有一个「C 侧所有权」。持有不与订阅冲突——但订阅与 recv 的
 * 二选一规则（§6.4）照常适用。
 *
 * **可在任意线程调用，含 accept 回调内**（2026-11-05，N-36）：它只改所有权表，
 * 不等待、不投递、不阻塞 ⇒ 矩阵（§3.2.1）里**没有** WOULD_DEADLOCK / TIMEOUT。
 * **retain 之后在回调外调 `conn_subscribe` 合法**（2026-11-05，N-41，与 ADR-002 的
 * 「`retain` 之后订阅是合法需求」一致）——两者是不同通道：retain 决定「谁持有」，
 * subscribe 决定「消息怎么送」，互不取消；但**订阅与 recv 的二选一照常适用**。
 *
 * **已由端点级推送/拉取持有的连接**（2026-11-05，N-38）：本函数只做所有权确认，
 * 返回 OK，**不改变投递路由**——消息仍在端点接收队列，`conn_recv` 对该连接返回
 * `INVALID_STATE`。详见 §5.2「端点级持有」。
 * **并发**：同一连接并发调 `conn_retain` 是安全的（幂等，内部串行化），返回码只取决于该连接是否有效。 */
int32_t iocomm_conn_retain(iocomm_runtime_t rt, iocomm_conn_t conn,
                           iocomm_error* err);

/* 立即关闭一条连接（入站或出站均可）。
 * **子对象随父对象销毁（总表）**：
 *
 * | 销毁 | 受影响 | 不受影响 |
 * |---|---|---|
 * | Runtime | 全部（端点 / 连接 / 订阅 / 监控者 / 快照），逐条 `on_done(CANCELLED)` | — |
 * | endpoint | 挂在它上面的订阅 / 监控者 / **入站连接**（FIN）；名字锁释放 | 出站连接（`ep_owner == ep` 的仍存活，只是不再计入扇出） |
 * | conn | 该连接上的订阅、接收队列剩余消息、在途异步发送 | 端点、其他连接 |
 * | subscription | 只是停止回调；**已入队的消息保留在端点/连接的接收队列里** | 端点、连接、消息 |
 * | monitor | 环与 arena 释放（v1.1）；之后的 `poll` 返回 `CLOSED` | 被监控的连接/端点 |
 *
 * 每条的详细语义见各函数注释；本表只给「谁受谁影响」。
 *
 * **同时触发时的裁决顺序（唯一口径）**：
 * 当多条终止规则命中同一条在途操作时，按下列优先级取**第一条命中的**：
 * **`on_done` 码只取一条**（不同时报告两个码）；**监控记录按该条规则给的那一格**——
 * 「不叠加」指码不叠加，不指监控记录。
 *
 * | 优先级 | 触发 | `on_done` 码 | 监控记录 |
 * |---|---|---|---|
 * | 1 | `runtime_destroy` | `CANCELLED` | 不产生（幂等销毁路径） |
 * | 2 | `endpoint_destroy`（扇出组） | `CANCELLED` | 不产生 |
 * | 3 | `conn_destroy` / `conn_abort` | `CANCELLED` | `DROPPED(PEER_GONE)`（若已入队） |
 * | 4 | 连接断开（含 `PEER_GONE`） | `DISCONNECTED` | `DROPPED(PEER_GONE)` |
 * | 5 | `send_cancel`（显式取消） | `CANCELLED` | **不产生**（用户主动取消不是丢弃） |
 * | 6 | `queue_timeout_ms` 到期 | `TIMEOUT` | `DROPPED(TIMEOUT)` |
 * | 7 | 正常完成 | `OK` | 无 |
 *
 * **`runtime_drain` 也不终止在途操作**：它只是等待；manual 模式下返回 `WOULD_BLOCK` 表示还需继续 `run_once`。
 *
 * **`runtime_stop` 不在此表**：它**不终止在途操作**——已登记的 `on_done` 会继续在
 * `run_once` / IO 线程上触发（stop 后不再接收新操作，但已登记的要跑完）。
 * 若 stop 后不再驱动 loop，这些回调**永远不触发**；这是调用方的责任，不是未定义行为。
 *
 * **在途异步发送一律取消**：每条未完成的 send_async 仍恰好触发一次
 * on_done(code = ICOMM_ERR_CANCELLED)（与 AC-27 的 Runtime 销毁路径一致）。
 * 发送缓冲中尚未交给传输层的数据直接丢弃；随后以 FIN 关闭。
 * **FIN 而不是 RST 的前提**：实现必须先 `shutdown(SHUT_WR)`，再**有界**读完接收缓冲
 * （上限 64 KiB 或 100 ms，先到者）后 `close()`——否则内核因「接收缓冲有未读数据」发 RST，
 * 对端看到的就不是 FIN（AC-33 / AC-33b 会失败）。
 * 不阻塞；任意线程可调用（同一连接的创建/销毁由调用方串行化，架构 §3.3）。重复调用返回 STALE_HANDLE。
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
| `iocomm_endpoint_t`（本地监听端点） | **扇出**：发给该端点的全部**成员连接**（它的全部入站连接 + `ep_owner == ep` 的出站连接）；没有成员连接时返回 `NO_RECEIVER` |

> **入站连接的所有权：借用语义**（完整理由见 [ADR-002](../adr/ADR-002-message-addressing-and-ownership.md)）。
> **交付时点**：本借用的起点是「双向 HELLO 完成」，不是「TCP 建立」——握手期的连接由库内部持有，
> 无 `iocomm_conn_t` 句柄、不占 `max_handles`、对应用不可见（见上方 `iocomm_accept_fn` 注释与 [线格式 §5](wire-format.md)）。
> 这与借用语义自洽：回调返回即收回的是**已经完成握手、可以正常收发的连接**，不存在「借出一个还不能用的连接」的窗口。
> `accept` 回调拿到的 `inbound` **只在回调期间有效**；**全部** `accept` 回调返回后若库仍没有观测到任何持有动作，
> 连接被自动收回并以 FIN 优雅关闭（**任一**回调完成持有即保留——同一端点可注册多个 accept 回调，
> 它们按注册顺序各触发一次，生命周期判定在全部跑完后进行；见 AC-33）。持有动作有**三种**：**显式 `conn_retain`**、**隐式
> `conn_subscribe`**、以及**端点级持有**——该监听端点已注册 `iocomm_subscribe(ep)` 或
> `endpoint_recv(ep)` 时，端点在**交付的同一时刻**接管它接入的入站连接（交付前是库的内部会话，见下方交付时点；机制见 §6.4）。
> `conn_send_async` 不是所有权开关——「发一条拒绝就走」用
> `send_options.flags = ICOMM_SEND_CLOSE_AFTER` 表达；不带 `CLOSE_AFTER` 的 `send_async`
> 若同时未持有，返回 `INVALID_STATE`，强制在回调内表态。
> **仅保存句柄不算持有**（库无法观测外部变量），该连接会被回收并返回 `STALE_HANDLE`。
> **无消费者端点（N-24）**：端点既未注册 `endpoint_accept`、也未启用 `iocomm_subscribe(ep)` /
> `endpoint_recv(ep)` 时，入站连接在交付时点**立即以 FIN 关闭**，不产生 `accept` 回调、
> 不产生任何监控记录/计数，写 `log_fn` 的 **WARN**（含端点名）。
>
> **成员资格**：入站连接被持有后即成为该监听端点的**成员**，参与 `endpoint_send` 扇出与
> `conn_count(ep)`；语义与 `ep_owner == ep` 的出站成员连接相同。（2026-11-03 修正 N-01：
> 此前「入站连接不归属端点、不参与扇出」的规定已废止——它使纯服务端无法广播。）

> **manual 模式的建连路径**：`iocomm_connect_async` / `iocomm_connect_node_async`。同步版本在 loop 驱动线程上一律返回 `WOULD_DEADLOCK`。
> **`endpoint` 与 `conn` 是两个独立句柄空间**，不能互相替代。

---

## 6. 发送与接收

### 6.0 队列与句柄的默认值（**唯一权威**）

| 参数 | 默认 | 单位 | 说明 |
|---|---|---|---|
| `send_queue_max` | **1024** | 条 | 每个端点的发送队列上限 |
| `recv_queue_max` | **1024** | 条 | 每个端点的接收队列上限 |
| `max_message_size` | **1 MiB** | 字节 | 见 §9.3；**上限 64 MiB**（超过则单条消息永远进不了队列）；**下限 56 B**（`20` 帧头 + `SEQ`/`TS_SEND`/`SOURCE_NODE` 三项必填 TLV 共 36 B，低于此值则任何 `DATA` 帧都无法通过校验） |
| `max_handles` | **4096** | 个 | 本 Runtime 内**五类对象句柄合计**（endpoint / conn / subscription / snapshot / monitor），**不含 Runtime 自身**（Runtime 是句柄表的主人，不占名额）；**入站连接只在交付时计入**——双向 HELLO 完成后 `accept` 分配 conn 句柄时才占用；**握手期的内部会话占位不分配句柄、不占名额**（§5.2、线格式 §5） |

- 队列上限**同时**受条数与字节约束：条数 ≤ `queue_max`，字节总量 ≤ `min(queue_max × max_message_size, 64 MiB)`。
- `max_message_size > 64 MiB` → `runtime_create` 返回 `INVALID_ARGUMENT`（否则单条消息永远进不了队列）。
- **字节上限**：`runtime_config` **不提供独立字段**（避免多一个旋钮）。超过字节上限时按该端点策略处理（与条数满同口径）。
- 默认值下：条数上限 1024 条，字节上限 64 MiB 每队列。最坏情况（消息都是 1 MiB）是 **64 条即满**，而不是 1024 条。
- 句柄超限：`endpoint_create` / `connect*` / `subscribe` / `conn_subscribe` / `discovery_snapshot_take` / `monitor_open` 一律返回 `ICOMM_ERR_RESOURCE_EXHAUSTED`。
- **握手期内部会话的上限（2026-11-03 定，2026-11-04 补口径 N-18）**：交付前（双向 HELLO 完成前）的入站会话不占 `max_handles`，但**并非无界**——**每端点**并发握手会话数 ≤ `max_handles`（**独立计数器**，与五类对象句柄表互不占用，AC-84 不受影响），超出时**直接关闭新接受的 socket**（不触发 `accept` 回调）。
  **总上限因此是 `端点数 × max_handles`**（默认 4096 × 4096 ≈ 1.7e7）——它是一个**软上界**，不等于「Runtime 全局 fd 上限」。因此：
  - 这条保护真正防的是「**单个端点**被大量半开会话淹没」——被拒的 socket 立刻关闭，不占用任何持续资源；
    它不是句柄名额保护（握手会话本来就不进五类对象句柄表，见上一条），
    **也不是**「Runtime 全局 fd 不会耗尽」——全局 fd 耗尽仍由部署侧的 `ulimit -n` / 系统上限兜底。
  - 若要全局上限，`max_handles` 已经约束了**已交付**连接的总数；握手期会话没有对应的全局旋钮是 v1 的已知取舍（见 `open-questions.md` N-18），v1.1 可按需在 `runtime_config` 尾部追加（尾部追加不破坏 ABI）。
  该拒绝是**本地资源保护**，不是协议错误：**不**计入 `stats.protocol_errors`（该计数只统计接收侧收到 `ERROR` / 判定帧损坏），也**不**计入 `queue_dropped`（被拒 socket 从未入队）；可见性只靠 `log_fn` 的 **WARN**（文本含**端点名**、当前握手会话数与上限，便于按端点聚合），不新增计数——理由是要给这两个既有计数保留唯一含义，宁可少一个可观测量也不让它们变成第二种口径。
- **交付时句柄表已满（2026-11-04 定，N-19）**：双向 HELLO 已完成、但 `accept` 需要新 conn 句柄而句柄表已满时：
  **不交付、不触发 `accept` 回调、立即 FIN 关闭该连接**（不留内部会话，避免长期占 fd），并写 `log_fn` 的 **ERROR**（含端点名与对端地址）。
  与握手表满同口径——**不**计入 `protocol_errors` / `queue_dropped`。选择关闭而不是「排队等句柄」的理由：排队会无限期占用一条已可用的 socket，且在内存压力下（表满往往正是内存/资源紧张）把问题放大。
  **调用方如何自查容量**：`iocomm_conn_count(rt, 0)` 是**实时存活连接数**（含 `ep_owner == 0` 的连接），可以直接读；但**五类对象句柄合计（Runtime 不占）的占用没有公开计数**——调用方须据 `max_handles` 与自己创建的端点 / 订阅 / 快照 / 监控者数量自行估算。两者之差（如"连接数远小于 `max_handles` 却仍被拒"）说明名额被非连接类句柄占住。验收：**AC-113**。
- **每个 Runtime 有独立的句柄表与计数**（AC-80 允许多个 Runtime 并存）。

### 6.1 溢出策略（每端点一个队列）

```c
/*
 * **队列归属规则（唯一口径）**：
 *   - **成员连接**（`ep_owner == ep` 的出站连接，以及被监听端点持有的入站连接——见 §5.2）
 *     共用该端点的**一条发送队列**——这是 FR-4.6 的有界资源，
 *     容量 `send_queue_max` **条**，且字节总量 ≤ **64 MiB**（§6.0）——**发送队列**的占用上界与连接数无关；
 *     接收方向则是「端点一条 + 每连接各一条」，总数随连接数增长（上界 = `(1 + N) × recv_queue_max`）；
 *   - **每个队列项都携带目标连接句柄**（`conn_send` 填该连接；`endpoint_send` 扇出时为 N 个独立项）；
 *   - **入站连接**：在**交付时点（双向 HELLO 完成）**才可能进入 `accept` 回调，回调内即确定为「拒绝」还是「持有」——
 *     拒绝时**不分配**发送队列；握手期的内部会话占位从不分配 conn 句柄、不占队列与 `max_handles` 名额。
 *     持有后（`conn_retain` / `conn_subscribe` / 端点级订阅）即成为**监听端点的成员**，
 *     与 `ep_owner == ep` 的出站连接**共用该端点的发送队列**，参与 `endpoint_send` 扇出与 `conn_count(ep)`。
 *     **`CLOSE_AFTER` 不是持有动作**（FR-8.8「发送不是所有权开关」）：它只把连接保持到数据 flush
 *     完毕并立即关闭，因此**不产生成员资格**、不参与扇出、不分配发送队列。
 *     > 2026-11-03 修正 N-01：此前「按不归属端点处理、各自一条队列、不参与扇出」的规定已废止——它使纯服务端无法广播。
 *   - 不归属任何端点的连接（`ep_owner == 0` 的出站连接）各自有一条队列，容量取 runtime 默认；
 *   - 接收方向：端点一条接收队列，连接一条接收队列（同样带归属）；
 *   - 溢出策略按端点取一个值，作用于该端点队列及其连接队列（ADR-002）。
 *
 * **`connect_async` 未完成时 `conn_destroy`**：此时尚无 conn 句柄可供销毁——
 *   只能用 `runtime_destroy` 或 `runtime_stop`（后者不终止，见下节裁决表）。
 *   `conn_destroy` 只接受已建立的连接句柄。
 *
 * **`conn_destroy` 如何精确取消**：扫描该连接所属队列，摘除 `target == conn` 的项。
 * 因此「每条未完成的 send_async 恰好触发一次 CANCELLED」（AC-76）可实现，且代价只与队列长度相关。
 *
 * **代价一：慢 peer 挤占共享容量**（与 ZeroMQ 的 per-peer HWM 相反，属有意取舍）。
 * 一条连接写不动时，它的项会占满共享队列，**其他连接的新消息因此遭遇溢出策略**——
 * 这是真正的跨连接影响，且与策略有关：
 *   - `DROP_OLDEST`：被丢的是**队头**（通常是慢 peer 自己的旧项），其他连接的新消息能进队；
 *   - `DROP_NEWEST`：被丢的是**其他连接的新消息**——跨连接影响最直接；
 *   - `ERROR`：其他连接的新消息被拒（`BACKPRESSURE`）。
 * 与 FR-4「慢消费者不阻塞发布者」一致，但**不等价于**「不影响其他连接」。
 * 需要几何隔离时把它们拆成不同端点；严格 per-peer 隔离不在 v1 范围。
 *
 * **代价二：队头阻塞**。队列严格 FIFO、不分连接轮转——队头项所属连接写不动时，
 * 后续项**不会**跳过（跳过会破坏同一连接内的顺序，而顺序是 per-source `sequence` 的前提）。
 * 这是共享队列模型的必然结果，不是实现缺陷。
 *
 * 一个端点 = 一条发送队列 + 一条接收队列 + 一个策略（ADR-002）。
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

> **心跳不走端点发送队列**：心跳是**连接级控制帧**，直接由连接自己的发送路径发出，
> 不经过端点队列、不受端点溢出策略影响、也不产生 `SENT` / `DROPPED` 记录。
> 否则慢 peer 会让心跳排在其数据后面 → `Lively` 误判为 False。
>
> **心跳的背压**：对端不读时心跳**最多缓存 1 条**（只保留最新序号），覆盖旧的——心跳是「最新状态」，
> 丢旧的没有语义损失。连续 `heartbeat_miss_limit` 次**发送失败**只计数、**不单独判死**——
> `Lively` 的唯一判据是「连续 `heartbeat_miss_limit` 次**未收到**对端心跳」（见架构 §6.2），
> 发送失败会自然导致对端收不到、进而触发该判据。两者不要混用。
> **计数口径**：心跳**计入** `stats.bytes_sent` / `bytes_received`，**不计入** `messages_sent` / `messages_received`。
>
> **`BLOCK` 只在同步发送的调用者线程上真阻塞**（最多到发送的 `timeout_ms`，超时返回 `ICOMM_ERR_TIMEOUT`，见下方 §6.2b）。
> 在**异步发送**与**接收侧入队**上，`BLOCK` 一律自动退化为 `ERROR`：本库的异步卖点是「立即返回」，
> 在调用方线程阻塞等于把异步用成同步；接收侧入队发生在 loop 线程，真阻塞会让唯一的事件循环自锁。
> 这是**运行时保护**，不是配置错误。
>
> **`ERROR` 的返回码与计数**：入队失败返回 `ICOMM_ERR_WOULD_BLOCK`；本表所列的运行期丢弃/拒绝都计入 `iocomm_stats.queue_dropped`（值定义见 §8 `iocomm_stats.queue_dropped`）。
> 同步发送直接返回该码；异步发送通过 `on_done(code = ICOMM_ERR_WOULD_BLOCK)` 报告。
>
> **接收侧**共用同一端点的策略；`BLOCK` 永不生效，`ERROR` 的语义固定为「丢弃 + 计数 + 产生
> `DROPPED(reason = QUEUE_FULL)`」，**不关闭连接**（接收侧没有可返回失败的调用方）。
>
> **两个 reason 的分界（唯一口径）**：分界依据是**策略**，不是方向。
> - 队列满 + `DROP_OLDEST`：旧项**曾被接受**、后被挤出 → `QUEUE_FULL`（发送侧、接收侧都适用）
> - 队列满 + `DROP_NEWEST`：**新消息从未被接受** → **仍记 `QUEUE_FULL`**（理由：按**策略**分界而非方向，见 §6.1；实现者不要因「未被接受」改记为 `BACKPRESSURE`）
> - 队列满 + `ERROR` → 消息**未被接受** → `BACKPRESSURE`；接收侧没有可返回失败的调用方，
>   按 §6.1 固定为「丢弃 + 计数 + `DROPPED(QUEUE_FULL)`」，因此 `BACKPRESSURE` 实际只出现在发送侧。
>
> **失败源的优先顺序**见上方「入队前失败」表：连接已断优先于队列满。

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
     * 0 = 无截止（默认；**异步特有**，与同步 `timeout_ms` 的 0 义不同，见 §6.2b）。
     * 开始写之后不再受此超时约束——
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
/* CLOSE_AFTER 与失败路径的裁决：
 *   - 消息**成功交给传输层** → on_done(OK) **之后**发 FIN；
 *   - 消息**入队前失败**（TOO_LARGE）→ 同同步返回报告，**连接保持打开**（没有数据要「发完」）；
 *   - 消息**入队前因连接已断/队列满失败** → 连接本就要断或该 op 被拒，**不改变连接状态**；
 *   - 消息**入队后被丢弃**（DROP_OLDEST 丢中它 / 排队超时）→ 该 op 报对应码，连接保持打开；
 *   - **`accept` 回调内**用 CLOSE_AFTER 时：**入队前的失败仍走同步返回**（该连接随后关闭，
 *     因为回调返回后无人持有）；**入队后**的失败（被丢弃 / 排队超时）走 `on_done`，随后 FIN。 */

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

/* 异步扇出到一个本地端点当前的所有连接。
 * 无连接时：on_done(code = ICOMM_ERR_NO_RECEIVER)，且若该端点有监控者，
 * 产生一条 DROPPED(NO_SUBSCRIBER)（FR-10.3 的 no_subscriber 原因）。
 * 码与记录是同一事件的两种视图，不互相替代。
 *
 * **部分失败**：`on_done` 只有单个 `code`，无法表达「7 条成功 3 条失败」。因此：
 *   - `code = ICOMM_OK` ⇔ **全部**目标连接都成功入队；
 *   - `code = ICOMM_ERR_WOULD_BLOCK` ⇔ **全部**失败（部分失败不会报这个码）；
 *   - 部分失败报 `ICOMM_OK` + 通过 `iocomm_stats.queue_dropped` 反映丢失数；
 *   - 需要逐连接结果时用 **`conn_send_async` 逐条发**，或用监控环的 `DROPPED` 记录。
 * 这与同步版（`out_delivered < N`）的信息量**不等价**——这是异步扇出的已知取舍。 */
int32_t iocomm_endpoint_send_async(iocomm_runtime_t rt, iocomm_endpoint_t ep,
                                   const iocomm_send_options* opt,
                                   iocomm_slice payload,
                                   void (*on_done)(void* user, int32_t code,
                                                   uint64_t op_id),
                                   void* user, uint64_t* out_op_id,
                                   iocomm_error* err);

/* 取消一个未完成的异步发送。on_done 仍会被调用一次，code = CANCELLED。
 * `op_id` 对 `conn_send_async` 是「一条消息」；对 `endpoint_send_async` 是**整组**：
 * 取消会移除该组中尚未开始写的全部队列项，`on_done` 仍只触发**一次**（整组计）。
 * 已经开始写的项不取消（与排队超时同口径，见 §6.2b）。
 *
 * **`op_id` 的唯一性（2026-11-04，N-10）**：
 *  - **作用域 = 每个 Runtime**（不是每连接 / 每端点）。两路 `send_async` 产出的 `op_id` 互不相同；
 *  - **单调分配、永不回绕**（与 `capture_id` 同口径）：从 1 起递增，`send_cancel` 因此不会误伤
 *    一个复用了同一 ID 的历史操作；
 *  - **耗尽**（64 位空间用完）→ `send_async` 返回 `RESOURCE_EXHAUSTED`，不静默回绕。
 *    按 10 万条/秒估算需约 580 万年，实际不可达，但语义必须唯一。
 *
 * **`send_cancel` 对各类 `op_id` 的返回**：
 *  | `op_id` 状态 | 返回 |
 *  |---|---|
 *  | 未完成、已成功取消 | `ICOMM_OK`；该 op 的 `on_done(CANCELLED)` **仍会触发**（恰好一次） |
 *  | 已完成（`on_done` 已触发） | `ICOMM_ERR_NOT_FOUND`，**不再**触发 `on_done` |
 *  | 已被取消过 | `ICOMM_ERR_NOT_FOUND`，**不再**触发 `on_done`（幂等失败） |
 *  | 从未在此 Runtime 分配过 | `ICOMM_ERR_NOT_FOUND` |
 *
 *  **作用域是本 Runtime**：`op_id` 里不含 Runtime 标识，两个 Runtime 各自从 1 编号必然重号。
 *  因此 `send_cancel(rt, op_id)` 的**唯一判据是「rt 自己的操作表里有没有这个 id、处于什么状态」**，
 *  完全由上表决定；「这个数值原本属于哪个 Runtime」不是判据。所以把 A 的 `op_id` 传给 B **不在契约内**：
 *  若 B 恰好有同号操作，就会真的取消 B 的那个操作——这正是 `op_id` 不可跨 Runtime 使用的原因。
 *  实现上不额外编码 Runtime 标识：那会让 `op_id` 不再是简单计数器，且对正确用法毫无收益。 */
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
- **开始写之后不再超时**：从「帧的第一个字节交给传输层」起就不再受 `queue_timeout_ms` 约束。
  ① **若已写出部分字节**，中途放弃只能 RST 整条连接（帧已残缺），那属于 `conn_abort`；
  ② **若一个字节都还没写出**，取消本可允许，但「开始写」与「写出首字节」之间的窗口不可观测，
  为保持唯一口径统一以「开始写」为界。超时只用于「排队等不到写机会」，不用于「写得太慢」。
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
    uint64_t sequence;           /* **每来源连接**的单调序号（不是 node 级全局序号）；重连后新连接从 1 重计，
                                  * 断开前后不可比——跨重连顺序靠 `correlation_id`（N-06，架构 §5.2c） */
    uint64_t timestamp_ns;       /* 发送方事件时间 */
    uint64_t correlation_id;     /* 0 = 无 */

    uint8_t  clock_synced;       /* 时间戳所在时钟是否已同步。**v1 恒为 0**——本库不做时间同步
                                  * （PTP/NTP 不在范围内），因此没有任何路径会把它置 1。
                                  * 字段与线格式 `CLOCK_SYNCED` tag 保留给 v2；调用方必须按 0 处理，
                                  * 不得据此认为「两端的 timestamp_ns 可比」（跨机比较本就不可信，
                                  * 见架构 §6.5）。排序以 `sequence` 为权威，不以时间为权威。 */
    uint8_t  reserved1[7];
} iocomm_message;

#define ICOMM_MESSAGE_INIT { sizeof(iocomm_message), 0, {NULL,0}, \
                             0, 0, 0, 0, 0, 0, {0} }

/* 订阅推送。ep 是**本地监听端点**，接收其**全部入站成员连接**的消息。
 * **端点级持有（唯一口径，2026-11-03 N-02）**：在该端点启用本订阅（或 `endpoint_recv(ep)`）后，
 * 该端点接入的入站连接在**交付的同一时刻**由端点接管，**不再需要**在 accept 回调内
 * 调 `conn_retain` / `conn_subscribe`——**但调了也不报错**：`conn_retain` 返回 `OK`（只确认所有权，
 * 不改路由），`conn_subscribe` 返回 `INVALID_STATE`（已由端点持有）。见 §6.4 `@special` 与 AC-119；`accept` 回调本身仍会触发，仅用于观测新连接。
 * 未注册 `endpoint_accept` 时，入站连接同样由本订阅隐式持有并正常投递——
 * 这是「只读端点、不关心单条连接」的服务端主用法。
 * 与 `conn_subscribe` 的关系：端点级订阅对**此后接入**的成员连接生效；
 * 已存在的入站连接需按 §6.4 的端点/连接互斥规则另行判定。 */
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
 * loop 线程（含回调内）调用返回 WOULD_DEADLOCK——**唯一例外**：在**本订阅自己的回调内**
 * 取消本订阅返回 ICOMM_OK，语义为「本次回调跑完后不再触发」（见 §6.4 @special）。
 * 该例外是 AC-5 的显式豁免，不适用于取消其他订阅。 */
int32_t iocomm_unsubscribe(iocomm_runtime_t rt, iocomm_subscription_t sub,
                           uint64_t timeout_ms, iocomm_error* err);

/* 拉取式接收（与 subscribe 二选一，见 §6.4）。
 * 端点级 recv 的隐式持有规则与 `iocomm_subscribe(ep)` 相同（见上）：
 * 启用后，该端点的入站连接在**交付时**由端点接管，消息进入**端点接收队列**。
 * **成员连接的 `conn_recv` 不可用**（2026-11-05，N-38）：这些连接的消息在端点队列里，
 * 对它们调 `conn_recv` **立即返回** `ICOMM_ERR_INVALID_STATE`（**不等待** `timeout_ms`；与 §6.4
 * 「先 subscribe 再 recv」同码）；`conn_retain` 对此**不改变路由**。
 * **与 `WOULD_DEADLOCK` 的优先级**：两者同时成立时（loop 线程 + 已由端点持有）**返回 `INVALID_STATE`**——
 * 它是**静态前置条件**检查，先于线程检测（与 §3.2.1「参数校验先于其它」同序）。 */
int32_t iocomm_endpoint_recv(iocomm_runtime_t rt, iocomm_endpoint_t ep,
                             iocomm_message* out, uint64_t timeout_ms,
                             iocomm_error* err);
/* `conn_recv` 的**前置条件**：该连接尚未启用 `conn_subscribe`、且**未由端点级收消息持有**
 * （否则返回 `INVALID_STATE`，见上方与 §6.4）。它**等待至多 `timeout_ms`**，超时返回 `TIMEOUT`；
 * 在 loop 线程调用返回 `WOULD_DEADLOCK`。 */
int32_t iocomm_conn_recv(iocomm_runtime_t rt, iocomm_conn_t conn,
                         iocomm_message* out, uint64_t timeout_ms,
                         iocomm_error* err);

/* 释放 recv 返回的消息。可重复调用（幂等）。 */
void iocomm_message_release(iocomm_message* msg);
```

### 6.4 拉取与推送的互斥规则

> **正交性：`endpoint_accept` 不受本节约束**（2026-11-05，N-37）。
> `iocomm_endpoint_accept` 只注册「**新入站连接的交付**」回调，与「**已建立的连接怎么收消息**」
> （`iocomm_subscribe(ep)` / `iocomm_endpoint_recv(ep)` / `conn_subscribe` / `conn_recv`）是**两条正交的轴**，
> **没有互斥关系，可任意顺序注册**。行业口径一致：Asio 的 `async_accept` + `async_read`、Netty 的
> `ChannelInboundHandler` + `read()`、OPC UA 的 Publish 与 Read 都分成两条轴，而非二选一。
>
> **对同一端点重复注册 `endpoint_accept` 合法**：每次返回各自的订阅句柄，交付时全部回调
> **按注册顺序各触发一次**。
>
> 本节下面的「二选一」**只约束接收对象本身**（同一个端点的推送与拉取、同一条连接的推送与拉取）。
> 历史注记：矩阵曾把 `endpoint_accept` 与 `iocomm_subscribe` 写在同一条错误码行内，
> 该写法已废止——`endpoint_accept` 不再返回 `INVALID_STATE`（§3.2.1）。

同一个接收对象（端点或连接）上，`subscribe` 与 `recv` **二选一**：

| 情形 | 行为 |
|---|---|
| 先 `subscribe` 再 `recv` | `recv` 返回 `ICOMM_ERR_INVALID_STATE` |
| 先 `recv` 再 `subscribe` | `subscribe` 返回 `ICOMM_ERR_INVALID_STATE` |
| 两者都未设置 | 消息进入**端点/连接的接收队列**，直到队列满后按溢出策略处理 |

> **端点级与连接级是两套独立的接收对象**（2026-11-03 N-15）：
> 入站成员连接的消息默认进入**端点接收队列**（这是 `endpoint_recv` / `iocomm_subscribe(ep)` 的来源）；
> 只有通过 `conn_subscribe` / `conn_retain` **单独接管**的连接，其消息才改进入**该连接的接收队列**
> （由 `conn_recv` 消费），且该连接不再参与端点级投递。二者互斥，不会双投。
>
> **路由在「端点级持有」成立那一刻即定死**（2026-11-05，N-38）：该端点已启用
> `iocomm_subscribe(ep)` / `endpoint_recv(ep)` 时，其入站连接在交付时点就由端点接管，
> 此后对该连接调 `conn_retain` **只确认所有权、不改路由**（返回 `OK`，消息仍进端点队列，
> `conn_recv` 返回 `INVALID_STATE`）；调 `conn_subscribe` 同样返回 `INVALID_STATE`。
> 上表「单独接管」指的是**端点级收消息未启用**时的 `conn_subscribe` / `conn_retain`——
> 那种情况下由它们把连接从「无消费者」状态接出来并绑定到连接接收队列。

> 这条规则消除了「谁消费、是否双投、背压如何合并」的歧义。若确实需要两种消费方式，请使用**两个不同的端点/连接**。

**回调规则（**对所有回调类型**通用，必须写进头文件注释）**：

适用于：`iocomm_message_fn`、`iocomm_accept_fn`、`iocomm_condition_fn`、`iocomm_discovery_fn`、`iocomm_connect_async.on_done`、`iocomm_conn_send_async.on_done`、`iocomm_endpoint_send_async.on_done`。

```
@thread  在 Runtime 的事件循环线程上调用（不是调用方线程）。
         loop 线程 ID 在**首次 `run_once`（manual）/ 启动 IO 线程（owned）时确定，`stop` 前不变**；
         同步入口据此判别 `WOULD_DEADLOCK`（见 [架构 §3.3](../architecture.md)）。
@lifetime 回调参数中的指针/切片只在本次回调期间有效
         （例外：明确标注「静态存储期」的字符串可长期缓存）。
@forbid  阻塞型调用；销毁**非本回调交付的**连接/订阅；**销毁端点**（`endpoint_destroy`）。
         违反一律返回 ICOMM_ERR_WOULD_DEADLOCK，**而不是死锁**。
         **`timeout_ms == 0` 的 `runtime_stop` / `runtime_drain` 不返回该码**——它们不等待，不会自锁
         （矩阵见 §3.2.1；`drain(0)` 在 manual 模式下本就是正常用法）。**是否**在回调内这么做由调用方自行判断，
         本条只消除「矩阵说不返回、本段说一律返回」的矛盾。
         **`timeout_ms > 0` 时两者仍属本项**：等待即自锁。
         **`runtime_destroy` 返回 void、没有错误通道**——它不属「返回某个码」的情形，而是
         **不得在回调内调用**（行为未定义）；请在回调返回后再销毁 Runtime。
@special 以下调用**允许**，但语义特殊：
         - `unsubscribe(本订阅)`         → ICOMM_OK；本次回调跑完后不再触发
         - `conn_destroy(本回调的 conn)` → ICOMM_OK（accept 回调内为拒绝；订阅回调内为关闭）。
                                           **多次 accept 注册时**：若 A 回调内 destroy 了连接，**其后尚未执行的
                                           accept 回调不再触发**（连接已不在，交付序列终止）；已触发的回调不受影响。
                                           2026-11-05，N-37
         - `send_cancel`                 → 允许；**取消已完成的 op 返回 `NOT_FOUND`，不会再触发 `on_done`**
                                           （「恰好一次」是硬约束，不允许在 on_done 内取消自己导致第二次回调）
         - `monitor_close`               → 允许（监控回调不存在，故仅 on_done 场景）
         - `discovery_stop`              → 允许；本次 discovery 回调跑完后停止
         - `runtime_wakeup`              → 允许
         - `conn_retain` / `conn_subscribe` → 允许，**不返回** `WOULD_DEADLOCK`。
                                           **若该端点已启用端点级收消息**，两者的行为**不同**：
                                           `conn_retain` **只做所有权确认、返回 `OK`、不改投递路由**（消息留端点队列）；
                                           `conn_subscribe` **返回 `INVALID_STATE`**（该连接已由端点持有，见矩阵与 §5.2）。
                                           **若未启用**，`conn_retain` 把投递切到**该连接的**接收队列、`conn_subscribe` 把消息改走订阅回调——
                                           这是「接管」的正常语义。
         - `endpoint_accept` / `conn_condition_subscribe` / `endpoint_condition_subscribe`
                                         → 允许（注册类入口，非阻塞、同步生效；同样**不返回** `WOULD_DEADLOCK`。
                                            线程口径见架构 §3.3——它们与 `subscribe` 同级，须串行化或经 loop 线程调用）
         - 任何**异步**发送 / 连接            → 允许（内部投递到 loop）
@except  `iocomm_accept_fn` 的 inbound 句柄**可以**在回调内 conn_destroy
         （用于拒绝入站连接），不返回 WOULD_DEADLOCK
@allow   回调内允许：读取快照、发起异步操作、**创建端点与异步连接**（`endpoint_create` / `iocomm_connect_async` / `iocomm_connect_node_async`）。
         **同步 `iocomm_connect` / `iocomm_connect_node` 不在其列**——它们是阻塞型调用，属上面的 `@forbid`（返回 `WOULD_DEADLOCK`）。
         **为什么允许在回调内建端点**（2026-11-05，N-49）：曾被收窄为「仅连接」，理由是
         「回调内建的端点在本轮内无合法销毁途径、会泄漏」——**该理由不成立**：`@forbid` 只约束
         **回调执行期间**，回调返回后随时可 `endpoint_destroy`，没有泄漏。收窄反而制造了
         「不在 `@forbid`、矩阵也无对应码」的三不管状态，故**维持允许**。
         **注意**：`endpoint_create` 是**非阻塞型**调用，在 loop 线程**合法**（不受 FR-6.7 约束）。
         **可重入**：同一回调内连调两次 `endpoint_create` 合法；**但在本回调内新建的端点不能在本回调内销毁**
         （`endpoint_destroy` 属 `@forbid`）——请在本轮回调返回之后再销毁。
@on_destroy
         Runtime 销毁时，所有尚未触发的异步回调**恰好以 CANCELLED 触发一次**。
         已在执行中的回调会先跑完，再销毁。
```

> **`on_done` 的触发语义**（`send_async` / `connect_async`）：**对已登记的操作恰好一次**——成功、失败、超时、取消、Runtime 销毁，五种路径都算。
> **登记失败的调用不产生回调**（见下条）。

> **「谁负责报告」的分界**（`send_async`）：同步返回值只报告**不可能再回调**的错误——句柄无效 / 参数非法 / 在 accept 回调内未表态 / 端点未监听等。
> 一旦操作已登记（返回 `ICOMM_OK`），**后续一切结果都走 `on_done`**：`OK` / `WOULD_BLOCK` / `TIMEOUT` / `CANCELLED` / `DISCONNECTED`。
> **`TOO_LARGE` 不在此列**——它在入队前检查，走同步返回（§9.3、AC-78）。
> 因此 **`on_done` 恰好一次**只对「登记成功」成立；同步返回非 `OK` 时 `on_done` **不会**被调用。

---

## 7. 发现

> **v1 是单发现域**（2026-11-05，N-44）：组播组地址与 UDP 端口**不可配置**（见 [线格式 §8.1](wire-format.md)），
> 因此同网段内所有启用发现的 Runtime 互相可见。**本结构体没有、v1 也不会加入** `domain_id` / `multicast_addr` 字段。
> 需要互不可见的通信域请在部署层用 **VLAN / 交换机 ACL / 独立网卡 / netns**；**域 ≠ 安全边界**（v1 无认证无加密，需求 §4.1）。
> 关闭组播（`enable_multicast = 2`）+ 配置 seed **不是**分域手段——对端仍可单播找到本端。

```c
typedef struct iocomm_discovery_config {
    iocomm_abi_header hdr;

    uint8_t  enable_multicast;     /* 0 = 用默认（**开**）；1 = 明确开启；2 = 明确关闭。
                                    * 关闭组播后**必须配置 seed 列表**（`seeds`），否则只能靠本机注册表发现。
                                    * 非 0/1/2 → INVALID_ARGUMENT */
    uint8_t  reserved8[3];
    uint32_t iface_index;          /* 0 = 自动；否则只在该网卡上收发组播 */
    uint32_t reserved0;

    uint64_t heartbeat_ms;         /* 0 = 默认 2000 ms */
    uint64_t lease_ms;             /* 0 = 默认 6000 ms（= 3 个心跳周期）；超时即判定离线 */

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
    const char* addr;          /* **静态存储期**；**通告值（可拨号）**，不是原始监听值——
                                * 通配地址 / 端口 0 已由发送端替换，见 §5.2a 与 FR-8.12 */
    uint64_t    addr_len;
} iocomm_endpoint_info;

typedef struct iocomm_node_info {
    uint64_t node_id;
    const char* name;              /* 对端的 runtime_config.node_name；未配置时为空串 */
    uint64_t    name_len;          /* 均为 **静态存储期** */
    uint32_t endpoint_count;
    const iocomm_endpoint_info* endpoints;  /* 数组：快照路径有效至 `snapshot_release`；
                                              * `discovery_event` 路径**仅本次回调**（见 `@lifetime`） */
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
/* 生命周期：**仅本次回调**；字节演进只做尾部追加，本结构体**不带 `size`**
 * （v1 不承诺跨版本二进制兼容，宿主用 `abi_version` 协商）。 */

typedef void (*iocomm_discovery_fn)(void* user, const iocomm_discovery_event* ev);

int32_t iocomm_discovery_start(iocomm_runtime_t rt,
                               const iocomm_discovery_config* cfg,
                               iocomm_discovery_fn fn, void* user,
                               iocomm_error* err);
/* 本机发现的发布范围（FR-2.6，机制见架构 §6.4b）：
 *   - 发布的是 `publish_local = 1` 的全部端点；**先于 discovery_start 创建的端点也会被扫描补发布**
 *     （不需要保证 discovery_start 在端点创建之前）；
 *   - 单元文件放在**每用户的固定目录**（`$XDG_RUNTIME_DIR/iocomm/local/` 等），**与本 Runtime 的 `state_dir` 无关**；
 *     同一用户下的 Runtime 互相可见，跨用户不可见；
 *   - `discovery_start` 无法写单元文件 → `INTERNAL`（不静默降级）；启动后写失败 → ERROR 日志并重试。 */
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
/* 非幂等：重复释放返回 STALE_HANDLE（与 FR-1.2 一致）。
 * **无错误通道**（AC-95 豁免）：`0` = 成功，非 0 = 错误码（`STALE_HANDLE` / `INTERNAL`）。 */
int32_t  iocomm_discovery_snapshot_release(iocomm_runtime_t rt, iocomm_snapshot_t s);
```

> **所有字符串均为静态存储期**（库持有），**不使用「紧随其后的变长区」**——那会破坏 `hdr.size` 的版本模型。

> **入参字符串的所有权（唯一口径）**：所有 `const char*` 入参（`state_dir` / `node_name` / 端点 `name` /
> `listen_transport` / `listen_addr` / `connect` 的 `transport` / `addr` / `seeds[]`）**库一律在调用返回前深拷贝**，
> 调用方可在返回后立即释放。**唯一例外**：**输出**字符串（`node_info.name` /
> `endpoint_info.*` / `strerror`）由库持有，生命周期见各自注释。
> **不要**依赖「库保留指针」——那是未定义行为，且未来版本可能改为引用计数。

---

## 8. 状态与指标

```c
typedef enum iocomm_condition_status {
    ICOMM_COND_UNKNOWN = 0,
    ICOMM_COND_TRUE    = 1,
    ICOMM_COND_FALSE   = 2,
} iocomm_condition_status;

struct iocomm_peer_status {
    uint32_t size;                 /* 库写入 sizeof(iocomm_peer_status)；调用方无需预置（§3.1） */
    uint32_t reserved0;

    uint64_t peer_node_id;
    /* 条件集（FR-5.1）：值为 iocomm_condition_status。
     * 自动重连期间（N-06）：句柄不变，`connected` = FALSE（确知未连通）→ 重连成功后 TRUE；
     * `lively` / `healthy` 在重连后的心跳窗口未满前为 UNKNOWN。AC-105 观测该序列。 */
    uint8_t connected;
    uint8_t lively;
    uint8_t healthy;             /* 最近一个判定窗口内无重连 / 无协议错误；见架构 §5.2b */
    uint8_t config_current;
    uint32_t reserved1;

    uint64_t last_rx_ns;
    uint64_t last_heartbeat_ns;
    uint64_t reconnect_count;
};

#define ICOMM_PEER_STATUS_INIT { sizeof(iocomm_peer_status), 0 }

/* FR-5.2：状态变化可订阅（适用于 conn 或 endpoint）。
 *
 * **连接级**（`iocomm_conn_condition_subscribe`）：只报该连接自身的条件集变化。
 *
 * **端点级**（`iocomm_endpoint_condition_subscribe`，2026-11-05 定，N-45 / AC-121）：
 * = 对「**当前与未来全部成员连接**」条件集变化的聚合，语义等价于对每个成员连接各订阅一次，
 * 但**只产生一个订阅句柄**（`unsubscribe` 一次即覆盖全部）。
 *   - **新成员自动纳入**：交付时点之后接入的成员连接自动进入订阅范围，
 *     **不需要**在 `endpoint_accept` 回调里补订阅；
 *   - **成员离开**（2026-11-05 补全，N-45）：该连接的**状态变化本身照常推送**——包括最后一次
 *     `connected = FALSE`（与逐连接订阅完全等价），**推送先于**它从成员集合中摘除；
 *     摘除之后不再为它投递。**不额外推送**「成员离开」这种**独立事件**——上线由 `endpoint_accept` 观测、
 *     节点上下线由 `discovery` 的 JOINED/LEFT 观测，这里再推一遍会形成第三套重复通道。
 *     **注意「上线」的观测渠道按成员类型分**：**入站**成员上线由 `endpoint_accept` 观测；
 *     **`ep_owner == ep` 的出站成员**不经过 accept，其上线由 `iocomm_connect*` 的返回 / `on_done(OK)` 观测；
 *   - **成员定义** = 与 FR-8.6 的扇出集合**完全一致**：该端点的全部入站成员连接 + `ep_owner == ep` 的出站连接；
 *   - **端点没有自身状态**：回调的 `conn` 与 `ep` **恒非 0**，永不以 `conn == 0` 触发；
 *   - 与消息接收通道**无关**：不受 §6.4 的 `subscribe` / `recv` 二选一约束（矩阵见 §3.2.1）。
 *
 * **是否在订阅建立时立刻推一次当前值**：与**连接级** `iocomm_conn_condition_subscribe` 取**同一口径**——
 * 两级是同一条规则（2026-11-05 复核后再无悬空）。在连接级的该口径写死之前，调用方应先用
 * `iocomm_conn_status` 取初始值、只依赖**变化**推送；AC-121 也只断言变化。
 */
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

struct iocomm_stats {
    uint32_t size;                 /* 库写入 sizeof(iocomm_stats)；调用方无需预置（§3.1） */
    uint32_t reserved0;

    uint64_t bytes_sent, bytes_received;
    uint64_t messages_sent, messages_received;
    uint64_t queue_dropped;        /* 该 Runtime 内「入队失败 / 被策略丢弃 / 入站帧被判超限或畸形」的累计条数；
                                    * 运行期事件都计；调用方编程错误（发送侧 `TOO_LARGE`、句柄无效）不计（见 §6.1） */
    uint64_t retransmits;          /* TCP 层重传（可读时）；否则 0 */
    uint64_t heartbeat_timeouts;
    uint64_t reconnects;
    uint64_t discovery_oversize;   /* 因单条超 1400 B 而未发送的发现条目数（FR-2.9） */
    uint64_t protocol_errors;      /* 收到 ERROR 帧或判定帧损坏的次数（v1） */
    uint64_t audit_events;         /* 已送交 audit_fn（v1：已写 log_fn 的 AUDIT 类别）的事件数 */

    int64_t  send_queue_depth, recv_queue_depth;
    int64_t  open_endpoints, discovered_peers;

    /* 延迟（FR-5.4）：基于心跳 RTT 的直方图分位 */
    uint64_t rtt_p50_ns, rtt_p99_ns, rtt_max_ns;
};

#define ICOMM_STATS_INIT { sizeof(iocomm_stats), 0 }

/* 快照非原子一致：各值可能来自不同时刻。 */
int32_t iocomm_stats_snapshot(iocomm_runtime_t rt, iocomm_stats* out,
                              iocomm_error* err);

/* 诊断 dump：返回 JSON 文本，调用方用 iocomm_free_text 释放。
 * v1 结构（FR-5.5；验收 AC-94）：
 *   { "version": 1,
 *     "connections": [ { "conn": <u64>, "peer_node_id": <u64>, "connected": <bool>,
 *                        "recv_queue_depth": <i64> }, ... ],
 *     "endpoints":   [ { "ep": <u64>, "name": <string>, "conn_count": <u32>,
 *                        "send_queue_depth": <i64> }, ... ] }
 * `send_queue_depth` **在端点对象里**（2026-11-05，N-40）：成员连接共用该端点的一条发送队列
 *   （§6.1「队列归属规则」），逐连接无定义。**例外**：`ep_owner == 0` 的出站连接各自一条发送队列（§6.1 同一清单末项），
 *   它们**不在任何端点**下，其发送队列深度**不出现在本 dump 中**——这是 v1 的已知盲区，
 *   记入 [open-questions N-47](../open-questions.md) 随 per-connection 指标一并评估。
 * `recv_queue_depth` 每连接一条（§6.1），故留在 `connections` 里。
 * 键名与类型属**契约**；新增键只允许在顶层与对象内追加（读取方忽略未知键）。
 * **例外（2026-11-05，N-40）**：`send_queue_depth` 从 `connections[]` **移到** `endpoints[]`，属**一次性的破坏性字段搬移**，不适用「只追加」规则——本库尚未发布（M0 未冻结），无兼容负担；**发布后**再要搬移字段就必须升 ABI major。
 * 「最后 N 条错误」属 v1.1（FR-5.5b）。 */
int32_t iocomm_diagnostic_dump(iocomm_runtime_t rt, char** out_text,
                               uint64_t* out_len, iocomm_error* err);
void    iocomm_free_text(char* text, uint64_t len);
```

---

---

## 9. 消息监控（信封级 + 可选载荷）

> **定位**：状态监控回答「链路健康吗」，消息监控回答「**这一条消息去哪了**」。
> 默认只记**信封元数据**；载荷捕获是显式、限时、限速、限量的调试能力。

### 9.0 v1 / v1.1 归属（**唯一权威**）

| 成员 | 所属 |
|---|---|
| `monitor_open` / `monitor_poll` / `monitor_close` / `monitor_get_stats` | v1 |
| `iocomm_mon_record` 全部**信封**字段（`capture_id` / `seq` / 时间 / 来源 / 连接 / `original_len` / `correlation_id` / `drop_reason` / `kind`） | v1 |
| `ring_capacity` / `retain_window` / `max_bytes` / `sample_per_mille` / `monitor_ttl_ms` | v1 |
| `max_payload_bytes` / `capture_per_mille` / `max_bytes_per_sec` / `max_total_bytes` / `capture_ttl_ms` | **v1.1**（v1 传非 0 视为 0） |
| `monitor_capture_set` | **v1.1**（v1 恒返回 `NOT_SUPPORTED`）。**v1 也导出该符号**——只是恒返回 `NOT_SUPPORTED`，保证同一份头文件可跨版本链接 |
| `iocomm_mon_record_payload` / 载荷视图 / `retained_*` | **v1.1** |
| `monitor_dump` 家族 | **v1.1** |
| `iocomm_mon_record.captured_len` / `flags` 的 `TRUNCATED` / `SAMPLED_OUT` | **v1.1**（v1 恒 0） |
| `SLOW` 事件（`slow_threshold_ms`） | **v1.1** |
| `audit_fn` / `iocomm_audit_record` | **v1.1**（v1 走 `log_fn` 的 AUDIT 类别） |
| `stats.audit_events` | **v1**——计「已写 `log_fn` 的 AUDIT 类别」的事件数；v1.1 起改为计「已送交 `audit_fn`」 |
| `stats.protocol_errors` | **v1**（FR-5.4） |
| `stats.discovery_oversize` | **v1**（FR-2.9） |
| `process_epoch`（FR-9.3） | **v1.1**（v1 无此字段） |

> 这张表是**版本归属的唯一权威**；各节里的〔v1.1〕标注若与它冲突，以本表为准。

### 9.0b 多个监控者的重叠作用域（**唯一口径**）

| 情形 | 规则 |
|---|---|
| 同一消息被 **N 个 monitor** 看到 | 每个 monitor **各记一条**（各自独立的环、独立配额、独立 `capture_id` 序列）；`stats` 按 monitor 独立统计，**不跨 monitor 去重** |
| **端点级 + 连接级** monitor 同时覆盖同一连接 | 同样**各记一条**——作用域重叠不合并 |
| 配额 | `monitor_budget_bytes` 按**每个 monitor 的 `max_bytes` 之和**计，重叠不减免（两个 monitor 各占一份配额） |
| `seq` | **每 monitor 独立单调**，不保证跨 monitor 可比 |

### 9.1 事件与丢弃原因

```c
typedef enum iocomm_mon_kind {
    ICOMM_MON_SENT      = 1,   /* **成功入队**后才产生（同步/异步同口径）；不等于已送达 */
    ICOMM_MON_RECEIVED  = 2,   /* 从传输收到（帧解码完成） */
    ICOMM_MON_DELIVERED = 3,   /* 已交付应用（推给回调 / 进入 recv 队列） */
    ICOMM_MON_DROPPED   = 4,   /* 被丢弃，原因见 drop_reason */
    ICOMM_MON_SLOW      = 5,   /* 见下方「SLOW 的配对规则」 */
    ICOMM_MON_LOST      = 6,   /* **聚合**：监控环满导致的丢失（见 C4） */
} iocomm_mon_kind;

typedef enum iocomm_drop_reason {
    ICOMM_DROP_NONE          = 0,  /* 非 DROPPED 记录使用（`kind != DROPPED` 时 drop_reason 恒为 0） */
    ICOMM_DROP_QUEUE_FULL    = 1,  /* 队列满且策略为 DROP_OLDEST / DROP_NEWEST → **被策略丢弃**（发送侧或接收侧） */
    ICOMM_DROP_NO_SUBSCRIBER = 2,  /* 端点扇出时无已建立连接 */
    ICOMM_DROP_TIMEOUT       = 3,  /* 异步发送排队超过 send_options.queue_timeout_ms */
    ICOMM_DROP_PEER_GONE     = 4,  /* 连接已断开时仍有待发消息 */
    ICOMM_DROP_BACKPRESSURE  = 5,  /* 队列满且策略为 ERROR → **入队前被拒绝**（发送侧；接收侧无返回方，见 §6.1） */
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
    uint32_t size;              /* 库写入 = sizeof(iocomm_mon_record)；调用方无需预置（§3.1） */
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
 * 即使传入非 0 也视为 0。`iocomm_monitor_capture_set` 在 v1 下恒返回 `NOT_SUPPORTED`（§9.0）。 */
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

> **内存模型**（D-09 / B-09 定稿）：**环的存储一次性预分配**（`ring_capacity × sizeof(record)`，在 `monitor_open` 时分配）；
> **记录槽位按需占用**，离开 `retain_window` 时归还（AC-72）；`max_bytes` 是**记账上限**，不是预留量。
> 另有 1 条 LOST 槽在 `max_bytes` 之外单独计。
> **`max_bytes` 覆盖记录 + 载荷**，见上表；`max_total_bytes` 是**累计**配额，不参与任何配额计算。
> **v1（载荷捕获关闭）**：`max_bytes` 只计记录，**默认固定 4 MiB**（约 4 万条），不随 `ring_capacity` 自动收紧——
> 默认值只允许一个，避免「同一配置在两种口径下得到不同上限」。要更小的占用请显式设置 `max_bytes`。
> **预分配失败** → `RESOURCE_EXHAUSTED`。
> 所有监控者的 **`max_bytes` 之和**（已提交配额，**不是实际占用**）不得超过全局预算 `runtime_config.monitor_budget_bytes`（0 = 默认 64 MiB）；
> 超预算（`monitor_open` 时即检查）或实际分配失败 → `RESOURCE_EXHAUSTED`。
> **`max_total_bytes` 不受预算限制**：它是累计配额，可在远大于工作集时配置（如 512 MiB），
> 达到后按 §9.4 的 `RESOURCE_EXHAUSTED` 规则停止捕获。
>
> **消息尺寸上限**：`max_message_size`（默认 1 MiB）约束**整帧**——`20 + tlv_len + payload_len`
> （见 [线格式 §1](wire-format.md)），即**发送方可见的 payload 上限比该值小约 20–80 B**。
> 该值**下限 56 B**（`20` 帧头 + `SEQ`/`TS_SEND`/`SOURCE_NODE` 三项必填 TLV 共 36 B）：低于此值则任何 `DATA` 帧都无法通过校验，`runtime_create` 返回 `INVALID_ARGUMENT`（见 §6.0）。
> 在发送侧**先于入队**检查——
> **同步返回**（`TOO_LARGE` 属于「不可能再回调」的入队前失败，见 §6.2）：
> 同步 `conn_send` / `endpoint_send` 与异步 `*_send_async` **一律同步返回 `ICOMM_ERR_TOO_LARGE`**，
> 异步**不会**再触发 `on_done`（AC-78）。**不入队**。
> 接收侧超限：关闭该连接（`DISCONNECTED`）并产生一条 `DROPPED(reason=TOO_LARGE)` 记录。
> **发送侧超限不产生 DROPPED**（消息从未入队，只返回错误码）。
>
> **入队前失败是否产生监控记录（唯一口径）**：
>
> | 情形 | `SENT` | `DROPPED` |
> |---|---|---|
> | 发送队列满且策略为 `ERROR` | ❌ | ✅ `BACKPRESSURE` |
> | 扇出时**无连接** | ❌ | ✅ `NO_SUBSCRIBER` |
> | 连接在**入队前**已断开 | ❌ | ✅ `PEER_GONE` |
> | `TOO_LARGE`（超过 `max_message_size`） | ❌ | ❌（编程错误，不是运行期事件） |
> | 句柄无效 / 参数非法 / 未持有连接 | ❌ | ❌ |
>
> 前三行是**运行期事件**，正是监控要回答的「这条消息为什么没发出去」；后两行是调用方的编程错误，
> 只走返回值 / `on_done`，不进监控环（否则误用会污染监控）。
>
> **多条同时命中时的优先顺序**（高 → 低）：**句柄/参数 → `TOO_LARGE` → `PEER_GONE` → `BACKPRESSURE` → `NO_SUBSCRIBER`**。
> 只报**第一条**命中的：例如连接已断开且队列也满，报 `PEER_GONE`，不报 `BACKPRESSURE`。
> **同步与异步在这一点上完全一致**——异步被拒同样不产生 `SENT`，同样产生对应的 `DROPPED`。
>
> **`PEER_GONE` 的两种形态**（二者语义不同，都应实现）：
> - 入队**前**已知连接已断开 → 入队失败，返回 `DISCONNECTED`，产生 `DROPPED(PEER_GONE)`；
> - 消息已**入队**（已产生 `SENT`）后连接断开 → 队列清空，逐条产生 `DROPPED(PEER_GONE)`，
>   异步的 `on_done(code = ICOMM_ERR_DISCONNECTED)`。
> **自动重连不改变这两条**（2026-11-04，N-06）：断开即结算，重连成功后**不重放**；重连窗口内的新发送
> 走「入队前已断开」形态（见架构 §5.2c）。
>
> 已产生 `SENT` 的消息，其后续结局是 `DROPPED(TIMEOUT / PEER_GONE)`、`DELIVERED` 或取消——
> **`SENT` 之后出现 `DROPPED` 是正常序列**（SENT = 已入队，不是「已送达」）。
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
/* 生效点：返回 ICOMM_OK 时，此后**入队**的消息都会进入该 monitor（返回前已在环中的不补记）。
 * 线程：任意线程。 */
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

struct iocomm_audit_record {
    uint32_t size;
    uint32_t kind;               /* iocomm_audit_kind */
    uint64_t seq;                /* runtime 内单调分配；并发回调的到达顺序可能与之不同，按 seq 排序与检漏 */
    uint64_t ts_wall_ns;
    uint64_t subject;            /* 相关句柄或节点 */
    uint64_t detail;             /* 低基数细节：CONTROL 时为 ICOMM_CTRL_* 子类型；其余为 0 */
    int32_t  result;             /* ICOMM_OK 或错误码 */
    uint32_t reserved0;
};

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
| **C4** | 环满时：新记录**写入失败**（不覆盖旧记录）→ `stats.lost++`、`degraded=1`。**LOST 槽位在 `ring_capacity` 之外额外分配 1 条**（有效业务容量仍是 `ring_capacity`，`max_bytes` 之外另计 1 条 LOST 槽）。每满 1024 次丢失就更新该槽位（`lost_count` 存本批条数，`capture_id` 每次**重新分配**——LOST 槽位**独占一个 `capture_id`**，不复用其他记录的值；`monitor_close` 时若尾批不足 1024 条，仍写入该槽一次）。**in-band LOST 是 best-effort，`stats.lost` / `stats.degraded` 才是权威信号**。poll **只读**，不写环 |
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
| **跨进程 / 集中式监控**（2026-11-05，N-42） | 监控作用域 = 本 Runtime；管理进程须在每进程内各嵌 Runtime 自行汇总。**v2 评估** |
| **事件循环投递入口（`post` 类）**（2026-11-05，N-43） | 回调内做异步发送 + 置标志、数据处理放 `run_once` 之后即可覆盖；**v2 评估** |
| **多通信域 / 网络级分区**（2026-11-05，N-44） | 单发现域；硬隔离用 VLAN / ACL / 独立网卡 / netns。**域 ≠ 安全边界**；v2 与 TLS 同批评估 |

> **跨进程监控的替代做法**（v1）（2026-11-05，N-42）：本库不提供跨进程指标通道，但调用方仍可：
> ① 在各进程内用 `monitor_open(rt, ep=0)` + `monitor_poll` 自行聚合；② 用 `iocomm_diagnostic_dump` 取 JSON 快照
> （作用域仍是本 Runtime）；③ 经应用自有通道（如共享内存、MQ）汇总到管理进程。**库不代劳，但也不阻止**。

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

> **发布前的同批调整（2026-11-04，同样不升 `abi_minor`）**：**N-12 套接字参数**——
> `endpoint_config` 尾部追加 `tcp_nodelay`（`uint8_t`，0 = 默认**开**）/ `reserved9` / `listen_backlog`（`uint16_t`，0 = 默认 128）；
> `tune_config` 尾部追加同名字段（0 = 保持）。二者均**只做尾部追加**，按本文件「尾部追加字段 → `minor + 1`」的
> **发布后**规则应升 minor；但这批改动与 2026-10-21 同属**发布前定型**（尚无可兼容宿主，见上式），故
> **不升 `abi_minor`**，与既有 `send_options.queue_timeout_ms` 等保持同一口径。首次发布后任何此类追加一律升 minor。
> 同批仅改注释/文档、不动布局的：N-04（`node_id` / `state_dir` 语义）、N-05（`connect_node` 解析规则）、
> N-06（重连语义）、N-07（心跳默认值）。

> **发布前的宏删除（2026-11-04，同样不升 `abi_minor`）**：删除 `ICOMM_ENDPOINT_UNIQUE`——它是**宏**，
> 不进入任何结构体布局；`endpoint_config.flags` 改为 v1 保留字段（无已定义位，非 0 → `INVALID_ARGUMENT`）。
> 与上面的理由相同：尚无兼容宿主，发布前删除宏不是对外 ABI 变更；且该标志对应的「可多实例 + 自动改名」
> 语义已被 [架构 §6.4](../architecture.md) 与 FR-1.4 废止（跨进程同名一律 `CONFLICT`）。
> 同批的端点名格式/长度约束（N-17，§5.1a）属**输入校验口径**，不改结构体布局，也不升 minor。

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
