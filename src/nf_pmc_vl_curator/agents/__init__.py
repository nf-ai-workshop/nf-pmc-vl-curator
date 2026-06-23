"""Agent-like pipeline modules.

Each module in this package is a small, single-responsibility "agent": it has
one job, a typed input and a typed output, and no knowledge of the stages
around it. The :mod:`nf_pmc_vl_curator.pipeline` orchestrator wires them into a
sequence. This mirrors how a coding agent might decompose a curation task into
inspectable, individually-testable steps.

Stages (in order):
    1. SearchAgent          -- find candidate articles (PMC E-utilities)
    2. OAAvailabilityAgent  -- confirm Open Access + capture license/package URL
    3. DownloadAgent        -- fetch article XML (and figure assets)
    4. FigureExtractionAgent-- parse JATS XML into figure/caption pairs
    5. AnnotationAgent      -- attach weak labels (NF relevance, modality, ...)
    6. QualityAgent         -- raise quality flags
    7. ExportAgent          -- write the dataset as JSONL
"""

from .search import SearchAgent
from .oa_checker import OAAvailabilityAgent
from .downloader import DownloadAgent
from .extractor import FigureExtractionAgent
from .annotator import AnnotationAgent
from .quality import QualityAgent
from .exporter import ExportAgent

__all__ = [
    "SearchAgent",
    "OAAvailabilityAgent",
    "DownloadAgent",
    "FigureExtractionAgent",
    "AnnotationAgent",
    "QualityAgent",
    "ExportAgent",
]
