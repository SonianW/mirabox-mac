"""Device lifecycle: open the M18, draw the current page, dispatch key presses."""

from __future__ import annotations

import datetime as dt
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
from .events import load_events
from .render import blank_key, render_alarm, render_clock, render_key, split_tiles

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
        self.last_activity = time.monotonic()
        self.clock_mode = False
        self._clock_stop = threading.Event()
        self._clock_thread = threading.Thread(target=self._clock_loop, daemon=True)
        self._clock_thread.start()
        self.alarm_event = None  # Event currently alarming
        self._alarm_started = 0.0
        self._alarm_done: set[str] = set()  # event ids already alarmed or dismissed
        self._events = []
        self._events_mtime = None
        self._alarm_thread = threading.Thread(target=self._alarm_loop, daemon=True)
        self._alarm_thread.start()
        self._sync_thread = threading.Thread(target=self._sync_loop, daemon=True)
        self._sync_thread.start()
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
            self.touch()
            self.draw_page()

    def detach(self, device=None) -> None:
        with self.lock:
            if self.device is None:
                return
            log.info("device removed")
            self.device = None

    # ----- drawing -----
    def _send_tiles(self, dev, tiles) -> None:
        for n, img in enumerate(tiles, start=1):
            path = self.workdir / f"key-{n}.jpg"
            img.save(path, "JPEG", quality=92)
            dev.set_key_image(n, str(path))
        dev.refresh()

    def draw_page(self) -> None:
        with self.lock:
            dev = self.device
            if dev is None:
                return
            self.clock_mode = False
            page = self.config.page(self.page_name)
            tiles = [render_key(page.keys[n]) if n in page.keys else blank_key() for n in LCD_KEYS]
            self._send_tiles(dev, tiles)
            log.info("drew page %r", self.page_name)

    # ----- idle clock -----
    def touch(self) -> None:
        self.last_activity = time.monotonic()

    def _clock_loop(self) -> None:
        last_frame = None
        while not self._clock_stop.wait(0.1):
            cfg = self.config.clock
            if cfg.idle_seconds <= 0:
                continue
            with self.lock:
                dev = self.device
                if dev is None:
                    continue
                if self.alarm_event is not None:
                    continue
                if not self.clock_mode:
                    if time.monotonic() - self.last_activity < cfg.idle_seconds:
                        continue
                    self.clock_mode = True
                    last_frame = None
                    log.info("idle for %ds, showing clock", cfg.idle_seconds)
                now = dt.datetime.now()
                colon_on = (now.second % 2 == 0) if cfg.blink else True
                frame = (now.hour, now.minute, colon_on, now.day, cfg.gap, cfg.show_date, cfg.fg, cfg.bg)
                if frame == last_frame:
                    continue
                last_frame = frame
                try:
                    self._send_tiles(dev, split_tiles(render_clock(now, colon_on, cfg), cfg.gap))
                except Exception:
                    log.exception("clock frame failed")

    # ----- meeting alarm -----
    def _refresh_events(self) -> None:
        path = self.config.alarm.events_file
        try:
            m = path.stat().st_mtime
        except FileNotFoundError:
            m = None
        if m != self._events_mtime:
            self._events_mtime = m
            self._events = load_events(path)
            log.info("loaded %d events from %s", len(self._events), path)

    def _alarm_loop(self) -> None:
        phase = 0
        while not self._clock_stop.wait(0.2):
            cfg = self.config.alarm
            if not cfg.enabled:
                continue
            self._refresh_events()
            now = dt.datetime.now()
            with self.lock:
                dev = self.device
                if dev is None:
                    continue
                if self.alarm_event is None:
                    for ev in self._events:
                        lead = (ev.start - now).total_seconds()
                        if ev.id not in self._alarm_done and -cfg.max_seconds < lead <= cfg.lead_seconds:
                            self.alarm_event = ev
                            self._alarm_started = time.monotonic()
                            self._alarm_done.add(ev.id)
                            phase = 0
                            dev.set_brightness(100)
                            log.info("ALARM: %r starts at %s", ev.title, ev.start.strftime("%H:%M"))
                            break
                    if self.alarm_event is None:
                        continue
                ev = self.alarm_event
                if time.monotonic() - self._alarm_started > cfg.max_seconds:
                    log.info("alarm for %r timed out", ev.title)
                    self._end_alarm()
                    continue
                seconds_left = max(0, int((ev.start - now).total_seconds()))
                try:
                    self._send_tiles(dev, split_tiles(render_alarm(ev.title, seconds_left, phase, self.config.clock.gap), self.config.clock.gap))
                    dev.set_led_color(*((255, 0, 0) if phase % 2 == 0 else (255, 255, 255)))
                except Exception:
                    log.exception("alarm frame failed")
                phase += 1
            time.sleep(max(0.0, 1.0 / cfg.fps - 0.2))

    def _sync_loop(self) -> None:
        from .wave_oauth import OauthError
        from .wave_sync import sync

        warned = False
        while True:
            cfg = self.config.alarm
            if cfg.enabled and cfg.wave_mcp_url:
                try:
                    sync(cfg.wave_mcp_url, cfg.events_file)
                    warned = False
                except OauthError as e:
                    if not warned:
                        log.warning("calendar sync needs login: %s", e)
                        warned = True
                except Exception:
                    log.exception("calendar sync failed")
            if self._clock_stop.wait(cfg.sync_minutes * 60):
                return

    def _end_alarm(self) -> None:
        """Caller holds self.lock."""
        self.alarm_event = None
        dev = self.device
        if dev is not None:
            dev.set_brightness(self.config.brightness)
            if self.config.led is not None:
                dev.set_led_color(*self.config.led)
            else:
                dev.set_led_color(0, 0, 0)
        self.touch()
        self.draw_page()

    def wake(self) -> bool:
        """Leave clock mode. Returns True if the display was showing the clock."""
        with self.lock:
            self.touch()
            if self.alarm_event is not None:
                log.info("alarm dismissed by key press")
                self._end_alarm()
                return True
            if not self.clock_mode:
                return False
            log.info("key press, leaving clock")
            self.draw_page()
            return True

    def switch_page(self, name: str) -> None:
        if name not in self.config.pages:
            log.warning("page %r not defined", name)
            return
        self.page_name = name
        self.touch()
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
    @staticmethod
    def _key_position(device, logical_key) -> int:
        """Map an SDK logical key to the screen position (1-15 LCD, 16-18 buttons).

        On M18 firmware V3.M18V3_E the hardware reports the LCD key's screen
        position directly, while the SDK decodes it through the row-swapped
        image map (rows 1 and 3 exchanged). Undo that swap so a press of the
        key drawn at position n is reported as n. Buttons 16-18 are unaffected.
        """
        n = int(logical_key)
        if 1 <= n <= 15:
            return int(device.get_image_key(logical_key))
        return n

    def _on_event(self, device, event) -> None:
        try:
            if event.event_type != EventType.BUTTON or event.state != 1:
                return
            if self.wake():
                return  # the press that wakes the screen does nothing else
            n = self._key_position(device, event.key)
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
