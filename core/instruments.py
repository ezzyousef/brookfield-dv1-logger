"""Instrument adapters: where readings come from other than the keyboard. No Qt.

    SimulatedViscometer  synthetic readings from a known fluid model (for training and tests)
    ReplayAdapter        a recorded session or CSV export played back, one reading per poll
    ProtocolAdapter      a user-supplied, documented line protocol on a serial port
    DV1 live automation  NOT AVAILABLE (see DV1_UNAVAILABLE_REASON)

Safety rules enforced here and in core.serial_interface.RawSerialLink:
  * the simulation and replay adapters never touch a serial port;
  * a ProtocolAdapter only parses what the instrument sends, unless its definition names the
    vendor document, states who authorised sending, allows commands, AND the user authorised
    writes on that port (RawSerialLink.authorize_writes);
  * definitions for the DV1 are refused outright: no public DV1 command set exists, and the
    meaning of any bytes it streams is unconfirmed.
Every reading carries its source ("simulated", "replay", "protocol"), so exports never present a
simulated or replayed value as a measurement.
"""
from __future__ import annotations

import json
import math
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from core.analysis import Reading, full_scale_range_cp, shear_rate_per_sec

DV1_UNAVAILABLE_REASON = (
    "Live DV1 automation is unavailable. Brookfield's DV1 Operating Instructions (M14-023-A0416) "
    "describe PC communication only through Brookfield's Wingather SQ software, and no DV1 command "
    "reference is public. The app will not send guessed commands to the instrument, nor interpret "
    "its raw output. Enter readings manually, or add a verified command set to DV1Protocol in "
    "core/serial_interface.py once you have Brookfield's documentation and consent to use it.")

PARSEABLE_FIELDS = ("viscosity_cp", "percent_torque", "temperature_c", "rpm")
MAX_LINE_CHARS = 256          # longer lines are ignored (guards the user's regex against huge input)
MAX_PATTERN_CHARS = 400
_DV1_NAME = re.compile(r"(?i)\bdv[\s\-]?1\b|\bdv1m")


class AdapterError(ValueError):
    """An adapter cannot be created or used (with a sentence for the user)."""


class AdapterUnavailable(AdapterError):
    pass


class InstrumentAdapter:
    """Common interface. `poll()` returns zero or more new readings; it never blocks for long."""
    name = "adapter"
    source = "unknown"
    sends_commands = False

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def poll(self) -> list[Reading]:
        raise NotImplementedError

    @property
    def finished(self) -> bool:
        return False


def dv1_live_adapter(*_a, **_k):
    """The DV1 live adapter does not exist; calling this explains why."""
    raise AdapterUnavailable(DV1_UNAVAILABLE_REASON)


# ----------------------------------------------------------------------------- simulation
@dataclass
class SimulatedViscometer(InstrumentAdapter):
    """Synthetic readings from a power-law fluid, eta = K * shear_rate^(n-1), at a speed sequence.

    For spindles without a shear-rate constant the apparent viscosity is K (a Newtonian fluid of
    viscosity K). % torque follows from the full-scale range: torque = 100 * eta / FSR. Noise is
    multiplicative and seeded, so a run is reproducible. Every reading is labelled "simulated".
    """
    model: str = "DV1MLV"
    spindle: str = "SC4-18"
    rpms: tuple = (1.0, 2.0, 5.0, 10.0, 20.0, 50.0)
    k_cp: float = 2000.0           # cP * s^(n-1)
    n: float = 0.6
    temperature_c: float = 25.0
    noise_pct: float = 0.0
    seed: int = 1
    start_time: Optional[datetime] = None
    interval_s: float = 30.0
    loop: bool = False
    name: str = "Simulation"
    source: str = "simulated"
    _i: int = field(default=0, init=False, repr=False)
    _rng: random.Random = field(default=None, init=False, repr=False)

    def __post_init__(self):
        if not self.rpms or any(r <= 0 for r in self.rpms):
            raise AdapterError("The simulation needs one or more speeds above 0 rpm.")
        if self.k_cp <= 0 or self.n <= 0:
            raise AdapterError("K and n must be greater than 0.")
        self._rng = random.Random(self.seed)
        self.start_time = self.start_time or datetime.now().replace(microsecond=0)

    def true_viscosity(self, rpm: float) -> float:
        rate = shear_rate_per_sec(self.spindle, rpm)
        return self.k_cp if rate is None else self.k_cp * rate ** (self.n - 1.0)

    @property
    def finished(self) -> bool:
        return not self.loop and self._i >= len(self.rpms)

    def poll(self) -> list[Reading]:
        if self.finished:
            return []
        rpm = self.rpms[self._i % len(self.rpms)]
        eta = self.true_viscosity(rpm)
        if self.noise_pct:
            eta *= 1.0 + self._rng.gauss(0.0, self.noise_pct / 100.0)
        fsr = full_scale_range_cp(self.model, self.spindle, rpm)
        torque = None if not fsr else 100.0 * eta / fsr
        reading = Reading(timestamp=self.start_time + timedelta(seconds=self.interval_s * self._i),
                          viscosity_cp=eta, percent_torque=torque, temperature_c=self.temperature_c,
                          rpm=rpm, spindle=self.spindle, model=self.model, source=self.source,
                          notes=f"simulated power-law fluid K={self.k_cp:g} cP·s^(n-1), n={self.n:g}")
        self._i += 1
        return [reading]


# ----------------------------------------------------------------------------- replay
class ReplayAdapter(InstrumentAdapter):
    """Plays back a recorded session (.json) or CSV export, one reading per poll.

    Values and original timestamps are kept exactly; the source becomes "replay" and the note
    names the file, so a replayed reading cannot pass for a new measurement.
    """
    name = "Replay"
    source = "replay"

    def __init__(self, path: str | Path):
        from core.data_io import ImportError_, SessionError, load_session, readings_from_csv
        p = Path(path)
        try:
            if p.suffix.lower() == ".csv":
                originals, self.warnings = readings_from_csv(str(p))
            else:
                session = load_session(str(p))
                originals, self.warnings = session.readings, session.warnings
        except (ImportError_, SessionError) as e:
            raise AdapterError(f"Cannot replay {p.name}: {e}") from e
        if not originals:
            raise AdapterError(f"{p.name} has no readings to replay.")
        self.file_name = p.name
        self._queue = []
        for r in originals:
            prior = "" if r.source == "manual" else f" (originally {r.source})"
            note = f"replay of {p.name}{prior}" + (f"; {r.notes}" if r.notes else "")
            self._queue.append(Reading(
                timestamp=r.timestamp, viscosity_cp=r.viscosity_cp, percent_torque=r.percent_torque,
                temperature_c=r.temperature_c, rpm=r.rpm, spindle=r.spindle, model=r.model,
                source="replay", notes=note, product=r.product, batch=r.batch,
                sample_id=r.sample_id, operator=r.operator, qc_flags=list(r.qc_flags)))
        self._i = 0

    def __len__(self) -> int:
        return len(self._queue)

    @property
    def finished(self) -> bool:
        return self._i >= len(self._queue)

    def poll(self) -> list[Reading]:
        if self.finished:
            return []
        self._i += 1
        return [self._queue[self._i - 1]]


# ----------------------------------------------------------------------------- documented protocol
@dataclass
class ProtocolDefinition:
    """A user-supplied line protocol, loaded from JSON. Every field is checked by `validate()`."""
    name: str
    instrument: str
    document: str                    # the vendor document this definition follows (required)
    line_pattern: str                # regex with named groups from PARSEABLE_FIELDS
    document_section: str = ""
    authorized_by: str = ""          # who approved sending commands (required for commands)
    allow_commands: bool = False
    query_command: str = ""          # sent once per poll, only when everything above allows it
    line_ending: str = "\r\n"
    baudrate: int = 9600

    @classmethod
    def from_file(cls, path: str | Path) -> "ProtocolDefinition":
        p = Path(path)
        try:
            if p.stat().st_size > 64 * 1024:
                raise AdapterError("A protocol definition larger than 64 kB is not plausible; refused.")
            data = json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as e:
            raise AdapterError(f"The protocol definition could not be read: {e}") from e
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data) -> "ProtocolDefinition":
        if not isinstance(data, dict):
            raise AdapterError("A protocol definition must be a JSON object.")
        allowed = set(cls.__dataclass_fields__)
        unknown = set(data) - allowed
        if unknown:
            raise AdapterError(f"Unknown field(s) in the protocol definition: {', '.join(sorted(unknown))}.")
        for key in ("name", "instrument", "document", "line_pattern"):
            if not isinstance(data.get(key), str) or not data[key].strip():
                raise AdapterError(f"The protocol definition needs a non-empty '{key}'.")
        for key in ("document_section", "authorized_by", "query_command", "line_ending"):
            if key in data and not isinstance(data[key], str):
                raise AdapterError(f"'{key}' must be text.")
        if "allow_commands" in data and not isinstance(data["allow_commands"], bool):
            raise AdapterError("'allow_commands' must be true or false.")
        if "baudrate" in data and (not isinstance(data["baudrate"], int) or isinstance(data["baudrate"], bool)
                                   or not 50 <= data["baudrate"] <= 4_000_000):
            raise AdapterError("'baudrate' must be a whole number of baud.")
        definition = cls(**data)
        definition.validate()
        return definition

    def validate(self) -> None:
        if _DV1_NAME.search(self.instrument) or _DV1_NAME.search(self.name):
            raise AdapterUnavailable(DV1_UNAVAILABLE_REASON)
        if len(self.line_pattern) > MAX_PATTERN_CHARS:
            raise AdapterError(f"line_pattern is longer than {MAX_PATTERN_CHARS} characters.")
        try:
            rx = re.compile(self.line_pattern)
        except re.error as e:
            raise AdapterError(f"line_pattern is not a valid regular expression: {e}") from e
        groups = set(rx.groupindex)
        if not groups:
            raise AdapterError(f"line_pattern needs named groups, e.g. (?P<viscosity_cp>...), from: "
                               f"{', '.join(PARSEABLE_FIELDS)}.")
        extra = groups - set(PARSEABLE_FIELDS)
        if extra:
            raise AdapterError(f"line_pattern has unsupported group(s): {', '.join(sorted(extra))}.")
        if self.query_command:
            if not self.allow_commands:
                raise AdapterError("query_command is set but allow_commands is false.")
            if not self.authorized_by.strip():
                raise AdapterError("Sending commands needs 'authorized_by' (who approved it).")
            if not self.document_section.strip():
                raise AdapterError("Sending commands needs 'document_section' (where the command is documented).")
        self._rx = rx

    def parse_line(self, line: str) -> Optional[dict]:
        if len(line) > MAX_LINE_CHARS:
            return None
        m = self._rx.fullmatch(line.strip())
        if not m:
            return None
        values = {}
        for key, text in m.groupdict().items():
            if text is None:
                continue
            try:
                v = float(text)
            except ValueError:
                return None
            if not math.isfinite(v):
                return None
            values[key] = v
        return values or None


class ProtocolAdapter(InstrumentAdapter):
    """Parses lines a documented instrument sends; sends a query only when fully authorised."""
    name = "Documented protocol"
    source = "protocol"

    def __init__(self, definition: ProtocolDefinition, link, *, model: str | None = None,
                 spindle: str | None = None, clock: Callable[[], datetime] = datetime.now):
        definition.validate()
        self.definition = definition
        self.link = link
        self.model = model
        self.spindle = spindle
        self.clock = clock
        self._buffer = ""
        self.unparsed = 0

    @property
    def sends_commands(self) -> bool:
        return bool(self.definition.allow_commands and self.definition.query_command
                    and self.link.writes_authorized)

    def poll(self) -> list[Reading]:
        if self.sends_commands:
            self.link.write_raw((self.definition.query_command + self.definition.line_ending).encode("ascii"))
        self._buffer += self.link.read_all_available()
        if len(self._buffer) > 64 * 1024:              # a stream with no line endings: drop it
            self._buffer = self._buffer[-MAX_LINE_CHARS:]
        out = []
        while True:
            cut = min((i for i in (self._buffer.find("\n"), self._buffer.find("\r")) if i >= 0), default=-1)
            if cut < 0:
                break
            line, self._buffer = self._buffer[:cut], self._buffer[cut + 1:]
            if not line.strip():
                continue
            values = self.definition.parse_line(line)
            if values is None:
                self.unparsed += 1
                continue
            out.append(Reading(timestamp=self.clock(), model=self.model, spindle=self.spindle,
                               source="protocol", notes=f"{self.definition.name} ({self.definition.document})",
                               **values))
        return out
