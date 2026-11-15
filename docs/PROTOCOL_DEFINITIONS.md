# Documented protocol definitions

**Instrument → Instrument source → Documented protocol** reads lines that an instrument sends over a serial port, using a definition file that you supply. The app has no built-in protocol for any instrument.

**The DV1 is not supported.** Brookfield's DV1 Operating Instructions (M14-023-A0416) describe PC communication only through Wingather SQ, and no DV1 command reference is public. The app refuses any definition whose `name` or `instrument` names a DV1. Enabling DV1 live logging needs a code change in `core/serial_interface.py` (`DV1Protocol`), made from Brookfield's own documentation and with Brookfield's consent to use it.

## File format (JSON)

| Field | Required | Meaning |
|---|---|---|
| `name` | yes | A short name for the definition |
| `instrument` | yes | The instrument make and model |
| `document` | yes | The vendor document this definition follows (title and revision) |
| `line_pattern` | yes | A Python regular expression for one received line, using named groups from `viscosity_cp`, `percent_torque`, `temperature_c`, `rpm`. At most 400 characters |
| `document_section` | for commands | Where in the document the query command is defined |
| `authorized_by` | for commands | Who approved sending commands to this instrument |
| `allow_commands` | for commands | `true` to permit `query_command` |
| `query_command` | no | Text sent once per poll. It is sent only when all of the three fields above are set **and** you have allowed sending on the port (Instrument page → Allow sending…) |
| `line_ending` | no | Default `"\r\n"` |
| `baudrate` | no | Recorded with the definition. Set the actual port speed on the Dashboard |

Unknown fields are refused. Lines longer than 256 characters, lines that do not match, and values that are not finite numbers are ignored and counted. Readings are labelled **received from instrument (documented protocol)**.

## Template

The template below is a listen-only sketch. Every value in it is a placeholder: replace each one from your instrument's documentation before you use it.

```json
{
  "name": "REPLACE: short name",
  "instrument": "REPLACE: make and model (not a DV1)",
  "document": "REPLACE: manual title, revision",
  "line_pattern": "REPLACE-WITH-THE-DOCUMENTED-FORMAT (?P<temperature_c>-?\\d+(\\.\\d+)?)"
}
```
