import unittest

from scripts import validate_status


class TestValidateStatus(unittest.TestCase):
    def test_validate_status_passes(self):
        errors = validate_status.validate_status()
        self.assertEqual(errors, [])

    def test_main_exits_zero_on_pass(self):
        # run main
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            try:
                validate_status.main()
            except SystemExit as e:
                self.assertEqual(e.code, 0)
        self.assertIn("STATUS_VALIDATION=PASS", f.getvalue())


if __name__ == "__main__":
    unittest.main()
