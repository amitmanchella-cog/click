import sys
from io import StringIO

import pytest

import click


@pytest.fixture(params=["isatty", "write", "flush"])
def interrupted_stderr(request, monkeypatch):
    def install():
        stderr = StringIO()
        interrupt = KeyboardInterrupt("during reporting")
        calls = []

        def interrupt_output(*args):
            calls.append(args)
            raise interrupt

        monkeypatch.setattr(stderr, request.param, interrupt_output)
        monkeypatch.setattr(sys, "stderr", stderr)
        return interrupt, calls

    return install


@pytest.mark.parametrize("exc", [KeyboardInterrupt, EOFError])
@pytest.mark.parametrize("prompt", [False, True])
@pytest.mark.parametrize("standalone", [False, True])
def test_single_interrupt(monkeypatch, capsys, exc, prompt, standalone):
    original = exc("first interrupt")

    def interrupt(*args):
        raise original

    monkeypatch.setattr("click.termui.visible_prompt_func", interrupt)
    cli = click.Command(
        "cli",
        callback=interrupt,
        params=[click.Option(["--name"], prompt="Name")] if prompt else [],
    )

    with pytest.raises(SystemExit if standalone else click.Abort) as caught:
        cli.main([], standalone_mode=standalone)

    if standalone:
        assert caught.value.code == 1
        assert capsys.readouterr().err == ("" if prompt else "\n") + "Aborted!\n"
    elif prompt:
        # prompt() already converts the exception to Abort, without a cause.
        assert caught.value.__context__ is original
    else:
        assert caught.value.__cause__ is original


@pytest.mark.parametrize("exc", [KeyboardInterrupt, EOFError])
@pytest.mark.parametrize("prompt", [False, True])
def test_interrupt_during_abort_reporting(monkeypatch, interrupted_stderr, exc, prompt):
    _, calls = interrupted_stderr()

    def interrupt(*args):
        raise exc()

    monkeypatch.setattr("click.termui.visible_prompt_func", interrupt)
    cli = click.Command(
        "cli",
        callback=interrupt,
        params=[click.Option(["--name"], prompt="Name")] if prompt else [],
    )

    # Catch KeyboardInterrupt too so a regression fails without stopping pytest.
    with pytest.raises((SystemExit, KeyboardInterrupt)) as caught:
        cli.main([])

    assert calls
    assert isinstance(caught.value, SystemExit)
    assert caught.value.code == 1


@pytest.mark.parametrize("exc", [KeyboardInterrupt, EOFError])
def test_late_interrupt_without_standalone_mode(interrupted_stderr, exc):
    interrupt, _ = interrupted_stderr()

    @click.command()
    def cli():
        raise exc()

    with pytest.raises(KeyboardInterrupt) as caught:
        cli.main([], standalone_mode=False)

    assert caught.value is interrupt


@pytest.mark.parametrize("exit_code", [2, 7])
@pytest.mark.parametrize("standalone", [False, True])
def test_interrupt_during_error_reporting(interrupted_stderr, exit_code, standalone):
    _, calls = interrupted_stderr()

    class CustomError(click.ClickException):
        pass

    CustomError.exit_code = exit_code
    error = CustomError("failed")

    @click.command()
    def cli():
        raise error

    with pytest.raises((SystemExit, KeyboardInterrupt, CustomError)) as caught:
        cli.main([], standalone_mode=standalone)

    if standalone:
        assert calls
        assert isinstance(caught.value, SystemExit)
        assert caught.value.code == exit_code
    else:
        assert not calls
        assert caught.value is error


@pytest.mark.parametrize(
    ("outcome", "exit_code"),
    [
        (None, 0),
        (click.Abort(), 1),
        (KeyboardInterrupt(), 1),
        (EOFError(), 1),
        (click.UsageError("failed"), 2),
        (click.exceptions.Exit(7), 7),
    ],
)
def test_interrupt_during_exit(monkeypatch, outcome, exit_code):
    exit_calls = []

    def interrupt_exit(code):
        exit_calls.append(code)
        raise KeyboardInterrupt("during exit")

    monkeypatch.setattr(sys, "exit", interrupt_exit)

    @click.command()
    def cli():
        if outcome is not None:
            raise outcome

    with pytest.raises((SystemExit, KeyboardInterrupt)) as caught:
        cli.main([])

    assert exit_calls == [exit_code]
    assert isinstance(caught.value, SystemExit)
    assert caught.value.code == exit_code
