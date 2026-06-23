from nf_pmc_vl_curator.agents.quality import QualityAgent
from nf_pmc_vl_curator.config import QualityConfig
from nf_pmc_vl_curator.models import (
    ArticleRef,
    Figure,
    FigureRecord,
    LicenseInfo,
    Modality,
    NFRelevance,
    QualityFlag,
    WeakAnnotations,
)


def make_record(rid, caption="A sufficiently long and descriptive caption here.",
                license=LicenseInfo(code="CC BY"), nf=NFRelevance.NF1,
                modality=Modality.MRI, href="x.jpg", local=None):
    return FigureRecord(
        record_id=rid,
        article=ArticleRef(pmcid=rid.split(":")[0]),
        figure=Figure(fig_id=rid.split(":")[1], caption=caption,
                      graphic_href=href, local_image_path=local),
        license=license,
        annotations=WeakAnnotations(nf_relevance=nf, modality=modality),
    )


def test_clean_record_passes():
    recs = QualityAgent().run([make_record("PMC1:fig1")], QualityConfig())
    assert recs[0].quality.passed
    assert recs[0].quality.flags == []


def test_missing_caption_is_fatal():
    recs = QualityAgent().run([make_record("PMC1:fig1", caption="")], QualityConfig())
    assert QualityFlag.MISSING_CAPTION in recs[0].quality.flags
    assert recs[0].quality.passed is False


def test_short_caption_is_advisory():
    recs = QualityAgent().run([make_record("PMC1:fig1", caption="tiny")], QualityConfig())
    assert QualityFlag.SHORT_CAPTION in recs[0].quality.flags
    assert recs[0].quality.passed is True  # advisory, not fatal


def test_duplicate_caption_keeps_first():
    a = make_record("PMC1:fig1", caption="Identical caption text repeated verbatim.")
    b = make_record("PMC2:fig1", caption="Identical caption text repeated verbatim.")
    recs = QualityAgent().run([a, b], QualityConfig())
    assert recs[0].quality.passed is True
    assert QualityFlag.DUPLICATE_CAPTION in recs[1].quality.flags
    assert recs[1].quality.passed is False


def test_missing_license_fatal_when_required():
    recs = QualityAgent().run([make_record("PMC1:fig1", license=None)], QualityConfig())
    assert QualityFlag.MISSING_LICENSE in recs[0].quality.flags
    assert recs[0].quality.passed is False
    # ...but tolerated when not required
    recs2 = QualityAgent().run(
        [make_record("PMC1:fig1", license=None)],
        QualityConfig(require_license=False),
    )
    assert recs2[0].quality.passed is True


def test_not_nf_relevant_flag_and_drop_policy():
    rec = make_record("PMC1:fig1", nf=NFRelevance.NONE)
    recs = QualityAgent().run([rec], QualityConfig())
    assert QualityFlag.NOT_NF_RELEVANT in recs[0].quality.flags
    assert recs[0].quality.passed is True  # advisory by default

    rec2 = make_record("PMC1:fig1", nf=NFRelevance.NONE)
    recs2 = QualityAgent().run([rec2], QualityConfig(drop_not_nf_relevant=True))
    assert recs2[0].quality.passed is False


def test_require_image_file():
    rec = make_record("PMC1:fig1", href="x.jpg", local=None)
    recs = QualityAgent().run([rec], QualityConfig(require_image_file=True))
    assert QualityFlag.MISSING_IMAGE in recs[0].quality.flags
    assert recs[0].quality.passed is False
