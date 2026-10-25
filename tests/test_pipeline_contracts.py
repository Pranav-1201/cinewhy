"""Boundary tests — the seam where Pranav's half meets Lakshay's.

Every test here asserts something one module promises another. They are the reason the
two halves will fit together: if either side drifts from the agreed shape, one of these
goes from xfail to failing-for-a-new-reason, and CI says so before the merge.

All are `xfail(strict=True)` until their module is implemented. Delete the marker in the
same PR that implements the function — an XPASS fails the suite, so a forgotten marker
cannot go unnoticed.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from cinewhy.absa import build_profile, detect_aspects, split_sentences
from cinewhy.artifacts.manifest import ManifestMismatchError, build, hash_file, verify
from cinewhy.schemas import Aspect, MovieAspectProfile, RecommendRequest, TasteProfile
from cinewhy.text import normalise, strip_html
from tests.conftest import KeywordScorer

pytestmark = pytest.mark.contract


class TestTextBoundary:
    """`cinewhy.text` is imported by BOTH the training job and the request path.

    Train/serve skew is the classic way two correct halves produce a broken whole. There
    must be exactly one definition of normalisation, and both sides must import it from
    here (audit idea B-7).
    """

    def test_serving_and_training_import_the_same_symbol(self) -> None:
        """Guard against a second copy of the cleaning logic appearing elsewhere."""
        from cinewhy.text import normalise as serving_path
        from cinewhy.text import preprocess as training_path

        assert serving_path is training_path.normalise

    def test_strip_html_removes_br_tags(self) -> None:
        """29,200 of the 50,000 source rows contain a literal '<br'."""
        assert strip_html("Great film.<br /><br />Loved it.") == "Great film.Loved it."

    def test_normalise_is_pure(self) -> None:
        """Calling twice on the same input returns the same output.

        The original notebook mutated its dataframe through six sequential steps, so
        re-running one cell silently double-stemmed the corpus (FLOW.md §1).
        """
        text = "A perfectly ordinary sentence."
        assert normalise(text) == normalise(text)

    def test_normalise_returns_a_string_not_a_token_list(self) -> None:
        """Vectorisers take strings. The boundary type is `str`, not `list[str]`."""
        assert isinstance(normalise("Some review text."), str)


class TestAbsaBoundary:
    """`cinewhy.absa` produces what `cinewhy.recsys` and `api` consume."""

    def test_split_sentences_never_returns_empty_for_real_input(self) -> None:
        assert split_sentences("The pacing dragged. The ending saved it.")

    def test_detect_aspects_may_return_nothing(self) -> None:
        """Most sentences belong to no aspect; that is the correct answer, not a bug."""
        assert detect_aspects("I watched this on a Tuesday.") == frozenset()

    def test_detect_aspects_returns_known_members_only(self) -> None:
        result = detect_aspects("The soundtrack was extraordinary.")
        assert result <= frozenset(Aspect)

    def test_build_profile_returns_the_contract_type(self, keyword_scorer: KeywordScorer) -> None:
        profile, evidence = build_profile(
            "cw-1", [("rv-1", "The pacing is superb.")], model=keyword_scorer
        )
        assert isinstance(profile, MovieAspectProfile)
        assert all(e.aspect in Aspect for e in evidence)

    def test_build_profile_drops_aspects_below_min_support(
        self, keyword_scorer: KeywordScorer
    ) -> None:
        """A score from one sentence must not render identically to one from four hundred."""
        profile, _ = build_profile(
            "cw-1", [("rv-1", "Nice pacing.")], min_support=10, model=keyword_scorer
        )
        assert profile.scores == ()


class TestApiBoundary:
    """Request/response shapes the frontend codes against.

    Phase F can build the whole "Why this?" panel against these types before Phase E's
    server exists — that is what lets the two run in parallel.
    """

    def test_recommend_request_defaults_are_stable(self, cold_profile: TasteProfile) -> None:
        """The frontend relies on these defaults; changing one is a contract change."""
        req = RecommendRequest(profile=cold_profile)
        assert req.limit == 20
        assert req.exclude_movie_ids == ()

    def test_recommend_request_rejects_unknown_fields(self, cold_profile: TasteProfile) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            RecommendRequest(profile=cold_profile, offset=10)  # type: ignore[call-arg]

    @pytest.mark.usefixtures("loaded_api")
    def test_cold_start_returns_fallback_items_not_an_error(
        self, cold_profile: TasteProfile
    ) -> None:
        """An unknown viewer gets popular films honestly labelled, never a 4xx."""
        from api.main import recommend

        response = recommend(RecommendRequest(profile=cold_profile))
        assert response.cold_start is True
        assert all(item.is_fallback for item in response.items)

    @pytest.mark.usefixtures("loaded_api")
    def test_recommendations_are_deterministic(self, warm_profile: TasteProfile) -> None:
        """The same profile returns the same ordering; a reshuffling list loses trust."""
        from api.main import recommend

        req = RecommendRequest(profile=warm_profile)
        first = [item.movie.movie_id for item in recommend(req).items]
        second = [item.movie.movie_id for item in recommend(req).items]
        assert first == second

    @pytest.mark.usefixtures("loaded_api")
    def test_health_reports_the_manifest_hash(self) -> None:
        """'ok' alone cannot distinguish a good server from one on stale artifacts."""
        from api.main import health

        assert health()["manifest"]


class TestArtifactBoundary:
    """Artifacts are immutable and verified; the API refuses to boot on a mismatch."""

    def test_verify_raises_on_hash_mismatch(self, tmp_path: Path) -> None:
        """Corrupting one byte must stop the boot, not degrade the results."""
        (tmp_path / "scores.json").write_bytes(b'{"a": 1}')
        manifest = build(tmp_path)
        verify(tmp_path, manifest)  # untouched artifacts verify cleanly
        (tmp_path / "scores.json").write_bytes(b'{"a": 2}')
        with pytest.raises(ManifestMismatchError):
            verify(tmp_path, manifest)

    def test_verify_raises_on_missing_file(self, tmp_path: Path) -> None:
        (tmp_path / "scores.json").write_bytes(b"{}")
        manifest = build(tmp_path)
        (tmp_path / "scores.json").unlink()
        with pytest.raises(ManifestMismatchError):
            verify(tmp_path, manifest)

    def test_verify_raises_when_manifest_itself_was_edited(self, tmp_path: Path) -> None:
        """Editing a file hash inside the manifest must not let a swapped file through."""
        (tmp_path / "scores.json").write_bytes(b"{}")
        manifest = build(tmp_path)
        forged = manifest.model_copy(update={"files": {"scores.json": "0" * 64}})
        with pytest.raises(ManifestMismatchError):
            verify(tmp_path, forged)

    def test_hash_is_stable_across_line_endings(self, tmp_path: Path) -> None:
        """Hash bytes, never text.

        A text-mode read on Windows rewrites CRLF to LF, so the same file would hash
        differently here and on a Linux CI runner. The hash of a CRLF file must equal the
        digest of its exact bytes.
        """
        path = tmp_path / "crlf.txt"
        path.write_bytes(b"a\r\nb\r\n")
        assert hash_file(path) == hashlib.sha256(b"a\r\nb\r\n").hexdigest()
