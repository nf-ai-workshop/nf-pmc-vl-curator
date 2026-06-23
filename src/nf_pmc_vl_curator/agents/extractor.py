"""Stage 4 -- FigureExtractionAgent.

Parses a JATS/NLM full-text XML document into figure/caption pairs and the
article's bibliographic reference.

JATS uses XML namespaces (notably ``xlink`` for ``<graphic xlink:href>``). To
keep the parser robust across the slightly different DTD versions PMC serves,
we match on *local* element names (ignoring namespace prefixes) and look for
any attribute whose local name is ``href``.
"""

from __future__ import annotations

import logging
import re
from xml.etree import ElementTree as ET

from ..models import ArticleRef, Figure, LicenseInfo

log = logging.getLogger(__name__)

_WS = re.compile(r"\s+")
_CC_RE = re.compile(r"\bCC[ -]?(BY(?:[ -](?:NC|SA|ND))*|0)\b", re.IGNORECASE)


def _local(tag: str) -> str:
    """Strip the ``{namespace}`` prefix from an ElementTree tag."""
    return tag.rsplit("}", 1)[-1]


def _findall_local(elem: ET.Element, name: str) -> list[ET.Element]:
    return [e for e in elem.iter() if _local(e.tag) == name]


def _href(elem: ET.Element) -> str | None:
    for key, value in elem.attrib.items():
        if _local(key) == "href":
            return value
    return None


def _text_content(elem: ET.Element) -> str:
    """Collapse all descendant text into a single normalised string."""
    text = "".join(elem.itertext())
    return _WS.sub(" ", text).strip()


class FigureExtractionAgent:
    """Extract figures + article metadata from JATS XML."""

    def parse(self, xml_text: str) -> tuple[ArticleRef, list[Figure]]:
        root = ET.fromstring(xml_text)
        return self.extract_article_ref(root), self.extract_figures(root)

    def parse_file(self, path) -> tuple[ArticleRef, list[Figure]]:
        from pathlib import Path

        return self.parse(Path(path).read_text(encoding="utf-8"))

    # -- license (from JATS <permissions>) --------------------------------- #
    def extract_license(self, root: ET.Element) -> LicenseInfo | None:
        """Best-effort license from the JATS ``<permissions><license>`` block.

        Used as a fallback when curating from local XML without an OA-service
        lookup, so offline/sample records still carry license metadata.
        """
        from .oa_checker import normalize_license

        license_el = next(iter(_findall_local(root, "license")), None)
        if license_el is None:
            return None
        text = _text_content(license_el)
        href = _href(license_el)
        match = _CC_RE.search(text) or _CC_RE.search(href or "")
        code = None
        if match:
            g = match.group(1).upper()
            code = "CC0" if g == "0" else "CC " + "-".join(re.split(r"[ -]+", g))
        elif "publicdomain/zero" in (href or ""):
            code = "CC0"  # canonical CC0 deed URL carries no "CC0" string
        info = normalize_license(code) if code else None
        if info is None:
            return LicenseInfo(code="unknown", url=href, raw=text or None)
        info.url = info.url or href
        info.raw = text or info.raw
        return info

    # -- figures ----------------------------------------------------------- #
    def extract_figures(self, root: ET.Element) -> list[Figure]:
        figures: list[Figure] = []
        for i, fig in enumerate(_findall_local(root, "fig"), start=1):
            fig_id = fig.get("id") or f"fig{i}"
            label = None
            caption = ""
            for child in fig:
                if _local(child.tag) == "label":
                    label = _text_content(child)
                elif _local(child.tag) == "caption":
                    caption = _text_content(child)
            graphic = next(iter(_findall_local(fig, "graphic")), None)
            href = _href(graphic) if graphic is not None else None
            figures.append(
                Figure(fig_id=fig_id, label=label, caption=caption, graphic_href=href)
            )
        log.debug("extracted %d figures", len(figures))
        return figures

    # -- article metadata -------------------------------------------------- #
    def extract_article_ref(self, root: ET.Element) -> ArticleRef:
        ids = {}
        for el in _findall_local(root, "article-id"):
            id_type = el.get("pub-id-type")
            if id_type:
                ids[id_type] = (el.text or "").strip()

        pmcid = ids.get("pmc") or ids.get("pmcid") or ""
        if pmcid and not pmcid.upper().startswith("PMC"):
            pmcid = f"PMC{pmcid}"

        title_el = next(iter(_findall_local(root, "article-title")), None)
        journal_el = next(iter(_findall_local(root, "journal-title")), None)

        year = None
        for el in _findall_local(root, "year"):
            txt = (el.text or "").strip()
            if txt.isdigit():
                year = int(txt)
                break

        return ArticleRef(
            pmid=ids.get("pmid"),
            pmcid=pmcid or "PMC0000000",
            doi=ids.get("doi"),
            title=_text_content(title_el) if title_el is not None else None,
            journal=_text_content(journal_el) if journal_el is not None else None,
            pub_year=year,
        )
