import hashlib, json, os, shutil, subprocess, tempfile, time, unittest
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
            self.assertEqual(
                {path.name for path in Path(cache).glob(".update.*")},
                {first.name},
                "failed activation left an orphaned cache generation",
            )
            listed = self.run_fw("list", env=env)
            self.assertEqual(listed.returncode, 0, listed.stderr)
            self.assertEqual(listed.stdout, first_list.stdout)

    def test_rename_reports_failure_after_commit_preserves_published_generation(self):
        with tempfile.TemporaryDirectory() as cache, tempfile.TemporaryDirectory() as bindir:
            fake_mv = Path(bindir) / "mv"
            fake_mv.write_text(
                '#!/bin/sh\ncase "$*" in *CURRENT) /usr/bin/mv "$@"; exit 88;; esac\n'
                'exec /usr/bin/mv "$@"\n', encoding="utf-8"
            )
            fake_mv.chmod(0o755)
            env = {"FW_REPO_BASE": FIXTURE.as_uri() + "/", "FW_CACHE_DIR": cache,
                   "PATH": bindir + os.pathsep + os.environ["PATH"]}
            got = self.run_fw("update", env=env)
            self.assertNotEqual(got.returncode, 0)
            self.assertIn("cannot activate cache generation", got.stderr)
            generation = self.active_generation(cache)
            self.assertTrue(generation.is_dir(), "published data must never be removed")
            listed = self.run_fw("list", env=env)
            self.assertEqual(listed.returncode, 0, listed.stderr)
            self.assertIn("fw\t0.1.0", listed.stdout)

    def test_unsafe_current_pointer_never_falls_back_to_legacy_cache(self):
        with tempfile.TemporaryDirectory() as cache:
            env = {"FW_REPO_BASE": FIXTURE.as_uri() + "/", "FW_CACHE_DIR": cache}
            self.assertEqual(self.run_fw("update", env=env).returncode, 0)
            (Path(cache) / "CURRENT").write_text("../escape\n", encoding="utf-8")
            got = self.run_fw("list", env=env)
            self.assertNotEqual(got.returncode, 0)
            self.assertIn("unsafe cache generation", got.stderr)
            opted_in = self.run_fw("list", env={**env, "FW_CACHE_AUTO_REFRESH": "1"})
            self.assertNotEqual(opted_in.returncode, 0)
            self.assertIn("unsafe cache generation", opted_in.stderr)
            self.assertEqual((Path(cache) / "CURRENT").read_text(), "../escape\n")


    def test_tmpfs_reset_can_refetch_only_with_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as cache:
            env = {"FW_REPO_BASE": FIXTURE.as_uri() + "/", "FW_CACHE_DIR": cache}
            first = self.run_fw("list", env=env)
            self.assertNotEqual(first.returncode, 0)
            self.assertFalse((Path(cache) / "CURRENT").exists())
            opt_in = {**env, "FW_CACHE_AUTO_REFRESH": "1"}
            refreshed = self.run_fw("list", env=opt_in)
            self.assertEqual(refreshed.returncode, 0, refreshed.stderr)
            self.assertIn("fw\t0.1.0", refreshed.stdout)
            first_gen = self.active_generation(cache).name
            shutil.rmtree(cache)
            Path(cache).mkdir()
            after_restart = self.run_fw("list", env=opt_in)
            self.assertEqual(after_restart.returncode, 0, after_restart.stderr)
            self.assertIn("fw\t0.1.0", after_restart.stdout)
            self.assertTrue((Path(cache) / "CURRENT").is_file())
            self.assertNotEqual(self.active_generation(cache).name, first_gen)

    def test_tmpfs_retention_bounds_generations_when_flock_available(self):
        with tempfile.TemporaryDirectory() as cache:
            env = {"FW_REPO_BASE": FIXTURE.as_uri() + "/", "FW_CACHE_DIR": cache}
            results = [self.run_fw("update", env=env) for _ in range(3)]
            generations = [p for p in Path(cache).glob(".update.*") if p.is_dir()]
            if os.name == "nt":
                self.assertEqual([r.returncode for r in results[:2]], [0, 0])
                self.assertNotEqual(results[2].returncode, 0)
                self.assertIn("flock unavailable", results[2].stderr)
                self.assertEqual(len(generations), 2)
            else:
                for result in results:
                    self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(len(generations), 1, "gc left unused generations")
            self.assertEqual(self.run_fw("list", env=env).returncode, 0)

    @unittest.skipIf(os.name == "nt", "Windows Git Bash has no flock; fallback tested separately")
    def test_flock_reader_survives_concurrent_update_and_gc(self):
        if not shutil.which("flock"):
            self.skipTest("No POSIX flock on this host")
        with tempfile.TemporaryDirectory() as cache, tempfile.TemporaryDirectory() as bindir:
            env = {"FW_REPO_BASE": FIXTURE.as_uri() + "/", "FW_CACHE_DIR": cache}
            self.assertEqual(self.run_fw("update", env=env).returncode, 0)
            first = self.active_generation(cache)
            ready, release = Path(bindir) / "reader-ready", Path(bindir) / "reader-release"
            fake = Path(bindir) / "awk"
            fake.write_text(
                '#!/bin/sh\necho ready > "$FW_TEST_READER_READY"\n'
                'while [ ! -e "$FW_TEST_READER_RELEASE" ]; do sleep 0.05; done\n'
                'exec /usr/bin/awk "$@"\n', encoding="utf-8"
            )
            fake.chmod(0o755)
            reader_env = {**os.environ, **env, "PATH": bindir + os.pathsep + os.environ["PATH"],
                          "FW_TEST_READER_READY": str(ready),
                          "FW_TEST_READER_RELEASE": str(release)}
            reader = subprocess.Popen([*self.command_for(FW), "list"], cwd=ROOT,
                                      env=reader_env, text=True, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE)
            updater = None
            try:
                deadline = time.monotonic() + 7
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.025)
                self.assertTrue(ready.exists(), "Reader did not reach protected metadata read")
                updater = subprocess.Popen([*self.command_for(FW), "update"], cwd=ROOT,
                                           env={**os.environ, **env}, text=True,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                time.sleep(0.2)
                self.assertIsNone(updater.poll(), "Updater pruned cache before reader released")
                self.assertTrue(first.is_dir())
                release.touch()
                read_out, read_err = reader.communicate(timeout=10)
                update_out, update_err = updater.communicate(timeout=10)
                self.assertEqual(reader.returncode, 0, read_err)
                self.assertEqual(updater.returncode, 0, update_err)
                self.assertIn("fw\t0.1.0", read_out)
                self.assertNotEqual(self.active_generation(cache), first)
                self.assertEqual(len(list(Path(cache).glob(".update.*"))), 1)
            finally:
                release.touch()
                for process in (reader, updater):
                    if process is not None and process.poll() is None:
                        process.kill()
                        process.communicate(timeout=5)



    @unittest.skipIf(os.name == "nt", "Linux subprocess race needs POSIX shim PATH")
    def test_no_flock_simultaneous_writers_cannot_bypass_generation_limit(self):
        with tempfile.TemporaryDirectory() as cache, tempfile.TemporaryDirectory() as bindir:
            shim = Path(bindir)
            for binary in ("dirname", "cat", "awk", "sed", "grep", "sha256sum",
                           "tr", "cp", "mv", "rm", "mkdir", "rmdir", "head", "wc", "uname"):
                source = shutil.which(binary)
                self.assertIsNotNone(source, binary)
                (shim / binary).symlink_to(source)
            entered, released = shim / "stage-entered", shim / "stage-released"
            fake = shim / "mktemp"
            fake.write_text(
                '#!/bin/sh\ncase "$*" in *".update."*)\n'
                ': > "$FW_TEST_STAGE_ENTERED"\n'
                'while [ ! -e "$FW_TEST_STAGE_RELEASED" ]; do /usr/bin/sleep 0.02; done\n'
                ';; esac\nexec /usr/bin/mktemp "$@"\n', encoding="utf-8"
            )
            fake.chmod(0o755)
            env = {**os.environ, "PATH": str(shim),
                   "FW_REPO_BASE": FIXTURE.as_uri() + "/", "FW_CACHE_DIR": cache,
                   "FW_TEST_STAGE_ENTERED": str(entered),
                   "FW_TEST_STAGE_RELEASED": str(released)}
            self.assertIsNone(shutil.which("flock", path=str(shim)))
            procs = []
            try:
                procs.append(subprocess.Popen([*self.command_for(FW), "update"],
                                              cwd=ROOT, env=env, text=True,
                                              stdout=subprocess.PIPE, stderr=subprocess.PIPE))
                deadline = time.monotonic() + 8
                while not entered.exists() and time.monotonic() < deadline:
                    time.sleep(0.025)
                self.assertTrue(entered.exists(), "first updater never staged")
                for _ in range(2):
                    procs.append(subprocess.Popen([*self.command_for(FW), "update"],
                                                  cwd=ROOT, env=env, text=True,
                                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE))
                time.sleep(0.3)
                released.touch()
                results = []
                for proc in procs:
                    stdout, stderr = proc.communicate(timeout=10)
                    results.append((proc.returncode, stdout, stderr))
                successes = [item for item in results if item[0] == 0]
                generations = [p for p in Path(cache).glob(".update.*") if p.is_dir()]
                self.assertEqual(len(successes), 1, results)
                self.assertEqual(len(generations), 1, generations)
                self.assertTrue((Path(cache) / "CURRENT").is_file())
                self.assertTrue(self.active_generation(cache).is_dir())
                self.assertTrue((Path(cache) / ".no-flock-mode").is_dir())
                self.assertFalse((Path(cache) / ".no-flock-writer").exists())
                mixed = self.run_fw("list", env={"FW_CACHE_DIR": cache,
                                                 "FW_REPO_BASE": FIXTURE.as_uri() + "/"})
                self.assertNotEqual(mixed.returncode, 0)
                self.assertIn("cache created without flock", mixed.stderr)
            finally:
                released.touch()
                for proc in procs:
                    if proc.poll() is None:
                        proc.kill()
                    proc.communicate(timeout=5)

    @unittest.skipUnless(os.name == "nt", "No-flock fallback exercised on Git Bash")
    def test_no_flock_reader_refuses_cache_owned_by_flock_mode(self):
        with tempfile.TemporaryDirectory() as cache:
            env = {"FW_REPO_BASE": FIXTURE.as_uri() + "/", "FW_CACHE_DIR": cache}
            self.assertEqual(self.run_fw("update", env=env).returncode, 0)
            (Path(cache) / ".cache.lock").touch()
            blocked = self.run_fw("list", env=env)
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("cache requires flock", blocked.stderr)
            self.assertTrue((Path(cache) / "CURRENT").is_file())


    @unittest.skipUnless(os.name == "nt", "No-flock fallback exercised on Git Bash")
    def test_no_flock_stale_writer_lock_fails_closed(self):
        with tempfile.TemporaryDirectory() as cache:
            (Path(cache) / ".no-flock-writer").mkdir()
            env = {"FW_REPO_BASE": FIXTURE.as_uri() + "/", "FW_CACHE_DIR": cache}
            blocked = self.run_fw("update", env=env)
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("no-flock update already running", blocked.stderr)
            self.assertFalse((Path(cache) / "CURRENT").exists())
            self.assertTrue((Path(cache) / ".no-flock-writer").is_dir())

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