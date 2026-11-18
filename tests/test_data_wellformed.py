import csv, json, unittest, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
class SampleData(unittest.TestCase):
    def test_camera_log_has_marker_and_header(self):
        with open(os.path.join(ROOT, "records/camera_log.csv"), encoding="utf-8-sig") as handle:
            raw = handle.read().splitlines()
        self.assertTrue(raw[0].startswith("#PLEARUN"))
        self.assertEqual(raw[1], "timestamp,device,speed_mph,zone_mph")
    def test_dispatch_json_parses(self):
        with open(os.path.join(ROOT, "records/dispatch.json")) as handle:
            json.load(handle)
    def test_notes_decode_as_cp1252(self):
        with open(os.path.join(ROOT, "records/notes_cp1252.csv"), "rb") as handle:
            handle.read().decode("cp1252")
    def test_transcript_is_webvtt(self):
        with open(os.path.join(ROOT, "records/bodycam_transcript.vtt"), encoding="utf-8-sig") as handle:
            self.assertTrue(handle.read().startswith("WEBVTT"))
if __name__ == "__main__":
    unittest.main()
