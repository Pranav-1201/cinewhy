"""The HTTP layer: boot verification, routes, error policy and abuse limits.

Runs against the six-film artifact set from `conftest.artifact_dir` with a toy polarity model,
so these tests check wiring and policy, never model quality.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from cinewhy.artifacts.manifest import ManifestMismatchError


@pytest.fixture
def client(artifact_dir: Path) -> Iterator[TestClient]:
    app = api_main.create_app(artifact_dir)
    with TestClient(app) as test_client:  # `with` runs the lifespan, i.e. boot verification
        yield test_client
    api_main._state = None


class TestBoot:
    def test_boot_refuses_a_tampered_artifact(self, artifact_dir: Path) -> None:
        (artifact_dir / "profiles.json").write_text("{}", encoding="utf-8")
        with pytest.raises(ManifestMismatchError), TestClient(api_main.create_app(artifact_dir)):
            pass

    def test_boot_refuses_a_missing_manifest(self, tmp_path: Path) -> None:
        with pytest.raises(ManifestMismatchError), TestClient(api_main.create_app(tmp_path)):
            pass

    def test_calling_before_load_is_a_clear_error(self) -> None:
        api_main._state = None
        with pytest.raises(RuntimeError, match="not loaded"):
            api_main.health()


class TestRoutes:
    def test_health_reports_the_manifest_hash(self, client: TestClient) -> None:
        body = client.get("/health").json()
        assert body["status"] == "ok" and len(body["manifest"]) == 64

    def test_search_finds_by_title_prefix(self, client: TestClient) -> None:
        assert [m["title"] for m in client.get("/search", params={"q": "alp"}).json()] == ["Alpha"]

    def test_search_limit_is_clamped(self, client: TestClient) -> None:
        assert len(client.get("/search", params={"q": "a", "limit": 100000}).json()) <= 50
        assert client.get("/search", params={"q": "a", "limit": -5}).status_code == 200

    def test_movie_page_has_aspects_with_quotes(self, client: TestClient) -> None:
        body = client.get("/movie/cw-1").json()
        assert body["movie"]["title"] == "Alpha"
        assert {a["aspect"] for a in body["aspects"]} == {"pacing", "ending"}
        assert all(a["evidence"] for a in body["aspects"])

    def test_unknown_movie_is_a_bare_404(self, client: TestClient) -> None:
        response = client.get("/movie/nope")
        assert response.status_code == 404 and response.json() == {"detail": "not found"}

    def test_recommend_cold_start(self, client: TestClient) -> None:
        body = client.post("/recommend", json={"profile": {}}).json()
        assert body["cold_start"] is True and all(i["is_fallback"] for i in body["items"])

    def test_recommend_personalised_carries_reasons(self, client: TestClient) -> None:
        body = client.post(
            "/recommend", json={"profile": {"aspect_weights": {"pacing": 1.0}}}
        ).json()
        assert body["cold_start"] is False
        assert body["items"] and all(i["reasons"] for i in body["items"])

    def test_aspects_endpoint_covers_every_aspect(self, client: TestClient) -> None:
        assert len(client.get("/aspects").json()) == 7

    def test_metrics_serves_the_eval_file(self, client: TestClient) -> None:
        assert client.get("/metrics").json()["catalogue"]["films"] == 6


class TestAnalyze:
    def test_splits_a_review_into_aspect_mentions(self, client: TestClient) -> None:
        text = "The acting was great but the pacing was dull and boring."
        body = client.post("/analyze", json={"text": text}).json()
        found = {
            m["aspect"] for s in body["sentences"] for c in s["clauses"] for m in c["mentions"]
        }
        assert found == {"acting", "pacing"}
        assert {s["aspect"] for s in body["summary"]} <= found

    def test_every_clause_is_verbatim_from_the_input(self, client: TestClient) -> None:
        text = "Superb acting, however the plot was awful; the ending was fine."
        body = client.post("/analyze", json={"text": text}).json()
        assert all(c["text"] in text for s in body["sentences"] for c in s["clauses"])

    def test_empty_and_oversized_text_are_rejected(self, client: TestClient) -> None:
        assert client.post("/analyze", json={"text": ""}).status_code == 422
        assert client.post("/analyze", json={"text": "x" * 5001}).status_code == 422


class TestPolicy:
    def test_unknown_fields_are_rejected(self, client: TestClient) -> None:
        assert client.post("/recommend", json={"profile": {}, "offset": 3}).status_code == 422

    def test_oversized_body_is_refused_before_parsing(self, client: TestClient) -> None:
        big = {"profile": {"liked_movie_ids": ["cw-1"] * 20000}}
        assert client.post("/recommend", json=big).status_code == 413

    def test_security_headers_are_set(self, client: TestClient) -> None:
        headers = client.get("/health").headers
        assert headers["x-content-type-options"] == "nosniff"
        assert "frame-ancestors 'none'" in headers["content-security-policy"]

    def test_post_rate_limit_returns_429(self, artifact_dir: Path) -> None:
        with TestClient(api_main.create_app(artifact_dir, rate_limit=3)) as limited:
            codes = [limited.post("/recommend", json={"profile": {}}).status_code for _ in range(5)]
        api_main._state = None
        assert codes == [200, 200, 200, 429, 429]

    def test_unhandled_errors_return_an_opaque_id_and_no_detail(
        self, artifact_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(_request: object) -> object:
            raise ValueError("secret internal path C:/Users/x/y")

        monkeypatch.setattr(api_main, "recommend", boom)
        app = api_main.create_app(artifact_dir)
        with TestClient(app, raise_server_exceptions=False) as test_client:
            response = test_client.post("/recommend", json={"profile": {}})
        api_main._state = None
        assert response.status_code == 500
        assert set(response.json()) == {"error_id"}
        assert "secret" not in response.text and "Users" not in response.text


class TestRateLimiter:
    def test_window_slides(self) -> None:
        limiter = api_main._RateLimiter(2, 10.0)
        assert limiter.allow("a", now=0.0) and limiter.allow("a", now=1.0)
        assert not limiter.allow("a", now=2.0)
        assert limiter.allow("a", now=11.5)  # the first hit has aged out
        assert limiter.allow("b", now=2.0)  # another client has its own budget
