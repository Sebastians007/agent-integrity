import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / ".claude" / "integrity" / "hooks" / "integrity.py"
spec = importlib.util.spec_from_file_location("integrity_runtime", MODULE_PATH)
ir = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ir)


class IntegrityRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.root, check=True)
        (self.root / "seed.txt").write_text("seed\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "seed"], cwd=self.root, check=True)
        self.old_root = ir.ROOT
        self.old_base = ir.BASE
        self.old_config = ir.CONFIG_PATH
        self.old_state_dir = ir.STATE_DIR
        self.old_state = ir.STATE_PATH
        self.old_evidence = ir.EVIDENCE_PATH
        self.old_handoff = ir.HANDOFF_PATH
        ir.ROOT = self.root
        ir.BASE = self.root / ".claude" / "integrity"
        ir.CONFIG_PATH = ir.BASE / "config.json"
        ir.STATE_DIR = self.root / ".ai-integrity"
        ir.STATE_PATH = ir.STATE_DIR / "state.json"
        ir.EVIDENCE_PATH = ir.STATE_DIR / "evidence.jsonl"
        ir.HANDOFF_PATH = ir.STATE_DIR / "HANDOFF.md"
        ir.BASE.mkdir(parents=True)
        ir.CONFIG_PATH.write_text(json.dumps({"ignore_changed_paths": [".ai-integrity/"]}), encoding="utf-8")

    def tearDown(self):
        ir.ROOT = self.old_root
        ir.BASE = self.old_base
        ir.CONFIG_PATH = self.old_config
        ir.STATE_DIR = self.old_state_dir
        ir.STATE_PATH = self.old_state
        ir.EVIDENCE_PATH = self.old_evidence
        ir.HANDOFF_PATH = self.old_handoff
        self.tmp.cleanup()

    def test_untracked_files_inside_new_directory_are_enumerated(self):
        p = self.root / "newpkg" / "nested" / "feature.py"
        p.parent.mkdir(parents=True)
        p.write_text("print('x')\n", encoding="utf-8")
        changed = ir.changed_files()
        self.assertIn("newpkg/nested/feature.py", changed)
        self.assertTrue(ir.is_code_change(changed))

    def test_preexisting_failure_classification(self):
        before = {"command": "test", "ok": False, "returncode": 1, "output": "FAILED test_a", "fingerprint": "abc"}
        st = ir.default_state()
        st["session_baseline"] = {"verification_results": [before]}
        current = [{"command": "test", "ok": False, "returncode": 1, "output": "FAILED test_a", "fingerprint": "abc"}]
        got = ir.classify_results(current, st)
        self.assertEqual("preexisting_failure", got[0]["classification"])

    def test_changed_failure_classification(self):
        before = {"command": "test", "ok": False, "returncode": 1, "output": "FAILED test_a", "fingerprint": "abc"}
        st = ir.default_state()
        st["session_baseline"] = {"verification_results": [before]}
        current = [{"command": "test", "ok": False, "returncode": 1, "output": "FAILED test_b", "fingerprint": "def"}]
        got = ir.classify_results(current, st)
        self.assertEqual("changed_failure", got[0]["classification"])

    def test_introduced_failure_classification(self):
        before = {"command": "test", "ok": True, "returncode": 0, "output": "", "fingerprint": "green"}
        st = ir.default_state()
        st["session_baseline"] = {"verification_results": [before]}
        current = [{"command": "test", "ok": False, "returncode": 1, "output": "FAILED", "fingerprint": "def"}]
        got = ir.classify_results(current, st)
        self.assertEqual("introduced_failure", got[0]["classification"])

    def test_claim_invalidation_is_transitive(self):
        ledger_path = Path(__file__).resolve().parents[1] / ".claude" / "integrity" / "ledger.py"
        spec2 = importlib.util.spec_from_file_location("integrity_ledger", ledger_path)
        ledger = importlib.util.module_from_spec(spec2)
        spec2.loader.exec_module(ledger)
        data = {"schema": 1, "claims": [
            {"id": "a", "depends_on": []},
            {"id": "b", "depends_on": ["a"]},
            {"id": "c", "depends_on": ["b"]},
        ]}
        self.assertEqual({"b", "c"}, ledger.descendants(data, "a"))


if __name__ == "__main__":
    unittest.main()
