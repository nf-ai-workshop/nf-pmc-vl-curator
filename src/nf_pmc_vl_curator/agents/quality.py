"""Stage 6 -- QualityAgent.

Raises machine-checkable quality flags on each record and decides whether the
record *passes* (is kept) given the configured policy. Some checks are per
record (missing caption, missing license); duplicate-caption detection needs
the whole batch, so this agent operates on the full list.

Flag policy:
  * always fatal:    MISSING_CAPTION, DUPLICATE_CAPTION
  * fatal if config: MISSING_LICENSE (require_license),
                     MISSING_IMAGE (require_image_file),
                     NOT_NF_RELEVANT (drop_not_nf_relevant)
  * advisory only:   SHORT_CAPTION, NO_MODALITY
"""

from __future__ import annotations

import logging

from ..config import QualityConfig
from ..models import FigureRecord, Modality, NFRelevance, QualityFlag, QualityReport

log = logging.getLogger(__name__)


class QualityAgent:
    """Validate and flag a batch of figure records."""

    def run(
        self, records: list[FigureRecord], config: QualityConfig
    ) -> list[FigureRecord]:
        seen_captions: dict[str, str] = {}  # normalised caption -> first record_id
        for rec in records:
            flags = self._record_flags(rec, config)

            norm = _normalise(rec.figure.caption)
            if norm:
                if norm in seen_captions:
                    flags.append(QualityFlag.DUPLICATE_CAPTION)
                else:
                    seen_captions[norm] = rec.record_id

            rec.quality = QualityReport(
                flags=flags, passed=self._passes(flags, config)
            )

        n_pass = sum(1 for r in records if r.quality.passed)
        log.info("quality: %d/%d records pass", n_pass, len(records))
        return records

    # -- per-record checks ------------------------------------------------- #
    @staticmethod
    def _record_flags(rec: FigureRecord, config: QualityConfig) -> list[QualityFlag]:
        flags: list[QualityFlag] = []
        caption = rec.figure.caption or ""

        if not caption.strip():
            flags.append(QualityFlag.MISSING_CAPTION)
        elif len(caption.strip()) < config.min_caption_length:
            flags.append(QualityFlag.SHORT_CAPTION)

        if rec.figure.local_image_path is None and rec.figure.graphic_href is None:
            flags.append(QualityFlag.MISSING_IMAGE)
        elif config.require_image_file and rec.figure.local_image_path is None:
            flags.append(QualityFlag.MISSING_IMAGE)

        if rec.license is None:
            flags.append(QualityFlag.MISSING_LICENSE)

        if rec.annotations.nf_relevance == NFRelevance.NONE:
            flags.append(QualityFlag.NOT_NF_RELEVANT)

        if rec.annotations.modality == Modality.UNKNOWN:
            flags.append(QualityFlag.NO_MODALITY)

        return flags

    @staticmethod
    def _passes(flags: list[QualityFlag], config: QualityConfig) -> bool:
        fatal = {QualityFlag.MISSING_CAPTION, QualityFlag.DUPLICATE_CAPTION}
        if config.require_license:
            fatal.add(QualityFlag.MISSING_LICENSE)
        if config.require_image_file:
            fatal.add(QualityFlag.MISSING_IMAGE)
        if config.drop_not_nf_relevant:
            fatal.add(QualityFlag.NOT_NF_RELEVANT)
        return not (set(flags) & fatal)


def _normalise(caption: str) -> str:
    return " ".join((caption or "").lower().split())
