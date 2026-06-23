"""Stage 7 -- ExportAgent.

Writes the curated dataset as JSONL (one :class:`FigureRecord` per line) plus a
human-readable ``summary.json`` with distribution stats. By default only
records that passed quality checks are exported; the rest can optionally be
written to ``rejected.jsonl`` for inspection.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path

from ..models import FigureRecord

log = logging.getLogger(__name__)


class ExportAgent:
    """Serialise records to JSONL and emit summary statistics."""

    def run(
        self,
        records: list[FigureRecord],
        output_dir: Path,
        *,
        only_passed: bool = True,
        write_rejected: bool = True,
    ) -> dict:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        passed = [r for r in records if r.quality.passed]
        rejected = [r for r in records if not r.quality.passed]
        exported = passed if only_passed else records

        dataset_path = output_dir / "dataset.jsonl"
        self._write_jsonl(exported, dataset_path)

        if write_rejected and rejected:
            self._write_jsonl(rejected, output_dir / "rejected.jsonl")

        summary = self._summarise(records, exported)
        (output_dir / "summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
        log.info("exported %d records to %s", len(exported), dataset_path)
        return summary

    @staticmethod
    def _write_jsonl(records: list[FigureRecord], path: Path) -> None:
        with path.open("w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(rec.model_dump_json())
                fh.write("\n")

    @staticmethod
    def _summarise(all_records: list[FigureRecord], exported: list[FigureRecord]) -> dict:
        flag_counter: Counter = Counter()
        for rec in all_records:
            for flag in rec.quality.flags:
                flag_counter[flag.value] += 1
        return {
            "total_candidates": len(all_records),
            "exported": len(exported),
            "rejected": len(all_records) - len(exported),
            "by_nf_relevance": _count(exported, lambda r: r.annotations.nf_relevance.value),
            "by_modality": _count(exported, lambda r: r.annotations.modality.value),
            "by_figure_type": _count(exported, lambda r: r.annotations.figure_type.value),
            "by_license": _count(
                exported, lambda r: r.license.code if r.license else "none"
            ),
            "quality_flags": dict(flag_counter),
            "articles": len({r.article.pmcid for r in exported}),
        }


def _count(records: list[FigureRecord], key) -> dict:
    counter: Counter = Counter(key(r) for r in records)
    return dict(counter)
