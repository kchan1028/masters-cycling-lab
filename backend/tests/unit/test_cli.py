import sys
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy.exc import OperationalError

from masters_cycling_lab import cli
from tests.conftest import MakeSettings


@pytest.mark.parametrize("split", ["test", "test2"])
@pytest.mark.parametrize("revision", ["3294220-dirty", None])
def test_held_out_splits_run_only_from_a_clean_checkout(
    split: str,
    revision: str | None,
    make_settings: MakeSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "get_settings", make_settings)
    monkeypatch.setattr(cli, "code_revision", lambda: revision)
    monkeypatch.setattr(cli, "make_engine", lambda url: pytest.fail("refused before touching the database"))

    assert cli.evaluate(split, ["vector"], 10, check_only=False) == 1
    assert "clean git checkout" in capsys.readouterr().out


class StallingEngine:
    """Times out on the first `failures` connections, like Docker Desktop on a bad day."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.attempts = 0

    @contextmanager
    def connect(self) -> Iterator[None]:
        self.attempts += 1
        if self.attempts <= self.failures:
            raise OperationalError("connect", {}, TimeoutError("connection timeout expired"))
        yield


def test_a_stalled_connection_is_retried(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    engine = StallingEngine(failures=2)
    monkeypatch.setattr(cli, "make_engine", lambda url: engine)

    assert cli.connected_engine("postgresql+psycopg://unused") is not None
    assert engine.attempts == 3
    assert "attempt 2 of 3" in capsys.readouterr().out


def test_an_unreachable_database_gets_a_message_not_a_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "make_engine", lambda url: StallingEngine(failures=99))

    assert cli.connected_engine("postgresql+psycopg://unused") is None
    output = capsys.readouterr().out
    assert "connection timeout expired" in output
    assert "make up" in output


def test_ctrl_c_stops_a_review_cleanly(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def interrupted(*args: object) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "review", interrupted)

    assert cli.main(["review", "--reviewer", "KC"]) == 0
    assert "Every verdict recorded so far is saved" in capsys.readouterr().out


def test_review_refuses_without_a_terminal(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    # Without a terminal every prompt would read an empty line, and questions would go by unrecorded.
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(cli, "connected_engine", lambda url: pytest.fail("refused before touching the database"))

    # A named question is always reviewable, so this does not depend on any label still being provisional.
    assert cli.review("KC", None, "q001") == 1
    assert "interactive terminal" in capsys.readouterr().out
