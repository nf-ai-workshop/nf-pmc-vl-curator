from nf_pmc_vl_curator.agents.oa_checker import OAAvailabilityAgent, normalize_license


def test_parse_oa_ok(oa_xml_ok):
    rec = OAAvailabilityAgent.parse_oa_xml("PMC9000001", oa_xml_ok, retrieved_at="t")
    assert rec.oa_available is True
    assert rec.license is not None
    assert rec.license.code == "CC BY"
    assert rec.package_url.endswith("PMC9000001.tar.gz")
    assert rec.package_url.startswith("ftp://")  # raw href preserved as-is
    assert rec.retrieved_at == "t"


def test_parse_oa_not_open_access(oa_xml_not_oa):
    rec = OAAvailabilityAgent.parse_oa_xml("PMC1", oa_xml_not_oa, retrieved_at="t")
    assert rec.oa_available is False
    assert rec.license is None
    assert rec.package_url is None


def test_normalize_license_cc_by():
    lic = normalize_license("CC BY")
    assert lic.code == "CC BY"
    assert lic.requires_attribution is True
    assert "creativecommons.org" in lic.url


def test_normalize_license_cc0_no_attribution():
    lic = normalize_license("CC0")
    assert lic.requires_attribution is False


def test_normalize_license_none():
    assert normalize_license(None) is None
    assert normalize_license("") is None
