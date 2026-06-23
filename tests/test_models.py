import pytest
from pydantic import ValidationError

from nf_pmc_vl_curator.models import (
    ArticleRef,
    Figure,
    FigureRecord,
    Modality,
    NFRelevance,
    QualityFlag,
    QualityReport,
    WeakAnnotations,
)


def test_make_id():
    assert FigureRecord.make_id("PMC9000001", "fig1") == "PMC9000001:fig1"


def test_weak_annotation_defaults():
    ann = WeakAnnotations()
    assert ann.nf_relevance is NFRelevance.UNKNOWN
    assert ann.modality is Modality.UNKNOWN
    assert ann.entities == []
    assert ann.nf_relevance_score == 0.0


def test_score_bounds_enforced():
    with pytest.raises(ValidationError):
        WeakAnnotations(nf_relevance_score=1.5)


def test_quality_report_is_clean():
    assert QualityReport().is_clean is True
    assert QualityReport(flags=[QualityFlag.SHORT_CAPTION]).is_clean is False


def test_figure_record_roundtrip():
    rec = FigureRecord(
        record_id="PMC9000001:fig1",
        article=ArticleRef(pmcid="PMC9000001"),
        figure=Figure(fig_id="fig1", caption="hello"),
    )
    dumped = rec.model_dump_json()
    restored = FigureRecord.model_validate_json(dumped)
    assert restored.figure.caption == "hello"
    assert restored.article.pmcid == "PMC9000001"
