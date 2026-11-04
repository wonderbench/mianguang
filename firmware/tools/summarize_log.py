#!/usr/bin/env python3
"""Offline schema-1 JSONL engineering summary; Python 3 standard library only."""

import argparse
import hashlib
import json
from pathlib import Path
import statistics


MAX_INTERVAL_MS = 2000
FIELDS = ("presence", "bed", "rr", "hr")
LIMITS = [
    "这是工程观察摘要，不是临床睡眠报告；在床观察时长不等于睡眠时长。",
    "日志记录数不等于独立雷达读数数；RR 与 HR 分别按分段内 t_ms-age_ms 去重。",
    "去重统计仅覆盖日志可见的观测时间键，不代表模组全部采样或 UART 帧总数。",
    "非在床观察时长不等于真实离床时长或离床次数；unknown 不计作非在床。",
    "t_ms 下降仅表明重启或乱序边界，不能单凭该日志确认实际重启次数。",
    "各段时长独立相加，没有绝对时间轴；乱序分段可能重叠，不能据此宣称真实整夜时长。",
    "不推断模组睡眠阶段、睡眠质量、医学事件或医学报警。",
]


def unsigned(value, maximum):
    return type(value) is int and 0 <= value <= maximum


def validate_sample(record):
    if not unsigned(record.get("t_ms"), (1 << 64) - 1):
        return "t_ms 必须为 uint64 整数"
    for name in FIELDS:
        field = record.get(name)
        if not isinstance(field, dict):
            return name + " 字段缺失或不是对象"
        if type(field.get("available")) is not bool or type(field.get("valid")) is not bool:
            return name + " 的 available/valid 必须为布尔值"
        if not unsigned(field.get("raw"), 1 if name in ("presence", "bed") else 65535):
            return name + " 的 raw 超出日志类型范围"
        if not unsigned(field.get("age_ms"), (1 << 32) - 1):
            return name + " 的 age_ms 必须为 uint32 整数"
        if field["available"] and field["age_ms"] > record["t_ms"]:
            return name + " 的推算观测时间早于本次开机"
        if field["valid"] and not field["available"]:
            return name + " 同时 valid=true 和 available=false"
    return None


def occupancy(record):
    presence, bed = record["presence"], record["bed"]
    if not (presence["valid"] and bed["valid"]):
        return "unknown"
    if not presence["raw"] and bed["raw"]:
        return "unknown"
    return "in_bed" if presence["raw"] and bed["raw"] else "not_in_bed"


def distribution(values):
    return {
        "count": len(values),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "median": statistics.median(values) if values else None,
    }


def reject_constant(value):
    raise ValueError("非标准 JSON 数值: " + value)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("重复 JSON 属性: " + key)
        result[key] = value
    return result


def summarize_bytes(data, source_name="<memory>", synthetic=False):
    counts = dict.fromkeys((
        "physical_lines", "blank_lines", "total_records", "valid_sample_records",
        "invalid_json_records", "invalid_schema_records", "non_sample_records",
        "duplicate_timestamp_records", "timestamp_decrease_records",
    ), 0)
    segments, issues, intervals = [], [], []
    observations = {name: {} for name in ("rr", "hr")}
    durations = dict.fromkeys(("observed_ms", "in_bed_ms", "not_in_bed_ms", "unknown_ms",
                              "rr_valid_ms", "hr_valid_ms", "both_valid_ms"), 0)
    previous = None
    previous_line = None
    previous_duplicate = False
    barrier = False
    versions = set()

    for line_number, line in enumerate(data.splitlines(), 1):
        counts["physical_lines"] += 1
        if not line.strip():
            counts["blank_lines"] += 1
            continue
        counts["total_records"] += 1
        try:
            record = json.loads(line.decode("utf-8"), parse_constant=reject_constant,
                                object_pairs_hook=unique_object)
        except (UnicodeDecodeError, ValueError) as error:
            counts["invalid_json_records"] += 1
            issues.append({"line": line_number, "kind": "invalid_json", "detail": str(error)})
            barrier = True
            continue
        if not isinstance(record, dict) or type(record.get("schema")) is not int or record["schema"] != 1:
            counts["invalid_schema_records"] += 1
            issues.append({"line": line_number, "kind": "invalid_schema", "detail": "需要 schema=1 对象"})
            barrier = True
            continue
        if record.get("type") != "sample":
            counts["non_sample_records"] += 1
            if record.get("type") == "meta" and record.get("synthetic") is True:
                synthetic = True
            issues.append({"line": line_number, "kind": "non_sample", "type": record.get("type")})
            barrier = True
            continue
        error = validate_sample(record)
        if error:
            counts["invalid_schema_records"] += 1
            issues.append({"line": line_number, "kind": "invalid_schema", "detail": error})
            barrier = True
            continue

        counts["valid_sample_records"] += 1
        if isinstance(record.get("version"), str):
            versions.add(record["version"])
        delta = record["t_ms"] - previous["t_ms"] if previous else None
        is_duplicate = delta == 0
        if previous is None or delta < 0:
            if previous is not None:
                counts["timestamp_decrease_records"] += 1
                issues.append({"line": line_number, "previous_line": previous_line,
                               "kind": "restart_or_out_of_order", "delta_ms": delta})
            segments.append({"id": len(segments) + 1, "start_line": line_number,
                             "end_line": line_number, "first_t_ms": record["t_ms"],
                             "last_t_ms": record["t_ms"], "sample_records": 0,
                             "boundary": "start" if previous is None else "restart_or_out_of_order"})
        segment = segments[-1]
        segment.update(end_line=line_number, last_t_ms=record["t_ms"])
        segment["sample_records"] += 1
        if is_duplicate:
            counts["duplicate_timestamp_records"] += 1
            issues.append({"line": line_number, "previous_line": previous_line,
                           "kind": "duplicate_timestamp", "t_ms": record["t_ms"]})
        if delta is not None and delta > 0:
            exclusion = None
            if barrier:
                exclusion = "intervening_invalid_or_non_sample_record"
            elif previous_duplicate:
                exclusion = "duplicate_left_timestamp"
            elif delta > MAX_INTERVAL_MS:
                exclusion = "gap_over_2000_ms"
            interval = {"segment_id": segment["id"], "left_line": previous_line,
                        "right_line": line_number, "start_t_ms": previous["t_ms"],
                        "end_t_ms": record["t_ms"], "duration_ms": delta,
                        "included": exclusion is None, "exclusion": exclusion}
            if exclusion is None:
                state = occupancy(previous)
                rr_valid, hr_valid = previous["rr"]["valid"], previous["hr"]["valid"]
                interval.update(occupancy=state, rr_valid=rr_valid, hr_valid=hr_valid)
                durations["observed_ms"] += delta
                durations[state + "_ms"] += delta
                durations["rr_valid_ms"] += delta if rr_valid else 0
                durations["hr_valid_ms"] += delta if hr_valid else 0
                durations["both_valid_ms"] += delta if rr_valid and hr_valid else 0
            intervals.append(interval)

        for name in observations:
            field = record[name]
            if not field["available"]:
                continue
            observed_ms = record["t_ms"] - field["age_ms"]
            key = (segment["id"], observed_ms)
            item = observations[name].setdefault(key, {
                "segment_id": segment["id"], "observation_t_ms": observed_ms,
                "raw_values": [], "source_lines": [], "valid_source_lines": [],
            })
            if field["raw"] not in item["raw_values"]:
                item["raw_values"].append(field["raw"])
            item["source_lines"].append(line_number)
            if field["valid"]:
                item["valid_source_lines"].append(line_number)
        previous, previous_line = record, line_number
        previous_duplicate, barrier = is_duplicate, False

    field_reports = {}
    for name, by_timestamp in observations.items():
        items = list(by_timestamp.values())
        unambiguous = [item for item in items if len(item["raw_values"]) == 1]
        conflicts = [item for item in items if len(item["raw_values"]) != 1]
        for item in conflicts:
            issues.append({"kind": "conflicting_observation", "field": name,
                           "segment_id": item["segment_id"],
                           "observation_t_ms": item["observation_t_ms"],
                           "source_lines": item["source_lines"]})
        field_reports[name] = {
            "unit": "次/分钟",
            "unique_observation_keys": len(items),
            "conflicting_observation_keys": len(conflicts),
            "available_raw": distribution([item["raw_values"][0] for item in unambiguous]),
            "valid_raw": distribution([item["raw_values"][0] for item in unambiguous
                                       if item["valid_source_lines"]]),
            "observations": items,
        }
    for segment in segments:
        segment["span_ms"] = segment["last_t_ms"] - segment["first_t_ms"]
    span_ms = sum(segment["span_ms"] for segment in segments)
    excluded_ms = sum(item["duration_ms"] for item in intervals if not item["included"])
    observed_ms = durations["observed_ms"]
    return {
        "report_schema": 1,
        "report_type": "engineering_log_summary",
        "synthetic": synthetic,
        "notice": "合成模拟非实测 — 仅用于工具验证" if synthetic else "工程日志摘要 — 数据来源真实性未经本工具核验",
        "source": {"path": str(source_name), "sha256": hashlib.sha256(data).hexdigest(),
                   "bytes": len(data), "firmware_versions": sorted(versions)},
        "method": {
            "max_interval_ms": MAX_INTERVAL_MS,
            "time_rule": "按文件顺序，只计同段相邻有效 sample 的 0<dt<=2000 ms 区间，使用左端标志；末行不外推。",
            "barrier_rule": "坏行、非 sample 记录以及重复时间记录后的区间均不计时；空白行忽略。",
            "segment_rule": "t_ms 为 64 位开机相对时间；每次下降切段，重启与乱序无法区分；不排序、不跨段拼接。",
            "coverage_denominator": "observed_ms（可积分观察时间）；另报其占各段首末跨度之和的比例。",
            "dedup_rule": "RR/HR 独立使用 (segment_id,t_ms-age_ms)；同键不同 raw 排除；同键任一有效标志可纳入 valid_raw。",
            "validity_rule": "沿用日志 available/valid 标志，不重算固件质量门控。presence/bed 冲突计 unknown。",
            "median_rule": "对去重后的原始读数算中位数，不对 trend.rr_median/hr_median 再求中位数；不按时间加权。",
        },
        "counts": dict(counts, segment_count=len(segments),
                       restart_or_out_of_order_boundaries=max(0, len(segments) - 1)),
        "time": dict(durations, segment_span_ms=span_ms, excluded_forward_ms=excluded_ms,
                     observed_fraction_of_segment_spans=observed_ms / span_ms if span_ms else None),
        "coverage": {name: {"valid_ms": durations[name + "_valid_ms"],
                            "fraction_of_observed": durations[name + "_valid_ms"] / observed_ms if observed_ms else None}
                     for name in ("rr", "hr", "both")},
        "segments": segments,
        "fields": field_reports,
        "issues": issues,
        "intervals": intervals,
        "limitations": LIMITS,
    }


def summarize_file(path, synthetic=False):
    path = Path(path)
    return summarize_bytes(path.read_bytes(), path.resolve(), synthetic)


def percent(value):
    return "无可计算区间" if value is None else f"{value:.1%}"


def markdown_report(report):
    c, t = report["counts"], report["time"]
    seconds = lambda value: f"{value / 1000:.3f} 秒"
    lines = ["# 固件日志工程摘要", "", "**" + report["notice"] + "**", "",
             f"来源：`{report['source']['path']}`  ",
             f"SHA-256：`{report['source']['sha256']}`", "",
             f"非空记录 {c['total_records']} 条，其中结构有效 sample {c['valid_sample_records']} 条；"
             f"无效 JSON {c['invalid_json_records']} 条，结构不合格 {c['invalid_schema_records']} 条，"
             f"非 sample {c['non_sample_records']} 条。空白行 {c['blank_lines']} 条。",
             f"重复相邻时间 {c['duplicate_timestamp_records']} 次，时间下降 {c['timestamp_decrease_records']} 次，"
             f"共 {c['segment_count']} 段。时间下降按重启或乱序边界处理，不能确证重启。", "",
             "| 时间项目 | 结果 |", "| --- | --- |",
             f"| 各段首末跨度之和 | {seconds(t['segment_span_ms'])} |",
             f"| 可积分观察时间 | {seconds(t['observed_ms'])}（跨度的 {percent(t['observed_fraction_of_segment_spans'])}） |",
             f"| 已知正向间隔中未计时间 | {seconds(t['excluded_forward_ms'])} |",
             f"| 有效在床观察 | {seconds(t['in_bed_ms'])} |",
             f"| 有效非在床观察 | {seconds(t['not_in_bed_ms'])} |",
             f"| 在床状态 unknown | {seconds(t['unknown_ms'])} |", "",
             "覆盖率分母为可积分观察时间。缺口和跨分段时间不补齐，也不自动算入 unknown。", "",
             "| 指标 | 有效时间 / 覆盖率 | 有效去重原始读数数 | 中位数 | 范围 |",
             "| --- | --- | --- | --- | --- |"]
    for name, label in (("rr", "RR 呼吸频率"), ("hr", "HR 心率")):
        raw, coverage = report["fields"][name]["valid_raw"], report["coverage"][name]
        median = "无" if raw["median"] is None else str(raw["median"])
        value_range = "无" if not raw["count"] else f"{raw['min']}–{raw['max']}"
        lines.append(f"| {label} | {seconds(coverage['valid_ms'])} / {percent(coverage['fraction_of_observed'])} | "
                     f"{raw['count']} | {median} | {value_range} |")
    lines += ["", "RR/HR 单位为次/分钟。原始读数按各字段独立的 `(分段,t_ms-age_ms)` 去重；"
              "中位数不使用固件趋势中位数，日志行数不当作独立样本数。原始 available 读数范围、冲突和来源行见 JSON。", "",
              "| 分段 | 来源行 | t_ms 范围 | sample 条数 |", "| --- | --- | --- | --- |"]
    for segment in report["segments"]:
        lines.append(f"| {segment['id']} | {segment['start_line']}–{segment['end_line']} | "
                     f"{segment['first_t_ms']}–{segment['last_t_ms']} | {segment['sample_records']} |")
    lines += ["", "统计只延续至下一条有效记录，且间隔须大于 0、不超过 2 秒；末条不外推。"
              "坏行/非 sample 会阻断区间；重复时间行不贡献时长，其后区间也保守排除。", ""]
    lines.extend("- " + limitation for limitation in report["limitations"])
    lines += ["", "JSON 附有每个计入/排除区间、原始读数来源行、异常位置与源文件哈希，可据此复核。", ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="离线生成 schema 1 JSONL 工程摘要，不连接硬件。")
    parser.add_argument("log", type=Path, help="输入 JSONL 文件")
    parser.add_argument("--json", required=True, type=Path, dest="json_path", help="JSON 摘要输出文件")
    parser.add_argument("--markdown", required=True, type=Path, help="中文 Markdown 摘要输出文件")
    parser.add_argument("--synthetic", action="store_true", help="醒目标注输入为合成模拟非实测")
    args = parser.parse_args(argv)
    if len({args.log.resolve(), args.json_path.resolve(), args.markdown.resolve()}) != 3:
        parser.error("输入、JSON 输出和 Markdown 输出必须为不同文件")
    try:
        report = summarize_file(args.log, args.synthetic)
        for path in (args.json_path, args.markdown):
            path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        args.markdown.write_text(markdown_report(report), encoding="utf-8")
    except OSError as error:
        parser.exit(1, "文件处理失败：" + str(error) + "\n")
    print(f"已生成工程摘要：{args.json_path} 和 {args.markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
