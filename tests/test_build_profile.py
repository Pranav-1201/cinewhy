"""Behaviour of clause splitting and per-film aspect aggregation.

Expected numbers are derived by hand from `KeywordScorer` (+0.9 / -0.9 / 0.0), so a wrong
mean, support or evidence choice is visible as a wrong integer, not a vague "looks fine".
"""

from __future__ import annotations

import pytest

import cinewhy.absa.extract as extract_module
from cinewhy.absa.extract import build_profile, split_clauses
from cinewhy.schemas import Aspect
from tests.conftest import KeywordScorer


class TestSplitClauses:
    def test_splits_at_a_contrast_marker(self) -> None:
        sentence = "The acting was brilliant but the plot was dull and tedious."
        assert split_clauses(sentence) == [
            "The acting was brilliant",
            "the plot was dull and tedious.",
        ]

    def test_every_clause_is_a_verbatim_substring(self) -> None:
        sentence = "Great soundtrack, however the pacing dragged badly; the ending was fine."
        assert all(clause in sentence for clause in split_clauses(sentence))

    def test_does_not_split_when_a_side_is_too_short(self) -> None:
        assert split_clauses("Good, but.") == ["Good, but."]

    def test_a_sentence_without_a_marker_is_one_clause(self) -> None:
        assert split_clauses("The pacing was slow.") == ["The pacing was slow."]

    def test_while_is_not_a_contrast_marker(self) -> None:
        sentence = "I was bored while watching the slow second act."
        assert split_clauses(sentence) == [sentence]

    # Two statements joined by "and" or a comma, each about its own aspect, used to share one
    # score: "The acting was great and the plot was dull" scored the ACTING negative.
    def test_splits_two_statements_about_different_aspects_joined_by_and(self) -> None:
        assert split_clauses("The acting was great and the plot was dull.") == [
            "The acting was great",
            "the plot was dull.",
        ]

    def test_splits_a_run_of_statements_joined_by_commas_and_and(self) -> None:
        sentence = "The acting was superb, the plot was dull, and the ending was terrible."
        assert split_clauses(sentence) == [
            "The acting was superb",
            "the plot was dull",
            "the ending was terrible.",
        ]

    def test_a_list_sharing_one_verb_is_not_split(self) -> None:
        # Splitting would leave "The acting, the plot" with no opinion at all.
        sentence = "The acting, the plot and the pacing were all great."
        assert split_clauses(sentence) == [sentence]

    def test_a_verb_before_the_aspect_does_not_make_a_list_into_statements(self) -> None:
        # Found by reading real reviews: "posted" belongs to an earlier clause, and cutting before
        # ", the acting" left "...that the plot" scored as positive ("I agree") while the list is
        # all about being bad. The verb of a statement must come AFTER its aspect.
        sentence = (
            "I agree with the others who posted that the plot, the acting and the scenery were bad."
        )
        assert split_clauses(sentence) == [sentence]

    def test_a_side_of_fewer_than_three_words_is_not_split_off(self) -> None:
        # The contrast rule keeps "Good, but." whole; the "and" rule follows the same minimum.
        sentence = "Plot dragged and the pacing was slow."
        assert split_clauses(sentence) == [sentence]

    def test_a_new_subject_must_be_a_determiner_or_pronoun(self) -> None:
        # Deliberately narrow (see _JOIN): a bare noun subject is left whole, not guessed at.
        sentence = "The acting was great and special effects were awful."
        assert split_clauses(sentence) == [sentence]
        assert split_clauses("The acting was great and it was shot beautifully.") == [
            "The acting was great and it was shot beautifully."
        ]  # no aspect after the join

    def test_a_verb_that_ends_in_ed_counts_as_a_verb(self) -> None:
        assert split_clauses("The acting impressed me and the plot bored me.") == [
            "The acting impressed me",
            "the plot bored me.",
        ]

    def test_and_so_was_is_not_a_new_statement(self) -> None:
        sentence = "The acting was great and so was the plot."
        assert split_clauses(sentence) == [sentence]

    def test_a_side_with_no_aspect_is_not_split_off(self) -> None:
        sentence = "The acting was great and the weather was nice."
        assert split_clauses(sentence) == [sentence]

    def test_a_side_with_no_verb_is_not_split_off(self) -> None:
        sentence = "The acting was great and the plot a mess."
        assert split_clauses(sentence) == [sentence]

    def test_and_between_two_adjectives_is_not_a_split(self) -> None:
        sentence = "The plot was dull and tedious."
        assert split_clauses(sentence) == [sentence]

    def test_a_split_after_and_also_works_alongside_a_contrast_split(self) -> None:
        sentence = "The acting was great and the plot was dull but the ending was superb."
        assert split_clauses(sentence) == [
            "The acting was great",
            "the plot was dull",
            "the ending was superb.",
        ]

    def test_every_clause_stays_a_verbatim_substring_after_the_new_splits(self) -> None:
        sentence = "The acting was superb, the plot was dull, and the ending was terrible."
        assert all(clause in sentence for clause in split_clauses(sentence))

    def test_a_negated_verb_counts_as_a_statement(self) -> None:
        sentence = "The acting wasn't good and the plot didn't work."
        assert split_clauses(sentence) == ["The acting wasn't good", "the plot didn't work."]

    def test_the_candidates_examined_in_one_span_are_bounded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No piece here is ever a statement, so no cut is made and the left side keeps growing:
        # the shape that made the splitter quadratic on crafted input. 140 candidates, under the
        # character limit, must cost at most `_MAX_JOINS` looks, not 140.
        calls: list[str] = []
        real = extract_module._is_statement

        def counting(piece: str) -> bool:
            calls.append(piece)
            return real(piece)

        monkeypatch.setattr(extract_module, "_is_statement", counting)
        sentence = ("x, the " * 142)[:990].strip()  # split_clauses strips its input
        assert split_clauses(sentence) == [sentence]
        # A literal, not the constant: a test that compares the cap with itself cannot notice
        # someone raising it. 60 candidates, one look each when the left side already fails.
        assert 0 < len(calls) <= 120

    def test_a_span_past_the_character_limit_is_not_split_at_all(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        short = "The acting was great and the plot was dull."
        assert split_clauses(short) == ["The acting was great", "the plot was dull."]  # control
        long = short + " word" * 400  # well past the limit, with a perfectly good join in it
        assert len(long) > extract_module._MAX_SPLIT_CHARS
        calls: list[str] = []
        monkeypatch.setattr(extract_module, "_is_statement", lambda piece: calls.append(piece))
        assert split_clauses(long) == [long]
        assert calls == []  # it never even looked: the work does not grow with a long span

    def test_two_short_verdicts_pointing_opposite_ways_are_cut(self) -> None:
        # The blended score here used to make a well-cast film's acting come out negative.
        assert split_clauses("Great cast, terrible script.") == ["Great cast", "terrible script."]
        assert split_clauses("Great cast and terrible script.") == [
            "Great cast",
            "terrible script.",
        ]

    def test_a_run_of_verdicts_is_cut_where_the_direction_changes(self) -> None:
        assert split_clauses("Great cast, terrible script, and a weak ending.") == [
            "Great cast",
            "terrible script, and a weak ending.",
        ]

    def test_verdicts_that_agree_are_left_whole(self) -> None:
        # They already share the right score, and two-word clauses score too weakly to count.
        assert split_clauses("Good acting, good plot.") == ["Good acting, good plot."]
        assert split_clauses("Bad acting and a bad story.") == ["Bad acting and a bad story."]

    def test_a_list_with_one_opinion_is_left_whole(self) -> None:
        sentence = "Great acting, plot, and soundtrack."
        assert split_clauses(sentence) == [sentence]

    def test_a_negator_flips_the_side_it_governs(self) -> None:
        assert split_clauses("Good acting, not a good plot") == ["Good acting", "not a good plot"]
        # "not terrible" is mildly positive, so the two sides agree and nothing is cut.
        sentence = "Great cast, not terrible script"
        assert split_clauses(sentence) == [sentence]

    def test_both_sides_must_name_an_aspect_to_be_cut(self) -> None:
        # "Awful weather" has an opinion but is about no aspect of the film, so there is no verdict
        # to separate from "great script".
        sentence = "Pretty awful weather, great script."
        assert split_clauses(sentence) == [sentence]

    def test_two_full_statements_are_left_to_the_statement_rule(self) -> None:
        # The statement rule is deliberately narrow about a bare-noun subject (D-036); the verdict
        # rule must not widen it. With a verbless side, the same pair of opinions is cut.
        whole = "The acting was great and special effects were awful."
        assert split_clauses(whole) == [whole]
        assert split_clauses("The acting was great and special effects awful.") == [
            "The acting was great",
            "special effects awful.",
        ]

    def test_a_side_too_long_to_be_a_verdict_is_not_cut(self) -> None:
        sentence = "The whole cast of this film was really truly great, terrible script"
        assert split_clauses(sentence) == [sentence]

    def test_verdict_clauses_stay_verbatim_substrings(self) -> None:
        sentence = "Great cast, terrible script, and a weak ending."
        assert all(clause in sentence for clause in split_clauses(sentence))

    def test_the_verdict_work_is_bounded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        real = extract_module._verdict_sign

        def counting(piece: str) -> int:
            calls.append(piece)
            return real(piece)

        monkeypatch.setattr(extract_module, "_verdict_sign", counting)
        sentence = ("x, bad " * 140)[:980].strip()  # 140 candidates, under the character limit
        split_clauses(sentence)
        assert 0 < len(calls) <= 120  # 60 candidates, two looks each: a literal, not the constant
        calls.clear()
        split_clauses(("x, bad " * 200)[:1400])  # past the limit: never even looked at
        assert calls == []

    def test_a_crafted_five_thousand_character_text_does_almost_no_work(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        monkeypatch.setattr(extract_module, "_is_statement", lambda piece: calls.append(piece))
        text = ("acting" + ", the" * 1000)[:5000]
        assert split_clauses(text) == [text]
        assert calls == []


def _reviews(*texts: str) -> list[tuple[str, str]]:
    return [(f"rv-{i}", t) for i, t in enumerate(texts)]


class TestBuildProfile:
    def test_score_is_the_mean_and_support_is_the_count(
        self, keyword_scorer: KeywordScorer
    ) -> None:
        reviews = _reviews(
            "The pacing was superb throughout the whole film.",
            "The pacing was brilliant and kept me hooked.",
            "The pacing dragged badly in the middle hour of it.",
        )
        profile, _ = build_profile("m", reviews, model=keyword_scorer)
        (pacing,) = [s for s in profile.scores if s.aspect is Aspect.PACING]
        assert pacing.support == 3
        assert pacing.score == pytest.approx((0.9 + 0.9 - 0.9) / 3)
        assert profile.total_reviews == 3

    def test_contrast_gives_each_aspect_its_own_polarity(
        self, keyword_scorer: KeywordScorer
    ) -> None:
        reviews = _reviews(*(["The acting was brilliant but the plot was dull and tedious."] * 3))
        profile, _ = build_profile("m", reviews, model=keyword_scorer)
        by_aspect = {s.aspect: s.score for s in profile.scores}
        assert by_aspect[Aspect.ACTING] == pytest.approx(0.9)
        assert by_aspect[Aspect.PLOT] == pytest.approx(-0.9)

    def test_two_statements_joined_by_and_each_get_their_own_polarity(
        self, keyword_scorer: KeywordScorer
    ) -> None:
        # Before the "and" split, the scorer saw "great ... dull" as one negative clause and both
        # aspects came out at -0.9: the acting of a well-acted film was scored as bad.
        reviews = _reviews(*(["The acting was great and the plot was dull."] * 3))
        profile, _ = build_profile("m", reviews, model=keyword_scorer)
        by_aspect = {s.aspect: s.score for s in profile.scores}
        assert by_aspect[Aspect.ACTING] == pytest.approx(0.9)
        assert by_aspect[Aspect.PLOT] == pytest.approx(-0.9)

    def test_aspects_below_min_support_are_dropped(self, keyword_scorer: KeywordScorer) -> None:
        reviews = _reviews("The pacing was superb throughout.", "The pacing was brilliant today.")
        profile, evidence = build_profile("m", reviews, min_support=3, model=keyword_scorer)
        assert profile.scores == ()
        assert list(evidence) == []

    def test_evidence_is_verbatim_and_agrees_with_the_score_sign(
        self, keyword_scorer: KeywordScorer
    ) -> None:
        reviews = _reviews(
            "The pacing was superb and never let up for a second.",
            "The pacing was brilliant from the opening scene on.",
            "The pacing was wonderful and kept every scene tight.",
            "The pacing dragged terribly in the dull middle hour.",
        )
        profile, evidence = build_profile("m", reviews, model=keyword_scorer)
        (pacing,) = [s for s in profile.scores if s.aspect is Aspect.PACING]
        assert pacing.score > 0
        assert evidence, "a supported aspect must come with evidence"
        sources = dict(reviews)
        for e in evidence:
            assert e.text in sources[e.source_review_id]
            assert e.polarity > 0, "negative sentence cited for a positive aspect"

    def test_at_most_one_evidence_sentence_per_review(self, keyword_scorer: KeywordScorer) -> None:
        one_review = (
            "The pacing was superb and never let up for a second. "
            "The pacing was brilliant from the opening scene on. "
            "The pacing was wonderful and kept every scene tight."
        )
        reviews = _reviews(one_review, one_review, one_review)
        _, evidence = build_profile("m", reviews, model=keyword_scorer)
        ids = [e.source_review_id for e in evidence]
        assert len(ids) == len(set(ids))

    def test_fragments_too_short_to_quote_are_not_evidence(
        self, keyword_scorer: KeywordScorer
    ) -> None:
        reviews = _reviews("Superb pacing.", "Brilliant pacing.", "Wonderful pacing.")
        profile, evidence = build_profile("m", reviews, model=keyword_scorer)
        assert profile.scores, "the aspect is still scored"
        assert list(evidence) == []

    def test_output_is_deterministic(self, keyword_scorer: KeywordScorer) -> None:
        reviews = _reviews(
            *(f"The pacing was superb in take number {i} of them." for i in range(5))
        )
        first = build_profile("m", reviews, model=keyword_scorer)
        second = build_profile("m", reviews, model=keyword_scorer)
        assert first == second

    def test_source_url_is_attached_to_evidence(self, keyword_scorer: KeywordScorer) -> None:
        reviews = _reviews(
            *(f"The pacing was superb in take number {i} of them." for i in range(3))
        )
        _, evidence = build_profile(
            "m", reviews, model=keyword_scorer, source_url="https://x.test/"
        )
        assert evidence and all(e.source_url == "https://x.test/" for e in evidence)

    def test_source_url_can_depend_on_which_review_a_sentence_came_from(
        self, keyword_scorer: KeywordScorer
    ) -> None:
        # Evidence for one film now comes from several dumps, each with its own page to check.
        text = "The pacing was superb and the pacing never dragged at all."
        reviews = [("rt/a", text), ("ebd/b", text), ("acl/c", text)]
        links = {"rt": "https://rt.test/film", "ebd": "https://imdb.test/film"}
        _, evidence = build_profile(
            "m", reviews, model=keyword_scorer, source_url=lambda rid: links.get(rid.split("/")[0])
        )
        got = {e.source_review_id: e.source_url for e in evidence}
        assert got == {
            "rt/a": "https://rt.test/film",
            "ebd/b": "https://imdb.test/film",
            "acl/c": None,
        }

    def test_no_reviews_is_an_empty_profile_not_an_error(
        self, keyword_scorer: KeywordScorer
    ) -> None:
        profile, evidence = build_profile("m", [], model=keyword_scorer)
        assert profile.scores == () and profile.total_reviews == 0 and list(evidence) == []
