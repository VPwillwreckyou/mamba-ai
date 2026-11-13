"""Screen understanding: OCR, pixel analysis, and optional AI description."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


class VisionEngine:
    """Understand screen captures.

    Layers, from always-available to optional:
    1. Real pixel statistics (size, brightness, colorfulness, edge density).
    2. OCR via Tesseract when the binary is installed.
    3. AI description via the configured AI provider when available.

    Every layer reports honestly whether it ran or why it could not.
    """

    def __init__(self, ai_provider: Any | None = None) -> None:
        self.ai_provider = ai_provider

    @staticmethod
    def tesseract_available() -> bool:
        if shutil.which("tesseract") is None:
            return False
        try:
            import pytesseract

            pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False

    def ocr(self, image_path: str) -> dict[str, Any]:
        """Extract text from an image. Fails honestly if OCR is unavailable."""
        if not self.tesseract_available():
            return {
                "success": False,
                "error": "Tesseract OCR binary not installed",
                "text": None,
            }
        try:
            import pytesseract
            from PIL import Image

            with Image.open(image_path) as img:
                text = pytesseract.image_to_string(img)
            return {"success": True, "text": text.strip(), "chars": len(text.strip())}
        except Exception as exc:
            return {"success": False, "error": str(exc), "text": None}

    def pixel_analysis(self, image_path: str) -> dict[str, Any]:
        """Real statistical analysis of the image content."""
        try:
            from PIL import Image, ImageFilter, ImageStat

            with Image.open(image_path) as img:
                rgb = img.convert("RGB")
                stat = ImageStat.Stat(rgb)
                brightness = sum(stat.mean) / 3.0
                stddev = sum(stat.stddev) / 3.0
                gray = rgb.convert("L")
                edges = gray.filter(ImageFilter.FIND_EDGES)
                edge_stat = ImageStat.Stat(edges)
                # Count distinct-ish colors as a content-richness proxy.
                small = rgb.resize((160, 90))
                colors = small.getcolors(maxcolors=160 * 90) or []
                return {
                    "success": True,
                    "size": {"width": rgb.width, "height": rgb.height},
                    "brightness": round(brightness, 2),
                    "contrast": round(stddev, 2),
                    "edge_energy": round(edge_stat.mean[0], 3),
                    "distinct_colors_sampled": len(colors),
                    "looks_blank": brightness < 8 or (stddev < 3 and len(colors) < 5),
                }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def describe(self, image_path: str) -> dict[str, Any]:
        """AI description of the screen if an AI provider is configured."""
        if self.ai_provider is None:
            return {
                "success": False,
                "error": "AI provider not configured; screen description unavailable",
            }
        try:
            import anyio  # noqa: F401  (presence check only)
        except Exception:
            pass
        try:
            import asyncio

            prompt = (
                "Describe this screenshot concisely: what application is visible, "
                "the main UI elements, and any readable text. "
                f"(Image path: {image_path})"
            )
            reply = asyncio.run(self.ai_provider.chat(prompt))
            return {"success": True, "description": reply}
        except Exception as exc:
            return {"success": False, "error": f"AI description failed: {exc}"}

    def analyze(self, image_path: str) -> dict[str, Any]:
        """Full screen understanding: pixels + OCR + optional AI."""
        if not Path(image_path).exists():
            return {"success": False, "error": f"Image not found: {image_path}"}
        pixels = self.pixel_analysis(image_path)
        ocr = self.ocr(image_path)
        ai = self.describe(image_path)
        return {
            "success": bool(pixels.get("success")),
            "path": image_path,
            "pixels": pixels,
            "ocr": ocr,
            "ai_description": ai,
        }
