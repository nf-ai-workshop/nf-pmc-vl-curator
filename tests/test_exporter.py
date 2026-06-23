import json

from nf_pmc_vl_curator.agents.exporter import ExportAgent
from nf_pmc_vl_curator.agents.quality import QualityAgent
from nf_pmc_vl_curator.config import QualityConfig
from nf_pmc_vl_curator.models import (
    ArticleRef,
    Figure,
    FigureRecord,
    LicenseInfo,
    Modality,
    NFRelevance,
    WeakAnnotations,
)


def _rec(rid, caption, passed_caption=True):
    return FigureRecord(
        record_id=rid,
        article=ArticleRef(pmcid=rid.split(":")[0]),
        figure=Figure(fig_id=rid.split(":")[1], caption=caption, graphic_href="x.jpg"),
        license=LicenseInfo(code="CC BY"),
        annotations=WeakAnnotations(nf_relevance=NFRelevance.NF1, modality=Modality.MRI),
    )


def test_export_jsonl_and_summary(tmp_path):
    recs = [
        _rec("PMC1:fig1", "A nicely detailed MRI caption about NF1."),
        _rec("PMC2:fig1", ""),  # missing caption -> rejected
    ]
    recs = QualityAgent().run(recs, QualityConfig())
    summary = ExportAgent().run(recs, tmp_path)

    dataset = tmp_path / "dataset.jsonl"
    lines = [l for l in dataset.read_text().splitlines() if l.strip()]
    assert len(lines) == 1  # only the passing record
    rec = json.loads(lines[0])
    assert rec["record_id"] == "PMC1:fig1"

    assert summary["total_candidates"] == 2
    assert summary["exported"] == 1
    assert summary["rejected"] == 1
    assert summary["by_nf_relevance"] == {"nf1": 1}
    assert (tmp_path / "summary.json").exists()
    assert (tmp_path / "rejected.jsonl").exists()


def test_summary_json_is_valid(tmp_path):
    recs = QualityAgent().run([_rec("PMC1:fig1", "Long enough caption text here.")],
                              QualityConfig())
    ExportAgent().run(recs, tmp_path)
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["articles"] == 1
