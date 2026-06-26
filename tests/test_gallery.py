import json

import pytest

from nf_pmc_vl_curator.gallery import build_gallery


def _make_dataset(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "PMC1_fig1.jpg").write_bytes(b"\xff\xd8\xffjpeg")
    rows = [
        {"file_name": "images/PMC1_fig1.jpg", "record_id": "PMC1:fig1",
         "caption": "Axial MRI of a plexiform neurofibroma.", "nf_relevance": "nf1",
         "modality": "mri", "image_modality": "ct", "image_modality_confidence": 0.9,
         "license": "CC BY", "pmcid": "PMC1", "doi": "10.x/y", "entities": ["nf"]},
        {"file_name": "images/PMC2_fig1.jpg", "record_id": "PMC2:fig1",
         "caption": "H&E micrograph.", "nf_relevance": "nf2",
         "modality": "histology", "image_modality": "histology", "license": "CC0",
         "pmcid": "PMC2", "entities": []},
    ]
    (tmp_path / "metadata.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    return tmp_path


def test_build_gallery_writes_self_contained_html(tmp_path):
    out = build_gallery(_make_dataset(tmp_path))
    assert out.name == "gallery.html"
    html = out.read_text(encoding="utf-8")

    # records embedded, no external/CDN dependency
    assert "PMC1:fig1" in html and "PMC2:fig1" in html
    assert "images/PMC1_fig1.jpg" in html
    assert "http" not in html.split("const RECORDS")[0].lower() or "doi.org" in html
    assert "2 figures" in html  # title reflects record count
    # filter controls + lightbox present
    for needle in ("id=\"q\"", "NF relevance", "Modality (image)", "only image", "lbmeta"):
        assert needle in html


def test_build_gallery_custom_output_path(tmp_path):
    ds = _make_dataset(tmp_path)
    target = tmp_path / "out" / "viz.html"
    target.parent.mkdir()
    out = build_gallery(ds, target)
    assert out == target and target.exists()


def test_missing_metadata_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_gallery(tmp_path)
