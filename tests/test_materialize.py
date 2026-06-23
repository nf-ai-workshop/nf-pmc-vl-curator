import json

import pytest

from nf_pmc_vl_curator.materialize import materialize_dataset
from nf_pmc_vl_curator.models import (
    ArticleRef,
    Figure,
    FigureRecord,
    LicenseInfo,
    Modality,
    NFRelevance,
    ReviewInfo,
    ReviewStatus,
    WeakAnnotations,
)

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


def _make_image(path, fmt, size=(8, 8), color=(200, 50, 50)):
    Image.new("RGB", size, color).save(path, format=fmt)
    return path


def _rec(rid, image_path, nf=NFRelevance.NF1, review=None):
    return FigureRecord(
        record_id=rid,
        article=ArticleRef(pmcid=rid.split(":")[0], doi="10.x/y", title="T"),
        figure=Figure(fig_id=rid.split(":")[1], label="Figure 1",
                      caption="A T1-weighted MRI of a plexiform neurofibroma.",
                      graphic_href="g.jpg", local_image_path=str(image_path)),
        license=LicenseInfo(code="CC BY", url="http://cc"),
        annotations=WeakAnnotations(nf_relevance=nf, modality=Modality.MRI,
                                    entities=["plexiform neurofibroma"]),
        review=review,
    )


def test_imagefolder_layout_and_metadata(tmp_path):
    jpg = _make_image(tmp_path / "a.jpg", "JPEG")
    gif = _make_image(tmp_path / "b.gif", "GIF")
    records = [_rec("PMC1:fig1", jpg), _rec("PMC2:fig2", gif, nf=NFRelevance.NF2)]

    out = tmp_path / "ds"
    stats = materialize_dataset(records, out)
    assert stats["images"] == 2

    # jpg copied as-is; gif normalised to png
    names = sorted(p.name for p in (out / "images").iterdir())
    assert names == ["PMC1_fig1.jpg", "PMC2_fig2.png"]

    rows = [json.loads(l) for l in (out / "metadata.jsonl").read_text().splitlines() if l.strip()]
    assert len(rows) == 2
    by_id = {r["record_id"]: r for r in rows}
    r1 = by_id["PMC1:fig1"]
    assert r1["file_name"] == "images/PMC1_fig1.jpg"   # HF imagefolder key
    assert r1["caption"].startswith("A T1-weighted")
    assert r1["modality"] == "mri"
    assert r1["entities"] == ["plexiform neurofibroma"]
    assert r1["license"] == "CC BY"
    # every metadata file_name points at a real file on disk
    for r in rows:
        assert (out / r["file_name"]).exists()
    assert (out / "README.md").exists()


def test_force_jpg_conversion(tmp_path):
    png = _make_image(tmp_path / "a.png", "PNG")
    out = tmp_path / "ds"
    materialize_dataset([_rec("PMC1:fig1", png)], out, image_format="jpg")
    img = next((out / "images").iterdir())
    assert img.suffix == ".jpg"
    with Image.open(img) as im:
        assert im.mode == "RGB"


def test_skips_records_without_image(tmp_path):
    jpg = _make_image(tmp_path / "a.jpg", "JPEG")
    rec_no_img = _rec("PMC2:fig1", jpg)
    rec_no_img.figure.local_image_path = None
    rec_missing = _rec("PMC3:fig1", tmp_path / "does_not_exist.jpg")

    out = tmp_path / "ds"
    stats = materialize_dataset([_rec("PMC1:fig1", jpg), rec_no_img, rec_missing], out)
    assert stats["images"] == 1
    assert stats["skipped_no_image"] == 1
    assert stats["missing_on_disk"] == 1


def test_accepted_only_filter(tmp_path):
    jpg = _make_image(tmp_path / "a.jpg", "JPEG")
    accepted = _rec("PMC1:fig1", jpg,
                    review=ReviewInfo(status=ReviewStatus.ACCEPTED, reviewer="x"))
    pending = _rec("PMC2:fig1", jpg)  # review=None -> pending
    out = tmp_path / "ds"
    stats = materialize_dataset([accepted, pending], out, accepted_only=True)
    assert stats["images"] == 1
    assert stats["skipped_not_accepted"] == 1
    row = json.loads((out / "metadata.jsonl").read_text().splitlines()[0])
    assert row["review_status"] == "accepted"
    assert row["reviewer"] == "x"


def test_relative_image_root(tmp_path):
    _make_image(tmp_path / "img.jpg", "JPEG")
    rec = _rec("PMC1:fig1", "img.jpg")  # relative path
    out = tmp_path / "ds"
    stats = materialize_dataset([rec], out, image_root=tmp_path)
    assert stats["images"] == 1
