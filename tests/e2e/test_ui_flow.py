"""End-to-end UI flow (needs the API on :8000 and an ingested 'otel' graph). Run: pytest tests/e2e -q"""
import os
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")
import httpx  # noqa: E402

BASE = os.getenv("BLAST_URL", "http://localhost:8000")
SHOTS = Path(os.getenv("SHOTS_DIR") or __import__("tempfile").gettempdir()) / "blast_shots"


def _up():
    try:
        return httpx.get(f"{BASE}/api/health", timeout=3).status_code == 200 and "otel" in httpx.get(f"{BASE}/api/health").json()["graphs"]
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _up(), reason="API with otel graph not running")


def test_demo_scenario_end_to_end():
    SHOTS.mkdir(exist_ok=True)
    errors = []
    with playwright.sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1440, "height": 860})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(BASE)
        page.wait_for_selector("#heroGo")
        page.screenshot(path=str(SHOTS / "1-hero.png"))
        page.click("#heroGo")
        page.wait_for_selector(".claim", timeout=30000)
        page.wait_for_timeout(3500)
        page.screenshot(path=str(SHOTS / "2-answer.png"))
        assert page.locator(".claim").count() >= 3
        assert int(page.inner_text("#tQ")) > 5
        page.click(".claim >> nth=1")
        page.wait_for_timeout(900)
        page.screenshot(path=str(SHOTS / "3-claim-path.png"))
        page.click("button[data-tab=hood]")
        assert page.locator("pre.cy").count() > 5
        assert "MATCH" in page.inner_text("pre.cy >> nth=0")
        page.screenshot(path=str(SHOTS / "4-hood.png"))
        page.click("#btnSchema")
        page.wait_for_timeout(1500)
        page.screenshot(path=str(SHOTS / "5-schema.png"))
        b.close()
    assert not errors, errors


def test_bad_input_graceful():
    r = httpx.post(f"{BASE}/api/investigate", json={"input": "   "})
    assert r.status_code == 400
    r = httpx.post(f"{BASE}/api/investigate", json={"input": "x" * 30000})
    assert r.status_code == 413
    r = httpx.post(f"{BASE}/api/investigate", json={"input": "x", "graph": "nope"})
    assert r.status_code == 404
