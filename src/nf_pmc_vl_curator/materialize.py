"""Materialize a ``dataset.jsonl`` index into a self-contained image dataset.

``dataset.jsonl`` is only an *index*: the actual figure images live in the
(ephemeral, git-ignored) download cache, referenced by ``local_image_path``.
This module copies those images into a portable ``imagefolder``-style dataset
with stable filenames and a ``metadata.jsonl`` that pairs each image with its
language annotation (caption) and the weak structured labels.

The output layout is the HuggingFace ``imagefolder`` convention, so it loads
directly:

    from datasets import load_dataset
    ds = load_dataset("imagefolder", data_dir="dataset")

Image formats are normalised to plain JPG/PNG: ``.jpg``/``.png`` are copied
as-is; other formats (``.gif``/``.tif``/...) are converted with Pillow.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path
from typing import Iterable, Optional

from .models import FigureRecord, ReviewStatus

log = logging.getLogger(__name__)

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
_PASSTHROUGH = {".jpg", ".png"}  # already web-friendly (jpeg normalised to jpg)


def _slug(text: str) -> str:
    return _SAFE.sub("_", text).strip("_") or "x"


def _safe_stem(rec: FigureRecord) -> str:
    return f"{_slug(rec.article.pmcid)}_{_slug(rec.figure.fig_id)}"


def _normalise_suffix(suffix: str) -> str:
    s = suffix.lower()
    return ".jpg" if s == ".jpeg" else s


def _emit_image(src: Path, dest_stem: Path, image_format: str) -> Path:
    """Copy or convert ``src`` to a file named after ``dest_stem``.

    image_format: 'keep' (copy jpg/png, convert others to png), 'png' or 'jpg'
    (force everything to that format).
    """
    src_ext = _normalise_suffix(src.suffix)
    if image_format == "keep":
        target_ext = src_ext if src_ext in _PASSTHROUGH else ".png"
    else:
        target_ext = f".{image_format}"

    dest = dest_stem.with_suffix(target_ext)
    if src_ext == target_ext:
        shutil.copyfile(src, dest)
        return dest

    # Conversion required (e.g. gif/tif -> png/jpg, or forced format change).
    from PIL import Image  # lazy import; pillow is a declared dependency

    with Image.open(src) as im:
        if target_ext == ".jpg":
            im = im.convert("RGB")  # JPEG has no alpha/palette
        im.save(dest)
    return dest


def _row(rec: FigureRecord, file_name: str) -> dict:
    """Build one HF-imagefolder metadata row: image + language annotation."""
    a, an, lic = rec.article, rec.annotations, rec.license
    row = {
        "file_name": file_name,                 # required by imagefolder loader
        "record_id": rec.record_id,
        "caption": rec.figure.caption,          # the language annotation
        "nf_relevance": an.nf_relevance.value,
        "nf_relevance_score": an.nf_relevance_score,
        "modality": an.modality.value,
        "figure_type": an.figure_type.value,
        "entities": an.entities,
        "figure_label": rec.figure.label,
        "pmcid": a.pmcid,
        "pmid": a.pmid,
        "doi": a.doi,
        "title": a.title,
        "journal": a.journal,
        "year": a.pub_year,
        "license": lic.code if lic else None,
        "license_url": lic.url if lic else None,
        "license_requires_attribution": lic.requires_attribution if lic else None,
    }
    if rec.review is not None:
        row["review_status"] = rec.review.status.value
        if rec.review.reviewer:
            row["reviewer"] = rec.review.reviewer
    return row


def materialize_dataset(
    records: Iterable[FigureRecord],
    output_dir: Path,
    *,
    accepted_only: bool = False,
    image_format: str = "keep",
    image_root: Optional[Path] = None,
) -> dict:
    """Write an imagefolder dataset (images/ + metadata.jsonl) and a data card.

    Records without a resolvable image file on disk are skipped (and counted),
    since the goal is a dataset of *actual* images.
    """
    output_dir = Path(output_dir)
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    root = Path(image_root) if image_root else None

    rows: list[dict] = []
    stats = {"images": 0, "skipped_no_image": 0, "missing_on_disk": 0,
             "skipped_not_accepted": 0}
    used: set[str] = set()

    for rec in records:
        if accepted_only and not (
            rec.review and rec.review.status is ReviewStatus.ACCEPTED
        ):
            stats["skipped_not_accepted"] += 1
            continue
        if not rec.figure.local_image_path:
            stats["skipped_no_image"] += 1
            continue
        src = Path(rec.figure.local_image_path)
        if root and not src.is_absolute():
            src = root / src
        if not src.exists():
            stats["missing_on_disk"] += 1
            log.warning("image missing on disk, skipping %s: %s", rec.record_id, src)
            continue

        stem = _safe_stem(rec)
        unique = stem
        n = 1
        while unique in used:
            unique = f"{stem}_{n}"
            n += 1
        used.add(unique)

        dest = _emit_image(src, images_dir / unique, image_format)
        rows.append(_row(rec, f"images/{dest.name}"))
        stats["images"] += 1

    metadata_path = output_dir / "metadata.jsonl"
    with metadata_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False))
            fh.write("\n")

    _write_datacard(output_dir, rows, stats)
    log.info("materialized %d image(s) to %s", stats["images"], output_dir)
    return stats


def _write_datacard(output_dir: Path, rows: list[dict], stats: dict) -> None:
    licenses = sorted({r["license"] for r in rows if r["license"]})
    pmcids = sorted({r["pmcid"] for r in rows})
    card = f"""# NF1/NF2 PMC figure dataset (imagefolder)

Generated by `nf-curator materialize`. This is a HuggingFace **imagefolder**
dataset: each image in `images/` is paired with a row in `metadata.jsonl` whose
`caption` is the figure legend and whose other columns are weak structured
labels (NF relevance, modality, figure type, entities).

```python
from datasets import load_dataset
ds = load_dataset("imagefolder", data_dir=".")
print(ds["train"][0]["caption"], ds["train"][0]["modality"])
```

- Images: **{stats['images']}** from **{len(pmcids)}** article(s)
- Licenses present: {', '.join(licenses) or 'n/a'}

## Provenance & licensing

Every row keeps its source article (`pmcid`/`doi`) and `license`. Images are
from the PMC Open Access subset; **respect each image's license** when
redistributing (CC BY/BY-NC/etc. require attribution to the source article;
CC0 does not). Labels in `metadata.jsonl` are *weak* heuristics unless a
`review_status` of `accepted` indicates human curation.
"""
    (output_dir / "README.md").write_text(card, encoding="utf-8")
