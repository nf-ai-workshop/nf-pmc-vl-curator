"""Typed data models for the NF PMC vision-language curation pipeline.

These Pydantic models are the *contract* that flows between the agent-like
modules. Each stage of the pipeline consumes and/or produces one of these
types, so the models double as documentation of the data shape at every step.

The export unit is :class:`FigureRecord` -- one figure/caption/image triple
with its weak annotations, quality flags, license and full provenance.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Controlled vocabularies (weak-annotation label spaces)
# --------------------------------------------------------------------------- #
class NFRelevance(str, Enum):
    """Whether a figure's article context relates to NF1, NF2, both or neither."""

    NF1 = "nf1"
    NF2 = "nf2"
    BOTH = "both"
    NONE = "none"
    UNKNOWN = "unknown"


class Modality(str, Enum):
    """Coarse imaging modality inferred from the caption text."""

    MRI = "mri"
    CT = "ct"
    ULTRASOUND = "ultrasound"
    XRAY = "xray"
    PET = "pet"
    HISTOLOGY = "histology"
    CLINICAL_PHOTO = "clinical_photo"
    ILLUSTRATION = "illustration"
    CHART = "chart"
    UNKNOWN = "unknown"


class FigureType(str, Enum):
    """Higher-level figure category (groups several modalities)."""

    RADIOLOGY = "radiology"
    HISTOPATHOLOGY = "histopathology"
    CLINICAL_PHOTO = "clinical_photo"
    DIAGRAM = "diagram"
    CHART = "chart"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class QualityFlag(str, Enum):
    """Machine-checkable issues raised by the quality agent."""

    MISSING_CAPTION = "missing_caption"
    SHORT_CAPTION = "short_caption"
    MISSING_IMAGE = "missing_image"
    MISSING_LICENSE = "missing_license"
    NOT_NF_RELEVANT = "not_nf_relevant"
    NO_MODALITY = "no_modality"
    DUPLICATE_CAPTION = "duplicate_caption"
    MODALITY_DISAGREEMENT = "modality_disagreement"  # caption label != image label


class ReviewStatus(str, Enum):
    """Human-in-the-loop review state for a record."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


# --------------------------------------------------------------------------- #
# Provenance / article-level models
# --------------------------------------------------------------------------- #
class LicenseInfo(BaseModel):
    """Normalised license metadata. Preserved for every image."""

    code: str = Field(description="Short license code, e.g. 'CC BY', 'CC BY-NC'.")
    url: Optional[str] = Field(default=None, description="Canonical license URL.")
    requires_attribution: bool = Field(
        default=True, description="True for all CC licenses except CC0."
    )
    raw: Optional[str] = Field(
        default=None, description="Raw license string as found in the OA record."
    )


class ArticleRef(BaseModel):
    """Bibliographic reference for a source article."""

    pmid: Optional[str] = None
    pmcid: str = Field(description="PMC accession, e.g. 'PMC1234567'.")
    doi: Optional[str] = None
    title: Optional[str] = None
    journal: Optional[str] = None
    pub_year: Optional[int] = None


class OARecord(BaseModel):
    """Result of the PMC Open Access availability check for one article."""

    pmcid: str
    oa_available: bool
    license: Optional[LicenseInfo] = None
    package_url: Optional[str] = Field(
        default=None, description="URL of the OA .tar.gz package (file-list service)."
    )
    retrieved_at: Optional[str] = Field(
        default=None, description="ISO-8601 timestamp of the OA lookup."
    )


class Figure(BaseModel):
    """A single figure parsed out of a JATS XML article."""

    fig_id: str = Field(description="Stable id within the article, e.g. 'fig1'.")
    label: Optional[str] = Field(default=None, description="e.g. 'Figure 1'.")
    caption: str = Field(default="", description="Plain-text caption / legend.")
    graphic_href: Optional[str] = Field(
        default=None, description="Image filename referenced by <graphic xlink:href>."
    )
    local_image_path: Optional[str] = Field(
        default=None, description="Path on disk once the asset is downloaded."
    )


# --------------------------------------------------------------------------- #
# Annotation / quality models
# --------------------------------------------------------------------------- #
class ImageModalityResult(BaseModel):
    """Image-derived modality label from a vision model (pixels, not caption).

    This is the *stronger* modality signal: it looks at the figure itself, so it
    resolves cases the caption-based annotator can't (MRI vs CT, real photo vs
    illustration, multi-panel composites).
    """

    modality: Modality = Modality.UNKNOWN
    figure_type: FigureType = FigureType.UNKNOWN
    is_multipanel: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: Optional[str] = None
    model: Optional[str] = Field(default=None, description="Vision model id used.")


class WeakAnnotations(BaseModel):
    """Heuristic (non-expert) labels derived from caption + article context.

    These are deliberately *weak*: keyword/regex driven, meant as a starting
    point for downstream filtering or active-learning, not ground truth.
    """

    nf_relevance: NFRelevance = NFRelevance.UNKNOWN
    nf_relevance_score: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Confidence in the NF relevance label."
    )
    modality: Modality = Modality.UNKNOWN
    figure_type: FigureType = FigureType.UNKNOWN
    entities: list[str] = Field(
        default_factory=list,
        description="Matched lesion/entity keywords, e.g. 'plexiform neurofibroma'.",
    )
    matched_terms: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Audit trail: which keywords triggered which label.",
    )
    # Populated only when image classification is enabled; the higher-quality
    # (pixel-based) counterpart to the caption-derived modality/figure_type above.
    image_modality: Optional[ImageModalityResult] = None


class QualityReport(BaseModel):
    """Outcome of the quality agent for one figure record."""

    flags: list[QualityFlag] = Field(default_factory=list)
    passed: bool = True

    @property
    def is_clean(self) -> bool:
        return not self.flags


class ReviewInfo(BaseModel):
    """A human reviewer's decision on a record (the curation layer).

    Persisted separately (see :mod:`nf_pmc_vl_curator.curation`) and merged back
    onto records, so the automated weak labels and the human judgement are both
    auditable. ``corrections`` records any label the reviewer changed.
    """

    status: ReviewStatus = ReviewStatus.PENDING
    reviewer: Optional[str] = None
    decided_at: Optional[str] = Field(default=None, description="ISO-8601 timestamp.")
    notes: Optional[str] = None
    corrections: dict[str, str] = Field(
        default_factory=dict,
        description="Audit of human label edits: field name -> new value.",
    )


# --------------------------------------------------------------------------- #
# Export unit
# --------------------------------------------------------------------------- #
class FigureRecord(BaseModel):
    """The exported dataset row: one image/caption pair + everything about it.

    This is what gets written to JSONL. It bundles the figure, its annotations,
    quality report, license and provenance so the dataset is self-describing.
    """

    record_id: str = Field(description="Globally unique id: '<pmcid>:<fig_id>'.")
    article: ArticleRef
    figure: Figure
    license: Optional[LicenseInfo] = None
    annotations: WeakAnnotations = Field(default_factory=WeakAnnotations)
    quality: QualityReport = Field(default_factory=QualityReport)

    # Human-in-the-loop review (None until a reviewer touches the record).
    review: Optional[ReviewInfo] = None

    # Provenance: how this record came to exist.
    provenance: dict[str, Optional[str]] = Field(
        default_factory=dict,
        description="search_query, source_xml, package_url, retrieved_at, tool_version.",
    )

    @staticmethod
    def make_id(pmcid: str, fig_id: str) -> str:
        return f"{pmcid}:{fig_id}"
