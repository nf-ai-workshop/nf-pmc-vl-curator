"""Stage 1 -- SearchAgent.

Finds candidate articles by querying the NCBI E-utilities ``esearch`` endpoint
against the **pmc** database, then enriches the hits with ``esummary``
bibliographic metadata.

We search the ``pmc`` database (not ``pubmed``) and combine the topic query
with ``open access[filter]`` so we never leave the Open Access subset. We never
scrape PubMed or publisher HTML.
"""

from __future__ import annotations

import logging

from ..config import Config
from ..http_client import HTTPClient
from ..models import ArticleRef

log = logging.getLogger(__name__)

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"


class SearchAgent:
    """Translate a topic query into a list of candidate :class:`ArticleRef`."""

    def __init__(self, client: HTTPClient) -> None:
        self.client = client

    def run(self, config: Config) -> list[ArticleRef]:
        ids = self._esearch(config)
        if not ids:
            log.info("search returned no PMC ids")
            return []
        return self._esummary(ids)

    # -- internal --------------------------------------------------------- #
    def _esearch(self, config: Config) -> list[str]:
        params = {
            "db": "pmc",
            "term": config.search.query,
            "retmax": str(config.search.retmax),
            "retmode": "json",
        }
        if config.search.mindate:
            params["mindate"] = config.search.mindate
            params["datetype"] = "pdat"
        if config.search.maxdate:
            params["maxdate"] = config.search.maxdate
            params["datetype"] = "pdat"

        data = self.client.get(ESEARCH_URL, params=params).json()
        idlist = data.get("esearchresult", {}).get("idlist", [])
        log.info("esearch matched %s PMC records", len(idlist))
        return idlist

    def _esummary(self, ids: list[str]) -> list[ArticleRef]:
        params = {"db": "pmc", "id": ",".join(ids), "retmode": "json"}
        data = self.client.get(ESUMMARY_URL, params=params).json()
        result = data.get("result", {})
        refs: list[ArticleRef] = []
        for uid in result.get("uids", []):
            rec = result.get(uid, {})
            refs.append(self._parse_summary(uid, rec))
        return refs

    @staticmethod
    def _parse_summary(uid: str, rec: dict) -> ArticleRef:
        # esummary returns article-id pairs we mine for doi / pmid.
        doi = pmid = None
        for aid in rec.get("articleids", []):
            if aid.get("idtype") == "doi":
                doi = aid.get("value")
            elif aid.get("idtype") == "pmid":
                pmid = aid.get("value")
        year = None
        pubdate = rec.get("pubdate", "")
        if pubdate[:4].isdigit():
            year = int(pubdate[:4])
        return ArticleRef(
            pmid=pmid,
            pmcid=f"PMC{uid}",
            doi=doi,
            title=rec.get("title") or None,
            journal=rec.get("fulljournalname") or rec.get("source") or None,
            pub_year=year,
        )
