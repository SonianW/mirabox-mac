"""Execute key actions without blocking the device reader thread."""

from __future__ import annotations

import logging
import subprocess
from typing import Callable

from .config import Action

log = logging.getLogger(__name__)


def run_action(action: Action, switch_page: Callable[[str], None]) -> None:
    if action.type in ("none", "agenda"):  # agenda is handled by the daemon itself
        return
    if action.type == "page":
        assert action.page
        switch_page(action.page)
        return
    if action.type == "shell":
        assert action.command
        log.info("shell: %s", action.command)
        subprocess.Popen(
            action.command,
            shell=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return
    if action.type == "open":
        assert action.target
        t = action.target
        if "://" in t or t.startswith("/") or t.startswith("~"):
            cmd = ["open", t]
        else:
            cmd = ["open", "-a", t]
        log.info("open: %s", " ".join(cmd))
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    log.warning("unknown action type %r", action.type)
