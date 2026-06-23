"""Stage 2 -- OAAvailabilityAgent.

Confirms an article is in the PMC **Open Access subset** and captures its
license and downloadable-package URL via the PMC OA Web Service
(``oa.fcgi``). Articles that are not OA are dropped here, which guarantees the
MVP constraint "PMC Open Access only".

OA service docs: https://www.ncbi.nlm.nih.gov/pmc/tools/oa-service/
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

from ..config import Config
from ..http_client import HTTPClient
from ..models import ArticleRef, LicenseInfo, OARecord

log = logging.getLogger(__name__)

OA_URL = "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi"

# Map the OA service's license strings to canonical URLs.
_LICENSE_URLS = {
    "CC BY": "https://creativecommons.org/licenses/by/4.0/",
    "CC BY-SA": "https://creativecommons.org/licenses/by-sa/4.0/",
    "CC BY-NC": "https://creativecommons.org/licenses/by-nc/4.0/",
    "CC BY-NC-SA": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
    "CC BY-NC-ND": "https://creativecommons.org/licenses/by-nc-nd/4.0/",
    "CC BY-ND": "https://creativecommons.org/licenses/by-nd/4.0/",
    "CC0": "https://creativecommons.org/publicdomain/zero/1.0/",
}


def normalize_license(raw: str | None) -> LicenseInfo | None:
    """Turn the OA service's raw license string into :class:`LicenseInfo`."""
    if not raw:
        return None
    code = raw.strip().upper().replace("CC-", "CC ").replace("LICENSE", "").strip()
    # The OA service typically uses forms like "CC BY" already.
    code = " ".join(code.split())
    url = _LICENSE_URLS.get(code)
    return LicenseInfo(
        code=code or raw.strip(),
        url=url,
        requires_attribution=code != "CC0",
        raw=raw,
    )


class OAAvailabilityAgent:
    """Check OA status for each candidate article."""

    def __init__(self, client: HTTPClient) -> None:
        self.client = client

    def run(self, refs: list[ArticleRef], config: Config) -> dict[str, OARecord]:
        out: dict[str, OARecord] = {}
        for ref in refs:
            out[ref.pmcid] = self.check(ref.pmcid)
        n_oa = sum(1 for r in out.values() if r.oa_available)
        log.info("OA check: %d/%d articles are Open Access", n_oa, len(out))
        return out

    def check(self, pmcid: str) -> OARecord:
        now = datetime.now(timezone.utc).isoformat()
        resp = self.client.get(OA_URL, params={"id": pmcid})
        return self.parse_oa_xml(pmcid, resp.text, retrieved_at=now)

    @staticmethod
    def parse_oa_xml(pmcid: str, xml_text: str, *, retrieved_at: str) -> OARecord:
        """Parse an ``oa.fcgi`` XML response into an :class:`OARecord`.

        Exposed as a static method so it can be unit-tested without a network.
        """
        root = ET.fromstring(xml_text)
        if root.find("error") is not None:
            return OARecord(pmcid=pmcid, oa_available=False, retrieved_at=retrieved_at)

        record = root.find(".//record")
        if record is None:
            return OARecord(pmcid=pmcid, oa_available=False, retrieved_at=retrieved_at)

        license_info = normalize_license(record.get("license"))
        package_url = None
        for link in record.findall("link"):
            if link.get("format") == "tgz":
                package_url = link.get("href")
                break
        return OARecord(
            pmcid=pmcid,
            oa_available=True,
            license=license_info,
            package_url=package_url,
            retrieved_at=retrieved_at,
        )
