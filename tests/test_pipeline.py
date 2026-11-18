import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from plearun.loader import load_dir, read_text
from plearun.pipeline import analyze

REPORT = os.path.join(ROOT, "reports", "report_fictional_02.txt")
RECORDS = os.path.join(ROOT, "records")
ALLOWED = {"match", "conflict", "not_settled", "not_checkable"}


def _find(findings, needle):
    matches = [item for item in findings if needle.lower() in item["claim"].lower()]
    return matches


class SamplePipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result, cls.clock = analyze(REPORT, RECORDS)
        cls.findings = cls.result["findings"]

    def test_output_shape(self):
        self.assertIsInstance(self.findings, list)
        self.assertGreaterEqual(len(self.findings), 6)
        for finding in self.findings:
            self.assertIn(finding["finding"], ALLOWED)
            self.assertIsInstance(finding["claim"], str)
            if finding["finding"] in ("match", "conflict"):
                self.assertIn("cite", finding)
                self.assertIn("quote", finding)
                self.assertEqual(set(finding["cite"]), {"file", "row"})
            else:
                self.assertNotIn("cite", finding)
                self.assertNotIn("quote", finding)

    def test_expected_statuses(self):
        self.assertEqual(_find(self.findings, "first observed")[0]["finding"], "match")
        self.assertEqual(_find(self.findings, "58 mph")[0]["finding"], "match")
        self.assertEqual(_find(self.findings, "stopped around")[0]["finding"], "match")
        self.assertEqual(_find(self.findings, "911 call")[0]["finding"], "match")
        self.assertEqual(_find(self.findings, "2 minutes after")[0]["finding"], "match")
        self.assertEqual(_find(self.findings, "only car")[0]["finding"], "not_checkable")
        locations = [item for item in self.findings if item["claim"] == "near mile marker 4"]
        self.assertEqual(locations[0]["finding"], "not_checkable")

    def test_no_conflicts_on_sample(self):
        self.assertFalse([item for item in self.findings if item["finding"] == "conflict"])

    def test_every_quote_is_in_the_cited_raw_row(self):
        events = load_dir(RECORDS)
        by_row = {(event.file, event.row): event for event in events}
        for finding in self.findings:
            if finding["finding"] not in ("match", "conflict"):
                continue
            key = (finding["cite"]["file"], finding["cite"]["row"])
            self.assertIn(key, by_row)
            self.assertIn(finding["quote"], by_row[key].raw)

    def test_every_quote_is_in_the_original_file(self):
        for finding in self.findings:
            if finding["finding"] not in ("match", "conflict"):
                continue
            text = read_text(os.path.join(RECORDS, finding["cite"]["file"]))
            self.assertIn(finding["quote"], text)

    def test_clock_model_finds_the_offsets(self):
        self.assertEqual(self.clock.stop_source, "notes")
        self.assertAlmostEqual(self.clock.note_skew, 41, delta=1)
        self.assertAlmostEqual(self.clock.skews["CAM-03"], -1, delta=2)
        self.assertAlmostEqual(self.clock.skews["CAM-07"], 89, delta=2)
        self.assertIsNone(self.clock.transcript_start)

    def test_llm_path_cannot_add_findings(self):
        result, _ = analyze(REPORT, RECORDS, use_llm=True)
        self.assertEqual(result, self.result)


if __name__ == "__main__":
    unittest.main()
