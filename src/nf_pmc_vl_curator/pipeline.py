"""The orchestrator that wires the agent modules into a curation pipeline.

Two entry points:

  * :meth:`Pipeline.run` -- the full networked pipeline
    (search -> OA check -> download -> extract -> annotate -> quality -> export).
  * :meth:`Pipeline.run_from_xml` -- curate a set of *local* JATS XML files
    (no network). This powers dry-run mode, the bundled sample data, and the
    "adapt to your own corpus" workflow.

Both paths converge on the same record-building + annotation + quality + export
tail, so the two modes produce identically-shaped datasets.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, Optional

from . import __version__
from .agents import (
    AnnotationAgent,
    DownloadAgent,
    ExportAgent,
    FigureExtractionAgent,
    OAAvailabilityAgent,
    QualityAgent,
    SearchAgent,
)
from .config import Config
from .http_client import HTTPClient
from .models import ArticleRef, Figure, FigureRecord, OARecord

log = logging.getLogger(__name__)


class Pipeline:
    """End-to-end curation pipeline."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.client = HTTPClient(config.ncbi, dry_run=config.dry_run)
        self.search = SearchAgent(self.client)
        self.oa = OAAvailabilityAgent(self.client)
        self.downloader = DownloadAgent(self.client, config.cache_dir)
        self.extractor = FigureExtractionAgent()
        self.annotator = AnnotationAgent(config.keywords_path)
        self.quality = QualityAgent()
        self.exporter = ExportAgent()

        # Optional pixel-based modality classifier (Claude vision). Only built
        # when enabled and online; lazily talks to the anthropic SDK.
        self.image_agent = None
        if config.vision.classify_images and not config.dry_run:
            from .agents import ImageModalityAgent

            self.image_agent = ImageModalityAgent(
                model=config.vision.model,
                api_key=config.vision.api_key,
                max_long_edge=config.vision.max_long_edge,
            )

    # ------------------------------------------------------------------ #
    # Networked pipeline
    # ------------------------------------------------------------------ #
    def run(self, *, download_assets: bool = True) -> dict:
        """Run the full networked pipeline and export a dataset."""
        refs = self.search.run(self.config)
        oa_map = self.oa.run(refs, self.config)

        records: list[FigureRecord] = []
        for ref in refs:
            oa = oa_map.get(ref.pmcid)
            if oa is None or not oa.oa_available:
                log.info("skipping %s: not Open Access", ref.pmcid)
                continue
            try:
                xml_path = self.downloader.fetch_article_xml(ref.pmcid)
                _, figures = self.extractor.parse_file(xml_path)
                if download_assets:
                    figures = self.downloader.fetch_assets(oa, figures)
            except Exception as exc:  # keep curating other articles
                log.warning("failed to process %s: %s", ref.pmcid, exc)
                continue
            records.extend(
                self._build_records(ref, figures, oa=oa, source_xml=str(xml_path))
            )

        return self._finish(records)

    # ------------------------------------------------------------------ #
    # Offline pipeline (dry-run / sample / custom corpus)
    # ------------------------------------------------------------------ #
    def run_from_xml(self, xml_paths: Iterable[Path]) -> dict:
        """Curate from local JATS XML files without any network access."""
        records: list[FigureRecord] = []
        for path in xml_paths:
            path = Path(path)
            from xml.etree import ElementTree as ET

            root = ET.fromstring(path.read_text(encoding="utf-8"))
            ref = self.extractor.extract_article_ref(root)
            figures = self.extractor.extract_figures(root)
            license_info = self.extractor.extract_license(root)
            oa = OARecord(
                pmcid=ref.pmcid,
                oa_available=True,
                license=license_info,
                package_url=None,
                retrieved_at=None,
            )
            records.extend(
                self._build_records(ref, figures, oa=oa, source_xml=str(path))
            )
        return self._finish(records)

    # ------------------------------------------------------------------ #
    # Shared tail
    # ------------------------------------------------------------------ #
    def _build_records(
        self,
        ref: ArticleRef,
        figures: list[Figure],
        *,
        oa: OARecord,
        source_xml: str,
    ) -> list[FigureRecord]:
        provenance_base = {
            "search_query": self.config.search.query if not self.config.dry_run else None,
            "source_xml": source_xml,
            "package_url": oa.package_url,
            "oa_retrieved_at": oa.retrieved_at,
            "tool_version": __version__,
        }
        out: list[FigureRecord] = []
        for fig in figures:
            annotations = self.annotator.annotate(fig, ref)
            if self.image_agent is not None and fig.local_image_path:
                try:
                    annotations.image_modality = self.image_agent.classify(
                        fig.local_image_path, caption=fig.caption
                    )
                except Exception as exc:  # vision is best-effort enrichment
                    log.warning("image classification failed for %s: %s",
                                fig.fig_id, exc)
            out.append(
                FigureRecord(
                    record_id=FigureRecord.make_id(ref.pmcid, fig.fig_id),
                    article=ref,
                    figure=fig,
                    license=oa.license,
                    annotations=annotations,
                    provenance=dict(provenance_base),
                )
            )
        return out

    def _finish(self, records: list[FigureRecord]) -> dict:
        records = self.quality.run(records, self.config.quality)
        return self.exporter.run(records, self.config.output_dir)


def sample_xml_files(root: Optional[Path] = None) -> list[Path]:
    """Locate the bundled sample JATS XML files (used by dry-run)."""
    if root is None:
        # repo layout: <repo>/data/sample/*.xml
        repo_root = Path(__file__).resolve().parents[2]
        root = repo_root / "data" / "sample"
    return sorted(Path(root).glob("*.xml"))
