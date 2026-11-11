"""11 Nov 2026: a rollout failed with "exceeded quota: team-quota, requested: requests.cpu=150m,
used: requests.cpu=300m, limited: requests.cpu=400m". The request must leave room inside the quota."""
import re
from pathlib import Path

MANIFEST = Path(__file__).resolve().parents[1] / "deploy" / "forge" / "app.yaml"


def test_cpu_request_fits_the_team_quota_with_room_to_spare():
    m = re.search(r"requests:\s*\{\s*cpu:\s*(\d+)m", MANIFEST.read_text())
    assert m, "app.yaml must set a CPU request"
    assert int(m.group(1)) <= 100  # quota is 400m for the whole namespace
