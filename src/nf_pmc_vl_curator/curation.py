"""Human-in-the-loop curation layer.

The automated pipeline produces *weak* labels; a researcher then reviews them.
This module persists those review decisions (accept / reject / label
corrections) independently of the dataset and merges them back on demand, so:

  * the weak labels and the human judgement are both auditable,
  * re-running the pipeline never clobbers human work, and
  * a review session is resumable -- decisions live in ``decisions.json``.

It is deliberately UI-agnostic (no Streamlit import) so the logic is unit
tested on its own; :mod:`nf_pmc_vl_curator.app` is just a thin Streamlit shell
over the functions here.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from .models import (
    FigureRecord,
    FigureType,
    Modality,
    NFRelevance,
    ReviewInfo,
    ReviewStatus,
)

# Annotation fields a reviewer is allowed to correct, mapped to their enum.
CORRECTABLE_FIELDS: dict[str, type] = {
    "nf_relevance": NFRelevance,
    "modality": Modality,
    "figure_type": FigureType,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DecisionStore:
    """A persistent map of ``record_id -> ReviewInfo`` backed by JSON on disk."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._data: dict[str, ReviewInfo] = {}

    # -- persistence ------------------------------------------------------- #
    @classmethod
    def load(cls, path: Path) -> "DecisionStore":
        store = cls(path)
        if store.path.exists():
            raw = json.loads(store.path.read_text(encoding="utf-8"))
            store._data = {
                rid: ReviewInfo.model_validate(info) for rid, info in raw.items()
            }
        return store

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {rid: info.model_dump() for rid, info in self._data.items()}
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # -- access ------------------------------------------------------------ #
    def get(self, record_id: str) -> Optional[ReviewInfo]:
        return self._data.get(record_id)

    def set(self, record_id: str, review: ReviewInfo) -> None:
        self._data[record_id] = review

    def decide(
        self,
        record_id: str,
        status: ReviewStatus,
        *,
        reviewer: Optional[str] = None,
        notes: Optional[str] = None,
        corrections: Optional[dict[str, str]] = None,
    ) -> ReviewInfo:
        """Record a decision (and persist nothing -- caller calls ``save``)."""
        review = ReviewInfo(
            status=status,
            reviewer=reviewer,
            decided_at=now_iso(),
            notes=notes,
            corrections=_validate_corrections(corrections or {}),
        )
        self._data[record_id] = review
        return review

    def counts(self) -> dict[str, int]:
        out = {s.value: 0 for s in ReviewStatus}
        for info in self._data.values():
            out[info.status.value] += 1
        return out

    def __len__(self) -> int:
        return len(self._data)


def _validate_corrections(corrections: dict[str, str]) -> dict[str, str]:
    """Reject unknown fields / invalid enum values early (fail fast)."""
    clean: dict[str, str] = {}
    for field, value in corrections.items():
        if field not in CORRECTABLE_FIELDS:
            raise ValueError(f"not a correctable field: {field!r}")
        enum_cls = CORRECTABLE_FIELDS[field]
        clean[field] = enum_cls(value).value  # raises ValueError if invalid
    return clean


def apply_decisions(
    records: Iterable[FigureRecord], store: DecisionStore
) -> list[FigureRecord]:
    """Return copies of ``records`` with review status + corrections merged in.

    Records with no stored decision get a ``PENDING`` review. Corrections
    overwrite the corresponding weak-annotation enum field; the original value
    is preserved in ``review.corrections`` as the audit trail.
    """
    out: list[FigureRecord] = []
    for rec in records:
        rec = rec.model_copy(deep=True)
        review = store.get(rec.record_id) or ReviewInfo(status=ReviewStatus.PENDING)
        for field, value in review.corrections.items():
            enum_cls = CORRECTABLE_FIELDS[field]
            setattr(rec.annotations, field, enum_cls(value))
        rec.review = review
        out.append(rec)
    return out


def curated_records(records: Iterable[FigureRecord]) -> list[FigureRecord]:
    """The reviewer-approved subset: records explicitly marked ACCEPTED."""
    return [
        r for r in records if r.review and r.review.status is ReviewStatus.ACCEPTED
    ]


# --------------------------------------------------------------------------- #
# Dataset I/O for the curation layer
# --------------------------------------------------------------------------- #
def load_dataset(path: Path) -> list[FigureRecord]:
    """Read a ``dataset.jsonl`` (one FigureRecord per line)."""
    records: list[FigureRecord] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(FigureRecord.model_validate_json(line))
    return records


_CSV_COLUMNS = [
    "record_id", "pmcid", "pmid", "doi", "title", "journal", "pub_year",
    "fig_id", "label", "nf_relevance", "modality", "figure_type", "entities",
    "license_code", "license_url", "requires_attribution",
    "review_status", "reviewer", "review_notes", "corrected_fields",
    "caption", "graphic_href", "local_image_path", "source_xml",
]


def flatten_record(rec: FigureRecord) -> dict:
    """Flatten a record into a single spreadsheet row."""
    lic = rec.license
    rev = rec.review
    return {
        "record_id": rec.record_id,
        "pmcid": rec.article.pmcid,
        "pmid": rec.article.pmid,
        "doi": rec.article.doi,
        "title": rec.article.title,
        "journal": rec.article.journal,
        "pub_year": rec.article.pub_year,
        "fig_id": rec.figure.fig_id,
        "label": rec.figure.label,
        "nf_relevance": rec.annotations.nf_relevance.value,
        "modality": rec.annotations.modality.value,
        "figure_type": rec.annotations.figure_type.value,
        "entities": "; ".join(rec.annotations.entities),
        "license_code": lic.code if lic else None,
        "license_url": lic.url if lic else None,
        "requires_attribution": lic.requires_attribution if lic else None,
        "review_status": rev.status.value if rev else "pending",
        "reviewer": rev.reviewer if rev else None,
        "review_notes": rev.notes if rev else None,
        "corrected_fields": "; ".join(rev.corrections) if rev else "",
        "caption": rec.figure.caption,
        "graphic_href": rec.figure.graphic_href,
        "local_image_path": rec.figure.local_image_path,
        "source_xml": rec.provenance.get("source_xml"),
    }


def write_curated(records: list[FigureRecord], output_dir: Path) -> dict[str, Path]:
    """Write the ACCEPTED subset as JSONL + CSV. Returns the written paths."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    approved = curated_records(records)

    jsonl_path = output_dir / "curated_dataset.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as fh:
        for rec in approved:
            fh.write(rec.model_dump_json())
            fh.write("\n")

    csv_path = output_dir / "curated_dataset.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_COLUMNS)
        writer.writeheader()
        for rec in approved:
            writer.writerow(flatten_record(rec))

    return {"jsonl": jsonl_path, "csv": csv_path}
