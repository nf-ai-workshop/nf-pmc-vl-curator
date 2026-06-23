"""Stage 3 -- DownloadAgent.

Fetches the two things downstream stages need:

  * the article **full-text XML** (JATS/NLM) via E-utilities ``efetch``, and
  * the **figure image assets**, extracted from the article's OA ``.tar.gz``
    package (the only sanctioned bulk source for OA figure files).

All downloads are cached on disk and keyed by PMCID so re-runs are cheap and
reproducible. We never fetch from publisher HTML pages.
"""

from __future__ import annotations

import logging
import tarfile
from pathlib import Path

from ..http_client import HTTPClient
from ..models import Figure, OARecord

log = logging.getLogger(__name__)

EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

# PMC OA packages are served over HTTPS at this base (the oa.fcgi href is FTP).
_FTP_PREFIX = "ftp://ftp.ncbi.nlm.nih.gov/"
_HTTPS_PREFIX = "https://ftp.ncbi.nlm.nih.gov/"

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff"}


def candidate_package_urls(package_url: str) -> list[str]:
    """HTTPS URLs to try for an OA ``.tar.gz``, most-current first.

    ``oa.fcgi`` returns a legacy ``ftp://`` href. NCBI is migrating the article
    datasets: as of 2026 the per-article packages were relocated under a
    ``/pub/pmc/deprecated/`` prefix (legacy FTP files slated for removal in
    Aug 2026). We therefore try the direct HTTPS path first and fall back to the
    deprecated path, so downloads keep working through the transition. See
    docs/network_access.md for the long-term (AWS Open Data) migration.
    """
    https = package_url.replace(_FTP_PREFIX, _HTTPS_PREFIX)
    candidates = [https]
    if "/pub/pmc/deprecated/" not in https and "/pub/pmc/" in https:
        candidates.append(https.replace("/pub/pmc/", "/pub/pmc/deprecated/", 1))
    return candidates


class DownloadAgent:
    """Download + cache article XML and figure assets."""

    def __init__(self, client: HTTPClient, cache_dir: Path) -> None:
        self.client = client
        self.cache_dir = Path(cache_dir)

    # -- XML --------------------------------------------------------------- #
    def fetch_article_xml(self, pmcid: str) -> Path:
        """Return a path to the article's full-text XML, downloading if needed."""
        dest = self.cache_dir / pmcid / f"{pmcid}.xml"
        if dest.exists():
            log.debug("XML cache hit for %s", pmcid)
            return dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        numeric = pmcid.removeprefix("PMC")
        resp = self.client.get(
            EFETCH_URL, params={"db": "pmc", "id": numeric, "rettype": "xml"}
        )
        dest.write_text(resp.text, encoding="utf-8")
        return dest

    # -- assets ------------------------------------------------------------ #
    def fetch_assets(
        self, oa: OARecord, figures: list[Figure]
    ) -> list[Figure]:
        """Download the OA package and resolve each figure's local image path.

        Figures whose image cannot be located are left with
        ``local_image_path = None`` (the quality agent flags this later).
        """
        if not oa.package_url:
            log.info("%s has no package URL; skipping asset download", oa.pmcid)
            return figures

        asset_dir = self.cache_dir / oa.pmcid / "assets"
        if not asset_dir.exists():
            self._download_and_extract(oa.package_url, asset_dir)

        index = self._index_images(asset_dir)
        for fig in figures:
            if not fig.graphic_href:
                continue
            match = index.get(Path(fig.graphic_href).stem.lower())
            if match:
                fig.local_image_path = str(match)
        return figures

    def _download_and_extract(self, package_url: str, asset_dir: Path) -> None:
        asset_dir.mkdir(parents=True, exist_ok=True)
        tgz_path = asset_dir.parent / "package.tar.gz"

        candidates = candidate_package_urls(package_url)
        last_exc: Exception | None = None
        for url in candidates:
            try:
                log.info("downloading OA package %s", url)
                self.client.download(url, tgz_path)
                break
            except Exception as exc:  # 404 on a stale path -> try the next form
                log.warning("package URL failed (%s): %s", url, exc)
                last_exc = exc
        else:
            raise RuntimeError(
                f"could not download OA package from any of {candidates}"
            ) from last_exc

        with tarfile.open(tgz_path, "r:gz") as tar:
            for member in tar.getmembers():
                if Path(member.name).suffix.lower() in _IMAGE_SUFFIXES:
                    member.name = Path(member.name).name  # flatten
                    tar.extract(member, asset_dir)  # noqa: S202 (OA source trusted)

    @staticmethod
    def _index_images(asset_dir: Path) -> dict[str, Path]:
        """Map lowercased image basename (no extension) -> path on disk.

        PMC packages often ship both a small ``.gif`` thumbnail and the full
        ``.jpg`` under the same stem; when stems collide we keep the largest
        file so figures resolve to the full-resolution image, not the thumb.
        """
        index: dict[str, Path] = {}
        if not asset_dir.exists():
            return index
        for p in asset_dir.iterdir():
            if p.suffix.lower() not in _IMAGE_SUFFIXES:
                continue
            stem = p.stem.lower()
            existing = index.get(stem)
            if existing is None or p.stat().st_size > existing.stat().st_size:
                index[stem] = p
        return index
