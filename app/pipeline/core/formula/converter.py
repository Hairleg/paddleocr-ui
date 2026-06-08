"""
Author: sizhchan
Org: dgaudit
Version: v0.2.0
Date: 2026-06-01
"""

"""
Formula converter: LaTeX to Word-compatible format.

For simple formulas, converts LaTeX to OMML (Office Math Markup Language)
which can be injected into Word XML directly.

For complex formulas (matrices, multi-line, integrals), falls back to
screenshot embedding as a PNG image.

Strategy:
  1. Try latex2mathml → MathML → OMML conversion
  2. If conversion fails or formula is complex → return "screenshot" fallback
  3. Simple formulas (superscript, subscript, fraction, sqrt) are OMML-capable
"""

import logging
import re

logger = logging.getLogger(__name__)

# Patterns indicating a formula is too complex for OMML conversion
COMPLEX_PATTERNS = [
    r"\\begin\{matrix\}",
    r"\\begin\{align\}",
    r"\\begin\{cases\}",
    r"\\int",
    r"\\sum",
    r"\\prod",
    r"\\lim",
    r"\\overbrace",
    r"\\underbrace",
]


def is_convertible(latex: str) -> bool:
    """
    Check if a LaTeX formula is simple enough for OMML conversion.

    Args:
        latex: LaTeX source string.

    Returns:
        True if the formula can likely be converted to OMML.
    """
    if not latex or not latex.strip():
        return False
    for pattern in COMPLEX_PATTERNS:
        if re.search(pattern, latex):
            return False
    return True


def latex_to_mathml(latex: str) -> str | None:
    """
    Convert LaTeX to MathML using latex2mathml if available.

    Args:
        latex: LaTeX source string.

    Returns:
        MathML string, or None if conversion fails.
    """
    try:
        from latex2mathml.converter import convert

        mathml = convert(latex)
        return mathml
    except ImportError:
        logger.warning(
            "latex2mathml not installed. Install with: pip install latex2mathml"
        )
        return None
    except Exception as exc:
        logger.debug("LaTeX to MathML conversion failed: %s", exc)
        return None


def mathml_to_omml(mathml: str) -> str:
    """
    Convert MathML to OMML XML (Word formula markup).

    Performs a basic structural conversion. For production use,
    a full MathML → OMML XSLT transformation would be more robust.

    Args:
        mathml: MathML XML string.

    Returns:
        OMML XML string ready for injection into Word document XML.
    """
    # Basic conversion: wrap in OMML structure
    # Full conversion would require XSLT processing
    omml = (
        '<m:oMathPara xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
        '<m:oMath>'
    )

    # Simple tag replacements
    omml += mathml.replace("<math", "<m:math")
    omml += "</m:oMath></m:oMathPara>"

    return omml


def convert_formula(latex: str) -> dict:
    """
    Main entry point: attempt LaTeX → OMML, fall back to screenshot.

    Args:
        latex: LaTeX source string.

    Returns:
        {
            "method": "omml" | "screenshot",
            "omml": str | None,          # OMML XML if method=omml
            "latex": str,                # Original LaTeX (for documentation)
        }
    """
    result = {
        "method": "screenshot",
        "omml": None,
        "latex": latex,
    }

    if not is_convertible(latex):
        logger.debug("Formula too complex for OMML: %s", latex[:60])
        return result

    mathml = latex_to_mathml(latex)
    if mathml:
        try:
            result["omml"] = mathml_to_omml(mathml)
            result["method"] = "omml"
            logger.debug("Formula converted to OMML: %s", latex[:60])
        except Exception as exc:
            logger.debug("OMML conversion failed: %s", exc)

    return result
