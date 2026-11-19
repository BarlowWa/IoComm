#!/usr/bin/env python3
"""AC-E6：每个 P0 的 FR 至少对应一条 AC。

判据来源：docs/requirements.md §5.3 的 AC-E6 行（口径定稿于 2026-11-19）。

覆盖关系从三张验收表里取：
  §5.1 功能验收 —— 第 4 列「覆盖」
  §5.2 平台验收 / §5.3 工程验收 —— 判定单元格里的「覆盖 FR-x.y」括注

被 ci/ac-e6-exceptions.txt 显式登记为「实现约束」的 P0 FR 视为通过。

退出码：
  0  全部 P0 FR 有覆盖或被豁免
  1  存在无覆盖的 P0 FR，或豁免清单里有无法解析的行
  2  文档结构无法解析（找不到表头 / FR 数为 0），检查器自身失效

本检查器只读、不修改任何文件。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# 本文件位于 <repo>/ci/，默认仓库根为上一级。
# 用 resolve() 跟随符号链接：若仓库或 ci/ 被软链引用，仍能定位到真实的 docs/ 与豁免清单。
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REQUIREMENTS = REPO_ROOT / "docs" / "requirements.md"
DEFAULT_EXCEPTIONS = REPO_ROOT / "ci" / "ac-e6-exceptions.txt"

FR_RE = re.compile(r"^FR-(\d+)\.(\d+)([a-z]?)$")
FR_IN_TEXT_RE = re.compile(r"\bFR-\d+\.\d+[a-z]?\b")
# 「覆盖 FR-x.y」但**排除**「不覆盖 FR-x.y」这类否定写法——否则一句「这里不覆盖 FR-7.2」
# 反而会被当成覆盖声明，检查器比自己声称的更宽。
#
# ⚠️ 这是**前缀黑名单**，不是穷举：`不` / `未` 被挡住，但「无覆盖 FR-7.2」「不是覆盖 FR-7.2」
# 仍会被当成覆盖声明。根治的做法是白名单（「覆盖」前只允许行首 / 标点 / 空白 / 括号），
# 注意不能写成固定宽度的后顾 `(?<=^|[…])`——Python re 会抛
# `look-behind requires fixed-width pattern`；要写成 `(?:^|(?<=[…] ))覆盖…`。
# 代价是中文正文里「…，覆盖 FR-x.y」这类写法要逐个兼容。当前依赖一条**不成文约定**：
# 判定列不出现否定式覆盖表述（现文档中「覆盖 FR-」只有 AC-P5 一处，故未触发）。
# 实测覆盖面与取舍记在 ci/README.md「否定式的实际覆盖面」一节。
COVER_ANNOTATION_RE = re.compile(r"(?<![不未])覆盖\s*(FR-\d+\.\d+[a-z]?)")


def _force_utf8_stdio() -> None:
    """把 stdout / stderr 钉到 UTF-8。

    不加这个，在 `LANG=C` 的 Linux CI 上打印中文会抛 UnicodeEncodeError——
    而 Python 的未捕获异常退出码是 1，与「发现无覆盖的 FR」**撞码**，
    CI 会把检查器自身崩溃误报成「需求缺 AC」。宁可输出成 UTF-8 字节，
    也不要把两种完全不同的失败混为一谈。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


_force_utf8_stdio()

# 优先级单元格里 P0 可能写成 `P0`、`**P0**`、`P0（说明）`、`**P0**（预算）/ arena 部分 P1` 等形态。
# 只认 `startswith("P0")` 会漏掉加粗形态——那会让一条真正 P0 的需求**静默地**不被检查，
# 正是本脚本要防的那类漏检。故先剥掉强调符号再判前缀。
LEADING_EMPHASIS = re.compile(r"^[*`_\s]+")


def _is_p0(priority: str) -> bool:
    return bool(re.match(r"P0(?![0-9])", LEADING_EMPHASIS.sub("", priority)))


def split_row(line: str) -> list[str]:
    """按未转义的 `|` 切分表格行。

    单元格正文里可能出现 `\\|`（如 `grep -n "node_id\\|runtime_config"`），
    直接 str.split('|') 会把一格切成两格，导致覆盖列取错位置。
    """
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]

    cells: list[str] = []
    buf: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body) and body[i + 1] == "|":
            buf.append("\\|")
            i += 2
            continue
        if ch == "|":
            cells.append("".join(buf).strip())
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    cells.append("".join(buf).strip())
    return cells


def is_separator(line: str) -> bool:
    return bool(re.fullmatch(r"\|[\s:|-]+\|", line.strip()))


def is_row(line: str) -> bool:
    return line.lstrip().startswith("|")


def iter_sections(lines: list[str]):
    """产出 (level2_heading, table_header_cells, row_cells)。"""
    h2 = ""
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("## "):
            h2 = line[3:].strip()

        if is_row(line) and i + 1 < len(lines) and is_separator(lines[i + 1]):
            header = split_row(line)
            j = i + 2
            while j < len(lines) and is_row(lines[j]):
                yield h2, header, split_row(lines[j])
                j += 1
            i = j
            continue
        i += 1


def collect(lines: list[str]) -> tuple[dict[str, str], dict[str, list[str]]]:
    """返回 (P0 FR -> 优先级单元格, FR -> 覆盖它的验证项编号列表)。"""
    p0: dict[str, str] = {}
    covered: dict[str, list[str]] = {}

    for h2, header, cells in iter_sections(lines):
        if not cells or not cells[0]:
            continue
        item = cells[0].strip("*` ")

        # FR 表：编号 | 需求 | 优先级
        if FR_RE.match(item):
            priority = cells[-1]
            if _is_p0(priority):
                p0[item] = priority
            continue

        if not h2.startswith("5. 验收标准"):
            continue

        # 验收表：§5.1 有独立的「覆盖」列，整格都算覆盖声明；
        # §5.2 / §5.3 只有三列，覆盖关系写成判定里的「覆盖 FR-x.y」括注。
        #
        # 两种口径必须分开：若在不带覆盖列的表格上也套用 FR_IN_TEXT_RE（匹配任意 FR 提及），
        # 判定格里任何一句「参见 FR-3.8」都会被当成覆盖声明，检查器就比文档承诺的更宽，
        # 该报的缺口会被静默放行。
        if "覆盖" in header:
            idx = header.index("覆盖")
            mentions = FR_IN_TEXT_RE.findall(cells[idx] if idx < len(cells) else "")
        else:
            for name in ("判定", "结果"):
                if name in header:
                    idx = header.index(name)
                    if idx < len(cells):
                        mentions = COVER_ANNOTATION_RE.findall(cells[idx])
                    break
            else:
                mentions = []

        for fr in mentions:
            covered.setdefault(fr, []).append(item)

    return p0, covered


def load_exceptions(path: Path) -> dict[str, str]:
    """豁免清单：每行 `FR-x.y  # 理由` 或 `FR-x.y`。返回 id -> 理由。"""
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        out[line] = raw.split("#", 1)[1].strip() if "#" in raw else ""
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="AC-E6: 每个 P0 的 FR 至少对应一条 AC")
    ap.add_argument("--requirements", type=Path, default=DEFAULT_REQUIREMENTS)
    ap.add_argument("--exceptions", type=Path, default=DEFAULT_EXCEPTIONS)
    ap.add_argument("-v", "--verbose", action="store_true", help="逐条列出 P0 FR 的判定")
    args = ap.parse_args()

    # 输入侧也要兜住：文件不是合法 UTF-8 时 read_text 抛 UnicodeDecodeError，
    # 它**不是** OSError 子类——漏掉就会以未捕获异常退出（码 1），与「发现无覆盖的 FR」撞码。
    try:
        text = args.requirements.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"[AC-E6] 无法读取 {args.requirements}: {exc}", file=sys.stderr)
        return 2
    except UnicodeDecodeError as exc:
        print(
            f"[AC-E6] {args.requirements} 不是合法的 UTF-8：{exc}\n"
            "        （检查器失效，不是需求缺失）",
            file=sys.stderr,
        )
        return 2

    p0, covered = collect(text.splitlines())

    if not p0:
        print("[AC-E6] 未解析到任何 P0 FR —— 文档结构或检查器假设已失效", file=sys.stderr)
        return 2

    exceptions = load_exceptions(args.exceptions)

    # 豁免清单里指向不存在 FR 的条目：算错误，避免拼错一个 id 就悄悄豁免了别的东西。
    unknown = sorted(f for f in exceptions if f not in p0)
    missing = sorted(f for f in p0 if f not in covered and f not in exceptions)

    if args.verbose:
        for fr in sorted(p0):
            if fr in exceptions:
                verdict = "豁免"
            elif fr in covered:
                verdict = "覆盖  " + " / ".join(sorted(set(covered[fr])))
            else:
                verdict = "缺失"
            print(f"  {verdict:<28} {fr}")

    total = len(p0)
    if missing or unknown:
        for fr in missing:
            print(f"[AC-E6] FAIL {fr} 是 P0，但没有对应的 AC，且未在豁免清单登记")
        for fr in unknown:
            print(f"[AC-E6] FAIL 豁免清单里的 {fr} 不是 P0 FR（拼写错误或已删除？）")
        print(f"\n[AC-E6] {total} 个 P0 FR，{len(missing)} 个无覆盖，{len(unknown)} 个无效豁免")
        return 1

    note = f"，{len(exceptions)} 个豁免" if exceptions else ""
    print(f"[AC-E6] OK  {total} 个 P0 FR 全部有覆盖{note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
