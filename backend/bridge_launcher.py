"""
TradeClaw — Bridge Launcher
=============================
Self-healing RPyC bridge manager.
Detects platform (macOS/Wine, Windows, Linux), locates MT5 and Python,
starts the bridge server as a managed subprocess.

No CLI needed — triggered automatically from /setup/connect or on first
MT5 connection attempt.  The frontend setup wizard IS the entry point.
"""

import logging
import os
import platform
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("tradeclaw.bridge_launcher")

BACKEND_DIR = Path(__file__).resolve().parent
BRIDGE_SCRIPT = "mt5_bridge_server.py"
DEFAULT_PORT = int(os.getenv("MT5_BRIDGE_PORT", "18812"))
DEFAULT_HOST = os.getenv("MT5_BRIDGE_HOST", "localhost")

# ── macOS / Wine paths (from mac_mt5_bridge_setup.sh) ──────────────────────

_MAC_WINE_PREFIX = os.path.expanduser(
    os.getenv("WINEPREFIX",
              "~/Library/Application Support/net.metaquotes.wine.metatrader5")
)
_MAC_WINE_BIN = os.getenv(
    "WINE_BIN",
    "/Applications/MetaTrader 5.app/Contents/SharedSupport/wine/bin/wine"
)
_MAC_WINE_PYTHON = os.path.join(_MAC_WINE_PREFIX, "drive_c/python/python.exe")

# ── Windows paths ──────────────────────────────────────────────────────────

_WIN32 = (platform.system().lower() in ("windows", "win32"))


@dataclass
class PlatformInfo:
    system: str                # darwin | win32 | linux
    wine_bin: Optional[str] = None
    wine_python: Optional[str] = None
    native_python: str = field(default_factory=lambda: sys.executable)

    @property
    def is_macos(self) -> bool:
        return self.system == "darwin"

    @property
    def is_windows(self) -> bool:
        return self.system in ("windows", "win32")

    @property
    def can_auto_launch(self) -> bool:
        """Can we realistically start a bridge on this machine?"""
        if self.is_windows:
            return True
        if self.is_macos:
            return self.wine_bin is not None and self.wine_python is not None
        return False  # Linux — bridge runs on a remote Windows host


# ═══════════════════════════════════════════════════════════════════════════
# Bridge Launcher
# ═══════════════════════════════════════════════════════════════════════════

class BridgeLauncher:
    """
    Manages the RPyC bridge server subprocess.
    Auto-detects platform, checks health, launches/stops the bridge.
    """

    def __init__(self):
        self._proc: Optional[subprocess.Popen] = None
        self._info = self._detect_platform()

    # ── Detection ──────────────────────────────────────────────────────

    def _detect_platform(self) -> PlatformInfo:
        system = platform.system().lower()
        if system == "darwin":
            return PlatformInfo(
                system="darwin",
                wine_bin=_MAC_WINE_BIN if os.path.isfile(_MAC_WINE_BIN) else None,
                wine_python=_MAC_WINE_PYTHON if os.path.isfile(_MAC_WINE_PYTHON) else None,
            )
        if system in ("windows", "win32"):
            return PlatformInfo(system="win32")
        return PlatformInfo(system="linux")

    # ── Health ─────────────────────────────────────────────────────────

    @staticmethod
    def is_bridge_running(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> bool:
        """TCP connect to check if the bridge port is open."""
        try:
            s = socket.create_connection((host, port), timeout=2)
            s.close()
            return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False

    @staticmethod
    def wait_for_bridge(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                        timeout: float = 30.0) -> bool:
        """Poll until the bridge responds, up to `timeout` seconds."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if BridgeLauncher.is_bridge_running(host, port):
                return True
            time.sleep(2)
        return False

    # ── Launch ─────────────────────────────────────────────────────────

    def launch_bridge(self, port: int = DEFAULT_PORT) -> bool:
        """Start the bridge server subprocess. Returns True if now reachable."""
        if self.is_bridge_running(port=port):
            logger.info("Bridge already running — skipping launch")
            return True

        if not self._info.can_auto_launch:
            logger.warning(
                f"Cannot auto-launch bridge on {self._info.system}. "
                f"Start it manually on the MT5 host: "
                f"python backend/{BRIDGE_SCRIPT}"
            )
            return False

        if self._info.is_macos:
            return self._launch_via_wine(port)
        return self._launch_native(port)

    def _launch_via_wine(self, port: int) -> bool:
        env = os.environ.copy()
        env["MT5_BRIDGE_PORT"] = str(port)
        if "WINEPREFIX" not in env:
            env["WINEPREFIX"] = _MAC_WINE_PREFIX

        script = str(BACKEND_DIR / BRIDGE_SCRIPT)
        cmd = [self._info.wine_bin, self._info.wine_python, script]
        logger.info(f"Bridge (Wine): {' '.join(cmd)}")

        try:
            self._proc = subprocess.Popen(
                cmd, env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return self.wait_for_bridge(port=port, timeout=30.0)
        except Exception as e:
            logger.error(f"Bridge launch failed: {e}")
            return False

    def _launch_native(self, port: int) -> bool:
        env = os.environ.copy()
        env["MT5_BRIDGE_PORT"] = str(port)

        script = str(BACKEND_DIR / BRIDGE_SCRIPT)
        cmd = [self._info.native_python, script]
        logger.info(f"Bridge (native): {' '.join(cmd)}")

        try:
            self._proc = subprocess.Popen(
                cmd, env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return self.wait_for_bridge(port=port, timeout=30.0)
        except Exception as e:
            logger.error(f"Bridge launch failed: {e}")
            return False

    def _launch_terminal(self) -> bool:
        """
        Start MetaTrader 5 via Wine on macOS.
        This is required *before* the bridge can initialize.
        Returns True if MT5 is/was already running.
        """
        if not self._info.is_macos or not self._info.wine_bin:
            return False

        # Check if MT5 terminal is already running (any wine process)
        try:
            result = subprocess.run(
                [self._info.wine_bin, "winepath", "-w", "C:\\"],
                capture_output=True, timeout=5,
                env={"WINEPREFIX": _MAC_WINE_PREFIX},
            )
            terminal_running = result.returncode == 0
        except Exception:
            terminal_running = False

        if terminal_running:
            logger.info("MT5 terminal already running via Wine")
            return True

        terminal_exe = "C:\\Program Files\\MetaTrader 5\\terminal64.exe"
        logger.info(f"Starting MT5 terminal via Wine: {terminal_exe}")

        try:
            subprocess.Popen(
                [self._info.wine_bin, terminal_exe, "/portable"],
                env={"WINEPREFIX": _MAC_WINE_PREFIX},
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            logger.info("MT5 terminal launched — waiting 25s for it to initialize")
            time.sleep(25)
            return True
        except Exception as e:
            logger.error(f"Failed to launch MT5 terminal: {e}")
            return False

    # ── Ensure ─────────────────────────────────────────────────────────

    def ensure_running(self, host: str = DEFAULT_HOST,
                       port: int = DEFAULT_PORT) -> bool:
        """
        Ensure a bridge is reachable.  Auto-launches MT5 terminal first if
        we're on macOS/Wine, then launches the bridge.
        """
        if self.is_bridge_running(host, port):
            return True

        logger.info(f"Bridge not found on {host}:{port} — attempting auto-launch")

        # On macOS: MT5 terminal must be running before bridge can connect
        if self._info.is_macos and self._info.wine_bin:
            self._launch_terminal()

        return self.launch_bridge(port)

    # ── Stop ───────────────────────────────────────────────────────────

    def stop_bridge(self):
        if self._proc and self._proc.poll() is None:
            logger.info(f"Stopping bridge subprocess (PID {self._proc.pid})")
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None


# ── Module-level singleton ─────────────────────────────────────────────────

_launcher: Optional[BridgeLauncher] = None


def get_bridge_launcher() -> BridgeLauncher:
    global _launcher
    if _launcher is None:
        _launcher = BridgeLauncher()
    return _launcher


def stop_bridge():
    global _launcher
    if _launcher:
        _launcher.stop_bridge()
        _launcher = None
