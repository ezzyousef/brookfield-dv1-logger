"""Instrument adapters and the serial write barrier, with a simulated port (no hardware).

The acceptance requirement: prove that real hardware cannot receive unsupported commands through
the app. Every test below opens a FakeSerial that records each byte written to it.
"""
from __future__ import annotations

import json

import pytest

from core.analysis import full_scale_range_cp, shear_rate_per_sec
from core.instruments import (DV1_UNAVAILABLE_REASON, AdapterError, AdapterUnavailable, ProtocolAdapter,
                              ProtocolDefinition, ReplayAdapter, SimulatedViscometer, dv1_live_adapter)
from core.serial_interface import DV1Protocol, RawSerialLink, SerialConnectionError, WriteNotAuthorized
from core.data_io import save_session_json, export_to_csv

from conftest import make_readings


class FakeSerial:
    """A stand-in for serial.Serial: scripted input, every write recorded."""
    instances: list["FakeSerial"] = []

    def __init__(self, port=None, baudrate=9600, timeout=1.0, **_):
        self.port, self.baudrate, self.timeout = port, baudrate, timeout
        self.is_open = True
        self.written = b""
        self.incoming = b""
        FakeSerial.instances.append(self)

    @property
    def in_waiting(self):
        return len(self.incoming)

    def read(self, n):
        out, self.incoming = self.incoming[:n], self.incoming[n:]
        return out

    def readline(self):
        i = self.incoming.find(b"\n")
        if i < 0:
            out, self.incoming = self.incoming, b""
        else:
            out, self.incoming = self.incoming[:i + 1], self.incoming[i + 1:]
        return out

    def write(self, data):
        self.written += data
        return len(data)

    def close(self):
        self.is_open = False


@pytest.fixture
def link():
    FakeSerial.instances.clear()
    lk = RawSerialLink("COM99", serial_factory=FakeSerial)
    lk.open()
    yield lk
    lk.close()


def _definition(**kw):
    data = {"name": "Bath thermometer", "instrument": "Example ASCII thermometer",
            "document": "Example manual rev. B", "line_pattern": r"T=(?P<temperature_c>-?\d+(\.\d+)?)"}
    data.update(kw)
    return ProtocolDefinition.from_dict(data)


# ----------------------------------------------------------------------------- write barrier
def test_a_new_connection_is_read_only(link):
    assert not link.writes_authorized
    with pytest.raises(WriteNotAuthorized):
        link.write_raw(b"R\r\n")
    assert FakeSerial.instances[0].written == b""


def test_reading_and_capture_never_write(link):
    port = FakeSerial.instances[0]
    port.incoming = b"line one\r\nline two\r\n"
    assert link.read_line() == "line one"
    assert link.read_all_available() == "line two\r\n"
    assert port.written == b"" and link.bytes_written == 0


def test_writes_need_a_stated_reason_and_end_when_the_port_closes(link):
    with pytest.raises(WriteNotAuthorized):
        link.authorize_writes("   ")
    link.authorize_writes("Example manual rev. B, section 4")
    link.write_raw(b"Q\r\n")
    assert FakeSerial.instances[0].written == b"Q\r\n"
    link.close()
    link.open()
    assert not link.writes_authorized
    with pytest.raises(WriteNotAuthorized):
        link.write_raw(b"Q\r\n")
    assert FakeSerial.instances[1].written == b""


def test_revoking_stops_writes(link):
    link.authorize_writes("doc")
    link.revoke_writes()
    with pytest.raises(WriteNotAuthorized):
        link.write_raw(b"x")


def test_closed_port_cannot_be_authorised():
    lk = RawSerialLink("COM98", serial_factory=FakeSerial)
    with pytest.raises(SerialConnectionError):
        lk.authorize_writes("doc")


def test_dv1_has_no_live_adapter_and_no_protocol_commands(link):
    with pytest.raises(AdapterUnavailable, match="Wingather"):
        dv1_live_adapter(link)
    with pytest.raises(NotImplementedError):
        DV1Protocol(link)
    assert "M14-023-A0416" in DV1_UNAVAILABLE_REASON


@pytest.mark.parametrize("instrument", ["Brookfield DV1", "DV-1 viscometer", "dv1mlv", "DV 1"])
def test_protocol_definitions_for_the_dv1_are_refused(instrument):
    with pytest.raises(AdapterUnavailable):
        _definition(instrument=instrument)
    with pytest.raises(AdapterUnavailable):
        _definition(instrument=instrument, allow_commands=True, authorized_by="me",
                    document_section="4", query_command="R")


def test_protocol_adapter_without_authorisation_only_listens(link):
    port = FakeSerial.instances[0]
    definition = _definition(allow_commands=True, authorized_by="Lab manager", document_section="4.2",
                             query_command="T?")
    adapter = ProtocolAdapter(definition, link, model="DV1MLV", spindle="SC4-18")
    port.incoming = b"T=24.9\r\nnoise\r\nT=25.1\n"
    readings = adapter.poll()
    assert [r.temperature_c for r in readings] == [24.9, 25.1]
    assert all(r.source == "protocol" for r in readings)
    assert adapter.unparsed == 1
    assert port.written == b""                              # the port was never authorised


def test_protocol_adapter_sends_its_documented_query_only_when_authorised(link):
    port = FakeSerial.instances[0]
    definition = _definition(allow_commands=True, authorized_by="Lab manager", document_section="4.2",
                             query_command="T?")
    adapter = ProtocolAdapter(definition, link)
    link.authorize_writes("Example manual rev. B, section 4.2")
    adapter.poll()
    assert port.written == b"T?\r\n"


def test_a_listen_only_definition_never_sends_even_on_an_authorised_port(link):
    adapter = ProtocolAdapter(_definition(), link)
    link.authorize_writes("doc")
    adapter.poll()
    assert FakeSerial.instances[0].written == b""


@pytest.mark.parametrize("change,needle", [
    ({"document": ""}, "document"),
    ({"line_pattern": "("}, "regular expression"),
    ({"line_pattern": r"\d+"}, "named groups"),
    ({"line_pattern": r"(?P<secret>\d+)"}, "unsupported"),
    ({"line_pattern": "a" * 500}, "longer"),
    ({"query_command": "R"}, "allow_commands"),
    ({"query_command": "R", "allow_commands": True}, "authorized_by"),
    ({"query_command": "R", "allow_commands": True, "authorized_by": "x"}, "document_section"),
    ({"allow_commands": "yes"}, "true or false"),
    ({"baudrate": "fast"}, "baud"),
    ({"run": "rm -rf /"}, "Unknown field"),
])
def test_bad_protocol_definitions_are_refused(change, needle):
    with pytest.raises(AdapterError, match=needle):
        _definition(**change)


def test_protocol_definition_file_errors(tmp_path):
    p = tmp_path / "p.json"
    p.write_text("{oops", encoding="utf-8")
    with pytest.raises(AdapterError, match="could not be read"):
        ProtocolDefinition.from_file(p)
    p.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    with pytest.raises(AdapterError, match="JSON object"):
        ProtocolDefinition.from_file(p)


def test_overlong_and_non_finite_lines_are_ignored(link):
    port = FakeSerial.instances[0]
    adapter = ProtocolAdapter(_definition(line_pattern=r"T=(?P<temperature_c>\S+)"), link)
    port.incoming = b"T=" + b"9" * 400 + b"\r\nT=inf\r\nT=nan\r\nT=20\r\n"
    assert [r.temperature_c for r in adapter.poll()] == [20.0]


# ----------------------------------------------------------------------------- simulation and replay
def test_simulation_follows_its_fluid_model_and_the_manual_formulas():
    sim = SimulatedViscometer(model="DV1MLV", spindle="SC4-18", rpms=(2.0, 20.0), k_cp=2000.0, n=0.6)
    readings = sim.poll() + sim.poll()
    assert sim.finished and sim.poll() == []
    for r in readings:
        rate = 1.32 * r.rpm                                   # SC4-18 SRC from the DV1 manual table
        assert r.viscosity_cp == pytest.approx(2000.0 * rate ** -0.4)
        fsr = 0.09375 * 3.2 * 10000.0 / r.rpm                 # TK(LV) * SMC(SC4-18) * 10000 / rpm
        assert r.percent_torque == pytest.approx(100.0 * r.viscosity_cp / fsr)
        assert r.source == "simulated" and "simulated" in r.source_label()


def test_simulation_noise_is_reproducible():
    a = SimulatedViscometer(noise_pct=2.0, seed=7)
    b = SimulatedViscometer(noise_pct=2.0, seed=7, start_time=a.start_time)
    assert [r.viscosity_cp for r in a.poll() + a.poll()] == [r.viscosity_cp for r in b.poll() + b.poll()]


def test_simulation_rejects_impossible_settings():
    with pytest.raises(AdapterError):
        SimulatedViscometer(rpms=(0.0,))
    with pytest.raises(AdapterError):
        SimulatedViscometer(n=0)


def test_replay_keeps_values_and_timestamps_but_labels_the_source(tmp_path):
    original = make_readings()
    path = tmp_path / "rec.json"
    save_session_json(original, str(path))
    replay = ReplayAdapter(path)
    out = []
    while not replay.finished:
        out += replay.poll()
    assert len(out) == len(original)
    for a, b in zip(original, out):
        assert (a.timestamp, a.viscosity_cp, a.percent_torque, a.rpm) == (b.timestamp, b.viscosity_cp,
                                                                         b.percent_torque, b.rpm)
        assert b.source == "replay" and "rec.json" in b.notes


def test_replay_of_a_csv_export(tmp_path):
    path = tmp_path / "rec.csv"
    export_to_csv(make_readings(), str(path))
    assert len(ReplayAdapter(path)) == 6


def test_replay_refuses_a_damaged_file(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("[{", encoding="utf-8")
    with pytest.raises(AdapterError, match="bad.json"):
        ReplayAdapter(path)


def test_shipped_example_session_replays():
    from pathlib import Path
    example = Path(__file__).resolve().parents[1] / "examples" / "synthetic_shear_sweep.json"
    replay = ReplayAdapter(example)
    readings = []
    while not replay.finished:
        readings += replay.poll()
    assert len(readings) >= 6
    assert all("simulated" in r.notes for r in readings)   # the example says it is synthetic


def test_no_adapter_writes_to_the_port(link):
    """Simulation and replay never get a port; the protocol adapter without authorisation reads only."""
    port = FakeSerial.instances[0]
    port.incoming = b"T=1\r\n" * 5
    ProtocolAdapter(_definition(), link).poll()
    SimulatedViscometer().poll()
    assert port.written == b""
    assert shear_rate_per_sec("SC4-18", 10) and full_scale_range_cp("DV1MLV", "SC4-18", 10)
