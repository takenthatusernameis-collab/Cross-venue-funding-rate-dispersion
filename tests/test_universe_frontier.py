import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from validate_universe_frontier import validate_frontier


class TestUniverseFrontierValidator(unittest.TestCase):
    def test_committed_passes(self):
        self.assertEqual(validate_frontier(), [])


if __name__ == "__main__":
    unittest.main()
