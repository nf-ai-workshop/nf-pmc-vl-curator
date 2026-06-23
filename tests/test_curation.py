import csv
import json

import pytest

from nf_pmc_vl_curator.curation import (
    DecisionStore,
    apply_decisions,
    curated_records,
    flatten_record,
    load_dataset,
    write_curated,
)
from nf_pmc_vl_curator.models import (
    ArticleRef,
    Figure,
    FigureRecord,
    Modality,
    NFRelevance,
    ReviewStatus,
    WeakAnnotations,
)


def _rec(rid, nf=NFRelevance.NF1, modality=Modality.MRI):
    return FigureRecord(
        record_id=rid,
        article=ArticleRef(pmcid=rid.split(":")[0], title="t"),
        figure=Figure(fig_id=rid.split(":")[1], caption="cap", graphic_href="x.jpg"),
        annotations=WeakAnnotations(nf_relevance=nf, modality=modality),
    )


def test_decision_store_roundtrip(tmp_path):
    store = DecisionStore(tmp_path / "decisions.json")
    store.decide("PMC1:fig1", ReviewStatus.ACCEPTED, reviewer="alice")
    store.save()

    reloaded = DecisionStore.load(tmp_path / "decisions.json")
    info = reloaded.get("PMC1:fig1")
    assert info.status is ReviewStatus.ACCEPTED
    assert info.reviewer == "alice"
    assert info.decided_at is not None


def test_decide_validates_corrections(tmp_path):
    store = DecisionStore(tmp_path / "d.json")
    with pytest.raises(ValueError):
        store.decide("PMC1:fig1", ReviewStatus.ACCEPTED,
                     corrections={"modality": "not-a-modality"})
    with pytest.raises(ValueError):
        store.decide("PMC1:fig1", ReviewStatus.ACCEPTED,
                     corrections={"bogus_field": "mri"})


def test_apply_decisions_merges_status_and_corrections(tmp_path):
    store = DecisionStore(tmp_path / "d.json")
    store.decide("PMC1:fig1", ReviewStatus.ACCEPTED,
                 corrections={"nf_relevance": "nf2"})

    merged = apply_decisions([_rec("PMC1:fig1"), _rec("PMC2:fig1")], store)

    # corrected record reflects the human label + status
    assert merged[0].annotations.nf_relevance is NFRelevance.NF2
    assert merged[0].review.status is ReviewStatus.ACCEPTED
    # untouched record defaults to PENDING and keeps its weak label
    assert merged[1].annotations.nf_relevance is NFRelevance.NF1
    assert merged[1].review.status is ReviewStatus.PENDING


def test_curated_records_only_accepted(tmp_path):
    store = DecisionStore(tmp_path / "d.json")
    store.decide("PMC1:fig1", ReviewStatus.ACCEPTED)
    store.decide("PMC2:fig1", ReviewStatus.REJECTED)
    merged = apply_decisions(
        [_rec("PMC1:fig1"), _rec("PMC2:fig1"), _rec("PMC3:fig1")], store
    )
    approved = curated_records(merged)
    assert [r.record_id for r in approved] == ["PMC1:fig1"]


def test_apply_does_not_mutate_input(tmp_path):
    store = DecisionStore(tmp_path / "d.json")
    store.decide("PMC1:fig1", ReviewStatus.ACCEPTED, corrections={"nf_relevance": "nf2"})
    original = _rec("PMC1:fig1")
    apply_decisions([original], store)
    assert original.annotations.nf_relevance is NFRelevance.NF1  # unchanged
    assert original.review is None


def test_write_curated_jsonl_and_csv(tmp_path):
    store = DecisionStore(tmp_path / "d.json")
    store.decide("PMC1:fig1", ReviewStatus.ACCEPTED,
                 reviewer="bob", corrections={"modality": "ct"})
    store.decide("PMC2:fig1", ReviewStatus.REJECTED)
    merged = apply_decisions([_rec("PMC1:fig1"), _rec("PMC2:fig1")], store)

    paths = write_curated(merged, tmp_path / "out")
    lines = [l for l in paths["jsonl"].read_text().splitlines() if l.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["record_id"] == "PMC1:fig1"

    rows = list(csv.DictReader(paths["csv"].open()))
    assert len(rows) == 1
    assert rows[0]["modality"] == "ct"
    assert rows[0]["review_status"] == "accepted"
    assert rows[0]["reviewer"] == "bob"
    assert "modality" in rows[0]["corrected_fields"]


def test_load_dataset_roundtrip(tmp_path):
    path = tmp_path / "dataset.jsonl"
    path.write_text(_rec("PMC1:fig1").model_dump_json() + "\n")
    loaded = load_dataset(path)
    assert len(loaded) == 1
    assert loaded[0].record_id == "PMC1:fig1"


def test_flatten_record_keys():
    row = flatten_record(_rec("PMC1:fig1"))
    assert row["pmcid"] == "PMC1"
    assert row["nf_relevance"] == "nf1"
    assert row["review_status"] == "pending"
