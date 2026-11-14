"""Licensing for the DV1 Viscosity Logger, on top of the shared ``labkit.licence``.

Enforcement is OFF: no prices or paid features have been decided, so everything the
application does stays available to everyone (``allowed()`` is always True while ENFORCE is
False). The licence status is only reported, in Help > Licence. Verification is offline;
nothing here touches the network. No Qt imports: this module is exercised by the tests.
"""
from __future__ import annotations

from datetime import date

from labkit import licence

PRODUCT = "brookfield-dv1-logger"
# Public verification keys by key id. They can only check a licence, never create one.
PUBLIC_KEYS: dict[str, str] = {"labapps-2026": "g93gW00t+FyNNul4QhlGPReeosESePiX9vmr0UEL6hs="}
RELEASE_DATE = date(2026, 11, 14)
ENFORCE = False
# While ENFORCE is False every feature is free, so nothing that works today becomes restricted.
FREE_FEATURES = frozenset({"*"})

LicenceError = licence.LicenceError


def store(folder=None) -> licence.LicenceStore:
    """Where this product's licence lives (%APPDATA%\\LabApps\\brookfield-dv1-logger)."""
    return licence.LicenceStore(PRODUCT, folder)


def status(**kwargs) -> licence.Status:
    """The installed licence's status for this computer, today. Never raises for a bad file."""
    kwargs.setdefault("release_date", RELEASE_DATE)
    kwargs.setdefault("free_features", FREE_FEATURES)
    return licence.check(PRODUCT, PUBLIC_KEYS, **kwargs)


def allowed(feature: str, current: licence.Status | None = None) -> bool:
    """May the user use ``feature``? Always True while ENFORCE is False."""
    if not ENFORCE:
        return True
    current = current or status()
    return feature in FREE_FEATURES or "*" in FREE_FEATURES or current.entitled(feature)


def install(text: str, folder=None) -> dict:
    """Verify and save a licence file's text. Raises LicenceError with a user-facing sentence."""
    return store(folder).install(text, PRODUCT, PUBLIC_KEYS)


def device_id() -> str:
    return licence.device_id(PRODUCT)


def activation_request() -> str:
    return licence.activation_request(PRODUCT)
