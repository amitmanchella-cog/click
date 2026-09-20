import io
import sys
from unittest.mock import Mock

import pytest

import click


@pytest.fixture
def interrupt_stderr(monkeypatch):
    def install(method, interrupt_at=1):
        stream = io.StringIO()
        original = getattr(stream, method)
        calls = 0

        def interrupt(*args):
            nonlocal calls
            calls += 1
            if calls >= interrupt_at:
                raise KeyboardInterrupt
            return original(*args)

        mock = Mock(side_effect=interrupt)
        monkeypatch.setattr(stream, method, mock)
        monkeypatch.setattr(sys, "stderr", stream)
        return mock

    return install


@pytest.mark.parametrize("method", ["isatty", "write", "flush"])
def test_prompt_abort_late_interrupt(monkeypatch, interrupt_stderr, method):
    @click.command()
    @click.option("--name", prompt="Name")
    def cli(name):
        pytest.fail("The interrupted prompt must not invoke the command.")

    monkeypatch.setattr(
        "click.termui.visible_prompt_func", Mock(side_effect=KeyboardInterrupt)
    )
    interrupted = interrupt_stderr(method)

    with pytest.raises((SystemExit, KeyboardInterrupt)) as exc_info:
        cli.main([], prog_name="cli")

    assert isinstance(exc_info.value, SystemExit)
    assert exc_info.value.code == 1
    interrupted.assert_called()


@pytest.mark.parametrize("first", [KeyboardInterrupt, EOFError])
@pytest.mark.parametrize("method", ["isatty", "write", "flush"])
@pytest.mark.parametrize(
    ("standalone_mode", "interrupt_at"), [(True, 1), (True, 2), (False, 1)]
)
def test_body_abort_late_interrupt(
    interrupt_stderr, first, method, interrupt_at, standalone_mode
):
    @click.command()
    def cli():
        raise first

    interrupted = interrupt_stderr(method, interrupt_at)

    with pytest.raises((SystemExit, KeyboardInterrupt)) as exc_info:
        cli.main([], prog_name="cli", standalone_mode=standalone_mode)

    if standalone_mode:
        assert isinstance(exc_info.value, SystemExit)
        assert exc_info.value.code == 1
    else:
        assert isinstance(exc_info.value, KeyboardInterrupt)

    assert interrupted.call_count == interrupt_at


class CustomError(click.ClickException):
    exit_code = 42


@pytest.mark.parametrize("error", [click.ClickException, click.UsageError, CustomError])
@pytest.mark.parametrize("method", ["isatty", "write", "flush"])
def test_error_late_interrupt(interrupt_stderr, error, method):
    @click.command()
    def cli():
        raise error("failure")

    interrupted = interrupt_stderr(method)

    with pytest.raises((SystemExit, KeyboardInterrupt)) as exc_info:
        cli.main([], prog_name="cli")

    assert isinstance(exc_info.value, SystemExit)
    assert exc_info.value.code == error.exit_code
    interrupted.assert_called()


@pytest.mark.parametrize(
    ("outcome", "exit_code"),
    [
        (None, 0),
        (click.Abort(), 1),
        (CustomError("failure"), 42),
        (click.exceptions.Exit(7), 7),
    ],
)
def test_interrupt_during_exit(monkeypatch, outcome, exit_code):
    @click.command()
    def cli():
        if outcome is not None:
            raise outcome

    interrupted = Mock(side_effect=KeyboardInterrupt)
    monkeypatch.setattr(sys, "exit", interrupted)

    with pytest.raises((SystemExit, KeyboardInterrupt)) as exc_info:
        cli.main([], prog_name="cli")

    assert isinstance(exc_info.value, SystemExit)
    assert exc_info.value.code == exit_code
    interrupted.assert_called_once_with(exit_code)


@pytest.mark.parametrize("first", [KeyboardInterrupt, EOFError])
def test_body_abort(runner, first):
    @click.command()
    def cli():
        raise first("interrupted")

    result = runner.invoke(cli)
    assert result.exit_code == 1
    assert result.stderr == "\nAborted!\n"

    result = runner.invoke(cli, standalone_mode=False)
    assert isinstance(result.exception, click.Abort)
    assert isinstance(result.exception.__cause__, first)
    assert result.exception.__cause__.args == ("interrupted",)
    assert result.stderr == "\n"
