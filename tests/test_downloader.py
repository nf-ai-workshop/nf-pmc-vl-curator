"""Offline tests for the asset-download logic (URL handling + image matching)."""

import tarfile

import pytest
import requests

from nf_pmc_vl_curator.agents.downloader import DownloadAgent, candidate_package_urls
from nf_pmc_vl_curator.config import NCBIConfig
from nf_pmc_vl_curator.http_client import HTTPClient
from nf_pmc_vl_curator.models import Figure, LicenseInfo, OARecord


def test_candidate_urls_ftp_to_https_and_deprecated_fallback():
    ftp = "ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_package/1b/4a/PMC1.tar.gz"
    cands = candidate_package_urls(ftp)
    assert cands == [
        "https://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_package/1b/4a/PMC1.tar.gz",
        "https://ftp.ncbi.nlm.nih.gov/pub/pmc/deprecated/oa_package/1b/4a/PMC1.tar.gz",
    ]


def test_candidate_urls_no_double_deprecated():
    already = "ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/deprecated/oa_package/x/PMC1.tar.gz"
    cands = candidate_package_urls(already)
    assert len(cands) == 1
    assert cands[0].startswith("https://")


def test_index_images_prefers_largest_per_stem(tmp_path):
    (tmp_path / "fig1.gif").write_bytes(b"x" * 10)      # thumbnail
    (tmp_path / "fig1.jpg").write_bytes(b"x" * 1000)    # full-res
    index = DownloadAgent._index_images(tmp_path)
    assert index["fig1"].suffix == ".jpg"


def test_fetch_assets_extracts_and_matches(tmp_path, monkeypatch):
    # Build a fake OA .tar.gz containing two images + a noise file.
    src = tmp_path / "src"
    src.mkdir()
    (src / "PMC1_fig1.jpg").write_bytes(b"\xff\xd8\xff\xe0jpegdata")
    (src / "PMC1_fig2.png").write_bytes(b"\x89PNGdata")
    (src / "article.nxml").write_bytes(b"<article/>")
    tgz = tmp_path / "pkg.tar.gz"
    with tarfile.open(tgz, "w:gz") as tar:
        for f in src.iterdir():
            tar.add(f, arcname=f"PMC1/{f.name}")

    client = HTTPClient(NCBIConfig(), dry_run=False)
    # Stub the network download to just copy our local tarball into place.
    def fake_download(url, dest, add_identity=False):
        dest = __import__("pathlib").Path(dest)
        dest.write_bytes(tgz.read_bytes())
    monkeypatch.setattr(client, "download", fake_download)

    agent = DownloadAgent(client, tmp_path / "cache")
    oa = OARecord(pmcid="PMC1", oa_available=True,
                  license=LicenseInfo(code="CC BY"),
                  package_url="ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_package/x/PMC1.tar.gz")
    figs = [Figure(fig_id="f1", graphic_href="PMC1_fig1.jpg"),
            Figure(fig_id="f2", graphic_href="PMC1_fig2"),       # no extension
            Figure(fig_id="f3", graphic_href="missing.jpg")]
    out = agent.fetch_assets(oa, figs)

    assert out[0].local_image_path and out[0].local_image_path.endswith("PMC1_fig1.jpg")
    assert out[1].local_image_path and out[1].local_image_path.endswith("PMC1_fig2.png")
    assert out[2].local_image_path is None  # unmatched href stays unresolved


def test_http_client_does_not_retry_404(monkeypatch):
    """A permanent 404 must fail immediately, not after max_retries attempts."""
    calls = {"n": 0}

    class FakeResp:
        status_code = 404
        def raise_for_status(self):
            raise requests.HTTPError("404")

    client = HTTPClient(NCBIConfig(max_retries=3), dry_run=False)

    def fake_get(url, params=None, timeout=None):
        calls["n"] += 1
        return FakeResp()

    monkeypatch.setattr(client._session, "get", fake_get)
    with pytest.raises(requests.HTTPError):
        client.get("https://example.com/missing")
    assert calls["n"] == 1  # exactly one attempt, no retries on 404
