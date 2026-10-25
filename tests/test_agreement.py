"""Inter-labeller agreement: the arithmetic is checked by hand, and typos must stop the run."""

from __future__ import annotations

from pathlib import Path

import pytest

from cinewhy.absa.agreement import cohen_kappa, compare, load_sheet, parse_labels
from cinewhy.absa.gold import RandomRow
from cinewhy.schemas import Aspect


class TestParseLabels:
    def test_reads_letters_and_signs(self) -> None:
        assert parse_labels("a+ p-") == {Aspect.ACTING: 1, Aspect.PLOT: -1}

    def test_blank_means_no_aspect(self) -> None:
        assert parse_labels("   ") == {}

    @pytest.mark.parametrize("cell", ["x+", "a?", "a", "a+ a-", "acting+"])
    def test_a_typo_stops_the_run_instead_of_hiding_a_mention(self, cell: str) -> None:
        with pytest.raises(ValueError):
            parse_labels(cell)


class TestKappa:
    def test_perfect_agreement_is_one(self) -> None:
        assert cohen_kappa([True, False, True], [True, False, True]) == 1.0

    def test_agreement_no_better_than_chance_is_zero(self) -> None:
        # observed 0.5; each rater says yes half the time so chance agreement is also 0.5
        assert cohen_kappa([True, True, False, False], [True, False, True, False]) == 0.0

    def test_hand_computed_value(self) -> None:
        # observed 3/4; p1 = 3/4, p2 = 1/2; expected = 3/8 + 1/8 = 1/2; kappa = (3/4-1/2)/(1/2)
        assert cohen_kappa([True, True, True, False], [True, True, False, False]) == pytest.approx(
            0.5
        )

    def test_unequal_lengths_are_rejected(self) -> None:
        with pytest.raises(ValueError):
            cohen_kappa([True], [True, False])


def _sheet(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "sheet.csv"
    path.write_text("id,text,labels,done\n" + body, encoding="utf-8")
    return path


class TestLoadSheet:
    def test_only_rows_marked_done_count(self, tmp_path: Path) -> None:
        rows = load_sheet(_sheet(tmp_path, "0,first clause,a+,y\n1,second clause,,\n2,third,,y\n"))
        assert [r.id for r in rows] == [0, 2]
        assert rows[1].aspects == {}  # done with no label means "no aspect", not "unseen"


class TestCompare:
    def test_counts_every_clause_aspect_cell(self) -> None:
        human = [RandomRow(0, "x", {Aspect.ACTING: 1}), RandomRow(1, "y", {})]
        assistant = [RandomRow(0, "x", {Aspect.ACTING: 1}), RandomRow(1, "y", {Aspect.PLOT: -1})]
        result = compare(human, assistant)
        assert result.n_clauses == 2
        assert result.presence_agreement.n == 14  # 2 clauses x 7 aspects
        assert result.presence_agreement.hits == 13  # one cell (clause 1, plot) differs
        assert result.polarity_agreement.n == 1 and result.polarity_agreement.hits == 1

    def test_polarity_disagreement_is_counted(self) -> None:
        human = [RandomRow(0, "x", {Aspect.ACTING: 1})]
        assistant = [RandomRow(0, "x", {Aspect.ACTING: -1})]
        assert compare(human, assistant).polarity_agreement.hits == 0

    def test_no_shared_ids_is_an_error_not_a_zero(self) -> None:
        with pytest.raises(ValueError):
            compare([RandomRow(5, "x", {})], [RandomRow(6, "x", {})])
