"""Where the app's own log lines go.

There was no logging configuration at all (audit 2026-11-26). gunicorn, with
uvicorn workers and no --log-config, gives handlers to its own loggers and
uvicorn's, never to the root logger -- so a `backend.*` logger fell through
to Python's last-resort handler: WARNING and above to stderr with no
timestamp or logger name, and every INFO line (sync summaries, "request
written to SharePoint", slow Graph calls) dropped. Suspected from the code;
to be confirmed in App Service's log stream after the next deploy.

`configure()` gives the root logger one stdout handler when nothing else has
given it one, so `backend.*`, `app` and libraries print one line each --
timestamp, level, logger, message. `backend` and `app` log from INFO (or
`LOG_LEVEL` from the environment), everything else from WARNING. uvicorn's
and gunicorn's own loggers are left as their runner set them up.

When the root logger already has handlers -- pytest's capture, or a
--log-config given to gunicorn -- they are kept and only the levels are set.

app.py imports this module once, for its effect; running it again is a no-op.
"""
from __future__ import annotations

import logging
import logging.config
import os

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

#: The loggers that are the app's own.
APP_LOGGERS = ("backend", "app")


def _level() -> str:
    level = (os.environ.get("LOG_LEVEL") or "INFO").strip().upper()
    return level if level in logging.getLevelNamesMapping() else "INFO"


def configure() -> None:
    level = _level()
    root = logging.getLogger()
    if root.handlers:
        for name in APP_LOGGERS:
            logging.getLogger(name).setLevel(level)
        return
    logging.config.dictConfig({
        "version": 1,
        # uvicorn and gunicorn configure their loggers before the app is
        # imported; switching those off would hide the access log.
        "disable_existing_loggers": False,
        "formatters": {"plain": {"format": FORMAT}},
        "handlers": {"stdout": {"class": "logging.StreamHandler", "formatter": "plain",
                                "stream": "ext://sys.stdout"}},
        "root": {"level": "WARNING", "handlers": ["stdout"]},
        # They propagate to root's one handler, so nothing prints twice.
        "loggers": {name: {"level": level} for name in APP_LOGGERS},
    })


configure()
