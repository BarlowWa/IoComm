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
| **跨进程名字锁**（`CreateMutexW`） | ⚠️ `Global\` 命名空间需 `SeCreateGlobalPrivilege`（默认仅管理员 / 服务账户持有），普通用户进程创建失败 | **优先 `Global\iocomm_<hash>`（跨会话可见）；失败时回退 `Local\iocomm_<hash>`**（同会话可见，**同机跨会话的端点名唯一性不保证**），并写 `log_fn` WARN。见 [架构 §6.4](architecture.md#64-跨进程名表fr-15-三态查询) |

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

> **命名管道优先用 `mio::windows::NamedPipe`**（**mio 0.7.2 起就已提供**——2026-11-20 逐版本核对 `raw.githubusercontent.com` 上的源码：`v0.7.2` / `v0.7.10` / `v0.8.0` 的 `src/sys/windows/named_pipe.rs` 均存在，`mio::windows::NamedPipe` 在各版本都公开导出。**原文称「0.7.2 / 0.7.10 无此模块」是错的**。**feature 门在 0.7.6 更名为 `os-ext`，不是 0.8.0**：`v0.7.5` 的 `Cargo.toml` 只有 `os-util = []`；`v0.7.6` 起为 `os-ext = ["os-poll"]`（**即恒需 `os-poll`**），并保留 `os-util = ["os-ext"]` 作兼容别名；`v0.7.6` / `v0.7.10` / `v0.8.0` 的 `lib.rs` 都是 `#[cfg(all(windows, feature = "os-ext"))] pub mod windows`。**⚠️ `0.7.2` / `0.7.3` 在 crates.io 上已 yank**（实测 `crates.io/api/v1/crates/mio/{0.7.2,0.7.3}` 的 `yanked` 均为 `true`），故**实际可用下限是 `0.7.10`**；写 `0.7.2` 只为说明「该模块出现得比 0.8 早」。把 IOCP 转换为就绪模型，可直接接入同一 `Poll`）。**仅在目标 mio 版本不提供或行为不满足时**，才自研 overlapped-IO 实现。
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
| **临时端口段与发现端口相邻/重叠**（2026-11-05 发现 N-48；**2026-11-10 按 D-4 迁出**） | 发现用的端口块为**组播 `23100` + 单播 `23101..23200`**（[线格式 §8.1](api/wire-format.md) 有选择理由的逐项核对）。**默认配置下不冲突**：Linux `ip_local_port_range` 默认 `32768–60999`、Windows 默认 `49152–65535`，块完全在外。**主要残余风险——`ip_local_port_range` 被人调宽到覆盖 23100 段**（离线加固基线、容器编排方、安全加固脚本都可能这么做）：此时期内核仍可能把该段分给**出站连接自动选源端口**的进程，抢先占走端口 → `discovery_start` 因 `bind` 失败返回 `RESOURCE_EXHAUSTED`。**核对方法**：`cat /proc/sys/net/ipv4/ip_local_port_range`，确认该区间**与 `23100–23200` 无交集**（只比上界不够——区间整体移到更高处同样无交集，却会被「上界 < 23100」误判）。**若确实重叠**：用 `sysctl -w net.ipv4.ip_local_reserved_ports=23100-23200` **保留**该段（与 N-48 短期方案相同的机制，只是端口不同），并让发现先于大量出站连接启动。**另一类冲突不在本行范围**：同机第三方软件若**显式** `bind` 了该段内的某个固定端口，内核保留段也拦不住——按端口块选择时的 IANA 核对（[线格式 §8.1](api/wire-format.md)）只能降低撞上「已注册服务」的概率，不能消除现场自定端口。**反方向**：发现占用 101 个端口、把内核对其它进程的出站端口分配切成两截的问题，随迁移一并消失（前提是 `ip_local_port_range` 未被调宽覆盖本段） |
| **`/tmp` 1–3 天清理** | socket 文件放 `/run`，不放 `/tmp` |
| **debuginfo 不可得** | 采购时索取 `kernel-devel` / `kernel-debuginfo` / SRPM |
| **国产网卡驱动** | 不假设多队列/RSS；提供单队列退化；启动时输出 `ethtool` 自检 |
| **seed 部署的防火墙要求**（2026-11-18，N-60） | 配置了 `seeds` 的一端会向 seed 主机的 **`23101..23200` 整段 100 个端口**各发一个 `CAP_Q`（bootstrap 扫描，[线格式 §8.1](api/wire-format.md)）。**seed 主机的防火墙必须放行该 UDP 段**——只开单个端口会漏：库无法预知对端从段内取了哪个端口。稳态只需对端 `BEACON` 上报的那一个端口，但 bootstrap 第一包必须扫全段。**建议规则**：`udp dport 23100-23200 accept`（含组播口 `23100`，若同时启用组播）。**不要**指望「配了 seed 就不用开组播口」——两条路径的端口要求不同，但都在同一段内 |

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
| 麒麟/UOS 是否提供官方容器镜像 | **已核实：两家都有官方 registry**（2026-11-20），详见下方 §7.1 |
| 国产网卡的 PTP 硬件时间戳支持 | 需逐型号确认 |

### 7.1 麒麟 / UOS 官方容器镜像（2026-11-20 核实）

两家都提供**公开的官方 OCI registry**（前提：CI runner 能访问这两个域名）。**注意**：它们可用作 CI 里的**兼容性冒烟**环境，但**不能**用作发布产物的构建环境——原因见下方「对 CI 的影响」。

**麒麟 — `cr.kylinos.cn`**（Harbor，`Docker-Distribution-Api-Version: registry/2.0`，匿名可读）

公共项目 `kylin` 下按 `V10-SPx` × `架构` 分仓，实测可匿名查询到：

| 仓库 | 架构 | 标签 | 大小 |
|---|---|---|---|
| `kylin/kylin-server-v10sp3-x86_64` | `amd64` | `20230324` | 91.9 MiB |
| `kylin/kylin-server-v10sp3-aarch64` | `arm64` | `20230324` | 90.9 MiB |
| `kylin/kylin-server-v10sp3-minimal-x86_64` | — | `202404` / `20220812` | 46.9 / 58.9 MiB |

拉取：`docker pull cr.kylinos.cn/kylin/kylin-server-v10sp3-x86_64:20230324`。
另有 `v10sp1` / `v10sp2` / `loongarch64` 变体、以及带 `-init`（systemd 系初始化）/ `-minimal` / `-micro` 后缀的裁剪版。

**UOS — `registry.uniontech.com`**（Harbor，同样的 `registry/2.0`），门户 `https://uoscr.chinauos.com`

仓库页的 JS 直接给出拉取命令模板 `docker pull registry.uniontech.com/uos-server-base/<repo>:<tag>`；标签与架构数据来自官方接口
`https://uoscr.chinauos.com/images/tags/uos-server-base/<repo>/`（JSON，实测可匿名取）。`uos-server-base/` 下实测 8 个变体：

| 仓库 | 标签 | 架构 | 压缩后大小 | 多架构 |
|---|---|---|---|---|
| `uos-server-20-1070a` | `latest` | **amd64 + arm64** | 206.1 MB | ✅ |
| `uos-server-20-1070e` | `latest` | **amd64 + arm64** | 303.3 MB | ✅ |
| `uos-server-20-1070u1a` | `latest` | **amd64 + arm64** | 200.4 MB | ✅ |
| `uos-server-20-1070u1e` | `latest` | **amd64 + arm64** | 291.2 MB | ✅ |
| `uos-server-20-1070-loongarch` | `loongarch64` | loong64 | 96.9 MB | — |
| `uos-server-20-1070-sw` | `sw64` | sw64 | 112.1 MB | — |
| `uos-server-20-1070u1e-sw64` | `6b` / `8a` | sw64 | 113.3 MB | ✅（同架构多标签） |
| `uos-server-2510` | `sw64-cui` 等 4 个 | sw64 | 626.7 MB | — |

⚠️ **arm64 以多架构 manifest index 提供，仓库名里不会带 `-arm64`**——按仓库名找 ARM 变体会得到错误结论。

**对 CI 的影响**：

- 麒麟的两条 `v10sp3` 镜像**覆盖了本项目的目标架构**（x86_64 + ARM64）。**但它们不直接满足任何 AC**（见下）。
- ⚠️ **不能当作发布构建环境**：`AC-E4` 要求产物不含高于 **glibc 2.17** 的符号；麒麟 V10 SP3 的 glibc 为 **2.28**（见本文件 §3.1 的平台表），远高于 2.17，在该容器里出产物会违反 `AC-E4`。正确分工是「**在 2.17 基线上出产物（含 ARM64 交叉编译），麒麟容器只在需要时做兼容性冒烟**」。容器内的实际 glibc 版本**未核实**，使用前须 `ldd --version` 确认。
- ⚠️ **容器不能替代 `AC-P2` / `AC-P4`**：`AC-P2` 要求「ARM64 构建 + QEMU 全量测试 + **实机**冒烟」，`AC-P4` 要求「麒麟 V10 SP3 / UOS 20 **实机**」。容器是 CI 便利手段，**不构成实机证据**。
- UOS 侧同样覆盖 **amd64 + arm64**（多架构 index），故架构上不构成缺口；`AC-P4` 本身只要求 x86_64 实机。
- **未能判定**：两侧镜像**均未实际 `docker pull`**（只经各自官方接口核实了架构、标签与大小），故镜像内的真实 glibc 版本仍须拉取后 `ldd --version` 确认。
- 镜像为**官方构建**，但这不等于「与实机 OS 完全等价」。用途定位：**CI 里的构建/加载冒烟与依赖解析验证**，不是验收证据来源。
