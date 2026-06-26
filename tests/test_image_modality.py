"""Tests for the Claude-vision ImageModalityAgent (fully mocked, no network)."""

import base64
import io
import json
import types

import pytest

from nf_pmc_vl_curator.agents.image_modality import ImageModalityAgent
from nf_pmc_vl_curator.agents.quality import QualityAgent
from nf_pmc_vl_curator.config import QualityConfig
from nf_pmc_vl_curator.models import (
    ArticleRef,
    Figure,
    FigureRecord,
    FigureType,
    ImageModalityResult,
    LicenseInfo,
    Modality,
    QualityFlag,
    WeakAnnotations,
)

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


class _FakeMessages:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        block = types.SimpleNamespace(type="text", text=json.dumps(self.payload))
        return types.SimpleNamespace(content=[block])


class _FakeClient:
    def __init__(self, payload):
        self.messages = _FakeMessages(payload)


def _image(tmp_path, size=(2000, 1000)):
    p = tmp_path / "fig.jpg"
    Image.new("RGB", size, (40, 50, 60)).save(p, "JPEG")
    return p


def test_classify_parses_structured_result(tmp_path):
    client = _FakeClient({
        "modality": "ct", "figure_type": "radiology",
        "is_multipanel": True, "confidence": 0.82, "rationale": "axial CT slices",
    })
    agent = ImageModalityAgent(model="claude-haiku-4-5", client=client, max_long_edge=512)
    res = agent.classify(_image(tmp_path), caption="Axial CT of the abdomen")

    assert isinstance(res, ImageModalityResult)
    assert res.modality is Modality.CT
    assert res.figure_type is FigureType.RADIOLOGY
    assert res.is_multipanel is True
    assert res.confidence == pytest.approx(0.82)
    assert res.model == "claude-haiku-4-5"


def test_request_shape_and_downscaling(tmp_path):
    client = _FakeClient({"modality": "mri", "figure_type": "radiology",
                          "is_multipanel": False, "confidence": 0.9})
    agent = ImageModalityAgent(client=client, max_long_edge=512)
    agent.classify(_image(tmp_path, size=(2000, 1000)))

    kw = client.messages.calls[0]
    content = kw["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert content[0]["source"]["media_type"] == "image/jpeg"
    assert kw["output_config"]["format"]["type"] == "json_schema"
    # enum is enforced server-side via the schema we send
    assert "mri" in kw["output_config"]["format"]["schema"]["properties"]["modality"]["enum"]

    # image was downscaled to <= max_long_edge before sending
    raw = base64.standard_b64decode(content[0]["source"]["data"])
    with Image.open(io.BytesIO(raw)) as im:
        assert max(im.size) <= 512


def test_invalid_enum_and_confidence_are_coerced(tmp_path):
    client = _FakeClient({"modality": "not-real", "figure_type": "nope",
                          "is_multipanel": False, "confidence": 1.7})
    agent = ImageModalityAgent(client=client)
    res = agent.classify(_image(tmp_path))
    assert res.modality is Modality.UNKNOWN
    assert res.figure_type is FigureType.UNKNOWN
    assert res.confidence == 1.0  # clamped


def test_quality_flags_modality_disagreement():
    rec = FigureRecord(
        record_id="PMC1:fig1",
        article=ArticleRef(pmcid="PMC1"),
        figure=Figure(fig_id="fig1", caption="A sufficiently long caption here.",
                      graphic_href="x.jpg"),
        license=LicenseInfo(code="CC BY"),
        annotations=WeakAnnotations(
            modality=Modality.MRI,  # caption said MRI
            image_modality=ImageModalityResult(modality=Modality.CT, confidence=0.9),
        ),
    )
    out = QualityAgent().run([rec], QualityConfig())
    assert QualityFlag.MODALITY_DISAGREEMENT in out[0].quality.flags
    # advisory only -> record still passes
    assert out[0].quality.passed is True
