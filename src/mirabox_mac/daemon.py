"""Device lifecycle: open the M18, draw the current page, dispatch key presses."""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from StreamDock.DeviceManager import DeviceManager
from StreamDock.Devices.StreamDockM18 import StreamDockM18
from StreamDock.InputTypes import EventType

from .actions import run_action
from .config import LCD_KEYS, Config, ConfigError, load_config
from .render import blank_key, render_key

log = logging.getLogger(__name__)

OFFICIAL_APP_PROCESS = "StreamDock"


def official_app_running() -> bool:
    r = subprocess.run(["pgrep", "-x", OFFICIAL_APP_PROCESS], capture_output=True)
    return r.returncode == 0


class Deck:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.config: Config = load_config(config_path)
        self.page_name = self.config.default_page
        self.device: StreamDockM18 | None = None
        self.lock = threading.RLock()
        # The SDK writes temporary JPEGs into the current directory.
        self.workdir = Path(tempfile.mkdtemp(prefix="mirabox-mac-"))
        os.chdir(self.workdir)

    # ----- device -----
    def attach(self, device) -> None:
        if not isinstance(device, StreamDockM18):
            log.info("ignoring unsupported device %s", type(device).__name__)
            return
        with self.lock:
            if not device.open():
                log.error("failed to open device at %s", device.path)
                return
            device.init()
            self.device = device
            log.info("attached M18 fw=%s sn=%s", device.firmware_version, device.serial_number)
            device.set_brightness(self.config.brightness)
            if self.config.led is not None:
                device.set_led_color(*self.config.led)
            device.set_key_callback(self._on_event)
            self.draw_page()

    def detach(self, device=None) -> None:
        with self.lock:
            if self.device is None:
                return
            log.info("device removed")
            self.device = None

    # ----- drawing -----
    def draw_page(self) -> None:
        with self.lock:
            dev = self.device
            if dev is None:
                return
            page = self.config.page(self.page_name)
            for n in LCD_KEYS:
                key = page.keys.get(n)
                img = render_key(key) if key else blank_key()
                path = self.workdir / f"key-{n}.jpg"
                img.save(path, "JPEG", quality=95)
                dev.set_key_image(n, str(path))
            dev.refresh()
            log.info("drew page %r", self.page_name)

    def switch_page(self, name: str) -> None:
        if name not in self.config.pages:
            log.warning("page %r not defined", name)
            return
        self.page_name = name
        self.draw_page()

    def reload(self) -> None:
        try:
            cfg = load_config(self.config_path)
        except ConfigError as e:
            log.error("config reload failed, keeping old config: %s", e)
            return
        self.config = cfg
        if self.page_name not in cfg.pages:
            self.page_name = cfg.default_page
        with self.lock:
            if self.device is not None:
                self.device.set_brightness(cfg.brightness)
                if cfg.led is not None:
                    self.device.set_led_color(*cfg.led)
        self.draw_page()
        log.info("config reloaded")

    # ----- input -----
    def _on_event(self, device, event) -> None:
        try:
            if event.event_type != EventType.BUTTON or event.state != 1:
                return
            n = int(event.key.value)
            key = self.config.page(self.page_name).keys.get(n)
            log.info("key %d pressed (%s)", n, key.label if key else "unbound")
            if key is None:
                return
            threading.Thread(target=run_action, args=(key.action, self.switch_page), daemon=True).start()
        except Exception:
            log.exception("error handling key event")


def run(config_path: Path, watch_config: bool = True) -> None:
    if official_app_running():
        log.warning("the official StreamDock app is running; it competes for the device. Quit it for reliable input.")

    deck = Deck(config_path)
    manager = DeviceManager()

    for dev in manager.enumerate():
        deck.attach(dev)
    if deck.device is None:
        log.info("no M18 connected yet, waiting for hotplug")

    listener = threading.Thread(
        target=manager.listen,
        kwargs=dict(on_device_added=deck.attach, on_device_removed=deck.detach, auto_open=False),
        daemon=True,
    )
    listener.start()

    mtime = config_path.stat().st_mtime
    try:
        while True:
            time.sleep(1)
            if watch_config:
                try:
                    m = config_path.stat().st_mtime
                except FileNotFoundError:
                    continue
                if m != mtime:
                    mtime = m
                    deck.reload()
    except KeyboardInterrupt:
        pass
    finally:
        with deck.lock:
            if deck.device is not None:
                try:
                    deck.device.close()
                except Exception:
                    pass
