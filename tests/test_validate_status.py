import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import validate_status as v


def test_validate_status_passes():
    assert v.validate_status() == []


def test_validate_status_main_passes(capsys):
    v.main()
    out = capsys.readouterr().out
    assert "STATUS_VALIDATION=PASS" in out
