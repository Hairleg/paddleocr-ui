"""
Author: sizhchan
Org: dgaudit
Version: v0.1.2
Date: 2026-06-01
"""

"""Plain text exporter — vectorization-ready, no tables, clean formatting."""

from app.pipeline.ir.types import DocumentLayout, ElementType


def write_text(doc: DocumentLayout, output_path: str):
    """Export paragraphs + table text, cleaned for semantic vectorization."""
    lines = []
    # 1. 段落
    for page in doc.pages:
        for idx in page.reading_order or range(len(page.elements)):
            elem = page.elements[idx]
            if elem.type == ElementType.PARAGRAPH and elem.content:
                parts = []
                for span in elem.content:
                    text = getattr(span, "text", str(span))
                    if text:
                        parts.append(text.replace("\n", "").replace("\r", "").strip())
                line = "".join(parts).strip()
                if line:
                    lines.append(line)
    # 2. 表格
    for table in doc.tables:
        if table.title:
            lines.append(table.title)
        for row in table.rows:
            row_text = "\t".join(cell.text.strip() for cell in row if cell.text.strip())
            if row_text:
                lines.append(row_text)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
