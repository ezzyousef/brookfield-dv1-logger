"""
core/serial_interface.py

IMPORTANT / READ BEFORE USING
------------------------------
Brookfield's DV1 Operating Instructions manual (M14-023-A0416, Section III.5)
documents that the DV1 communicates with a PC over its USB-B port only in
conjunction with Brookfield's own "Wingather SQ" software. That document does
NOT publish an open ASCII command set for the DV1 the way Brookfield does for
some other models (e.g. the DV2+Pro RS-232 output strings, or the DV-II+/DV3T
serial command tables). I was not able to find a publicly documented DV1
serial protocol, and I am not willing to invent command bytes to send to real
lab hardware -- a wrong command could produce nonsense results or an
unexpected instrument state.

This module therefore does NOT implement any DV1-specific commands. It only
provides:
  1. Generic port discovery (list_ports) and open/close/raw read-write, so you
     can test connectivity and, if you get official protocol documentation
     from Brookfield support, experiment with it directly.
  2. A pass-through "terminal" mode the GUI uses for manual protocol
     discovery/testing.
  3. A clearly marked extension point (`DV1Protocol` class) where real command
     methods should go once you have verified them against Brookfield's
     documentation or your own instrument.

To find the real protocol: contact Brookfield/AMETEK technical support and
ask specifically for the "DV1 RS-232/USB Interface Command Reference" (some
Brookfield instruments have this as a separate document from the main
operating manual). If your instrument is actually a DV-II+, DV2T, DV3T, or
DV2+Pro, those do have documented ASCII command protocols and this module
can be extended accordingly -- ask and I can wire that up directly.
"""

from __future__ import annotations
import re
from typing import List, Optional

# A connection, instrument or document naming a DV1. Sending is refused for any of them: the
# DV1 command set is not public (see the module docstring).
DV1_NAME = re.compile(r"(?i)\bdv[\s\-]?1\b|\bdv1m")

try:
    import serial
    from serial.tools import list_ports
    PYSERIAL_AVAILABLE = True
except ImportError:
    PYSERIAL_AVAILABLE = False


def list_available_ports() -> List[str]:
    """Return a list of device names for currently available serial ports."""
    if not PYSERIAL_AVAILABLE:
        return []
    return [p.device for p in list_ports.comports()]


def list_available_ports_detailed() -> List[tuple[str, str]]:
    """
    Return (device, description) pairs for currently available serial ports,
    e.g. ("COM3", "USB Serial Port (FTDIBUS) - FTDI"). A lab PC often has
    several COM ports (Bluetooth, other instruments, etc.) -- the description
    helps identify which one is the DV1's USB-B connection without guessing.
    """
    if not PYSERIAL_AVAILABLE:
        return []
    out = []
    for p in list_ports.comports():
        desc = p.description or ""
        if p.manufacturer and p.manufacturer not in desc:
            desc = f"{desc} - {p.manufacturer}" if desc else p.manufacturer
        out.append((p.device, desc))
    return out


class SerialConnectionError(Exception):
    pass


class WriteNotAuthorized(SerialConnectionError):
    """Raised when something tries to send bytes on a port the user has not authorised."""


class RawSerialLink:
    """
    Thin wrapper around pyserial for raw, protocol-agnostic access.

    READ-ONLY BY DEFAULT. Opening, reading and auto-capture never send a byte. Sending requires
    `authorize_writes(reason)`, which the GUI calls only after the user confirms that they have
    documentation for the instrument on that port. The authorisation ends when the port closes.
    This is the single place bytes leave the app, so it is the barrier the tests exercise.

    `serial_factory` replaces `serial.Serial` (tests pass a simulated port; no hardware needed).
    """

    def __init__(self, port: str, baudrate: int = 9600, timeout: float = 1.0, serial_factory=None,
                 description: str = ""):
        if serial_factory is None and not PYSERIAL_AVAILABLE:
            raise SerialConnectionError(
                "pyserial is not installed. Run: pip install pyserial"
            )
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._factory = serial_factory
        self._conn = None
        self._write_reason = ""
        self.bytes_written = 0
        self.description = description      # the port's USB description, if known
        self.instrument = ""

    def open(self) -> None:
        factory = self._factory or serial.Serial
        try:
            self._conn = factory(port=self.port, baudrate=self.baudrate, timeout=self.timeout)
        except Exception as e:
            raise SerialConnectionError(f"Could not open {self.port}: {e}") from e

    def close(self) -> None:
        if self._conn and self._conn.is_open:
            self._conn.close()
        self._conn = None
        self._write_reason = ""

    @property
    def is_open(self) -> bool:
        return self._conn is not None and self._conn.is_open

    # ---- write authorisation
    @property
    def writes_authorized(self) -> bool:
        return bool(self._write_reason) and self.is_open

    @property
    def write_reason(self) -> str:
        return self._write_reason

    def authorize_writes(self, reason: str, instrument: str = "") -> None:
        """Allow sending on this open port.

        `instrument` (what is connected) and `reason` (the documented protocol followed) are both
        required. Sending is REFUSED when the instrument, the reason or the port's description
        names a DV1, whose command set is not public.
        """
        if not self.is_open:
            raise SerialConnectionError("Port is not open.")
        if not reason or not reason.strip():
            raise WriteNotAuthorized("Sending needs a stated reason (the protocol document you are following).")
        if not instrument or not instrument.strip():
            raise WriteNotAuthorized("Sending needs the connected instrument to be named.")
        for text in (instrument, reason, self.description):
            if text and DV1_NAME.search(text):
                raise WriteNotAuthorized(
                    "Sending to a Brookfield DV1 is refused: its command set is not publicly documented, and "
                    "guessed bytes could put the instrument in an unexpected state. Enter readings manually.")
        self.instrument = instrument.strip()
        self._write_reason = reason.strip()

    def revoke_writes(self) -> None:
        self._write_reason = ""

    def write_raw(self, data: bytes) -> None:
        if not self.is_open:
            raise SerialConnectionError("Port is not open.")
        if not self.writes_authorized:
            raise WriteNotAuthorized(
                f"Sending to {self.port} is not authorised. The connection is read-only until you "
                "allow sending for a documented protocol.")
        self._conn.write(data)
        self.bytes_written += len(data)

    def read_line(self) -> Optional[str]:
        """Read a single newline-terminated line, if any arrived within the timeout."""
        if not self.is_open:
            raise SerialConnectionError("Port is not open.")
        raw = self._conn.readline()
        if not raw:
            return None
        return raw.decode(errors="replace").rstrip("\r\n")

    def read_all_available(self) -> str:
        if not self.is_open:
            raise SerialConnectionError("Port is not open.")
        n = self._conn.in_waiting
        if n:
            return self._conn.read(n).decode(errors="replace")
        return ""


class DV1Protocol:
    """
    EXTENSION POINT -- currently empty.

    Once you have a verified DV1 command reference (from Brookfield support
    or your own documentation), real methods belong here, e.g.:

        def get_viscosity(self) -> float: ...
        def get_percent_torque(self) -> float: ...

    implemented in terms of `self.link.write_raw(...)` / `self.link.read_line()`.
    Nothing below is implemented because I don't have a verified command set
    to build it against -- adding guessed commands here would be worse than
    leaving this unimplemented.
    """

    def __init__(self, link: RawSerialLink):
        self.link = link
        raise NotImplementedError(
            "DV1Protocol has no verified commands yet. See the module "
            "docstring in core/serial_interface.py for how to get the real "
            "protocol from Brookfield, then implement methods here."
        )
