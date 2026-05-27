"""
Author: sizhchan
Org: dgaudit
Version: v0.1
Date: 2026-05-27
"""

"""Plain text exporter — vectorization-ready, no tables, clean formatting."""

from app.pipeline.ir.types import DocumentLayout, ElementType


def write_text(doc: DocumentLayout, output_path: str):
    """Export paragraphs only, cleaned for semantic vectorization."""
    lines = []
    for page in doc.pages:
        for idx in page.reading_order or range(len(page.elements)):
            elem = page.elements[idx]
            if elem.type == ElementType.PARAGRAPH and elem.content:
                parts = []
                for span in elem.content:
                    text = getattr(span, "text", str(span))
                    if text:
                        # Merge all spans into one line, strip internal newlines
                        parts.append(text.replace("\n", "").replace("\r", "").strip())
                line = "".join(parts).strip()
                if line:
                    lines.append(line)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
