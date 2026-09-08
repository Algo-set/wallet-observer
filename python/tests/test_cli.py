import json
import os
from pathlib import Path

import pytest

from wallet_observer import ObserverError, PortfolioSnapshot
from wallet_observer.cli import main, read_json, write_atomic

FIXTURES = Path(__file__).parent / "fixtures"


def test_offline_cli_stdout_and_atomic_output(tmp_path, capsys):
    args = [
        "analyze",
        str(FIXTURES / "example_snapshot.json"),
        str(FIXTURES / "example_policy.json"),
    ]
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert not report["healthy"]
    assert report["recommendations"][0]["quantity"] == "40.00"
    assert report["recommendations"][0]["executable"] is False
    target = tmp_path / "report.json"
    assert main([*args, str(target)]) == 0
    assert target.is_file()
    if os.name == "posix":
        assert target.stat().st_mode & 0o777 == 0o600


def test_failed_atomic_write_preserves_previous_file_and_cleans_up(tmp_path, monkeypatch):
    target = tmp_path / "report.json"
    target.write_text("previous")
    snapshot = read_json(FIXTURES / "example_snapshot.json", PortfolioSnapshot)

    def fail(*args):
        raise OSError("opaque-path")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(ObserverError, match="output_write_failed"):
        write_atomic(target, snapshot)
    assert target.read_text() == "previous"
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize(
    "body",
    ["not json opaque", '{"schema_version":1,"schema_version":2}', '{"schema_version":true}', "[]"],
)
def test_bad_input_is_sanitized(tmp_path, capsys, body):
    source = tmp_path / "opaque-name.json"
    source.write_text(body)
    assert main(["analyze", str(source), str(FIXTURES / "example_policy.json")]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "invalid_input_file\n"


def test_missing_input_and_unknown_command(tmp_path, capsys):
    assert main(["analyze", str(tmp_path / "opaque"), "other"]) == 2
    assert "opaque" not in capsys.readouterr().err
    with pytest.raises(SystemExit) as status:
        main(["--help"])
    assert status.value.code == 0
