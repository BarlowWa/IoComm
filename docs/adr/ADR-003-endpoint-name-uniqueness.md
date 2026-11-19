# ADR-003：端点名唯一性——跨进程同名一律拒绝

- **状态**：已接受
- **日期**：2026-11-04
- **决策者**：项目负责人
- **影响**：`api/c-abi.md`（§5.1 / §3.2 / §3.2.1 / §10）· `architecture.md`（§6.4）· `requirements.md`（FR-1.4 / FR-1.5 / AC-89）· `open-questions.md`（D-05 追加、N-16）

---

## 背景

端点名（`endpoint_config.name`）在本库承担三重身份：

1. **跨进程唯一资源**——同一台机器上不能被两个 Runtime 同时持有（FR-1.4 的拒绝语义；FR-1.5 的三态查询用于探测）。
2. **远端寻址主键**——`iocomm_connect_node(node_id, endpoint_name)` 按名字**精确字节匹配**（C ABI §5.2a），发现报文 `ENDPOINTS` 里上报的也是它。
3. **人读标签**——排障时看日志、看 `iocomm_diagnostic_dump` 输出。

这三重身份对「同名冲突该怎么办」的要求并不一致，这是本 ADR 要解决的分歧。

**历史**（已用 git 历史核实）：`ICOMM_ENDPOINT_UNIQUE` 标志与「非 `UNIQUE` 时以 `<name>#<pid>` 注册第二实例」的规则**从设计文档首次入库（本仓库根提交 `ef24ffd`）就存在**，不是某次审计修复引入的。D-05 处置（2026-10-22，本仓库 `f206ff4`）新增 **AC-89**，把该行为**固化成验收项**——从「无人验证的行为」变成「不得改动的要求」。

该规则**与 FR-1.4（P0「重名注册被拒绝」）直接冲突**，且仓库内**没有任何一处写明它为什么需要**。2026-11-04 复核时该矛盾被识别（`open-questions.md` N-16）。

---

## 决策

> **跨进程同名一律拒绝**：`endpoint_create` 返回 `ICOMM_ERR_CONFLICT`，**不注册**；同进程同名仍返回 `ICOMM_ERR_ALREADY_EXISTS`。删除 `ICOMM_ENDPOINT_UNIQUE` 标志——不再有「单实例 / 可多实例」两种模式。

---

## 理由

### 1. 行业有三种范式，只有一种是「注册一个唯一名字」的表达

| 范式 | 代表 | 规则 | 适用前提 |
|---|---|---|---|
| **拒绝** | ZeroMQ / nng | 名字已被占用 → 注册失败 | 名字是系统级唯一资源，服务方是它的所有者 |
| **接管** | MQTT 5 | 新连接踢掉旧连接（`0x8E Session taken over`） | 名字标识**一个客户端会话**，重连必须能顶替自己的僵尸会话 |
| **改名** | mDNS（RFC 6762 §9） | 输者改名、**持久化**、**告知用户** | 名字是**人可见的标签**，改名代价由用户承担 |

（来源见本文末。）

### 2. 改名范式在 IoComm 的三个前提都不成立

RFC 6762 §9 的改名流程不是「换个名就算完」，其推荐的完整做法是（原文为 *"The recommended course of action"*，非 MUST）：

1. **把新名字持久化**——*"record this newly chosen name in persistent storage so that the device will use the same name the next time it is power-cycled"*；
2. **告知用户或操作员**——*"Display a message to the user or operator informing them of…"*；
3. 名字本身主要**给人看**，机器靠另外的机制定位。

逐条对照：

| RFC 6762 的改名前提 | IoComm 的现实 |
|---|---|
| 新名字持久化、重启后沿用 | `<name>#<pid>` 中的 **pid 每次启动都变**，无法持久化，也永远不可预测 |
| 告警用户 / 操作员 | 库无 UI；只有 `endpoint_name_state()` 三态查询，且该函数明确写着「不是原子的，仅用于诊断与友好提示」 |
| 名字主要是**人可见的标签** | 端点名是 `connect_node` 的**跨机寻址主键**，按字节精确匹配（*注：这一条是本文的推断，RFC 6762 §9 未明写「名字主要给人看」*） |

三个前提全不满足。**改名唯一的效果是让第二个实例「看起来注册成功了」，同时让所有远端寻址失效**——远端不可能预先知道 `plant3/line2/temp#4821` 这个身份。现场表现就是「连接到了错误的进程」，属于最难排查的一类故障。

### 3. 接管范式更不合适

MQTT 的接管成立，是因为 ClientID 标识一个**会话**，而会话是可以被重建的。IoComm 的端点是一个**正在运行的监听者**：接管意味着把正常工作中的一个实例踢下线。MQTT 至少会向**被踢的一方**发 `DISCONNECT(0x8E Session taken over)`；而工业现场里，「新进程上线把老进程顶掉」本身就是最不能接受的失败方式——即便被踢方收到了通知，出故障的也是它。

### 4. 拒绝范式的前提 IoComm 全部满足

- 端点名确实是系统级唯一资源（§6.4 用 Linux 抽象命名空间 socket / Windows 命名对象做跨进程锁）。
- 冲突在 `endpoint_create` 时**立即、同步**暴露，调用方启动阶段即可处理。
- 失败即停（fail-fast）远优于在远端寻址时才暴露（fail-late）。

### 5. 与既有 P0 需求一致，而非常规「新增约束」

FR-1.4 原文就是「重名注册被**拒绝**，返回明确错误码」并标 **P0**。本决策是让实现回到需求，而不是提出一条新规则。

### 6. 顺带消除一个实现陷阱

Linux 抽象命名空间 socket 与 Windows 命名对象都由**内核在进程退出时回收**，因此进程崩溃后名字自动释放，不会出现「陈旧锁导致重启失败」。这是拒绝范式最常见的现场问题，§6.4 的机制天然规避。

---

## 被否决的方案

| 方案 | 否决理由 |
|---|---|
| **保留自动改名**（`<name>#<pid>`） | pid 不持久化，名字对远端永不可预测；`connect_node` 可能连到错误进程；三个改名前提全不满足；且与 FR-1.4（P0）冲突 |
| **mDNS 式改名 + 持久化** | 一个进程要改名，就得让**其他所有进程**知道它换了名字——发现表可做到，但 `connect_node` 的调用方缓存的是旧名字，没有「名字变更通知」这一机制。引入它相当于在 v1 加一套软状态协议。且工业现场的端点名通常由组态配置生成（`plant3/line2/temp`），不是即时生成的名字，改名没有意义 |
| **MQTT 式接管** | 把正常工作实例踢下线（MQTT 会通知被踢方，但故障本身仍由被踢方承担）；端点不是可重建的会话 |
| **保留 `ICOMM_ENDPOINT_UNIQUE`，默认关闭排他** | 一个「默认允许无冲突」的开关，会让最常见的配置（什么都不设）落在最宽松的一侧；且它只会制造两套语义。删除它之后所有端点行为一致，也省掉一个 ABI 标志位 |
| **库内重试/等待名字释放** | 把同步的注册变成阻塞行为，且没有「等到何时算失败」的合理答案；调用方自己重试语义更清晰 |

---

## 后果

### 正面

- 与 FR-1.4（P0）一致，文档不再自相矛盾。
- 冲突在启动阶段暴露，不会退化成现场寻址故障。
- 端点名保持稳定、可预测、可配置——这是跨机寻址的前提。
- 头文件少一个标志、少一套模式（`flags` 变为 v1 保留字段）。

### 负面 / 需要说明

- **同机多进程需要不同的端点名**。部署脚本 / 组态系统要为每个实例生成唯一名字（例如带上实例编号）。这是显式的运维职责，而不是库替用户猜测。
- `endpoint_name_state()` 只能用于**注册前探测**，存在 TOCTOU 窗口；`endpoint_create()` 的返回值才是权威。这一点维持不变。
- 该决策**废止**了自初始设计起就存在的「允许第二实例 + 自动改名」规则，以及 D-05 处置时固化的 AC-89 旧断言（该断言首见于本仓库 `f206ff4`）（`open-questions.md` D-05 已追加说明；D-05 其余部分——跨进程名字表落 M1——仍然有效）。

---

## 来源

- **ZeroMQ**：`zmq_bind` 错误表——`EADDRINUSE — The requested 'address' is already in use.`
  <https://libzmq.readthedocs.io/en/latest/zmq_bind.html>
- **nng**：`NNG_EADDRINUSE: The listener address is already in use.`；错误码表——*"The network address is already used by another process. Most often this is seen for listeners."*
  <https://nng.nanomsg.org/ref/v2.0/print.html>
- **Windows 命名管道（对照用，非「拒绝范式」的代表）**：命名管道**默认支持多实例**，`nMaxInstances` 可取 1–255；**独占是显式选项**——可用 `FILE_FLAG_FIRST_PIPE_INSTANCE`（*"creation of the first instance succeeds, but creation of the next instance fails with ERROR_ACCESS_DENIED"*），或把 `nMaxInstances` 设为 1。**本库选择的是后者式的「只允许一个」语义，但把它做成唯一行为而非选项**。这条对照说明的是：独占在操作系统层面也需要显式声明，默认值通常是「允许多个」。
  <https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-createnamedpipea>
- **mDNS**：RFC 6762 §9「Conflict Resolution」——*"the loser MUST cease using the name, and reconfigure"*；改名后须持久化并在重启后沿用、须告知用户。
  <https://www.rfc-editor.org/rfc/rfc6762.html#section-9>
- **MQTT 5.0**：`[MQTT-3.1.4-3]`——*"the Server sends a DISCONNECT packet to the existing Client with Reason Code of 0x8E (Session taken over) … and MUST close the Network Connection of the existing Client."*
  <https://docs.oasis-open.org/mqtt/mqtt/v5.0/os/mqtt-v5.0-os.html>

---

## 相关文档

- [需求](../requirements.md) · [架构](../architecture.md) · [C ABI](../api/c-abi.md) · [ADR-002](ADR-002-message-addressing-and-ownership.md)
