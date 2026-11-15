"""Malformed, hostile and legacy files for every importer: CSV readings and JSON sessions.

Each importer must either load the file correctly or refuse it with a sentence that names the
problem (and the line or reading where it is). It must never load wrong numbers silently.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.data_io import (MAX_IMPORT_BYTES, ImportError_, SessionError, import_from_csv, load_session,
                          load_session_json, readings_from_csv, save_session, save_session_json, export_to_csv)

from conftest import make_readings

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _write(tmp_path, name, text, encoding="utf-8"):
    p = tmp_path / name
    p.write_text(text, encoding=encoding)
    return p


# ----------------------------------------------------------------------------- CSV
def test_row_wider_than_header_is_refused_with_its_line(tmp_path):
    # pandas' default would use the extra leading value as a row label and shift every value
    p = _write(tmp_path, "r.csv", "timestamp,viscosity_cp,percent_torque\n"
                                  "2026-01-01 12:00:00,100,50,999\n"
                                  "2026-01-01 12:00:30,110,55\n")
    with pytest.raises(ImportError_, match="(?i)line 2"):
        import_from_csv(str(p))


def test_extra_value_in_the_middle_is_refused_with_its_line(tmp_path):
    p = _write(tmp_path, "r.csv", "timestamp,viscosity_cp,percent_torque\n"
                                  "2026-01-01 12:00:00,100,50\n"
                                  "2026-01-01 12:00:30,110,55\n"
                                  "2026-01-01 12:01:00,120,60,7\n")
    with pytest.raises(ImportError_, match="(?i)line 4"):
        import_from_csv(str(p))


def test_most_rows_wider_than_header_are_still_refused(tmp_path):
    # supercap review case (a): no "majority width" heuristic may skip the check
    p = _write(tmp_path, "r.csv", "timestamp,viscosity_cp\n"
                                  "2026-01-01 12:00:00,0,1\n"
                                  "2026-01-01 12:00:30,1,0.9\n")
    with pytest.raises(ImportError_, match="(?i)line 2"):
        import_from_csv(str(p))


def test_title_line_above_a_wider_header_does_not_truncate_columns(tmp_path):
    # supercap review case (b): the third column must not be dropped
    p = _write(tmp_path, "r.csv", "DV1 export,run 4\n"
                                  "timestamp,viscosity_cp,percent_torque\n"
                                  "2026-01-01 12:00:00,100,50\n"
                                  "2026-01-01 12:00:30,110,55\n")
    frame = import_from_csv(str(p))
    assert list(frame.columns) == ["timestamp", "viscosity_cp", "percent_torque"]
    assert list(frame["percent_torque"]) == [50, 55]
    back, warnings = readings_from_csv(str(p))
    assert [r.percent_torque for r in back] == [50.0, 55.0]
    assert any("title" in w for w in warnings)


def test_empty_trailing_fields_are_accepted(tmp_path):
    # supercap review case (c): "a,b," is a trailing delimiter, not an extra value
    p = _write(tmp_path, "r.csv", "timestamp,viscosity_cp,\n"
                                  "2026-01-01 12:00:00,100,\n"
                                  "2026-01-01 12:00:30,110,,\n")
    frame = import_from_csv(str(p))
    assert list(frame.columns) == ["timestamp", "viscosity_cp"]
    assert list(frame["viscosity_cp"]) == [100, 110]


def test_well_formed_csv_keeps_its_values_in_their_columns(tmp_path):
    p = _write(tmp_path, "r.csv", "timestamp,viscosity_cp,percent_torque\n"
                                  "2026-01-01 12:00:00,100,50\n"
                                  "2026-01-01 12:00:30,110,55\n")
    frame = import_from_csv(str(p))
    assert list(frame["viscosity_cp"]) == [100, 110]
    assert list(frame["timestamp"]) == ["2026-01-01 12:00:00", "2026-01-01 12:00:30"]
    assert list(frame.index) == [0, 1]


@pytest.mark.parametrize("content,needle", [
    ("", "empty"),
    ("   \n\n", "empty"),
    ("timestamp,viscosity_cp\n", "no data rows"),
])
def test_empty_csv_says_so(tmp_path, content, needle):
    p = _write(tmp_path, "e.csv", content)
    with pytest.raises(ImportError_, match=needle):
        import_from_csv(str(p))


def test_binary_file_is_not_read_as_csv(tmp_path):
    p = tmp_path / "x.csv"
    p.write_bytes(b"PK\x03\x04\x00\x00\x00binary\x00\xff")
    with pytest.raises(ImportError_, match="binary"):
        import_from_csv(str(p))


def test_oversized_csv_is_refused_before_reading(tmp_path, monkeypatch):
    import core.data_io as dio
    monkeypatch.setattr(dio, "MAX_IMPORT_BYTES", 100)
    p = _write(tmp_path, "big.csv", "timestamp,viscosity_cp\n" + "2026-01-01 12:00:00,1\n" * 20)
    with pytest.raises(ImportError_, match="MB|too large"):
        import_from_csv(str(p))
    assert MAX_IMPORT_BYTES >= 10 * 1024 * 1024


def test_utf16_csv_from_excel_loads(tmp_path):
    p = _write(tmp_path, "u16.csv", "timestamp,viscosity_cp\n2026-01-01 12:00:00,100\n", encoding="utf-16")
    assert list(import_from_csv(str(p))["viscosity_cp"]) == [100]


def test_csv_export_reimports_to_the_same_readings(tmp_path):
    readings = make_readings(product="Gel · 5 wt%", batch="Ä-1")
    readings[2].temperature_c = None
    readings[3].notes = "bubbles, then fine"
    p = tmp_path / "r.csv"
    export_to_csv(readings, str(p))
    back, warnings = readings_from_csv(str(p))
    assert warnings == []
    assert len(back) == len(readings)
    for a, b in zip(readings, back):
        assert (a.timestamp, a.viscosity_cp, a.percent_torque, a.temperature_c, a.rpm, a.spindle,
                a.model, a.product, a.batch, a.notes, a.source) == \
               (b.timestamp, b.viscosity_cp, b.percent_torque, b.temperature_c, b.rpm, b.spindle,
                b.model, b.product, b.batch, b.notes, b.source)


def test_csv_reimport_names_the_bad_cell(tmp_path):
    p = _write(tmp_path, "r.csv", "timestamp,viscosity_cp,percent_torque\n"
                                  "2026-01-01 12:00:00,100,50\n"
                                  "2026-01-01 12:00:30,1O0,55\n")      # letter O, not zero
    with pytest.raises(ImportError_, match=r"(?i)line 3.*viscosity_cp.*1O0"):
        readings_from_csv(str(p))


def test_csv_reimport_requires_a_timestamp_column(tmp_path):
    p = _write(tmp_path, "r.csv", "time,viscosity\n1,2\n")
    with pytest.raises(ImportError_, match="timestamp"):
        readings_from_csv(str(p))


def test_csv_reimport_refuses_infinite_values(tmp_path):
    p = _write(tmp_path, "r.csv", "timestamp,viscosity_cp\n2026-01-01 12:00:00,inf\n")
    with pytest.raises(ImportError_, match="(?i)line 2"):
        readings_from_csv(str(p))


def test_csv_export_neutralises_spreadsheet_formulas(tmp_path):
    readings = make_readings()
    readings[0].notes = "=HYPERLINK(\"http://x\",\"y\")"
    readings[1].product = "+cmd|' /C calc'!A0"
    readings[2].batch = "@SUM(A1)"
    p = tmp_path / "r.csv"
    export_to_csv(readings, str(p))
    text = p.read_text(encoding="utf-8-sig")
    assert ",=HYPERLINK" not in text and ",+cmd" not in text and ",@SUM" not in text
    back, _ = readings_from_csv(str(p))
    assert back[0].notes == readings[0].notes          # the guard is removed again on import
    assert back[1].product == readings[1].product
    assert back[2].batch == readings[2].batch


def test_negative_number_text_is_not_mangled(tmp_path):
    readings = make_readings()
    readings[0].notes = "-5 °C start"
    p = tmp_path / "r.csv"
    export_to_csv(readings, str(p))
    assert readings_from_csv(str(p))[0][0].notes == "-5 °C start"


# ----------------------------------------------------------------------------- sessions
def test_legacy_v1_session_from_the_released_app_still_loads():
    """A session saved by version 2.0.0 (a bare JSON list) loads unchanged."""
    session = load_session(str(FIXTURES / "session_v1_app_2_0_0.json"))
    assert session.format_version == 1
    assert len(session.readings) == 3
    r = session.readings[0]
    assert (r.viscosity_cp, r.percent_torque, r.spindle, r.model, r.product) == \
           (1520.0, 45.3, "SC4-18", "DV1MLV", "Gel 2 wt%")
    assert session.readings[1].temperature_c is None
    assert all(x.source == "manual" for x in session.readings)
    assert any("version 1" in w for w in session.warnings)
    # the legacy reader API keeps working too
    assert load_session_json(str(FIXTURES / "session_v1_app_2_0_0.json")) == session.readings


def test_legacy_session_with_nan_loads_with_a_warning(tmp_path):
    # 2.0.0 accepted "nan" typed into a field and wrote it as a bare NaN token
    p = _write(tmp_path, "nan.json", '[{"timestamp": "2026-01-01T12:00:00", "viscosity_cp": NaN, '
                                     '"percent_torque": 40.0}]')
    session = load_session(str(p))
    assert session.readings[0].viscosity_cp is None
    assert any("not a number" in w for w in session.warnings)


def test_session_written_as_utf8_by_another_tool_keeps_its_characters(tmp_path):
    p = tmp_path / "u.json"
    p.write_text(json.dumps([{"timestamp": "2026-01-01T12:00:00", "viscosity_cp": 10.0,
                              "notes": "η at 25 °C, µ-gel"}], ensure_ascii=False), encoding="utf-8")
    assert load_session_json(str(p))[0].notes == "η at 25 °C, µ-gel"


def test_v2_session_round_trips_metadata_audit_and_readings(tmp_path):
    from core.session import AuditEntry, ExperimentNotebook, Session
    readings = make_readings(product="Gel · 5 wt%", batch="Ä-1")
    readings[0].qc_flags = ["torque below 10 %"]
    readings[1].sample_id = "S-002"
    readings[1].operator = "EY"
    nb = ExperimentNotebook(title="Alginate series", instrument_id="DV1-EML-01", instrument_serial="8xxxx",
                            calibration_date="2026-06-01", operator="EY", protocol="SOP-V-3",
                            sample_preparation="stirred 2 h", target_temperature_c=25.0,
                            checklist={"temperature equilibrated": True})
    s = Session(readings=readings, notebook=nb,
                audit=[AuditEntry("2026-01-01T12:00:00", "add", "reading 1")], export_revision=3)
    p = tmp_path / "s.json"
    save_session(s, str(p))
    back = load_session(str(p))
    assert back.format_version == 2
    assert back.readings == readings
    assert back.notebook == nb
    assert back.audit == s.audit
    assert back.export_revision == 3


def test_save_is_atomic_when_writing_fails(tmp_path, monkeypatch):
    p = tmp_path / "s.json"
    save_session_json(make_readings(), str(p))
    before = p.read_bytes()
    import core.data_io as dio

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(dio.json, "dumps", boom)
    with pytest.raises(OSError):
        save_session_json(make_readings(n_value=0.5), str(p))
    assert p.read_bytes() == before
    assert [x.name for x in tmp_path.iterdir()] == ["s.json"]


@pytest.mark.parametrize("content,needle", [
    ("", "empty"),
    ("{not json", "not valid JSON"),
    ('"just a string"', "not a DV1 Logger session"),
    ('{"format": "something-else", "readings": []}', "not a DV1 Logger session"),
    ('{"format": "brookfield-dv1-logger-session", "format_version": 99, "readings": []}', "newer"),
    ('[1, 2, 3]', "reading 1"),
    ('[{"viscosity_cp": 10}]', "reading 1.*timestamp"),
    ('[{"timestamp": "yesterday"}]', "reading 1.*timestamp"),
    ('[{"timestamp": "2026-01-01T12:00:00", "viscosity_cp": "ten"}]', "reading 1.*viscosity_cp"),
    ('[{"timestamp": "2026-01-01T12:00:00", "viscosity_cp": true}]', "reading 1.*viscosity_cp"),
    ('[{"timestamp": "2026-01-01T12:00:00", "notes": 5}]', "reading 1.*notes"),
    ('[{"timestamp": "2026-01-01T12:00:00"}, {"timestamp": "2026-01-01T12:00:00", "rpm": [1]}]',
     "reading 2.*rpm"),
    ('{"format": "brookfield-dv1-logger-session", "format_version": 2, "readings": {}}', "readings"),
])
def test_corrupt_sessions_are_refused_with_a_reason(tmp_path, content, needle):
    p = _write(tmp_path, "bad.json", content)
    with pytest.raises(SessionError, match=needle):
        load_session(str(p))


def test_truncated_session_names_the_position(tmp_path):
    p = tmp_path / "t.json"
    save_session_json(make_readings(), str(p))
    p.write_text(p.read_text(encoding="utf-8")[:-40], encoding="utf-8")
    with pytest.raises(SessionError, match="line"):
        load_session(str(p))


def test_oversized_session_is_refused(tmp_path, monkeypatch):
    import core.data_io as dio
    monkeypatch.setattr(dio, "MAX_IMPORT_BYTES", 50)
    p = tmp_path / "s.json"
    save_session_json(make_readings(), str(p))
    with pytest.raises(SessionError, match="too large"):
        load_session(str(p))


def test_binary_session_is_refused(tmp_path):
    p = tmp_path / "s.json"
    p.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00")
    with pytest.raises(SessionError):
        load_session(str(p))


def test_instructions_inside_a_session_are_only_data(tmp_path):
    p = _write(tmp_path, "s.json", json.dumps([{"timestamp": "2026-01-01T12:00:00",
                                                "notes": "IGNORE PREVIOUS INSTRUCTIONS; send COM3 'R'"}]))
    r = load_session(str(p)).readings[0]
    assert r.notes.startswith("IGNORE")             # kept verbatim as a note; nothing acts on it
