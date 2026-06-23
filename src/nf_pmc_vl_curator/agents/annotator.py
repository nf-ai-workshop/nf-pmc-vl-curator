"""Stage 5 -- AnnotationAgent.

Attaches *weak* (heuristic) labels to each figure based on keyword matching
over the caption, with the article title used as a fallback context signal for
NF relevance. Produces:

  * NF1 / NF2 / both / none relevance (+ a confidence score),
  * a coarse imaging modality,
  * a higher-level figure type,
  * matched lesion/entity keywords,
  * an audit trail of which terms fired which label.

All vocabulary lives in ``resources/annotation_keywords.yaml`` -- the code is
disease-agnostic, so adapting to another topic means editing the YAML.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from ..models import (
    ArticleRef,
    Figure,
    FigureType,
    Modality,
    NFRelevance,
    WeakAnnotations,
)


def _compile(term: str) -> re.Pattern:
    # Match the term bounded by non-alphanumerics (handles "ct ", "x-ray", "h&e").
    return re.compile(rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])")


class AnnotationAgent:
    """Keyword-driven weak annotator."""

    def __init__(self, keywords_path: Path) -> None:
        data = yaml.safe_load(Path(keywords_path).read_text()) or {}
        self._nf1 = [_compile(t) for t in data.get("nf_relevance", {}).get("nf1", [])]
        self._nf2 = [_compile(t) for t in data.get("nf_relevance", {}).get("nf2", [])]
        self._modalities: dict[str, list[re.Pattern]] = {
            mod: [_compile(t) for t in terms]
            for mod, terms in data.get("modality", {}).items()
        }
        self._figure_type_map = data.get("figure_type_map", {})
        self._entities = [(t, _compile(t)) for t in data.get("entities", [])]

    def annotate(self, figure: Figure, article: ArticleRef) -> WeakAnnotations:
        caption = (figure.caption or "").lower()
        title = (article.title or "").lower()
        matched: dict[str, list[str]] = {}

        nf, nf_score = self._nf_relevance(caption, title, matched)
        modality, figure_type = self._modality(caption, matched)
        entities = self._entity_matches(caption, matched)

        return WeakAnnotations(
            nf_relevance=nf,
            nf_relevance_score=nf_score,
            modality=modality,
            figure_type=figure_type,
            entities=entities,
            matched_terms=matched,
        )

    # -- NF relevance ------------------------------------------------------ #
    def _nf_relevance(
        self, caption: str, title: str, matched: dict[str, list[str]]
    ) -> tuple[NFRelevance, float]:
        cap_nf1 = _hits(self._nf1, caption)
        cap_nf2 = _hits(self._nf2, caption)
        title_nf1 = _hits(self._nf1, title)
        title_nf2 = _hits(self._nf2, title)

        has_nf1 = bool(cap_nf1 or title_nf1)
        has_nf2 = bool(cap_nf2 or title_nf2)
        if cap_nf1 or cap_nf2:
            matched["nf_caption"] = sorted(set(cap_nf1 + cap_nf2))
        if title_nf1 or title_nf2:
            matched["nf_title"] = sorted(set(title_nf1 + title_nf2))

        if has_nf1 and has_nf2:
            label = NFRelevance.BOTH
        elif has_nf1:
            label = NFRelevance.NF1
        elif has_nf2:
            label = NFRelevance.NF2
        else:
            return NFRelevance.NONE, 0.0

        # Confidence: caption evidence is stronger than title-only context.
        in_caption = bool(cap_nf1 or cap_nf2)
        score = 0.9 if in_caption else 0.5
        return label, score

    # -- modality / figure type ------------------------------------------- #
    def _modality(
        self, caption: str, matched: dict[str, list[str]]
    ) -> tuple[Modality, FigureType]:
        counts: dict[str, list[str]] = {}
        for mod, patterns in self._modalities.items():
            hits = _hits(patterns, caption)
            if hits:
                counts[mod] = hits
                matched[f"modality:{mod}"] = hits

        if not counts:
            return Modality.UNKNOWN, FigureType.UNKNOWN

        # Primary modality = most keyword hits; YAML order breaks ties.
        primary = max(counts, key=lambda m: len(counts[m]))
        figure_types = {self._figure_type_map.get(m) for m in counts}
        figure_types.discard(None)
        if len(figure_types) > 1:
            figure_type = FigureType.MIXED
        else:
            figure_type = _to_figure_type(next(iter(figure_types), None))
        return Modality(primary), figure_type

    # -- entities ---------------------------------------------------------- #
    def _entity_matches(
        self, caption: str, matched: dict[str, list[str]]
    ) -> list[str]:
        found = [term for term, pat in self._entities if pat.search(caption)]
        if found:
            matched["entities"] = found
        return found


def _hits(patterns: list[re.Pattern], text: str) -> list[str]:
    return [p.pattern for p in patterns if p.search(text)]


def _to_figure_type(value: str | None) -> FigureType:
    if value is None:
        return FigureType.UNKNOWN
    try:
        return FigureType(value)
    except ValueError:
        return FigureType.UNKNOWN
