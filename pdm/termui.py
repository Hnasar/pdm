from __future__ import annotations

import atexit
import contextlib
import enum
import logging
import os
import warnings
from functools import partial
from tempfile import mktemp
from typing import Any, Iterator, Sequence, Type

from rich.box import ROUNDED
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import Progress, ProgressColumn
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

from pdm._types import Spinner, SpinnerT

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.addHandler(logging.NullHandler())
unearch_logger = logging.getLogger("unearth")
unearch_logger.setLevel(logging.DEBUG)


_console = Console(highlight=False)
_err_console = Console(stderr=True)


def is_interactive(console: Console | None = None) -> bool:
    """Check if the terminal is run under interactive mode"""
    if console is None:
        console = _console
    return console.is_interactive


def is_legacy_windows(console: Console | None = None) -> bool:
    """Legacy Windows renderer may have problem rendering emojis"""
    if console is None:
        console = _console
    return console.legacy_windows


def style(
    text: str,
    *args: str,
    style: str = None,
    deprecated: bool = False,
    **kwargs: Any,
) -> str:
    """return text with ansi codes using rich console

    :param text: message with rich markup, defaults to "".
    :param style: rich style to apply to whole string
    :return: string containing ansi codes
    """
    if deprecated:  # pragma: no cover
        warnings.warn(
            "calling color function from termui is deprecated, please use "
            "rich's console markup",
            DeprecationWarning,
            stacklevel=2,
        )
    with _console.capture() as capture:
        _console.print(text, *args, end="", style=style, **kwargs)
    return capture.get()


def confirm(*args: str, **kwargs: Any) -> str:
    return Confirm.ask(*args, **kwargs)


# For backward-compatiblity
green = partial(style, style="green", deprecated=True)
red = partial(style, style="red", deprecated=True)
yellow = partial(style, style="yellow", deprecated=True)
blue = partial(style, style="blue", deprecated=True)
cyan = partial(style, style="cyan", deprecated=True)
bold = partial(style, style="bold", deprecated=True)


def ask(
    *args: str, prompt_type: Type[str] | Type[int] | None = None, **kwargs: Any
) -> str:
    """prompt user and return reponse

    :prompt_type: which rich prompt to use, defaults to str.
    :raises ValueError: unsupported prompt type
    :return: str of user's selection
    """
    if not prompt_type or prompt_type is str:
        return Prompt.ask(*args, **kwargs)
    elif prompt_type is int:
        return str(IntPrompt.ask(*args, **kwargs))
    else:
        raise ValueError(f"unsupported {prompt_type}")


class Verbosity(enum.IntEnum):
    NORMAL = 0
    DETAIL = enum.auto()
    DEBUG = enum.auto()


LOG_LEVELS = {
    Verbosity.NORMAL: logging.WARN,
    Verbosity.DETAIL: logging.INFO,
    Verbosity.DEBUG: logging.DEBUG,
}


class Emoji:
    if is_legacy_windows():
        SUCC = "v"
        FAIL = "x"
        LOCK = " "
        CONGRAT = " "
        POPPER = " "
        ELLIPSIS = "..."
        ARROW_SEPARATOR = ">"
    else:
        SUCC = ":heavy_check_mark:"
        FAIL = ":heavy_multiplication_x:"
        LOCK = ":lock:"
        POPPER = ":party_popper:"
        ELLIPSIS = "…"
        ARROW_SEPARATOR = "➤"


if is_legacy_windows():
    SPINNER = "line"
else:
    SPINNER = "dots"


class DummySpinner:
    """A dummy spinner class implementing needed interfaces.
    But only display text onto screen.
    """

    def update(self, text: str) -> None:
        self.text = text

    def __enter__(self: SpinnerT) -> SpinnerT:
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class UI:
    """Terminal UI object"""

    def __init__(self, verbosity: Verbosity = Verbosity.NORMAL) -> None:
        self.verbosity = verbosity

    def set_verbosity(self, verbosity: int) -> None:
        self.verbosity = Verbosity(verbosity)

    def echo(
        self,
        message: str = "",
        err: bool = False,
        verbosity: Verbosity = Verbosity.NORMAL,
        **kwargs: Any,
    ) -> None:
        """print message using rich console

        :param message: message with rich markup, defaults to "".
        :param err: if true print to stderr, defaults to False.
        :param verbosity: verbosity level, defaults to NORMAL.
        """
        if self.verbosity >= verbosity:
            console = _err_console if err else _console
            if not console.is_interactive:
                kwargs.setdefault("crop", False)
                kwargs.setdefault("overflow", "ignore")
            console.print(message, **kwargs)

    def display_columns(
        self, rows: Sequence[Sequence[str]], header: list[str] | None = None
    ) -> None:
        """Print rows in aligned columns.

        :param rows: a rows of data to be displayed.
        :param header: a list of header strings.
        """

        if header:
            table = Table(box=ROUNDED)
            for title in header:
                if title[0] == "^":
                    title, justify = title[1:], "center"
                elif title[0] == ">":
                    title, justify = title[1:], "right"
                else:
                    title, justify = title, "left"
                table.add_column(title, justify=justify)
        else:
            table = Table.grid(padding=(0, 1))
            for _ in rows[0]:
                table.add_column()
        for row in rows:
            table.add_row(*row)

        _console.print(table)

    @contextlib.contextmanager
    def logging(self, type_: str = "install") -> Iterator[logging.Logger]:
        """A context manager that opens a file for logging when verbosity is NORMAL or
        print to the stdout otherwise.
        """
        file_name = mktemp(".log", f"pdm-{type_}-")

        if self.verbosity >= Verbosity.DETAIL:
            handler: logging.Handler = RichHandler(
                console=_err_console, show_time=False, show_level=False, show_path=False
            )
            handler.setLevel(LOG_LEVELS[self.verbosity])
        else:
            handler = logging.FileHandler(file_name, encoding="utf-8")
            handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
        logger.handlers[1:] = unearch_logger.handlers[:] = [handler]

        def cleanup() -> None:
            try:
                os.unlink(file_name)
            except OSError:
                pass

        try:
            yield logger
        except Exception:
            if self.verbosity < Verbosity.DETAIL:
                logger.exception("Error occurs")
                self.echo(
                    f"See [bold yellow]{file_name}[/] for detailed debug log.",
                    style="red",
                    err=True,
                )
            raise
        else:
            atexit.register(cleanup)
        finally:
            logger.handlers.remove(handler)

    def open_spinner(self, title: str) -> Spinner:
        """Open a spinner as a context manager."""
        if self.verbosity >= Verbosity.DETAIL or not is_interactive():
            return DummySpinner()
        else:
            return _console.status(title, spinner=SPINNER, spinner_style="bold cyan")

    def make_progress(self, *columns: str | ProgressColumn, **kwargs: Any) -> Progress:
        """create a progress instance for indented spinners"""
        return Progress(
            *columns,
            console=_console,
            disable=self.verbosity >= Verbosity.DETAIL,
            **kwargs,
        )
