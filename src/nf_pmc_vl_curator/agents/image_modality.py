"""Optional stage -- ImageModalityAgent (Claude vision).

Classifies a figure's imaging modality from the **image pixels** (not the
caption) using a Claude vision model with *structured outputs*, so the result
is always a valid label from our controlled vocabulary -- never free text.

This is the higher-quality counterpart to the caption-keyword annotator: it
resolves MRI vs CT, real clinical photo vs illustration, and multi-panel
composites that captions often don't describe.

Cost is small (a figure is ~1-1.5K input tokens; ~$0.15 per 100 images on
``claude-haiku-4-5``). The ``anthropic`` SDK is an optional dependency -- install
with ``uv sync --extra vision``.
"""

from __future__ import annotations

import base64
import io
import json
import logging
from pathlib import Path
from typing import Optional

from ..models import FigureType, ImageModalityResult, Modality

log = logging.getLogger(__name__)

# The controlled label space handed to the model (drives the JSON schema enums).
_MODALITIES = [m.value for m in Modality]
_FIGURE_TYPES = [f.value for f in FigureType]

_SCHEMA = {
    "type": "object",
    "properties": {
        "modality": {"type": "string", "enum": _MODALITIES},
        "figure_type": {"type": "string", "enum": _FIGURE_TYPES},
        "is_multipanel": {"type": "boolean"},
        "confidence": {"type": "number"},
        "rationale": {"type": "string"},
    },
    "required": ["modality", "figure_type", "is_multipanel", "confidence"],
    "additionalProperties": False,
}

_PROMPT = (
    "You are labeling a figure from a biomedical journal article for a "
    "vision-language dataset. Look at the IMAGE and classify it.\n\n"
    f"- modality: the imaging modality, one of {_MODALITIES}. Use 'mri'/'ct'/"
    "'ultrasound'/'xray'/'pet' for radiology; 'histology' for stained "
    "microscopy/histopathology; 'clinical_photo' for a real photograph of a "
    "patient/skin/body; 'illustration' for drawn schematics/diagrams; 'chart' "
    "for plots/graphs; 'unknown' if genuinely unclear.\n"
    f"- figure_type: a coarse grouping, one of {_FIGURE_TYPES} ('mixed' for a "
    "multi-panel figure combining different types).\n"
    "- is_multipanel: true if the figure contains multiple sub-panels.\n"
    "- confidence: 0..1, your confidence in the modality label.\n"
    "Classify from the image content. Any caption text is secondary context only."
)


class ImageModalityAgent:
    """Vision-based modality classifier backed by a Claude model."""

    def __init__(
        self,
        model: str = "claude-haiku-4-5",
        *,
        api_key: Optional[str] = None,
        max_long_edge: int = 1568,
        client=None,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.max_long_edge = max_long_edge
        self._client = client  # injectable for tests

    @property
    def client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:  # optional dependency
                raise ImportError(
                    "the 'anthropic' SDK is required for image classification; "
                    "install it with: uv sync --extra vision"
                ) from exc
            self._client = (
                anthropic.Anthropic(api_key=self.api_key)
                if self.api_key
                else anthropic.Anthropic()
            )
        return self._client

    def classify(
        self, image_path, caption: Optional[str] = None
    ) -> ImageModalityResult:
        """Return an :class:`ImageModalityResult` for one image."""
        b64 = self._encode(Path(image_path), self.max_long_edge)
        content = [
            {"type": "image",
             "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
        ]
        text = _PROMPT
        if caption:
            text += f"\n\nCaption (context): {caption[:600]}"
        content.append({"type": "text", "text": text})

        resp = self.client.messages.create(
            model=self.model,
            max_tokens=512,
            messages=[{"role": "user", "content": content}],
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        )
        data = json.loads(_first_text(resp))
        return ImageModalityResult(
            modality=_to_enum(Modality, data.get("modality"), Modality.UNKNOWN),
            figure_type=_to_enum(FigureType, data.get("figure_type"), FigureType.UNKNOWN),
            is_multipanel=bool(data.get("is_multipanel", False)),
            confidence=_clamp(data.get("confidence", 0.0)),
            rationale=data.get("rationale"),
            model=self.model,
        )

    # -- image encoding ---------------------------------------------------- #
    @staticmethod
    def _encode(path: Path, max_long_edge: int) -> str:
        """Downscale (to cap tokens), re-encode to JPEG, return base64."""
        from PIL import Image

        with Image.open(path) as im:
            im = im.convert("RGB")
            if max_long_edge and max(im.size) > max_long_edge:
                im.thumbnail((max_long_edge, max_long_edge))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=90)
        return base64.standard_b64encode(buf.getvalue()).decode("ascii")


def _first_text(resp) -> str:
    for block in resp.content:
        if getattr(block, "type", None) == "text":
            return block.text
    raise ValueError("vision response contained no text block")


def _to_enum(enum_cls, value, default):
    try:
        return enum_cls(value)
    except (ValueError, TypeError):
        return default


def _clamp(value) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
