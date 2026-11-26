#!/usr/bin/env python3
"""实验证据汇总（只读）。

职责边界（对应个人任务书 04-C）：
  * 只读读取现有实验结果，不运行实验、不改动结果文件。
  * 每项记录：实验名称、代码版本、数据来源、模型/网关来源、结果路径、
    请求次数、耗时、结论限制。
  * 严格区分六类证据来源；无法判定或无证据的内容标注"未开展/待确认"。

用法：
  python dev/tests/export_experiment_summary.py \
      --scan tmp docs/experiments \
      --out docs/experiments/EXPERIMENT_SUMMARY.json \
      --index docs/experiments/EVIDENCE_INDEX.md

退出码始终为 0（汇总脚本不因数据缺失而中断，缺失项在输出中标注）。
"""

import argparse
import json
import os
import sys
from datetime import datetime


# 六类证据来源，顺序固定；判定依赖结果 JSON 中的 evidence_type 字段。
EVIDENCE_TYPES = [
    ("official_io", "官方 IO 校验"),
    ("fixed_fixture", "固定值夹具"),
    ("scripted_gateway", "脚本化网关"),
    ("in_process_stub", "进程内替身"),
    ("real_model", "真实模型调用"),
    ("official_eval", "官方正式评测"),
]
TYPE_LABEL = dict(EVIDENCE_TYPES)

# 结果 JSON 中字段名候选，按优先级取第一个命中的。
FIELD_ALIASES = {
    "experiment_name": ["experiment_name", "name", "experiment", "exp_name"],
    "code_version": ["code_version", "version", "commit", "git_commit", "revision"],
    "data_source": ["data_source", "dataset", "input_data", "data"],
    "model_source": ["model_source", "model", "gateway", "model_or_gateway", "backend"],
    "evidence_type": ["evidence_type", "source_type", "evidence", "category"],
    "request_count": ["request_count", "requests", "num_requests", "call_count"],
    "elapsed": ["elapsed_seconds", "elapsed", "duration_seconds", "duration", "time_sec"],
    "limitation": ["limitation", "conclusion_limit", "limitations", "notes", "caveat"],
}

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv"}


def _pick(obj, aliases):
    for key in aliases:
        if key in obj and obj[key] not in (None, ""):
            return obj[key]
    return None


def _walk_json_files(paths):
    """遍历给定文件或目录，产出所有 .json 文件路径（跳过 SKIP_DIRS）。"""
    seen = set()
    for p in paths:
        if os.path.isfile(p):
            if p.endswith(".json"):
                yield os.path.abspath(p)
            continue
        if not os.path.isdir(p):
            continue
        for root, dirs, files in os.walk(p):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in sorted(files):
                if name.endswith(".json"):
                    full = os.path.abspath(os.path.join(root, name))
                    if full not in seen:
                        seen.add(full)
                        yield full


def _classify(value):
    """把 evidence_type 原始值归一到六类之一，无法判定返回 None。"""
    if value is None:
        return None
    raw = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "official_io": "official_io",
        "official_io_check": "official_io",
        "io_validation": "official_io",
        "fixed_fixture": "fixed_fixture",
        "fixture": "fixed_fixture",
        "fixed_value": "fixed_fixture",
        "scripted_gateway": "scripted_gateway",
        "gateway": "scripted_gateway",
        "script_gateway": "scripted_gateway",
        "in_process_stub": "in_process_stub",
        "stub": "in_process_stub",
        "inprocess": "in_process_stub",
        "real_model": "real_model",
        "real_llm": "real_model",
        "live_model": "real_model",
        "official_eval": "official_eval",
        "official_evaluation": "official_eval",
        "formal_eval": "official_eval",
    }
    if raw in aliases:
        return aliases[raw]
    # 中文标签直接匹配
    for key, label in EVIDENCE_TYPES:
        if raw == label:
            return key
    return None


# 结果专属字段：命中任意一个才视为实验结果，避免把输入数据文件误当结果。
RESULT_MARKERS = [
    "evidence_type", "source_type", "evidence", "category",
    "request_count", "requests", "num_requests", "call_count",
    "elapsed_seconds", "elapsed", "duration_seconds", "duration", "time_sec",
    "limitation", "conclusion_limit", "limitations", "caveat",
    "experiment_name", "exp_name", "result", "results", "output",
    "offline_score", "comparison", "summary",
]


def is_result_file(data):
    """判断是否实验结果文件：顶层含任一结果专属字段。输入数据文件返回 False。"""
    if not isinstance(data, dict):
        return False
    return any(k in data for k in RESULT_MARKERS)


def summarize_file(path):
    """只读读取一个结果 JSON，返回一条汇总记录。"""
    record = {
        "result_path": os.path.relpath(path, os.getcwd()).replace("\\", "/"),
        "experiment_name": None,
        "code_version": None,
        "data_source": None,
        "model_source": None,
        "evidence_type_raw": None,
        "evidence_type": None,
        "evidence_type_label": "未开展/待确认",
        "request_count": None,
        "elapsed_seconds": None,
        "limitation": None,
        "parse_error": None,
    }
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:  # noqa: BLE001
        record["parse_error"] = "%s: %s" % (type(exc).__name__, exc)
        return record
    if not isinstance(data, dict):
        record["parse_error"] = "顶层非对象，跳过字段提取"
        return record

    record["experiment_name"] = _pick(data, FIELD_ALIASES["experiment_name"])
    record["code_version"] = _pick(data, FIELD_ALIASES["code_version"])
    record["data_source"] = _pick(data, FIELD_ALIASES["data_source"])
    record["model_source"] = _pick(data, FIELD_ALIASES["model_source"])
    record["request_count"] = _pick(data, FIELD_ALIASES["request_count"])
    record["elapsed_seconds"] = _pick(data, FIELD_ALIASES["elapsed"])
    record["limitation"] = _pick(data, FIELD_ALIASES["limitation"])

    raw = _pick(data, FIELD_ALIASES["evidence_type"])
    record["evidence_type_raw"] = raw
    kind = _classify(raw)
    if kind:
        record["evidence_type"] = kind
        record["evidence_type_label"] = TYPE_LABEL[kind]
    elif raw is not None:
        record["evidence_type_label"] = "未识别（%s）" % raw
    return record


def build_summary(records, scan_paths):
    by_type = {}
    for key, label in EVIDENCE_TYPES:
        by_type[key] = [r for r in records if r["evidence_type"] == key]
    unknown = [r for r in records if r["evidence_type"] is None]
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scan_paths": [os.path.relpath(p, os.getcwd()).replace("\\", "/") for p in scan_paths],
        "evidence_type_legend": [{"key": k, "label": l} for k, l in EVIDENCE_TYPES],
        "total_records": len(records),
        "counts_by_type": {k: len(v) for k, v in by_type.items()},
        "unclassified_count": len(unknown),
        "records": records,
        "note": "各项为只读汇总；无证据来源的实验类型 counts 为 0，表示未开展。",
    }


def render_index(summary):
    """生成可写入 EVIDENCE_INDEX.md 的区间文本（含 AUTO_SUMMARY 标记）。"""
    lines = [
        "<!-- AUTO_SUMMARY_START -->",
        "## 自动汇总结果（由 export_experiment_summary.py 生成）",
        "",
        "生成时间：%s" % summary["generated_at"],
        "扫描路径：%s" % ", ".join(summary["scan_paths"]),
        "输入/非结果文件已跳过：%d 个（不计入证据）" % summary.get("skipped_input_count", 0),
        "",
        "### 各类型证据计数",
        "",
        "| 证据类型 | 记录数 | 状态 |",
        "| --- | --- | --- |",
    ]
    for key, label in EVIDENCE_TYPES:
        count = summary["counts_by_type"][key]
        lines.append("| %s | %d | %s |" % (label, count, "有证据" if count else "未开展"))
    lines.append("| 未识别/待确认 | %d | 待确认 |" % summary["unclassified_count"])
    lines += [
        "",
        "### 记录明细",
        "",
        "| 实验名称 | 代码版本 | 证据类型 | 数据来源 | 模型/网关来源 | 请求次数 | 耗时(s) | 结果路径 | 结论限制 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    if not summary["records"]:
        lines.append("| （无结果记录） | — | — | — | — | — | — | — | — |")
    for r in summary["records"]:
        def cell(v):
            return "—" if v in (None, "") else str(v).replace("|", "\\|").replace("\n", " ")
        if r["parse_error"]:
            lines.append("| %s | — | 解析失败 | — | — | — | — | %s | %s |"
                         % (cell(r["experiment_name"]), cell(r["result_path"]), cell(r["parse_error"])))
            continue
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            cell(r["experiment_name"]), cell(r["code_version"]),
            cell(r["evidence_type_label"]), cell(r["data_source"]),
            cell(r["model_source"]), cell(r["request_count"]),
            cell(r["elapsed_seconds"]), cell(r["result_path"]), cell(r["limitation"])))
    lines += ["", "<!-- AUTO_SUMMARY_END -->"]
    return "\n".join(lines)


def inject_or_write(out_path, block):
    markers = ("<!-- AUTO_SUMMARY_START -->", "<!-- AUTO_SUMMARY_END -->")
    if os.path.isfile(out_path):
        with open(out_path, "r", encoding="utf-8") as fh:
            text = fh.read()
        if markers[0] in text and markers[1] in text:
            head, rest = text.split(markers[0], 1)
            _, tail = rest.split(markers[1], 1)
            new_inner = block.split(markers[0], 1)[1].split(markers[1], 1)[0]
            with open(out_path, "w", encoding="utf-8") as fh:
                fh.write(head + markers[0] + new_inner + markers[1] + tail)
            return
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(block)


def main(argv=None):
    parser = argparse.ArgumentParser(description="实验证据汇总（只读）")
    parser.add_argument("--scan", nargs="+", default=["tmp", "docs/experiments"],
                        help="待扫描的结果文件或目录（只读）")
    parser.add_argument("--out", default="docs/experiments/EXPERIMENT_SUMMARY.json",
                        help="汇总 JSON 输出路径")
    parser.add_argument("--index", default=None,
                        help="可选：把汇总区间写入/更新到 EVIDENCE_INDEX.md")
    args = parser.parse_args(argv)

    files = list(_walk_json_files(args.scan))
    result_files = []
    skipped = []
    for p in files:
        try:
            with open(p, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:  # noqa: BLE001 - 解析失败的文件仍作为结果收录并在记录中标注
            result_files.append(p)
            continue
        if is_result_file(data):
            result_files.append(p)
        else:
            skipped.append(os.path.relpath(p, os.getcwd()).replace("\\", "/"))

    records = [summarize_file(p) for p in result_files]
    summary = build_summary(records, [os.path.abspath(p) for p in args.scan])
    summary["skipped_input_files"] = skipped
    summary["skipped_input_count"] = len(skipped)

    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    print("已扫描 %d 个 JSON：结果文件 %d，输入/非结果文件 %d（已跳过），写入 %s"
          % (len(files), len(records), len(skipped), args.out))

    if args.index:
        inject_or_write(args.index, render_index(summary))
        print("已更新索引区间: %s" % args.index)

    for key, label in EVIDENCE_TYPES:
        print("  %s: %d" % (label, summary["counts_by_type"][key]))
    print("  未识别/待确认: %d" % summary["unclassified_count"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
