import pytest

from nf_pmc_vl_curator.agents.annotator import AnnotationAgent
from nf_pmc_vl_curator.models import ArticleRef, Figure, FigureType, Modality, NFRelevance


@pytest.fixture
def agent(keywords_path):
    return AnnotationAgent(keywords_path)


def annotate(agent, caption, title=""):
    return agent.annotate(
        Figure(fig_id="f", caption=caption), ArticleRef(pmcid="PMC0", title=title)
    )


def test_nf1_from_caption(agent):
    ann = annotate(agent, "MRI of a plexiform neurofibroma in NF1.")
    assert ann.nf_relevance is NFRelevance.NF1
    assert ann.nf_relevance_score == pytest.approx(0.9)


def test_nf2_from_caption(agent):
    ann = annotate(agent, "Bilateral vestibular schwannoma consistent with NF2.")
    assert ann.nf_relevance is NFRelevance.NF2


def test_both_when_nf1_and_nf2(agent):
    ann = annotate(agent, "Comparison of NF1 and NF2 imaging features.")
    assert ann.nf_relevance is NFRelevance.BOTH


def test_none_when_unrelated(agent):
    ann = annotate(agent, "Kaplan-Meier survival curve for the cohort.")
    assert ann.nf_relevance is NFRelevance.NONE
    assert ann.nf_relevance_score == 0.0


def test_title_only_relevance_is_lower_confidence(agent):
    ann = annotate(agent, "A figure with no disease terms.", title="A study of NF1")
    assert ann.nf_relevance is NFRelevance.NF1
    assert ann.nf_relevance_score == pytest.approx(0.5)


@pytest.mark.parametrize(
    "caption,modality,ftype",
    [
        ("T2-weighted magnetic resonance imaging", Modality.MRI, FigureType.RADIOLOGY),
        ("Hematoxylin and eosin stained micrograph", Modality.HISTOLOGY, FigureType.HISTOPATHOLOGY),
        ("Clinical photograph of a cutaneous lesion", Modality.CLINICAL_PHOTO, FigureType.CLINICAL_PHOTO),
        ("Kaplan-Meier survival curve", Modality.CHART, FigureType.CHART),
    ],
)
def test_modality_and_figure_type(agent, caption, modality, ftype):
    ann = annotate(agent, caption)
    assert ann.modality is modality
    assert ann.figure_type is ftype


def test_mixed_figure_type(agent):
    ann = annotate(agent, "MRI panel alongside an H&E stained histology micrograph.")
    assert ann.figure_type is FigureType.MIXED


def test_entities_collected(agent):
    ann = annotate(agent, "A malignant peripheral nerve sheath tumor (MPNST) arising from a plexiform neurofibroma.")
    assert "mpnst" in ann.entities
    assert "plexiform neurofibroma" in ann.entities
    assert "entities" in ann.matched_terms
