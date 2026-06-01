"""
Author: sizhchan
Org: dgaudit
Version: v0.1.2
Date: 2026-06-01
"""

"""
Font rules for Chinese government documents (红头文件).

Chinese official documents follow strict formatting standards
(GB/T 9704-2012). This module maps document visual features
to standard government font assignments.

When a "red-header" document is detected, fonts are applied
according to these rules, even when the original PDF lacks
embedded font metadata.
"""

import logging

logger = logging.getLogger(__name__)

# ── Government document font rules ──
# Based on GB/T 9704-2012 党政机关公文格式

# Standard fonts for each document role
GOVERNMENT_FONT_MAP = {
    # Red header: the red organizational title at the top
    "red_header": {
        "font_name": "FZXiaoBiaoSong",  # 方正小标宋简体
        "font_fallback": "SimHei",        # Fallback: 黑体
        "size_pt": 42,                     # 初号 or 小初
        "color": "#FF0000",
        "bold": False,
    },
    # Document title (after red header)
    "title": {
        "font_name": "FZXiaoBiaoSong",
        "font_fallback": "SimHei",
        "size_pt": 22,                     # 二号
        "color": "#000000",
        "bold": False,
    },
    # Level 1 heading
    "heading_1": {
        "font_name": "SimHei",             # 黑体
        "font_fallback": "SimHei",
        "size_pt": 16,                     # 三号
        "color": "#000000",
        "bold": True,
    },
    # Level 2 heading
    "heading_2": {
        "font_name": "KaiTi",              # 楷体_GB2312
        "font_fallback": "KaiTi",
        "size_pt": 16,                     # 三号
        "color": "#000000",
        "bold": True,
    },
    # Body text
    "body": {
        "font_name": "FangSong",           # 仿宋_GB2312
        "font_fallback": "FangSong",
        "size_pt": 16,                     # 三号
        "color": "#000000",
        "bold": False,
    },
    # Page numbers
    "page_number": {
        "font_name": "FangSong",
        "font_fallback": "FangSong",
        "size_pt": 12,
        "color": "#000000",
        "bold": False,
    },
}


def classify_text_role(
    text: str,
    y_position: float,
    page_height: float,
    font_size_pt: int,
    is_red: bool = False,
) -> str:
    """
    Classify a text element's document role based on position and properties.

    Args:
        text: Text content.
        y_position: Y coordinate in points from top of page.
        page_height: Total page height in points.
        font_size_pt: Estimated font size in points.
        is_red: Whether the text is red.

    Returns:
        One of: "red_header", "title", "heading_1", "heading_2", "body", "page_number"
    """
    # Red text at top → red header
    if is_red and y_position < page_height * 0.15:
        return "red_header"

    # Very large text near top → title
    if font_size_pt >= 20 and y_position < page_height * 0.2:
        return "title"

    # Large bold text → heading
    if font_size_pt >= 15 and y_position < page_height * 0.9:
        # Level 1 headings typically start with "一、", "二、", etc.
        if any(text.strip().startswith(p) for p in ["一、", "二、", "三、", "四、", "五、"]):
            return "heading_1"
        # Level 2 headings start with "（一）", etc.
        if any(text.strip().startswith(p) for p in ["（一）", "（二）", "（三）"]):
            return "heading_2"
        if font_size_pt >= 18:
            return "heading_1"

    # Near bottom → page number
    if y_position > page_height * 0.92:
        return "page_number"

    return "body"


def apply_government_font_rules(
    page_elements: list,
    page_height: float,
) -> None:
    """
    Apply GB/T 9704-2012 font rules to page elements in-place.

    Only triggers when the page is detected as a government document
    (has red header element).

    Args:
        page_elements: List of PageElement objects for a single page.
        page_height: Page height in points.
    """
    # Check for red header (indicates government document)
    has_red_header = any(
        hasattr(e, "content") and e.content
        and hasattr(e.content[0], "color") and e.content[0].color
        and "FF0000" in (e.content[0].color or "").upper()
        for e in page_elements
    )

    if not has_red_header:
        return

    logger.debug("Government document detected, applying font rules")

    for elem in page_elements:
        if not elem.content or not elem.bbox:
            continue
        y = elem.bbox[1]
        for span in elem.content:
            if not hasattr(span, "font_size"):
                continue
            font_size = span.font_size or 12
            is_red = hasattr(span, "color") and "FF0000" in (span.color or "").upper()

            role = classify_text_role(
                span.text or "", y, page_height, font_size, is_red,
            )
            rules = GOVERNMENT_FONT_MAP.get(role)
            if rules:
                span.font_name = rules.get("font_name", span.font_name)
                span.font_size = rules.get("size_pt", span.font_size)
                if "bold" in rules:
                    span.is_bold = rules["bold"]
                if "color" in rules:
                    span.color = rules["color"]
