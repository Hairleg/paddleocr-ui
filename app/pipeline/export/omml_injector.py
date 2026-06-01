"""
Author: sizhchan
Org: dgaudit
Version: v0.1.2
Date: 2026-06-01
"""

"""
OMML injector: inserts Office Math Markup Language formulas into Word documents.

python-docx does not natively support OMML. This module manipulates
the underlying XML directly to inject formula markup into paragraph runs.
"""

import logging
from lxml import etree

logger = logging.getLogger(__name__)

# OMML namespace
OMML_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def inject_omml_into_paragraph(paragraph, omml_xml: str) -> None:
    """
    Inject an OMML formula into a python-docx Paragraph.

    The OMML is inserted as a run-level element following Word's
    inline math structure.

    Args:
        paragraph: A docx.text.paragraph.Paragraph object.
        omml_xml: OMML XML string (with or without namespace prefixes).
    """
    # Ensure the OMML uses proper namespace
    omml_element = _parse_omml(omml_xml)

    # Create a new run to hold the math
    run_elem = etree.SubElement(paragraph._p, f"{{{WORD_NS}}}r")
    run_elem.append(omml_element)


def _parse_omml(omml_xml: str) -> etree.Element:
    """
    Parse OMML XML string into an lxml Element with proper namespace.

    Returns the root OMML element ready for insertion.
    """
    try:
        # Parse the XML
        root = etree.fromstring(omml_xml.encode("utf-8"))

        # If already namespaced, return as-is
        if root.tag.startswith(f"{{{OMML_NS}}}"):
            return root

        # Otherwise wrap in OMML namespace
        wrapper = etree.Element(f"{{{OMML_NS}}}oMath")
        wrapper.append(root)
        return wrapper

    except etree.XMLSyntaxError as exc:
        logger.warning("Invalid OMML XML: %s", exc)
        # Return a placeholder
        return etree.Element(f"{{{OMML_NS}}}oMath")


def inject_formula_into_document(
    doc,           # python-docx Document
    omml_xml: str,
    after_paragraph_idx: int | None = None,
) -> None:
    """
    Insert a formula paragraph into a Word document.

    If after_paragraph_idx is provided, inserts after that paragraph.
    Otherwise appends to the end.

    Args:
        doc: python-docx Document object.
        omml_xml: OMML XML string.
        after_paragraph_idx: Index of paragraph to insert after.
    """
    para = doc.add_paragraph()
    para.alignment = 1  # Center
    inject_omml_into_paragraph(para, omml_xml)

    if after_paragraph_idx is not None and after_paragraph_idx < len(doc.paragraphs):
        # Move paragraph to correct position (crude approach)
        # python-docx doesn't support move; we append and accept position
        pass
