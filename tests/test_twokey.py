"""Run in Linux: python3 -m unittest discover tests"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).parents[1] / "twokey" / "twokey.py"
PATCH = """--- a/pricing.json
+++ b/pricing.json
@@ -1,1 +1,1 @@
-broken
+fixed
"""


class Gate(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        (self.root / "service").mkdir()
        self.target = self.root / "service" / "pricing.json"
        self.target.write_text("broken\n")
        self.patch = self.root / "fix.patch"
        self.patch.write_text(PATCH)
        self.env = {
            **os.environ,
            "TWOKEY_HOME": str(self.root / "state"),
            "TWOKEY_TARGET": str(self.root / "service"),
        }
        self.run_tool("init")
        self.run_tool("propose", str(self.patch), "-s", "fix")

    def run_tool(self, *args: str, ok: bool = True) -> str:
        done = subprocess.run(
            [sys.executable, str(TOOL), *args],
            env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(done.returncode == 0, ok, done.stdout + done.stderr)
        return done.stdout + done.stderr

    def test_shipping_opens_a_change_with_the_vendors_key_turned(self) -> None:
        self.run_tool("turn", "vendor")
        self.run_tool("turn", "customer")
        self.target.write_text("broken\n")
        done = subprocess.run(
            [sys.executable, str(TOOL), "ship", "-s", "again"],
            input=PATCH, env=self.env, capture_output=True, text=True,
        )
        self.assertIn("CHG-002", done.stdout)
        self.assertEqual(self.target.read_text(), "broken\n")
        self.assertIn("applied", self.run_tool("turn", "customer"))
        self.assertEqual(self.target.read_text(), "fixed\n")

    def test_one_key_changes_nothing(self) -> None:
        self.run_tool("turn", "vendor")
        self.assertEqual(self.target.read_text(), "broken\n")

    def test_two_keys_apply_the_change(self) -> None:
        self.run_tool("turn", "vendor")
        self.assertIn("applied", self.run_tool("turn", "customer"))
        self.assertEqual(self.target.read_text(), "fixed\n")

    def test_the_order_of_the_keys_does_not_matter(self) -> None:
        self.run_tool("turn", "customer")
        self.run_tool("turn", "vendor")
        self.assertEqual(self.target.read_text(), "fixed\n")

    def test_the_same_key_cannot_count_twice(self) -> None:
        self.run_tool("turn", "vendor")
        self.assertIn("already turned", self.run_tool("turn", "vendor", ok=False))
        self.assertEqual(self.target.read_text(), "broken\n")

    def test_a_patch_edited_after_a_key_is_refused(self) -> None:
        self.run_tool("turn", "vendor")
        stored = self.root / "state" / "patches" / "CHG-001.patch"
        stored.write_text(PATCH.replace("fixed", "evil"))
        self.assertIn("not the one proposed", self.run_tool("turn", "customer", ok=False))
        self.assertEqual(self.target.read_text(), "broken\n")

    def test_one_partys_signature_cannot_stand_in_for_the_other(self) -> None:
        self.run_tool("turn", "customer")
        path = self.root / "state" / "change.json"
        change = json.loads(path.read_text())
        change["signatures"]["vendor"] = change["signatures"]["customer"]
        path.write_text(json.dumps(change))
        self.assertIn("already turned", self.run_tool("turn", "vendor", ok=False))
        check = (
            "import json, sys; sys.path.insert(0, sys.argv[1]); import twokey; "
            "change = json.load(open(sys.argv[2])); "
            "print(twokey.verifies('vendor', change, change['signatures']['vendor']))"
        )
        forged = subprocess.run(
            [sys.executable, "-c", check, str(TOOL.parent), str(path)],
            env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(forged.stdout.strip(), "False", forged.stderr)

    def test_editing_the_ledger_is_detected(self) -> None:
        self.run_tool("turn", "vendor")
        ledger = self.root / "state" / "ledger.jsonl"
        ledger.write_text(ledger.read_text().replace('"vendor"', '"customer"'))
        self.assertIn("Ledger broken", self.run_tool("audit", ok=False))


if __name__ == "__main__":
    unittest.main()
