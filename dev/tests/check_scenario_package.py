#!/usr/bin/env python3
"""场景包一致性检查（只读）。

职责边界（对应个人任务书 04-B）：
  * 只做格式和一致性检查：文件存在性、JSON 可解析性、必需字段、类型、
    矩阵/向量维度、有限数值、报告引用文件是否存在。
  * 不生成任何专用决策数据，不修改场景文件本身。

用法：
  python dev/tests/check_scenario_package.py \
      --root data/team_scenario \
      --manifest data/team_scenario/manifest.json \
      --out docs/scenario/SCENARIO_PACKAGE_CHECK.md

manifest.json 格式见 data/team_scenario/manifest.json 中的模板条目。
退出码：0=全部通过；1=存在 FAIL；2=配置或参数错误。
"""

import argparse
import json
import math
import os
import sys
from datetime import datetime


# ---------- 通用工具 ----------

def _get_by_path(obj, dotted):
    """按点分路径取值，例如 'simulation.tick_rate_hz'。返回 (found, value)。"""
    cur = obj
    for key in dotted.split("."):
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        elif isinstance(cur, list) and key.isdigit() and int(key) < len(cur):
            cur = cur[int(key)]
        else:
            return False, None
    return True, cur


def _reject_constant(value):
    """拒绝 JSON 中的 NaN / Infinity，保证有限数值检查生效。"""
    raise ValueError("非有限数值常量: %s" % value)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_type(value, expected):
    table = {
        "object": lambda v: isinstance(v, dict),
        "array": lambda v: isinstance(v, list),
        "string": lambda v: isinstance(v, str),
        "number": _is_number,
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "boolean": lambda v: isinstance(v, bool),
        "null": lambda v: v is None,
    }
    if expected not in table:
        return None  # 未知类型声明
    return table[expected](value)


def _all_finite(obj, path="$"):
    """递归检查所有数值是否有限，返回问题列表。"""
    problems = []
    if _is_number(obj):
        if not math.isfinite(obj):
            problems.append("%s = %r 非有限" % (path, obj))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            problems.extend(_all_finite(v, "%s.%s" % (path, k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            problems.extend(_all_finite(v, "%s[%d]" % (path, i)))
    return problems


def _check_vector(value):
    if not isinstance(value, list):
        return False, "不是数组"
    if not all(_is_number(x) for x in value):
        return False, "含非数值元素"
    return True, "维度 %d" % len(value)


def _check_matrix(value):
    if not isinstance(value, list) or not all(isinstance(row, list) for row in value):
        return False, "不是二维数组"
    if not value:
        return True, "空矩阵（0x0）"
    width = len(value[0])
    if any(len(row) != width for row in value):
        return False, "各行列数不一致: %s" % [len(r) for r in value]
    if not all(_is_number(x) for row in value for x in row):
        return False, "含非数值元素"
    return True, "维度 %dx%d" % (len(value), width)


# ---------- 单个条目检查 ----------

def check_entry(entry, root):
    """返回 (results, data)，results 为 [(item, status, detail)]。"""
    results = []
    rel = entry.get("path", "")
    full = os.path.join(root, rel)
    checks = entry.get("checks", {}) or {}

    # 1. 文件存在性
    if not os.path.isfile(full):
        results.append(("文件存在", "FAIL", "缺失: %s" % full))
        return results, None
    results.append(("文件存在", "PASS", rel))

    # 2. JSON 可解析性
    data = None
    if checks.get("json", True):
        try:
            with open(full, "r", encoding="utf-8") as fh:
                data = json.load(fh, parse_constant=_reject_constant)
            results.append(("JSON 可解析", "PASS", "parse_constant 已启用"))
        except Exception as exc:  # noqa: BLE001 - 汇总所有格式问题
            results.append(("JSON 可解析", "FAIL", "%s: %s" % (type(exc).__name__, exc)))
            return results, None
    else:
        try:
            with open(full, "r", encoding="utf-8") as fh:
                raw = fh.read()
            data = {"__text__": raw}
            results.append(("文本可读", "PASS", "非 JSON 文件，跳过结构检查"))
        except Exception as exc:  # noqa: BLE001
            results.append(("文本可读", "FAIL", str(exc)))
            return results, None

    # 3. 必需字段
    for field in checks.get("required_fields", []):
        found, value = _get_by_path(data, field)
        if not found or value is None:
            results.append(("必需字段 %s" % field, "FAIL", "缺失或为 null"))
        else:
            results.append(("必需字段 %s" % field, "PASS", "存在"))

    # 4. 字段类型
    for field, expected in checks.get("field_types", {}).items():
        found, value = _get_by_path(data, field)
        if not found:
            results.append(("类型 %s" % field, "FAIL", "字段不存在"))
            continue
        verdict = _check_type(value, expected)
        if verdict is None:
            results.append(("类型 %s" % field, "WARN", "未知类型声明: %s" % expected))
        elif verdict:
            results.append(("类型 %s" % field, "PASS", expected))
        else:
            results.append(("类型 %s" % field, "FAIL",
                            "期望 %s，实际 %s" % (expected, type(value).__name__)))

    # 5. 向量维度
    for field in checks.get("vector_fields", []):
        found, value = _get_by_path(data, field)
        if not found:
            results.append(("向量 %s" % field, "FAIL", "字段不存在"))
            continue
        ok, detail = _check_vector(value)
        results.append(("向量 %s" % field, "PASS" if ok else "FAIL", detail))

    # 6. 矩阵维度
    for field in checks.get("matrix_fields", []):
        found, value = _get_by_path(data, field)
        if not found:
            results.append(("矩阵 %s" % field, "FAIL", "字段不存在"))
            continue
        ok, detail = _check_matrix(value)
        results.append(("矩阵 %s" % field, "PASS" if ok else "FAIL", detail))

    # 7. 有限数值
    if checks.get("finite_numbers", True):
        problems = _all_finite(data)
        if problems:
            results.append(("有限数值", "FAIL", "; ".join(problems)))
        else:
            results.append(("有限数值", "PASS", "无 NaN/Inf"))

    return results, data


def check_report_refs(manifest, root, extra_results):
    """检查报告引用文件是否存在（manifest 顶层 report_refs）。"""
    for rel in manifest.get("report_refs", []):
        full = os.path.join(root, rel)
        if os.path.exists(full):
            extra_results.append(("报告引用 %s" % rel, "PASS", "存在"))
        else:
            extra_results.append(("报告引用 %s" % rel, "FAIL", "缺失: %s" % full))


# ---------- 报告输出 ----------

def render_report(manifest, per_file, timestamp):
    lines = [
        "# 场景包一致性检查报告",
        "",
        "> 本报告由 `dev/tests/check_scenario_package.py` 自动生成（只读检查，不生成决策数据）。",
        "> 人工差异分析请填写在标记之外，避免被覆盖。",
        "",
        "生成时间：%s" % timestamp,
        "",
        "<!-- AUTO_CHECK_START -->",
        "",
        "## 自动检查结果",
        "",
        "| 文件 | 用途 | 报告章节 | 版本日期 | 确认状态 | 检查项 | 结果 | 说明 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for entry, results in per_file:
        meta = [
            entry.get("path", ""),
            entry.get("purpose", ""),
            entry.get("report_section", ""),
            entry.get("version_date", ""),
            entry.get("status", ""),
        ]
        for item, status, detail in results:
            lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |"
                         % (meta[0], meta[1], meta[2], meta[3], meta[4],
                            item, status, str(detail).replace("|", "\\|")))
    lines += [
        "",
        "<!-- AUTO_CHECK_END -->",
        "",
    ]
    return "\n".join(lines)


def inject_or_write(out_path, block):
    """若目标文件含 AUTO_CHECK 标记则仅替换标记区间，否则写独立报告。"""
    marker_s = "<!-- AUTO_CHECK_START -->"
    marker_e = "<!-- AUTO_CHECK_END -->"
    if os.path.isfile(out_path):
        with open(out_path, "r", encoding="utf-8") as fh:
            text = fh.read()
        if marker_s in text and marker_e in text:
            head, rest = text.split(marker_s, 1)
            _, tail = rest.split(marker_e, 1)
            new_inner = block.split(marker_s, 1)[1].split(marker_e, 1)[0]
            merged = head + marker_s + new_inner + marker_e + tail
            with open(out_path, "w", encoding="utf-8") as fh:
                fh.write(merged)
            return
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(block)


def main(argv=None):
    parser = argparse.ArgumentParser(description="场景包一致性检查（只读）")
    parser.add_argument("--root", default="data/team_scenario", help="场景材料目录")
    parser.add_argument("--manifest", default=None, help="清单 JSON 路径，默认 <root>/manifest.json")
    parser.add_argument("--out", default=None, help="报告输出路径（含 AUTO_CHECK 标记则局部更新）")
    args = parser.parse_args(argv)

    manifest_path = args.manifest or os.path.join(args.root, "manifest.json")
    if not os.path.isfile(manifest_path):
        print("清单不存在: %s" % manifest_path, file=sys.stderr)
        return 2
    try:
        with open(manifest_path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh, parse_constant=_reject_constant)
    except Exception as exc:  # noqa: BLE001
        print("清单解析失败: %s" % exc, file=sys.stderr)
        return 2

    per_file = []
    all_results = []
    for entry in manifest.get("entries", []):
        results, _ = check_entry(entry, args.root)
        per_file.append((entry, results))
        all_results.extend(results)

    check_report_refs(manifest, args.root, all_results)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report = render_report(manifest, per_file, timestamp)
    # 报告引用结果不在表格内，单独追加一段
    ref_lines = [r for r in all_results if r[0].startswith("报告引用")]
    if ref_lines:
        report = report.replace(
            "<!-- AUTO_CHECK_END -->",
            "\n".join("报告引用检查：%s — %s — %s" % r for r in ref_lines)
            + "\n\n<!-- AUTO_CHECK_END -->",
        )
    if args.out:
        inject_or_write(args.out, report)

    counts = {"PASS": 0, "FAIL": 0, "WARN": 0}
    for _, status, _ in all_results:
        counts[status] = counts.get(status, 0) + 1
    print("检查完成: PASS=%d FAIL=%d WARN=%d" % (counts["PASS"], counts["FAIL"], counts["WARN"]))
    for item, status, detail in all_results:
        if status != "PASS":
            print("  [%s] %s: %s" % (status, item, detail))
    if args.out:
        print("报告: %s" % args.out)
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
