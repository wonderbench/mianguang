"""Tests of offline log accounting; all records here are synthetic, not measured."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "summarize_log.py"
SPEC = importlib.util.spec_from_file_location("summarize_log", SCRIPT)
SUMMARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SUMMARY)


def sample(t_ms, rr=16, hr=70):
    return {"schema": 1, "type": "sample", "t_ms": t_ms,
            **{name: {"raw": raw, "available": True, "valid": True,
                       "age_ms": 0, "reason": "ok"}
               for name, raw in (("presence", 1), ("bed", 1), ("rr", rr), ("hr", hr))}}


def summary(*records):
    data = "\n".join(json.dumps(item) if isinstance(item, dict) else item for item in records)
    return SUMMARY.summarize_bytes(data.encode("utf-8"))


class LogSummaryTests(unittest.TestCase):
    def test_left_endpoint_and_last_record_not_extrapolated(self):
        first, second, third = sample(1000), sample(2000), sample(3000)
        first["rr"]["valid"] = False
        third["rr"]["valid"] = False
        result = summary(first, second, third)
        self.assertEqual(result["time"]["observed_ms"], 2000)
        self.assertEqual(result["coverage"]["rr"]["valid_ms"], 1000)
        self.assertEqual(result["coverage"]["rr"]["fraction_of_observed"], 0.5)
        self.assertFalse(result["intervals"][0]["rr_valid"])
        self.assertTrue(result["intervals"][1]["rr_valid"])

    def test_two_second_limit_never_fills_large_gaps(self):
        result = summary(sample(1000), sample(3000), sample(5001), sample(6001))
        self.assertEqual(result["time"]["observed_ms"], 3000)
        self.assertEqual(result["time"]["excluded_forward_ms"], 2001)
        self.assertEqual(result["time"]["segment_span_ms"], 5001)
        self.assertEqual(result["intervals"][1]["exclusion"], "gap_over_2000_ms")

    def test_raw_dedup_is_per_field_and_not_trend_medians(self):
        records = [sample(t, rr=16, hr=hr) for t, hr in ((1000, 60), (2000, 80), (3000, 100))]
        for record in records:
            record["rr"]["age_ms"] = record["t_ms"] - 1000
            record["trend"] = {"rr_median": 999, "hr_median": 999}
        result = summary(*records)
        self.assertEqual(result["counts"]["valid_sample_records"], 3)
        self.assertEqual(result["fields"]["rr"]["valid_raw"], {"count": 1, "min": 16, "max": 16, "median": 16})
        self.assertEqual(result["fields"]["hr"]["valid_raw"]["count"], 3)
        self.assertEqual(result["fields"]["hr"]["valid_raw"]["median"], 80)
        self.assertEqual(result["fields"]["rr"]["observations"][0]["source_lines"], [1, 2, 3])

    def test_uint64_timestamps_do_not_wrap_at_uint32_boundary(self):
        start = (1 << 32) - 500
        result = summary(sample(start), sample(start + 1000), sample(start + 2000))
        self.assertEqual(result["counts"]["segment_count"], 1)
        self.assertEqual(result["time"]["observed_ms"], 2000)
        self.assertEqual(result["segments"][0]["last_t_ms"], start + 2000)

    def test_decrease_splits_segments_without_merging_observation_keys(self):
        result = summary(sample(1000, rr=10), sample(2000, rr=12),
                         sample(1000, rr=20), sample(2000, rr=24))
        self.assertEqual(result["counts"]["restart_or_out_of_order_boundaries"], 1)
        self.assertEqual(result["counts"]["timestamp_decrease_records"], 1)
        self.assertEqual(result["time"]["observed_ms"], 2000)
        self.assertEqual(result["fields"]["rr"]["valid_raw"]["count"], 4)
        self.assertEqual(result["fields"]["rr"]["valid_raw"]["median"], 16)
        self.assertEqual([item["boundary"] for item in result["segments"]],
                         ["start", "restart_or_out_of_order"])

    def test_duplicate_time_is_reported_and_next_interval_excluded(self):
        result = summary(sample(1000), sample(1000), sample(2000), sample(3000))
        self.assertEqual(result["counts"]["duplicate_timestamp_records"], 1)
        self.assertEqual(result["time"]["observed_ms"], 1000)
        self.assertEqual(result["time"]["excluded_forward_ms"], 1000)
        self.assertEqual(result["fields"]["rr"]["valid_raw"]["count"], 3)

    def test_bad_json_and_non_samples_break_continuity(self):
        result = summary(sample(1000), "broken", sample(2000),
                         {"schema": 1, "type": "error", "reason": "log_overflow"}, sample(3000))
        self.assertEqual(result["counts"]["total_records"], 5)
        self.assertEqual(result["counts"]["invalid_json_records"], 1)
        self.assertEqual(result["counts"]["non_sample_records"], 1)
        self.assertEqual(result["time"]["observed_ms"], 0)
        self.assertEqual(result["time"]["excluded_forward_ms"], 2000)

    def test_occupancy_unknown_is_distinct_from_not_in_bed(self):
        unknown, absent, in_bed, end = [sample(t) for t in (1000, 2000, 3000, 4000)]
        unknown["bed"]["valid"] = False
        absent["bed"]["raw"] = 0
        result = summary(unknown, absent, in_bed, end)
        self.assertEqual(result["time"]["unknown_ms"], 1000)
        self.assertEqual(result["time"]["not_in_bed_ms"], 1000)
        self.assertEqual(result["time"]["in_bed_ms"], 1000)

    def test_conflicting_occupancy_is_unknown(self):
        first = sample(1000)
        first["presence"]["raw"] = 0
        result = summary(first, sample(2000))
        self.assertEqual(result["time"]["unknown_ms"], 1000)

    def test_conflicting_raw_same_timestamp_excluded_from_median(self):
        first, second = sample(1000, rr=16), sample(2000, rr=18)
        second["rr"]["age_ms"] = 1000
        result = summary(first, second)
        self.assertEqual(result["fields"]["rr"]["conflicting_observation_keys"], 1)
        self.assertEqual(result["fields"]["rr"]["valid_raw"]["count"], 0)
        self.assertIsNone(result["fields"]["rr"]["valid_raw"]["median"])
        self.assertEqual(result["issues"][-1]["kind"], "conflicting_observation")

    def test_available_and_valid_distributions_are_separate(self):
        first, second = sample(1000, rr=0), sample(2000, rr=16)
        first["rr"]["valid"] = False
        result = summary(first, second)
        self.assertEqual(result["fields"]["rr"]["available_raw"]["median"], 8)
        self.assertEqual(result["fields"]["rr"]["valid_raw"]["median"], 16)
        self.assertEqual(result["coverage"]["rr"]["valid_ms"], 0)

    def test_invalid_structure_rejected_not_coerced(self):
        mutations = [lambda r: r.update(t_ms=-1),
                     lambda r: r.update(t_ms=(1 << 64)),
                     lambda r: r.update(t_ms=True),
                     lambda r: r["rr"].update(valid="false"),
                     lambda r: r["rr"].update(age_ms=1001),
                     lambda r: r["rr"].update(available=False),
                     lambda r: r["bed"].update(raw=2)]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                record = sample(1000)
                mutate(record)
                result = summary(record)
                self.assertEqual(result["counts"]["invalid_schema_records"], 1)
                self.assertEqual(result["time"]["observed_ms"], 0)

    def test_nonstandard_json_numbers_and_duplicate_keys_rejected(self):
        result = summary('{"schema": 1, "type":"sample", "t_ms":NaN}',
                         '{"schema":1,"schema":2}', '[]')
        self.assertEqual(result["counts"]["invalid_json_records"], 2)
        self.assertEqual(result["counts"]["invalid_schema_records"], 1)

    def test_empty_and_single_record_have_no_time_coverage(self):
        for result in (summary("", " "), summary(sample(1000))):
            self.assertEqual(result["time"]["observed_ms"], 0)
            self.assertIsNone(result["coverage"]["rr"]["fraction_of_observed"])
            self.assertIn("无可计算区间", SUMMARY.markdown_report(result))

    def test_fixture_and_cli_outputs_are_traceable_and_marked_synthetic(self):
        fixture = ROOT / "fixtures" / "demo_synthetic.jsonl"
        result = SUMMARY.summarize_file(fixture)
        self.assertTrue(result["synthetic"])
        self.assertEqual(result["counts"]["valid_sample_records"], 13)
        self.assertEqual(result["counts"]["invalid_json_records"], 1)
        self.assertEqual(result["counts"]["duplicate_timestamp_records"], 1)
        self.assertEqual(result["counts"]["segment_count"], 2)
        self.assertEqual(result["time"]["observed_ms"], 8000)
        self.assertEqual(result["time"]["in_bed_ms"], 6000)
        self.assertEqual(result["time"]["unknown_ms"], 2000)
        self.assertEqual(result["time"]["excluded_forward_ms"], 6000)
        self.assertEqual(result["coverage"]["rr"]["fraction_of_observed"], 0.75)
        self.assertEqual(result["fields"]["rr"]["valid_raw"]["median"], 17)
        self.assertEqual(result["fields"]["hr"]["valid_raw"]["median"], 71)
        with tempfile.TemporaryDirectory() as directory:
            json_path, md_path = Path(directory) / "summary.json", Path(directory) / "summary.md"
            completed = subprocess.run([sys.executable, str(SCRIPT), str(fixture),
                                        "--json", str(json_path), "--markdown", str(md_path)],
                                       check=True, capture_output=True, text=True)
            self.assertIn("已生成", completed.stdout)
            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8")), result)
            self.assertIn("合成模拟非实测", md_path.read_text(encoding="utf-8"))
            self.assertEqual(len(result["source"]["sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
