"""
MReyeXtract Package

Initialize logging for the package

"""

import logging
from typing import Protocol, Any

__all__ = ["enable_logging", "LOG_FORMAT"]

PACKAGE_NAME = __name__

# Package-level logger
LOG_FORMAT = "%(asctime)s | [%(levelname)s] | %(name)s: %(message)s"
logger = logging.getLogger(PACKAGE_NAME)
logger.addHandler(logging.NullHandler())  # default: silent unless configured


def enable_logging(level: int | str = "INFO") -> None:
    """
    Configure root console logging (works in main process and in joblib workers
    if called there too, or if workers call basicConfig(force=True)).
    """
    if isinstance(level, str):
        level = logging.getLevelName(level.upper())

    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        force=True,  # replace existing handlers; avoids "does nothing" surprises
    )

    logging.getLogger("mreyextract").setLevel(level)
    logging.getLogger("mreyextract").propagate = True


class ContextAdapter(logging.LoggerAdapter):
    """
    Logging adapter to add context (used currently for parallel worker processes)
    """

    def process(self, msg, kwargs):
        """
        Parameters
        ----------
        msg
        kwargs

        Returns
        -------

        """
        ctx = self.extra.get("ctx", {})
        if ctx:
            prefix = " ".join(f"{k}={v}" for k, v in ctx.items())
            msg = f"[{prefix}] {msg}"
        return msg, kwargs

    def with_ctx(self, **more: Any) -> "ContextAdapter":
        """
        Add context to log message

        Parameters
        ----------
        more

        Returns
        -------

        """

        ctx = dict(self.extra.get("ctx", {}))  # type: ignore
        ctx.update(more)
        return ContextAdapter(self.logger, {"ctx": ctx})


def _ensure_worker_logging(log_level: int = logging.INFO):
    logging.basicConfig(
        level=log_level,
        format=LOG_FORMAT,
        force=True,
    )


class LoggerLike(Protocol):
    # pylint: disable=missing-function-docstring
    """
    Protocol for any Logger
    """

    def debug(self, msg: str, *args, **kwargs) -> None: ...
    def info(self, msg: str, *args, **kwargs) -> None: ...
    def warning(self, msg: str, *args, **kwargs) -> None: ...
    def error(self, msg: str, *args, **kwargs) -> None: ...
    def exception(self, msg: str, *args, **kwargs) -> None: ...
