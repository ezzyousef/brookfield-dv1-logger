"""Licensing: reported only, never enforced, and nothing the app does becomes restricted.

Licences here are signed with a throwaway key generated in the test; the real private key is
never used.
"""
from __future__ import annotations

import secrets
import sys
from datetime import date
from pathlib import Path

import pytest

from core import licensing
from labkit import licence

LABKIT_REPO = Path(r"E:\Lab Apps\labkit")


@pytest.fixture(scope="module")
def issuer():
    if not (LABKIT_REPO / "labkit_issuer" / "issuer.py").exists():
        pytest.skip("labkit repository (with labkit_issuer) is not available")
    # labkit (vendored) is already imported, so the issuer reuses the same labkit.licence.
    before = list(sys.path)
    sys.path.append(str(LABKIT_REPO))
    try:
        from labkit_issuer import issuer as mod
    finally:
        sys.path[:] = before
    return mod


@pytest.fixture
def test_key(monkeypatch, issuer):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(licensing, "PUBLIC_KEYS", {"test-key": issuer.public_b64(key)})
    return key


def _claims(product=licensing.PRODUCT, device=None):
    return {"product": product, "edition": "pro", "kind": "commercial", "serial": "DV1-TEST-1",
            "lid": secrets.token_hex(16), "issued": date.today().isoformat(),
            "organisation": "Test Lab", "device": device or licensing.device_id()}


def test_constants():
    assert licensing.PRODUCT == "brookfield-dv1-logger"
    assert licensing.ENFORCE is False
    assert licensing.RELEASE_DATE == date(2026, 11, 14)
    assert "*" in licensing.FREE_FEATURES


def test_no_licence_reports_but_allows_everything(tmp_path):
    st = licensing.status(store=licensing.store(tmp_path))
    assert not st.ok
    assert st.reason == "No licence installed."
    assert st.can_save
    for feature in ("origin-export", "excel-export", "serial", "anything-at-all"):
        assert licensing.allowed(feature)
        assert licensing.allowed(feature, st)


def test_test_key_licence_installs_and_verifies(tmp_path, test_key, issuer):
    text = issuer.make_licence(test_key, "test-key", _claims())
    claims = licensing.install(text, tmp_path)
    assert claims["product"] == licensing.PRODUCT
    assert (tmp_path / "licence.json").exists()
    st = licensing.status(store=licensing.store(tmp_path))
    assert st.ok, st.reason
    assert st.edition == "pro"
    assert licensing.allowed("anything")


def test_licence_for_another_product_is_refused(tmp_path, test_key, issuer):
    text = issuer.make_licence(test_key, "test-key", _claims(product="figure-studio"))
    with pytest.raises(licence.LicenceError, match="figure-studio"):
        licensing.install(text, tmp_path)
    assert not (tmp_path / "licence.json").exists()


def test_real_keys_reject_a_test_signed_licence(tmp_path, issuer):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    text = issuer.make_licence(Ed25519PrivateKey.generate(), "labapps-2026", _claims())
    with pytest.raises(licence.LicenceError):
        licensing.install(text, tmp_path)


def test_dialog_shows_device_id_offscreen(qapp, tmp_path):
    from ui.licence_dialog import LicenceDialog
    dlg = LicenceDialog(folder=tmp_path)
    try:
        assert dlg.device.text() == licensing.device_id()
        assert licence.DEVICE_RE.match(dlg.device.text())
        assert dlg.device.isReadOnly()
        assert "No licence installed." in dlg.status_label.text()
        assert dlg.copy_button.text() and dlg.install_button.text() and dlg.close_button.text()
        dlg.copy_request()
        assert qapp.clipboard().text().startswith("REQ-")
    finally:
        dlg.close()


def test_dialog_installs_a_file_and_reports_errors(qapp, tmp_path, test_key, issuer):
    from ui.licence_dialog import LicenceDialog
    store_dir = tmp_path / "store"
    dlg = LicenceDialog(folder=store_dir)
    try:
        bad = tmp_path / "bad.json"
        bad.write_text("{}", encoding="utf-8")
        assert not dlg.install_file(bad)
        assert "not a licence" in dlg.message.text()
        good = tmp_path / "good.json"
        good.write_text(issuer.make_licence(test_key, "test-key", _claims()), encoding="utf-8")
        assert dlg.install_file(good)
        assert dlg.current.ok
        assert "Licensed" in dlg.status_label.text()
    finally:
        dlg.close()


def test_help_menu_has_licence_entry(window):
    from PySide6.QtGui import QAction
    labels = [a.text() for a in window.findChildren(QAction)]
    assert "&Licence…" in labels
