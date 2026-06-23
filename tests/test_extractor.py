from nf_pmc_vl_curator.agents.extractor import FigureExtractionAgent
from xml.etree import ElementTree as ET


def test_extract_figures_and_metadata(sample_dir):
    agent = FigureExtractionAgent()
    ref, figs = agent.parse_file(sample_dir / "PMC9000001.xml")

    assert ref.pmcid == "PMC9000001"
    assert ref.pmid == "90000001"
    assert ref.doi == "10.0000/synthetic.9000001"
    assert ref.pub_year == 2021
    assert "plexiform neurofibroma" in (ref.title or "").lower()

    assert len(figs) == 2
    fig1 = figs[0]
    assert fig1.fig_id == "fig1"
    assert fig1.label == "Figure 1"
    assert fig1.graphic_href == "9000001_fig1.jpg"
    assert "T1-weighted" in fig1.caption
    # ampersand entity decoded in the second figure caption
    assert "H&E" in figs[1].caption


def test_extract_license_variants(sample_dir):
    agent = FigureExtractionAgent()
    cases = {
        "PMC9000001.xml": "CC BY",
        "PMC9000002.xml": "CC BY-NC",
        "PMC9000003.xml": "CC0",
    }
    for fname, expected in cases.items():
        root = ET.fromstring((sample_dir / fname).read_text())
        lic = agent.extract_license(root)
        assert lic is not None
        assert lic.code == expected


def test_namespace_agnostic_href(sample_dir):
    # graphic href lives under the xlink namespace; the parser must still find it.
    agent = FigureExtractionAgent()
    _, figs = agent.parse_file(sample_dir / "PMC9000002.xml")
    assert figs[0].graphic_href == "9000002_fig1.png"
