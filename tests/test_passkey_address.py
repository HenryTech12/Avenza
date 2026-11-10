"""Phone test through a tunnel (10 Nov): no fingerprint prompt, then "something went wrong".

The passkey settings named one address and the phone opened another; the browser refuses
before showing the prompt. Registration now says exactly what to change.
"""
from fastapi.testclient import TestClient

from avenza.config import Settings
from avenza.main import create_app, passkey_address_problem

TUNNEL = "calm-river-1234.trycloudflare.com"


def test_matching_address_is_fine():
    s = Settings().for_test(webauthn_rp_id=TUNNEL, webauthn_origin=f"https://{TUNNEL}")
    assert passkey_address_problem(s, f"https://{TUNNEL}", TUNNEL) is None
    local = Settings().for_test(webauthn_rp_id="localhost", webauthn_origin="http://localhost:8000")
    assert passkey_address_problem(local, "http://localhost:8000", "localhost:8000") is None
    assert passkey_address_problem(local, None, None) is None


def test_settings_still_on_localhost_while_using_a_tunnel():
    local = Settings().for_test(webauthn_rp_id="localhost", webauthn_origin="http://localhost:8000")
    problem = passkey_address_problem(local, f"https://{TUNNEL}", TUNNEL)
    assert f"WEBAUTHN_RP_ID={TUNNEL}" in problem and f"WEBAUTHN_ORIGIN=https://{TUNNEL}" in problem


def test_origin_written_with_a_typo():
    s = Settings().for_test(webauthn_rp_id=TUNNEL, webauthn_origin=f"http://{TUNNEL}")
    problem = passkey_address_problem(s, f"https://{TUNNEL}", TUNNEL)
    assert "not in WEBAUTHN_ORIGIN" in problem


def test_registration_explains_the_mismatch_instead_of_failing_silently():
    app = create_app(Settings().for_test(webauthn_rp_id="localhost", webauthn_origin="http://localhost:8000"))
    with TestClient(app) as client:
        r = client.post(
            "/devices/register/options",
            json={"display_name": "Ngozi"},
            headers={"origin": f"https://{TUNNEL}", "host": TUNNEL},
        )
        assert r.status_code == 400
        assert f"WEBAUTHN_RP_ID={TUNNEL}" in r.json()["detail"]
        ok = client.post("/devices/register/options", json={"display_name": "Ngozi"}, headers={"origin": "http://localhost:8000"})
        assert ok.status_code == 200
