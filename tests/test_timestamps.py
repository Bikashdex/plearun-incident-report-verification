import os
import sys
import unittest
from datetime import timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from plearun.timestamps import (
    infer_default_offset,
    median_sod,
    parse_clock_text,
    parse_timestamp,
    sod_absdiff,
)

EASTERN = timezone(timedelta(hours=-5))


class TimestampParsing(unittest.TestCase):
    def test_epoch_milliseconds_string(self):
        parsed = parse_timestamp("1772502579000", EASTERN)
        self.assertTrue(parsed.ok)
        self.assertAlmostEqual(parsed.sod, 20 * 3600 + 49 * 60 + 39, delta=0.001)

    def test_epoch_milliseconds_integer(self):
        parsed = parse_timestamp(1772502579000, EASTERN)
        self.assertTrue(parsed.ok)
        self.assertAlmostEqual(parsed.sod, 20 * 3600 + 49 * 60 + 39, delta=0.001)

    def test_iso_with_offset(self):
        parsed = parse_timestamp("2026-03-02T20:51:06-05:00", EASTERN)
        self.assertTrue(parsed.ok)
        self.assertAlmostEqual(parsed.sod, 20 * 3600 + 51 * 60 + 6, delta=0.001)

    def test_naive_iso_is_wall_clock(self):
        parsed = parse_timestamp("2026-03-02 21:10:19", EASTERN)
        self.assertTrue(parsed.ok)
        self.assertAlmostEqual(parsed.sod, 21 * 3600 + 10 * 60 + 19, delta=0.001)

    def test_time_of_day_with_dotted_meridiem(self):
        parsed = parse_timestamp("9:14 p.m.", EASTERN)
        self.assertTrue(parsed.ok)
        self.assertAlmostEqual(parsed.sod, 21 * 3600 + 14 * 60, delta=0.001)

    def test_infer_dominant_offset(self):
        offset = infer_default_offset(
            [
                "2026-03-02T20:51:06-05:00",
                "2026-03-02T20:55:54-05:00",
                "2026-03-02T21:17:19+00:00",
            ]
        )
        self.assertEqual(offset.utcoffset(None), timedelta(hours=-5))

    def test_clock_in_free_text(self):
        self.assertEqual(parse_clock_text("Pulling in, about 21:16."), 21 * 3600 + 16 * 60)

    def test_circular_distance(self):
        self.assertAlmostEqual(sod_absdiff(60, 86400 + 60), 0.0)
        self.assertAlmostEqual(sod_absdiff(86399, 1), 2.0)

    def test_median_handles_midnight(self):
        value = median_sod([86390, 10, 5])
        self.assertLess(sod_absdiff(value, 5), 10)


if __name__ == "__main__":
    unittest.main()
