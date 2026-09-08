import json, os, subprocess, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FW = ROOT / "bin" / "fw"
FIXTURE = ROOT / "tests" / "fixtures" / "repo"

class FwTest(unittest.TestCase):
    def run_fw(self, *args, env=None):
        merged = os.environ.copy()
        if env:
            merged.update(env)
        return subprocess.run([str(FW), *args], cwd=ROOT, env=merged, text=True, capture_output=True)

    def test_version_and_aliases_are_identical(self):
        expected = self.run_fw("version")
        self.assertEqual(expected.returncode, 0, expected.stderr)
        self.assertIn("0.1.0", expected.stdout)
        for alias in (ROOT / "bin" / "fwulf", ROOT / "bin" / "fritzwulf"):
            got = subprocess.run([str(alias), "version"], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(got.stdout, expected.stdout)
            self.assertEqual(got.returncode, 0)

    def test_repo_json_reports_canonical_index(self):
        got = self.run_fw("--json", "repo")
        self.assertEqual(got.returncode, 0, got.stderr)
        data = json.loads(got.stdout)
        self.assertEqual(data["index"], "https://fritz-wulf.github.io/repo/index.json")
    def test_update_list_search_and_info_use_generated_feed(self):
        with tempfile.TemporaryDirectory() as cache:
            env = {"FW_REPO_BASE": FIXTURE.as_uri() + "/", "FW_CACHE_DIR": cache}
            updated = self.run_fw("update", env=env)
            self.assertEqual(updated.returncode, 0, updated.stderr)
            self.assertTrue((Path(cache) / "index.json").is_file())
            self.assertTrue((Path(cache) / "Packages").is_file())
            listed = self.run_fw("list", env=env)
            self.assertIn("fw\t0.1.0", listed.stdout)
            self.assertIn("yourfritz-fitdump", listed.stdout)
            found = self.run_fw("search", "yourfritz", env=env)
            self.assertIn("yourfritz-fitdump", found.stdout)
            self.assertNotIn("fw\t0.1.0", found.stdout)
            info = self.run_fw("info", "fw", env=env)
            self.assertIn("Package: fw", info.stdout)
            self.assertIn("Installable: yes", info.stdout)

    def test_device_json_has_safe_structured_fields(self):
        got = self.run_fw("--json", "device")
        self.assertEqual(got.returncode, 0, got.stderr)
        data = json.loads(got.stdout)
        self.assertIn("model", data)
        self.assertIn("architecture", data)
        self.assertIn("kernel", data)
        self.assertIn("endianness", data)

if __name__ == "__main__":
    unittest.main()