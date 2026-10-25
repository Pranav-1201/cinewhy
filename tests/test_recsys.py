"""Collaborative filtering, ranking, catalogue I/O and the offline evaluation protocol.

Expected values are derived by hand from small planted structures (two taste clusters, a
six-film catalogue), so a wrong result shows up as a wrong ordering, not a vague "looks
plausible".
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest

import cinewhy.recsys.evaluate as evaluate_module
from cinewhy.recsys.catalogue import Catalogue, aspect_order, load_catalogue, write_catalogue
from cinewhy.recsys.cf import bayesian_popularity, build_item_similarity
from cinewhy.recsys.evaluate import evaluate_recommenders
from cinewhy.recsys.rank import infer_weights, popular, recommend, search
from cinewhy.schemas import Aspect, RecommendRequest, TasteProfile
from tests.conftest import make_catalogue

_catalogue = make_catalogue  # the shared six-film catalogue, defined in conftest.py


class TestItemSimilarity:
    @staticmethod
    def _clusters() -> tuple[npt.NDArray[np.int32], npt.NDArray[np.int32], npt.NDArray[np.float32]]:
        """Users 0-9 love items 0-2 and dislike 3-5; users 10-19 the reverse."""
        users, items, ratings = [], [], []
        for u in range(20):
            loves = (0, 1, 2) if u < 10 else (3, 4, 5)
            for i in range(6):
                users.append(u)
                items.append(i)
                ratings.append(5.0 if i in loves else 1.0)
        return (
            np.array(users, dtype=np.int32),
            np.array(items, dtype=np.int32),
            np.array(ratings, dtype=np.float32),
        )

    def test_items_liked_together_are_similar_and_opposed_items_are_not(self) -> None:
        sim = build_item_similarity(*self._clusters(), 6, shrink=0.0)
        assert sim[0, 1] > 0.9
        assert sim[0, 3] < -0.9

    def test_diagonal_is_zero_and_matrix_is_symmetric(self) -> None:
        sim = build_item_similarity(*self._clusters(), 6)
        assert np.all(np.diag(sim) == 0.0)
        assert np.allclose(sim, sim.T)

    def test_shrinkage_pulls_similarity_toward_zero(self) -> None:
        loose = build_item_similarity(*self._clusters(), 6, shrink=0.0)
        tight = build_item_similarity(*self._clusters(), 6, shrink=100.0)
        assert 0 < tight[0, 1] < loose[0, 1]

    def test_users_below_the_rating_floor_contribute_nothing(self) -> None:
        users, items, ratings = self._clusters()
        base = build_item_similarity(users, items, ratings, 6)
        # One extra user with two ratings that would link item 0 to item 3 if they counted.
        users2 = np.append(users, [99, 99]).astype(np.int32)
        items2 = np.append(items, [0, 3]).astype(np.int32)
        ratings2 = np.append(ratings, [5.0, 5.0]).astype(np.float32)
        assert np.allclose(build_item_similarity(users2, items2, ratings2, 6), base)


class TestPopularity:
    def test_one_perfect_rating_does_not_beat_many_good_ones(self) -> None:
        # Film 2 drags the global mean to (5 + 450 + 200) / 201 = 3.26, so film 0's prior-pulled
        # mean is (5 + 25 * 3.26) / 26 = 3.35 while film 1 stays near 4.25.
        items = np.array([0] + [1] * 100 + [2] * 100, dtype=np.int32)
        ratings = np.array([5.0] + [4.5] * 100 + [2.0] * 100, dtype=np.float32)
        mean, counts = bayesian_popularity(items, ratings, 4)
        assert mean[1] > mean[0] > mean[2]
        assert counts.tolist() == [1, 100, 100, 0]

    def test_unrated_item_gets_the_global_mean(self) -> None:
        items = np.array([0, 0], dtype=np.int32)
        ratings = np.array([4.0, 2.0], dtype=np.float32)
        mean, _ = bayesian_popularity(items, ratings, 2)
        assert mean[1] == pytest.approx(3.0)


class TestRecommend:
    def test_cold_start_is_the_popularity_fallback(self) -> None:
        cat = _catalogue()
        response = recommend(cat, RecommendRequest(profile=TasteProfile()), "m")
        assert response.cold_start is True
        assert [r.movie.movie_id for r in response.items] == [
            "cw-5", "cw-3", "cw-1", "cw-2", "cw-6", "cw-4",
        ]  # fmt: skip
        assert all(r.is_fallback and not r.reasons for r in response.items)

    def test_aspect_weights_only_return_films_that_can_be_explained(self) -> None:
        cat = _catalogue()
        profile = TasteProfile(aspect_weights={Aspect.PACING: 1.0})
        response = recommend(cat, RecommendRequest(profile=profile), "m")
        assert response.cold_start is False
        # cw-4's pacing is negative, cw-3/cw-5 have no pacing evidence: none may appear.
        assert {r.movie.movie_id for r in response.items} == {"cw-1", "cw-2", "cw-6"}
        assert all(r.reasons for r in response.items)

    def test_every_reason_quotes_catalogue_evidence_for_its_own_aspect(self) -> None:
        cat = _catalogue()
        profile = TasteProfile(aspect_weights={Aspect.PACING: 1.0, Aspect.ENDING: 0.5})
        for rec in recommend(cat, RecommendRequest(profile=profile), "m").items:
            for reason in rec.reasons:
                stored = cat.evidence[rec.movie.movie_id][reason.aspect]
                assert set(reason.evidence) <= set(stored)
                assert {e.aspect for e in reason.evidence} == {reason.aspect}

    def test_liked_film_is_excluded_and_its_nearest_neighbour_leads(self) -> None:
        cat = _catalogue()
        profile = TasteProfile(liked_movie_ids=("cw-1",))
        items = recommend(cat, RecommendRequest(profile=profile), "m").items
        assert "cw-1" not in {r.movie.movie_id for r in items}
        assert items[0].movie.movie_id == "cw-2"

    def test_disliked_and_explicitly_excluded_films_never_appear(self) -> None:
        cat = _catalogue()
        profile = TasteProfile(aspect_weights={Aspect.PACING: 1.0}, disliked_movie_ids=("cw-1",))
        request = RecommendRequest(profile=profile, exclude_movie_ids=("cw-2",))
        ids = {r.movie.movie_id for r in recommend(cat, request, "m").items}
        assert ids == {"cw-6"}

    def test_limit_is_respected(self) -> None:
        cat = _catalogue()
        profile = TasteProfile(aspect_weights={Aspect.PACING: 1.0})
        assert len(recommend(cat, RecommendRequest(profile=profile, limit=2), "m").items) == 2

    def test_same_request_gives_the_same_answer(self) -> None:
        cat = _catalogue()
        request = RecommendRequest(
            profile=TasteProfile(aspect_weights={Aspect.PACING: 0.9}, liked_movie_ids=("cw-3",))
        )
        assert recommend(cat, request, "m") == recommend(cat, request, "m")

    def test_unknown_liked_ids_alone_are_treated_as_cold_start(self) -> None:
        cat = _catalogue()
        profile = TasteProfile(liked_movie_ids=("cw-does-not-exist",))
        response = recommend(cat, RecommendRequest(profile=profile), "m")
        assert response.items and all(r.is_fallback for r in response.items)

    def test_nothing_to_infer_still_explains_with_highlights_not_a_silent_fallback(self) -> None:
        """Liking a film with no positive aspect must not dump the viewer on the popular list."""
        profile = TasteProfile(liked_movie_ids=("cw-5",))
        response = recommend(_catalogue(), RecommendRequest(profile=profile), "m")
        assert response.cold_start is False
        assert response.items and not any(i.is_fallback for i in response.items)
        assert all(r.user_weight == 0.0 for i in response.items for r in i.reasons)

    def test_manifest_is_echoed(self) -> None:
        response = recommend(_catalogue(), RecommendRequest(profile=TasteProfile()), "abc123")
        assert response.manifest == "abc123"

    def test_popular_respects_exclusions(self) -> None:
        picked = popular(_catalogue(), {"cw-5"}, 2)
        assert [r.movie.movie_id for r in picked] == ["cw-3", "cw-1"]


class TestInferWeights:
    def test_strongest_aspect_is_one_and_weak_ones_are_dropped(self) -> None:
        cat = _catalogue()
        weights = infer_weights(cat, ("cw-1",))
        assert weights[Aspect.PACING] == pytest.approx(1.0)
        assert weights[Aspect.ENDING] == pytest.approx(0.75)
        assert Aspect.SOUNDTRACK not in weights

    def test_negative_scores_never_become_weights(self) -> None:
        assert Aspect.PACING not in infer_weights(_catalogue(), ("cw-4",))

    def test_nothing_to_infer_from_a_film_without_aspects(self) -> None:
        assert infer_weights(_catalogue(), ("cw-5",)) == {}
        assert infer_weights(_catalogue(), ()) == {}


class TestSearch:
    def test_prefix_beats_word_start_beats_substring(self) -> None:
        cat = _catalogue(("Animatrix", "The Matrix", "Matrix Reloaded", "X", "Y", "Z"))
        assert [m.title for m in search(cat, "matrix")] == [
            "Matrix Reloaded", "The Matrix", "Animatrix",
        ]  # fmt: skip

    def test_blank_query_returns_nothing(self) -> None:
        assert search(_catalogue(), "   ") == []

    def test_query_is_literal_not_a_pattern(self) -> None:
        assert search(_catalogue(), ".*") == []


class TestCatalogueIO:
    def test_write_then_load_round_trips(self, tmp_path: Path) -> None:
        cat = _catalogue()
        write_catalogue(tmp_path, cat)
        loaded = load_catalogue(tmp_path)
        assert loaded.movies == cat.movies
        assert loaded.stats == cat.stats
        assert loaded.profiles == cat.profiles
        assert loaded.evidence == cat.evidence
        assert np.array_equal(loaded.similarity, cat.similarity)

    def test_wrong_similarity_shape_is_rejected(self) -> None:
        cat = _catalogue()
        with pytest.raises(ValueError, match="similarity"):
            Catalogue(
                cat.movies, cat.stats, cat.profiles, cat.evidence, np.zeros((2, 2), np.float32)
            )

    def test_shrunk_matrix_follows_the_support_formula(self) -> None:
        cat = _catalogue()
        # 0.9 * 2 / (2 + 5) for cw-6 pacing, 0.8 * 20 / 25 for cw-1 pacing
        assert cat.shrunk("cw-6", Aspect.PACING) == pytest.approx(0.9 * 2 / 7)
        assert cat.shrunk("cw-1", Aspect.PACING) == pytest.approx(0.64)
        assert cat.shrunk("cw-5", Aspect.PACING) == 0.0
        assert len(aspect_order()) == cat.aspect_matrix.shape[1]


class TestEvaluationProtocol:
    @staticmethod
    def _planted() -> tuple[npt.NDArray[np.int32], npt.NDArray[np.int32], npt.NDArray[np.float32]]:
        """60 items in two halves; each user loves 15 of their half and hates 5 of the other."""
        rng = np.random.default_rng(0)
        users, items, ratings = [], [], []
        for u in range(600):
            own, other = (0, 30) if u % 2 == 0 else (30, 0)
            for base, count, stars in ((own, 15, 5.0), (other, 5, 1.5)):
                for i in rng.choice(30, count, replace=False):
                    users.append(u)
                    items.append(base + int(i))
                    ratings.append(stars)
        return (
            np.array(users, dtype=np.int32),
            np.array(items, dtype=np.int32),
            np.array(ratings, dtype=np.float32),
        )

    def test_collaborative_filtering_significantly_beats_popularity_on_planted_clusters(
        self,
    ) -> None:
        report, _ = evaluate_recommenders(
            *self._planted(),
            60,
            np.zeros((60, len(aspect_order())), dtype=np.float32),
            min_likes=5,
            n_seeds=3,
            max_eval_users=150,
        )
        by_name = {m.name: m for m in report.methods}
        assert by_name["cf"].hit_rate[10].mean > by_name["popularity"].hit_rate[10].mean
        gap = next(d for d in report.differences if (d.a, d.b, d.k) == ("cf", "popularity", 10))
        assert gap.significant and gap.diff.lo > 0

    def test_held_out_users_never_reach_the_similarity_fit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[set[int]] = []
        real = build_item_similarity

        def spy(
            users: npt.NDArray[np.int32],
            items: npt.NDArray[np.int32],
            ratings: npt.NDArray[np.float32],
            n_items: int,
            *,
            shrink: float = 50.0,
        ) -> npt.NDArray[np.float32]:
            seen.append({int(u) for u in np.unique(users)})
            return real(users, items, ratings, n_items, shrink=shrink)

        monkeypatch.setattr(evaluate_module, "build_item_similarity", spy)
        data = self._planted()
        report, _ = evaluate_recommenders(
            *data,
            60,
            np.zeros((60, len(aspect_order())), dtype=np.float32),
            min_likes=5,
            n_seeds=3,
            max_eval_users=100,
        )
        all_users = {int(u) for u in np.unique(data[0])}
        assert seen, "similarity was never built"
        for fitted_on in seen:
            assert len(fitted_on) == report.n_train_users
            assert len(all_users - fitted_on) >= report.n_test_users  # test users were withheld

    def test_chosen_shrink_comes_from_the_candidates(self) -> None:
        report, chosen = evaluate_recommenders(
            *self._planted(),
            60,
            np.zeros((60, len(aspect_order())), dtype=np.float32),
            min_likes=5,
            n_seeds=3,
            max_eval_users=100,
            shrinks=(5.0, 20.0),
        )
        assert chosen in (5.0, 20.0) and report.chosen_shrink == chosen
