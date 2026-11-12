import pytest

from masters_cycling_lab import cli
from tests.conftest import MakeSettings


@pytest.mark.parametrize("revision", ["3294220-dirty", None])
def test_the_test_split_runs_only_from_a_clean_checkout(
    revision: str | None,
    make_settings: MakeSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "get_settings", make_settings)
    monkeypatch.setattr(cli, "code_revision", lambda: revision)
    monkeypatch.setattr(cli, "make_engine", lambda url: pytest.fail("refused before touching the database"))

    assert cli.evaluate("test", ["vector"], 10, check_only=False) == 1
    assert "clean git checkout" in capsys.readouterr().out
