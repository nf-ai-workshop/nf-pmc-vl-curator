"""Shared pytest fixtures."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = REPO_ROOT / "data" / "sample"
KEYWORDS = REPO_ROOT / "src" / "nf_pmc_vl_curator" / "resources" / "annotation_keywords.yaml"


@pytest.fixture
def sample_dir() -> Path:
    return SAMPLE_DIR


@pytest.fixture
def sample_xml_files() -> list[Path]:
    return sorted(SAMPLE_DIR.glob("*.xml"))


@pytest.fixture
def keywords_path() -> Path:
    return KEYWORDS


# A trimmed but representative PMC OA service (oa.fcgi) response.
OA_XML_OK = """<?xml version="1.0"?>
<OA>
  <responseDate>2024-01-01 00:00:00</responseDate>
  <request id="PMC9000001">https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id=PMC9000001</request>
  <records returned-count="1" total-count="1">
    <record id="PMC9000001" citation="J Synth 2021" license="CC BY">
      <link format="tgz" updated="2021-01-01"
            href="ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_package/00/00/PMC9000001.tar.gz"/>
      <link format="pdf" href="ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_pdf/PMC9000001.pdf"/>
    </record>
  </records>
</OA>"""

OA_XML_NOT_OA = """<?xml version="1.0"?>
<OA>
  <responseDate>2024-01-01 00:00:00</responseDate>
  <request id="PMC1">...</request>
  <error code="idIsNotOpenAccess">identifier 'PMC1' is not in the OA subset</error>
</OA>"""


@pytest.fixture
def oa_xml_ok() -> str:
    return OA_XML_OK


@pytest.fixture
def oa_xml_not_oa() -> str:
    return OA_XML_NOT_OA
