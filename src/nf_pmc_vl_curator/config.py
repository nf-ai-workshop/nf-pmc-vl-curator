"""Pipeline configuration: typed, file-backed, with sane defaults.

Configuration is loaded from a YAML file and validated into a :class:`Config`
model. CLI flags can override individual fields. Keeping config typed means a
bad value fails fast with a clear error instead of surfacing deep in a network
call.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


# Default keyword resources live next to the source so the package is runnable
# out of the box.
_PKG_ROOT = Path(__file__).resolve().parent
DEFAULT_KEYWORDS_PATH = _PKG_ROOT / "resources" / "annotation_keywords.yaml"


class NCBIConfig(BaseModel):
    """Identity + politeness settings for NCBI E-utilities / PMC OA service.

    NCBI asks every client to identify itself with a ``tool`` name and contact
    ``email``. Supplying an ``api_key`` raises the rate limit from 3 to 10
    requests/second.
    """

    tool: str = "nf-pmc-vl-curator"
    email: str = "you@example.com"
    api_key: Optional[str] = None
    requests_per_second: float = Field(
        default=3.0, gt=0, description="Client-side rate limit (NCBI allows 3 w/o key)."
    )
    timeout_seconds: float = 30.0
    max_retries: int = 3


class SearchConfig(BaseModel):
    """What to search for."""

    query: str = (
        '(neurofibromatosis type 1[Title/Abstract] OR NF1[Title/Abstract] '
        'OR neurofibromatosis type 2[Title/Abstract] OR NF2[Title/Abstract]) '
        'AND open access[filter]'
    )
    retmax: int = Field(default=20, ge=1, le=10000)
    mindate: Optional[str] = Field(default=None, description="YYYY or YYYY/MM/DD.")
    maxdate: Optional[str] = None


class QualityConfig(BaseModel):
    """Thresholds for the quality agent."""

    min_caption_length: int = 30
    require_image_file: bool = False
    require_license: bool = True
    drop_not_nf_relevant: bool = False


class Config(BaseModel):
    """Top-level pipeline configuration."""

    ncbi: NCBIConfig = Field(default_factory=NCBIConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    quality: QualityConfig = Field(default_factory=QualityConfig)

    keywords_path: Path = DEFAULT_KEYWORDS_PATH
    output_dir: Path = Path("output")
    cache_dir: Path = Path("cache")

    # When True, no network calls are made and only sample/cached data is used.
    dry_run: bool = False


def load_config(path: Optional[Path] = None) -> Config:
    """Load configuration from a YAML file, falling back to built-in defaults.

    Unknown keys in the YAML are rejected by Pydantic, which catches typos like
    ``retmaxx`` early.
    """
    if path is None:
        return Config()
    data = yaml.safe_load(Path(path).read_text()) or {}
    return Config.model_validate(data)
