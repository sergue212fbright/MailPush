"""Reject deceptive-success transcripts before an APK can reach the signer."""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_device_checks import TEST_CLASS, evaluate_instrumentation


def transcript(names=("first", "second")):
    lines = []
    for index, name in enumerate(names, 1):
        for code in (1, 0):
            lines.extend([
                "INSTRUMENTATION_STATUS: class=" + TEST_CLASS,
                "INSTRUMENTATION_STATUS: test=" + name,
                "INSTRUMENTATION_STATUS: numtests=" + str(len(names)),
                "INSTRUMENTATION_STATUS: current=" + str(index),
                "INSTRUMENTATION_STATUS_CODE: " + str(code),
            ])
    lines.extend(["OK (" + str(len(names)) + " tests)", "INSTRUMENTATION_CODE: -1"])
    return "\n".join(lines) + "\n"


class DeviceGateTests(unittest.TestCase):
    def check(self, output=None, expected=None, exit_code=0):
        return evaluate_instrumentation(transcript() if output is None else output,
                                        {"first", "second"} if expected is None else expected,
                                        exit_code)

    def assertRejected(self, output, exit_code=0):
        result = self.check(output, exit_code=exit_code)
        self.assertEqual("failed", result["status"])
        self.assertTrue(result["validation_errors"])

    def test_complete_named_suite_passes(self):
        result = self.check()
        self.assertEqual("passed", result["status"])
        self.assertEqual(2, result["passed"])
        self.assertEqual(0, result["skipped"])

    def test_adb_zero_exit_does_not_hide_process_crash(self):
        self.assertRejected("INSTRUMENTATION_RESULT: shortMsg=Process crashed.\nINSTRUMENTATION_CODE: 0\n")

    def test_assumption_skip_is_rejected_even_with_ok_summary(self):
        output = transcript().replace("INSTRUMENTATION_STATUS_CODE: 0", "INSTRUMENTATION_STATUS_CODE: -4", 1)
        self.assertRejected(output)
        self.assertEqual(1, self.check(output)["skipped"])

    def test_ignored_test_is_rejected(self):
        self.assertRejected(transcript().replace("INSTRUMENTATION_STATUS_CODE: 0", "INSTRUMENTATION_STATUS_CODE: -3", 1))

    def test_failure_and_error_statuses_are_rejected(self):
        for code in (-1, -2, 2):
            with self.subTest(code=code):
                self.assertRejected(transcript().replace("INSTRUMENTATION_STATUS_CODE: 0", "INSTRUMENTATION_STATUS_CODE: " + str(code), 1))

    def test_successful_summary_without_method_results_is_rejected(self):
        self.assertRejected("OK (2 tests)\nINSTRUMENTATION_CODE: -1\n")

    def test_unknown_method_or_class_is_rejected(self):
        self.assertRejected(transcript(("first", "different")))
        self.assertRejected(transcript().replace(TEST_CLASS, "other.Test"))

    def test_duplicate_method_cannot_replace_missing_method(self):
        self.assertRejected(transcript(("first", "first")))

    def test_end_result_without_start_is_rejected(self):
        block = "\n".join(transcript().splitlines()[:5]) + "\n"
        self.assertRejected(transcript().replace(block, "", 1))

    def test_duplicate_result_is_rejected(self):
        block = "\n".join(transcript().splitlines()[5:10]) + "\n"
        self.assertRejected(transcript() + block)

    def test_wrong_suite_count_or_index_is_rejected(self):
        self.assertRejected(transcript().replace("numtests=2", "numtests=3"))
        self.assertRejected(transcript().replace("current=1", "current=0"))

    def test_wrong_or_duplicate_final_result_is_rejected(self):
        self.assertRejected(transcript().replace("INSTRUMENTATION_CODE: -1", "INSTRUMENTATION_CODE: 0"))
        self.assertRejected(transcript() + "INSTRUMENTATION_CODE: -1\n")
        self.assertRejected(transcript().replace("OK (2 tests)", "OK (1 tests)"))

    def test_nonzero_or_timeout_exit_is_rejected(self):
        self.assertRejected(transcript(), exit_code=1)
        self.assertRejected(transcript(), exit_code=None)

    def test_failure_marker_overrides_apparent_success(self):
        for marker in ("FAILURES!!!", "INSTRUMENTATION_FAILED", "INSTRUMENTATION_ABORTED", "Process crashed"):
            with self.subTest(marker=marker):
                self.assertRejected(transcript() + marker + "\n")

    def test_empty_expected_suite_is_rejected(self):
        self.assertEqual("failed", self.check("OK (0 tests)\nINSTRUMENTATION_CODE: -1\n", expected=set())["status"])


if __name__ == "__main__":
    unittest.main()
