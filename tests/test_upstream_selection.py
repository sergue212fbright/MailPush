"""Source selection must validate pinned PRs offline and preserve release gates."""

import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import upstream_check


class SourceSelectionTests(unittest.TestCase):
    def run_selection(self, *, pinned, repository="owner/MailPush", responses=None):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            policy = {"repository": upstream_check.OFFICIAL, "track": "main",
                      "commit": "a" * 40, "base_version_code": 1_000_000}
            (root / "upstream.json").write_text(json.dumps(policy))
            output, actions_output = root / "selection.json", root / "actions-output"
            argv = ["upstream_check.py", "--output", str(output)] + (["--pinned"] if pinned else [])
            with patch.object(upstream_check, "ROOT", root), \
                    patch.object(upstream_check, "module_digest", return_value="b" * 64), \
                    patch.object(upstream_check, "api", side_effect=responses or AssertionError("Unexpected network access")) as api, \
                    patch.object(sys, "argv", argv), \
                    patch.dict(os.environ, {"GITHUB_REPOSITORY": repository, "GITHUB_RUN_NUMBER": "7",
                                           "GITHUB_OUTPUT": str(actions_output)}, clear=True), \
                    contextlib.redirect_stdout(io.StringIO()):
                upstream_check.main()
                return json.loads(output.read_text()), actions_output.read_text(), api.call_args_list

    def test_pinned_pr_never_uses_network_or_skips_build_validation(self):
        selection, outputs, calls = self.run_selection(pinned=True)
        self.assertEqual([], calls)
        self.assertEqual("a" * 40, selection["upstream_commit"])
        self.assertEqual(1_000_007, selection["version_code"])
        self.assertIs(True, selection["needed"])
        self.assertIn("needed=true\n", outputs)

    def test_release_poll_still_uses_upstream_and_existing_release(self):
        selection, _, calls = self.run_selection(pinned=False,
                                                responses=[{"sha": "c" * 40}, {"draft": False}])
        self.assertEqual("c" * 40, selection["upstream_commit"])
        self.assertIs(False, selection["needed"])
        self.assertEqual(2, len(calls))
        self.assertEqual("/repos/ProtonMail/android-mail/commits/main", calls[0].args[0])
        self.assertIn("/repos/owner/MailPush/releases/tags/mailpush-", calls[1].args[0])

    def test_missing_release_preserves_required_build(self):
        missing = urllib.error.HTTPError("https://api.github.com/synthetic", 404, "not found", {}, None)
        selection, _, _ = self.run_selection(pinned=False, responses=[{"sha": "c" * 40}, missing])
        self.assertIs(True, selection["needed"])

    def test_invalid_repository_is_rejected_even_offline(self):
        with self.assertRaisesRegex(ValueError, "Invalid repository"):
            self.run_selection(pinned=True, repository="owner/MailPush/../../another")

    def test_release_poll_does_not_hide_authorization_or_service_errors(self):
        for code in (403, 429, 503):
            error = urllib.error.HTTPError("https://api.github.com/synthetic", code, "failed", {}, None)
            with self.subTest(code=code), self.assertRaises(urllib.error.HTTPError):
                self.run_selection(pinned=False, responses=[{"sha": "c" * 40}, error])


if __name__ == "__main__":
    unittest.main()
