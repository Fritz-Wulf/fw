import hashlib, json, os, shutil, subprocess, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FW = ROOT / "bin" / "fw"
FIXTURE = ROOT / "tests" / "fixtures" / "repo"

class FwTest(unittest.TestCase):
    @staticmethod
    def command_for(script):
        if os.name != "nt":
            return [str(script)]
        git = shutil.which("git")
        if not git:
            raise RuntimeError("Git for Windows is required for POSIX shell tests")
        bash = next((parent / "usr" / "bin" / "bash.exe" for parent in Path(git).resolve().parents
                     if (parent / "usr" / "bin" / "bash.exe").is_file()), None)
        if bash is None:
            raise RuntimeError("Git for Windows bash.exe not found")
        return [str(bash), script.relative_to(ROOT).as_posix()]

    @staticmethod
    def msys_path(value):
        drive, tail = os.path.splitdrive(os.path.abspath(value))
        if not drive:
            return value
        return "/" + drive[0].lower() + tail.replace("\\", "/")

    @staticmethod
    def active_generation(cache):
        current = Path(cache) / "CURRENT"
        return Path(cache) / current.read_text(encoding="utf-8").strip()

    def run_script(self, script, *args, env=None):
        merged = os.environ.copy()
        if env:
            merged.update(env)
        if os.name == "nt":
            if "FW_CACHE_DIR" in merged:
                merged["FW_CACHE_DIR"] = self.msys_path(merged["FW_CACHE_DIR"])
            base = merged.get("FW_REPO_BASE", "")
            if base.startswith("file:///") and len(base) > 10 and base[8].isalpha() and base[9:11] == ":/":
                merged["FW_REPO_BASE"] = "file:///" + base[8].lower() + base[10:]
        return subprocess.run([*self.command_for(script), *args], cwd=ROOT, env=merged, text=True, capture_output=True)

    def run_fw(self, *args, env=None):
        return self.run_script(FW, *args, env=env)

    def test_version_and_aliases_are_identical(self):
        expected = self.run_fw("version")
        self.assertEqual(expected.returncode, 0, expected.stderr)
        self.assertIn("0.4.0", expected.stdout)
        for alias in (ROOT / "bin" / "fwulf", ROOT / "bin" / "fritzwulf"):
            got = self.run_script(alias, "version")
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
            self.assertTrue((self.active_generation(cache) / "index.json").is_file())
            self.assertTrue((self.active_generation(cache) / "Packages").is_file())
            listed = self.run_fw("list", env=env)
            self.assertIn("fw\t0.1.0\tall\tno", listed.stdout)
            self.assertIn("yourfritz-fitdump", listed.stdout)
            found = self.run_fw("search", "yourfritz", env=env)
            self.assertIn("yourfritz-fitdump", found.stdout)
            self.assertNotIn("fw\t0.1.0", found.stdout)
            info = self.run_fw("info", "fw", env=env)
            self.assertIn("Package: fw", info.stdout)
            self.assertIn("X-Fritz-Wulf-Installable: no", info.stdout)
            verified = self.run_fw("verify", "fw", "0.1.0", env=env)
            self.assertEqual(verified.returncode, 0, verified.stderr)
            self.assertIn("verified: fw 0.1.0", verified.stdout)

    def test_update_caches_repository_checksum_manifest(self):
        with tempfile.TemporaryDirectory() as cache:
            env = {"FW_REPO_BASE": FIXTURE.as_uri() + "/", "FW_CACHE_DIR": cache}
            got = self.run_fw("update", env=env)
            self.assertEqual(got.returncode, 0, got.stderr)
            sums = self.active_generation(cache) / "SHA256SUMS"
            self.assertTrue(sums.is_file())
            self.assertIn("index.json", sums.read_text())
            self.assertIn("Packages", sums.read_text())

    def test_update_rejects_manifest_mismatch_without_replacing_cache(self):
        with tempfile.TemporaryDirectory() as cache, tempfile.TemporaryDirectory() as bad_repo:
            env = {"FW_REPO_BASE": FIXTURE.as_uri() + "/", "FW_CACHE_DIR": cache}
            self.assertEqual(self.run_fw("update", env=env).returncode, 0)
            before_generation = self.active_generation(cache)
            before_index = (before_generation / "index.json").read_bytes()
            before_packages = (before_generation / "Packages").read_bytes()
            shutil.copytree(FIXTURE, bad_repo, dirs_exist_ok=True)
            packages = Path(bad_repo) / "Packages"
            packages.write_text(packages.read_text() + "\n# tampered\n", encoding="utf-8")
            bad_env = {"FW_REPO_BASE": Path(bad_repo).as_uri() + "/", "FW_CACHE_DIR": cache}
            got = self.run_fw("update", env=bad_env)
            self.assertNotEqual(got.returncode, 0)
            self.assertIn("repository checksum mismatch", got.stderr)
            self.assertEqual(self.active_generation(cache), before_generation)
            self.assertEqual((before_generation / "index.json").read_bytes(), before_index)
            self.assertEqual((before_generation / "Packages").read_bytes(), before_packages)

    def test_verify_fails_closed_on_checksum_mismatch(self):
        with tempfile.TemporaryDirectory() as cache:
            env = {"FW_REPO_BASE": FIXTURE.as_uri() + "/", "FW_CACHE_DIR": cache}
            self.assertEqual(self.run_fw("update", env=env).returncode, 0)
            bad = self.active_generation(cache) / "Packages"
            bad.write_text(bad.read_text().replace("32dfcc02", "02dfcc02"), encoding="utf-8")
            got = self.run_fw("verify", "fw", "0.1.0", env=env)
            self.assertNotEqual(got.returncode, 0)
            self.assertIn("checksum mismatch", got.stderr)

    def test_doctor_reports_signature_verifier(self):
        with tempfile.TemporaryDirectory() as bindir:
            fake = Path(bindir) / "usign"
            fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake.chmod(0o755)
            got = self.run_fw("doctor", env={"PATH": bindir + os.pathsep + os.environ["PATH"]})
            self.assertEqual(got.returncode, 0, got.stderr)
            self.assertIn("signature verifier: usign", got.stdout)
            self.assertIn("signature enforcement: disabled", got.stdout)

    def test_device_json_has_safe_structured_fields(self):
        got = self.run_fw("--json", "device")
        self.assertEqual(got.returncode, 0, got.stderr)
        data = json.loads(got.stdout)
        self.assertIn("model", data)
        self.assertIn("architecture", data)
        self.assertIn("kernel", data)
        self.assertIn("endianness", data)


    def test_verified_hw185_model_mapping_rejects_unknown_product_ids(self):
        shell = self.command_for(FW)[0] if os.name == "nt" else "/bin/sh"
        env = os.environ.copy()
        env.pop("FW_DEVICE_PROFILE", None)
        for model, expected in (
            ("Fritz_Box_HW185", "7490"),
            ("Fritz_Box_HW185X", "unknown"),
            ("Fritz_Box_HW999", "unknown"),
            ("FRITZ Box 7530", "7530"),
        ):
            with self.subTest(model=model):
                snippet = (
                    "set -- help; . ./bin/fw >/dev/null; "
                    f"detect_model() {{ printf '%s' '{model}'; }}; "
                    "detect_profile"
                )
                got = subprocess.run([shell, "-c", snippet], cwd=ROOT, env=env,
                                     text=True, capture_output=True)
                self.assertEqual(got.returncode, 0, got.stderr)
                self.assertEqual(got.stdout, expected)

    def test_update_activates_validated_generation_and_fails_closed_on_tamper(self):
        with tempfile.TemporaryDirectory() as cache:
            env = {"FW_REPO_BASE": FIXTURE.as_uri() + "/", "FW_CACHE_DIR": cache}
            updated = self.run_fw("update", env=env)
            self.assertEqual(updated.returncode, 0, updated.stderr)
            current = Path(cache) / "CURRENT"
            self.assertTrue(current.is_file(), "No single atomic cache generation pointer")
            name = current.read_text(encoding="utf-8").strip()
            self.assertTrue(name.startswith(".update."), name)
            generation = Path(cache) / name
            for filename in ("index.json", "Packages", "SHA256SUMS"):
                self.assertTrue((generation / filename).is_file(), filename)
            packages = generation / "Packages"
            before = packages.read_bytes()
            packages.write_bytes(before + b"\n# tampered\n")
            rejected = self.run_fw("list", env=env)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("repository checksum mismatch", rejected.stderr)
            self.assertEqual(current.read_text(encoding="utf-8").strip(), name)

    def test_failed_pointer_commit_keeps_prior_generation_and_package_list(self):
        with tempfile.TemporaryDirectory() as cache, tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as bindir:
            env = {"FW_REPO_BASE": FIXTURE.as_uri() + "/", "FW_CACHE_DIR": cache}
            initial = self.run_fw("update", env=env)
            self.assertEqual(initial.returncode, 0, initial.stderr)
            first = self.active_generation(cache)
            first_list = self.run_fw("list", env=env)
            self.assertEqual(first_list.returncode, 0, first_list.stderr)
            shutil.copytree(FIXTURE, repo, dirs_exist_ok=True)
            packages = Path(repo) / "Packages"
            index = Path(repo) / "index.json"
            packages.write_text(packages.read_text().replace("Version: 0.1.0", "Version: 0.1.9", 1), encoding="utf-8")
            index.write_text(index.read_text().replace("0.1.0", "0.1.9", 1), encoding="utf-8")
            (Path(repo) / "SHA256SUMS").write_text(
                f"{hashlib.sha256(index.read_bytes()).hexdigest()}  index.json\n"
                f"{hashlib.sha256(packages.read_bytes()).hexdigest()}  Packages\n", encoding="utf-8")
            fake_mv = Path(bindir) / "mv"
            fake_mv.write_text('#!/bin/sh\ncase "$*" in *CURRENT) exit 88;; esac\nexec /usr/bin/mv "$@"\n', encoding="utf-8")
            fake_mv.chmod(0o755)
            blocked_env = {"FW_REPO_BASE": Path(repo).as_uri() + "/", "FW_CACHE_DIR": cache,
                           "PATH": bindir + os.pathsep + os.environ["PATH"]}
            failed = self.run_fw("update", env=blocked_env)
            self.assertNotEqual(failed.returncode, 0, failed.stdout)
            self.assertIn("cannot activate cache generation", failed.stderr)
            self.assertEqual(self.active_generation(cache), first)
            listed = self.run_fw("list", env=env)
            self.assertEqual(listed.returncode, 0, listed.stderr)
            self.assertEqual(listed.stdout, first_list.stdout)

    def test_unsafe_current_pointer_never_falls_back_to_legacy_cache(self):
        with tempfile.TemporaryDirectory() as cache:
            env = {"FW_REPO_BASE": FIXTURE.as_uri() + "/", "FW_CACHE_DIR": cache}
            self.assertEqual(self.run_fw("update", env=env).returncode, 0)
            (Path(cache) / "CURRENT").write_text("../escape\n", encoding="utf-8")
            got = self.run_fw("list", env=env)
            self.assertNotEqual(got.returncode, 0)
            self.assertIn("unsafe cache generation", got.stderr)

    def test_compatible_checks_structured_device_targets(self):
        with tempfile.TemporaryDirectory() as cache:
            env = {"FW_REPO_BASE": FIXTURE.as_uri() + "/", "FW_CACHE_DIR": cache, "FW_DEVICE_PROFILE": "7490"}
            self.assertEqual(self.run_fw("update", env=env).returncode, 0)
            good = self.run_fw("compatible", "fw", "0.1.0", env=env)
            self.assertEqual(good.returncode, 0, good.stderr)
            self.assertIn("compatible: fw 0.1.0 on 7490", good.stdout)
            machine = self.run_fw("--json", "compatible", "fw", "0.1.0", env=env)
            self.assertEqual(machine.returncode, 0, machine.stderr)
            data = json.loads(machine.stdout)
            self.assertEqual(data["device"], "7490")
            self.assertTrue(data["compatible"])
            self.assertEqual(data["installable"], "no")
            source = self.run_fw("compatible", "yourfritz-fitdump", "git-20220623-a", env=env)
            self.assertNotEqual(source.returncode, 0)
            self.assertIn("no verified device targets", source.stderr)

    def test_compatible_fails_closed_for_unknown_device(self):
        with tempfile.TemporaryDirectory() as cache:
            env = {"FW_REPO_BASE": FIXTURE.as_uri() + "/", "FW_CACHE_DIR": cache, "FW_DEVICE_PROFILE": "unknown"}
            self.assertEqual(self.run_fw("update", env=env).returncode, 0)
            got = self.run_fw("compatible", "fw", "0.1.0", env=env)
            self.assertNotEqual(got.returncode, 0)
            self.assertIn("device profile unknown", got.stderr)


    def test_compatible_rejects_missing_device_contract(self):
        with tempfile.TemporaryDirectory() as cache, tempfile.TemporaryDirectory() as repo:
            shutil.copytree(FIXTURE, repo, dirs_exist_ok=True)
            packages = Path(repo) / "Packages"
            packages.write_text(packages.read_text().replace("X-Fritz-Wulf-Devices: 3270,7490,7530,7590\n", "", 1))
            index = Path(repo) / "index.json"
            sums = Path(repo) / "SHA256SUMS"
            sums.write_text(f"{hashlib.sha256(index.read_bytes()).hexdigest()}  index.json\n{hashlib.sha256(packages.read_bytes()).hexdigest()}  Packages\n")
            env = {"FW_REPO_BASE": Path(repo).as_uri() + "/", "FW_CACHE_DIR": cache, "FW_DEVICE_PROFILE": "7490"}
            self.assertEqual(self.run_fw("update", env=env).returncode, 0)
            got = self.run_fw("compatible", "fw", "0.1.0", env=env)
            self.assertNotEqual(got.returncode, 0)
            self.assertIn("device targets missing", got.stderr)

    def test_compatible_rejects_unverified_architecture(self):
        with tempfile.TemporaryDirectory() as cache, tempfile.TemporaryDirectory() as repo:
            shutil.copytree(FIXTURE, repo, dirs_exist_ok=True)
            packages = Path(repo) / "Packages"
            packages.write_text(packages.read_text().replace("Architecture: all", "Architecture: mips32", 1))
            index = Path(repo) / "index.json"
            sums = Path(repo) / "SHA256SUMS"
            sums.write_text(f"{hashlib.sha256(index.read_bytes()).hexdigest()}  index.json\n{hashlib.sha256(packages.read_bytes()).hexdigest()}  Packages\n")
            env = {"FW_REPO_BASE": Path(repo).as_uri() + "/", "FW_CACHE_DIR": cache, "FW_DEVICE_PROFILE": "7490"}
            self.assertEqual(self.run_fw("update", env=env).returncode, 0)
            got = self.run_fw("compatible", "fw", "0.1.0", env=env)
            self.assertNotEqual(got.returncode, 0)
            self.assertIn("architecture compatibility not verified", got.stderr)

if __name__ == "__main__":
    unittest.main()