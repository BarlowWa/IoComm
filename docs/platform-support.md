# IoComm 平台支持

> 状态：设计阶段 ｜ 相关：[架构](architecture.md) · [需求](requirements.md) · [ADR-001](adr/ADR-001-language-and-platform.md)

---

## 1. 支持矩阵

### 1.1 架构

| 架构 | Rust target | Tier | 说明 |
|---|---|---|---|
| **x86_64 Linux** | `x86_64-unknown-linux-gnu` | **Tier 1** | kernel 3.2+ / glibc 2.17+ |
| **ARM64 Linux** | `aarch64-unknown-linux-gnu` | **Tier 1** | kernel 4.1+ / glibc 2.17+ |
| **x86_64 Windows** | `x86_64-pc-windows-msvc` | **Tier 1** | Windows 10+ / Server 2016+ |
| ARM64 Windows | `aarch64-pc-windows-msvc` | —（不在产品范围） | 工具链可构建，但不承诺、不验收 |

### 1.2 操作系统

| 等级 | 环境 | 说明 |
|---|---|---|
| **必须（发版门槛）** | Windows Server 2016 / 2019 / 2022 x64 | Rust Windows 目标最低 Server 2016 |
| **必须（发版门槛）** | Linux x86_64，glibc ≥ 2.17 | 一套构建覆盖 RHEL 7 + 麒麟 V10 + UOS 20 |
| **必须（发版门槛）** | Linux ARM64，glibc ≥ 2.17 | 飞腾 / 鲲鹏 |
| **必须（发版门槛）** | 麒麟 V10 SP3（x86_64） | 工业信创主流；实机冒烟计入发版 |
| **必须（发版门槛）** | 统信 UOS 20（x86_64） | 工业信创主流；实机冒烟计入发版 |
| **重要（不阻塞发版）** | 麒麟 V10 SP3 ARM64、UOS 20 ARM64 | ARM64 的国产 OS 实机验证 |
| **best-effort（不承诺）** | RHEL 7（ELS 期内）、麒麟 V11、UOS V25 | 前向兼容；**不列入验收** |

> **RHEL 7 的定位已澄清**：它是 **best-effort（前向兼容）**，不是发版门槛。它之所以能被覆盖，是因为 Linux x86_64 的 **glibc 2.17 构建基线**顺带兼容了它——**不单独为 RHEL 7 做构建或验收**。若客户需要 RHEL 7 的正式支持，需先核实其 ELS 状态并单独立项。

### 1.3 明确不支持

- **LoongArch / MIPS64 / SW64** —— 见 §5。
- **硬实时承诺**（任何 OS）—— RT 作为客户选配单独验收。
- 32 位目标、Windows 7 / Server 2008 R2 及更早、macOS。

---

## 2. Windows 平台差异

### 2.1 Windows Server 2016 的能力缺口

Server 2016 = build 14393。以下特性在它上面**不可用**：

| 能力 | 状态 | 替代方案 |
|---|---|---|
| **AF_UNIX** | ❌ 需 Win10 1803+ / Server 2019+ | **命名管道**（byte 模式） |
| `TCP_USER_TIMEOUT` | ❌ | 应用层心跳 |
| `TCP_KEEPIDLE` / `TCP_KEEPINTVL` | ❌（Win10 1709+ 才有） | `SIO_KEEPALIVE_VALS` |
| `SO_REUSEPORT` | ❌ | 单 acceptor + IOCP 分发 |
| `SO_REUSEADDR` | ⚠️ 语义不同（会抢占端口） | 服务端用 `SO_EXCLUSIVEADDRUSE` |

**可用**：Winsock 2、IOCP、命名管道、组播、`AcceptEx`/`ConnectEx`、overlapped IO。

### 2.2 生命周期

| 产品 | 主流支持结束 | 扩展支持结束 |
|---|---|---|
| Windows Server 2016 | 2022-01-11 | **2027-01-12** |
| Windows Server 2019 | 2024-01-09 | 2029-01-09 |
| Windows Server 2022 | **2026-10-13** | **2031-10-14** |

> **日期来源**：2022 的日期未能直读 Microsoft 官方页（该页 JS 渲染被拦截），取自公开生命周期表；
> **签约前须以官方页面复核**。2016 / 2019 两行与官方一致。

> **2027-01-12 之后**，Server 2016 需要 ESU（Azure Arc 或带 SA/SPLA 的本地许可）。**必须写进合同**，否则客户环境属于「无补丁运行」。

### 2.3 本机 IPC

| 后端 | Server 2016 | 说明 |
|---|---|---|
| 命名管道 | ✅ | **主选**，byte 模式 + 库内长度前缀分帧 |
| loopback TCP | ✅ | 兜底 |
| AF_UNIX | ❌ | Server 2019+ 才有 |

> **命名管道优先用 `mio::windows::NamedPipe`**（**mio 0.8 起提供**——已核对 0.8.0 源码含 `sys/windows/named_pipe.rs`，0.7.2 / 0.7.10 无此模块；把 IOCP 转换为就绪模型，可直接接入同一 `Poll`）。**仅在目标 mio 版本不提供或行为不满足时**，才自研 overlapped-IO 实现。
>
> **备选自研路径**：`iocomm-transport` 内建 `win_pipe` 模块，用 `CreateNamedPipeW` / `ReadFile` / `WriteFile` + `OVERLAPPED` 自管完成端口（估 800–1200 行 + 测试）。**S2 Spike 先验证 `mio::windows::NamedPipe`：可用则不做自研。**
> → mio 方案为**主路径**；自研仅作兜底，其工作量已单列为 [架构 §10.4](architecture.md) 的「合计（自研命名管道）」。
>
> 若在 S1 Spike 中证明该路径成本过高，**fallback 是 loopback TCP**（功能等价、延迟更高约 2×）。

---

## 3. Linux 平台

### 3.1 构建基线

**在 glibc 2.17 容器（CentOS 7 / manylinux2014）中构建**，产物可运行于：

| 目标 | glibc | 内核 |
|---|---|---|
| RHEL 7 | 2.17 | 3.10 |
| 麒麟 V10 初版桌面 | 2.23 | 4.15 |
| 麒麟 V10 服务器 SP2/SP3 | 2.28 | 4.19 |
| 麒麟 V10 SP1 桌面 | 2.31 | 5.4–5.15 |
| 麒麟 V11 | 2.38 | 6.6 |
| UOS 服务器 V20 (E) | 2.28 | 4.19 |
| UOS 桌面 V20 | 2.28.x | 4.19–5.10 |

交付前必须审计：

```bash
readelf --version-info libiocomm.so | grep -o 'GLIBC_[0-9.]*' | sort -Vu | tail -1
# 结果不得高于目标系统 glibc 版本
```

### 3.2 本机 IPC

| 后端 | 说明 |
|---|---|
| **Unix domain socket** | 主选。优先 abstract namespace（零残留）；否则 pathname + 互锁文件清理 |
| loopback TCP | 兜底 |

**残留清理**：AF_UNIX 路径 socket 无 `bind(O_EXCL)`，崩溃后会留下 inode。采用 PostgreSQL 范式：`O_CREAT|O_EXCL` 锁文件串行化 → `unlink` → `bind` → 锁文件内 `kill(pid,0)` 判活。

### 3.3 国产 OS 的工程现实

**不是「内核改坏了网络栈」**（无公开证据；4.19 衍生内核 + 厂商补丁，syscall ABI 稳定）。

真正的风险：

| 风险 | 处理 |
|---|---|
| **版本碎片化**（麒麟 SP1/SP2/SP3；UOS 1050/1060/1070 + A/D/E 底座） | 支持矩阵细化到「产品 + SP + 内核 + glibc」 |
| **KYSEC 安全模块** | 白名单流程；优先 socket/pipe，不用 SysV IPC |
| **默认 `nofile=1024`** | 显式 `LimitNOFILE`（systemd） |
| **`/tmp` 1–3 天清理** | socket 文件放 `/run`，不放 `/tmp` |
| **debuginfo 不可得** | 采购时索取 `kernel-devel` / `kernel-debuginfo` / SRPM |
| **国产网卡驱动** | 不假设多队列/RSS；提供单队列退化；启动时输出 `ethtool` 自检 |

### 3.4 glibc 2.17 的注意点

| 缺失 | 影响 | 处理 |
|---|---|---|
| `getrandom` (2.25) | 无法用 glibc 封装 | 用 `syscall(SYS_getrandom)` 或 `/dev/urandom` |
| `memfd_create` (2.27) | 无 | 用 `syscall` 直调 |
| `statx` (2.28) | 无 | 用 `stat` |
| `__cxa_thread_atexit_impl` (2.18) | Rust 的 `thread_local` 析构可能引用 | Rust 侧已处理；C++ 消费方需注意 |

---

## 4. 平台行为差异对照

| 行为 | Linux | Windows |
|---|---|---|
| 本机 IPC | Unix socket | 命名管道（`mio::windows::NamedPipe`） |
| 连接被拒 | `ECONNREFUSED` | `ERROR_PIPE_BUSY` / `WSAECONNREFUSED` |
| 对端关闭 | `read()==0` | `ReadFile` 返回 0 / `ERROR_BROKEN_PIPE` |
| 非阻塞建连 | `EINPROGRESS` | overlapped + `ConnectEx` |
| 写已关闭对端 | `SIGPIPE`（默认杀进程！） | 无挂起信号 |
| 半开检测 | 应用层心跳（不依赖内核 keepalive；见 FR-5.3 / 架构 §6.2） | 应用层心跳（WS2016 缺 `TCP_KEEPIDLE`，内核 keepalive 默认 2 h，不可用） |
| 端口复用 | `SO_REUSEPORT` | 不可用 |
| 事件机制 | epoll | IOCP |

> **`SIGPIPE`**：Linux 上写已关闭的对端会触发 `SIGPIPE`，默认终止进程。库内部必须使用 `MSG_NOSIGNAL` 或忽略该信号。

---

## 5. 国产私有架构（软排除）

| 架构 | Rust 状态 | 结论 |
|---|---|---|
| **LoongArch** | Tier 2，要求 glibc 2.36 / 内核 5.19 | 与主流国产系统基线冲突；**不支持** |
| **MIPS64** | Tier 3，无预编译 std | **不支持** |
| **SW64** | **无 LLVM 后端** | 原理上不可行；**不支持** |

**业务依据**（2026-10 核实）：

- 工业现场以 **x86_64（海光/兆芯）为主**，ARM64（飞腾/鲲鹏）次之，LoongArch/SW64 是点状。
- 龙芯 2025 年工控芯片营收 1.58 亿元，约为飞腾的 1/6；且高度依赖安全领域大单。
- 申威在工业控制领域**无公开落地案例**。
- 无公开证据表明任何主流 DCS 厂商把 LoongArch 作为默认控制 CPU。

**但保持可移植**：

- 代码层避免架构假设（字节序、原子宽度、对齐、内联汇编、`long` 宽度）。
- 提供交叉编译脚本 + QEMU 冒烟测试，放 CI 的「允许失败」job，防代码腐化。
- 不承诺 SLA；遇到项目按「定制移植」报价。

**重新评估的触发器**（任一触发即启动评估）：

| 触发器 | 门槛 |
|---|---|
| 财务 | 龙芯工控营收 > 3 亿元/年且连续两年增长 |
| 客户 | 单客户占营收 > 10% 且明确要求该架构 |
| 行业标准 | 发布**强制**「自主指令集」标准（而非仅「国产 CPU」） |
| 头部厂商 | 前五 DCS/PLC 厂商在多站点项目默认采用 |
| 生态 | 关键第三方库/驱动在该架构上有官方支持 |

**复核点：2028 年。**

---

## 6. 测试矩阵

| 环境 | 构建 | 自动化测试 | 人工验证 | 发版门槛 |
|---|---|---|---|---|
| x86_64 Linux（glibc 2.17 容器） | ✅ | ✅ 全量 | — | ✅ |
| x86_64 Linux（Ubuntu 24.04） | ✅ | ✅ 全量 | — | ✅ |
| ARM64 Linux | ✅ 交叉 | ✅ QEMU 全量 | 实机：跨机收发 + 发现 | ✅ |
| Windows Server 2016 | ✅ | ✅ | 命名管道 IPC + TCP + 心跳超时 | ✅ |
| Windows Server 2019/2022 | ✅ | ✅ | — | ✅ |
| 麒麟 V10 SP3 **x86_64** | ✅ | 冒烟 | ✅ 实机 | ✅ |
| 统信 UOS 20 **x86_64** | ✅ | 冒烟 | ✅ 实机 | ✅ |
| 麒麟 V10 SP3 **ARM64** | ✅ | 冒烟 | ✅ 实机 | ❌（重要） |
| 统信 UOS 20 **ARM64** | ✅ | 冒烟 | ✅ 实机 | ❌（重要） |
| RHEL 7 | 复用 glibc 2.17 产物 | 冒烟 | — | ❌（best-effort） |

> **发版门槛**：列中为 ✅ 的环境必须全绿才能发版；❌ 的环境仅记录结果，不作为阻塞条件。

---

## 7. 待核实

| 项 | 状态 |
|---|---|
| **RHEL 7 ELS 结束日期** | 两份二手来源矛盾（2026-06 vs 2028-06），**须向 Red Hat 核实** |
| 麒麟/UOS 的官方支持终止日期 | 无统一公开生命周期表，多为合同项 |
| 麒麟/UOS 是否提供官方容器镜像 | 未核实 |
| 国产网卡的 PTP 硬件时间戳支持 | 需逐型号确认 |
