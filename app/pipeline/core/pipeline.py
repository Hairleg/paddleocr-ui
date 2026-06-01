"""
Author: sizhchan
Org: dgaudit
Version: v0.1.2
Date: 2026-06-01
"""

"""
Main document processing pipeline.

Orchestrates the full processing of a PDF document:
  1. Determine page type (electronic / scanned / dual-layer)
  2. For electronic: extract text from PDF text layer (fast, with formatting)
  3. For scanned: render → watermark removal → OCR → table detection → stamp detection
  4. Build intermediate representation (IR) with text, tables, images, stamps
  5. Export to Word + Excel + ZIP
"""

import gc
import logging
import sys
import time as _time
import os
from pathlib import Path
from typing import Optional

import fitz
import cv2

from app.pipeline.core.page_router import classify_page, has_tables
from app.pipeline.ir.types import (
    DocumentLayout,
    ElementType,
    PageLayout,
    PageSource,
    TextSpan,
    PageElement,
    FontStyle,
    TableData,
    TableCell,
)
from app.pipeline.ir.builder import build_page_from_ocr_result
# PaddleOCR is imported lazily — only needed for scanned pages
from app.pipeline.core.watermark import remove_watermark, has_watermark

logger = logging.getLogger(__name__)


def process_pdf(
    pdf_path: str,
    output_dir: str,
    dpi: int = 250,
    progress_callback: Optional[callable] = None,
    **kwargs,
) -> DocumentLayout:
    """
    Process a PDF document end-to-end.

    Electronic pages: direct text layer extraction with formatting.
    Scanned pages: render → watermark → OCR → table detection → stamp detection.

    Kwargs (user-configurable):
        table: bool (default True) — enable table detection
        table_strategy: str (default "auto") — PyMuPDF find_tables strategy
                       "lines" | "text" | "auto"
        table_merge: bool (default False) — enable cross-page table merging
        stamp: bool (default True) — enable stamp detection

        image: int (default 0) — image recognition intensity (0=text only, 1=moderate, 2=deep)
    Returns a DocumentLayout with all extracted content including tables.
    """
    enable_table = kwargs.get("table", True) if isinstance(kwargs.get("table"), bool) else str(kwargs.get("table", "1")) != "0"
    table_strategy = kwargs.get("table_strategy", "lines")
    enable_table_merge = kwargs.get("table_merge", False) if isinstance(kwargs.get("table_merge"), bool) else str(kwargs.get("table_merge", "0")) == "1"
    enable_stamp = kwargs.get("stamp", True) if isinstance(kwargs.get("stamp"), bool) else str(kwargs.get("stamp", "0")) != "0"
    ocr_lang = kwargs.get("lang", "ch")
    doc = fitz.open(pdf_path)
    image_level = int(kwargs.get("image", 0))  # 0=text only, 1=moderate, 2=deep
    total_pages = len(doc)
    logger.info("Processing %s: %d pages at %d DPI", pdf_path, total_pages, dpi)

    os.makedirs(output_dir, exist_ok=True)

    pages: list[PageLayout] = []
    all_tables: list[TableData] = []

    for page_num in range(total_pages):
        if progress_callback:
            progress_callback(page_num + 1, total_pages)

        page = doc[page_num]
        page_type = classify_page(page)
        source = _to_page_source(page_type)

        width_pt = int(page.rect.width)
        height_pt = int(page.rect.height)

        # Electronic/dual-layer pages → text layer extraction with table detection
        if page_type in ("electronic", "dual_layer"):
            page_layout, page_tables = _extract_electronic_page_with_tables(
                page, page_num + 1, enable_table=enable_table, strategy=table_strategy,
                output_dir=output_dir)
            pages.append(page_layout)
            all_tables.extend(page_tables)
            continue

        # Scanned/dual-layer → full image processing pipeline
        elements = []
        image_path = os.path.join(output_dir, f"page_{page_num + 1:04d}.png")
        pix = page.get_pixmap(dpi=dpi)
        pix.save(image_path)
        img = cv2.imread(image_path)
        if img is None:
            pages.append(PageLayout(page_num + 1, width_pt, height_pt, source))
            continue

        # Watermark removal: SKIP for scanned pages — watermarks are rare
        # on scanned documents and the HSV filter can destroy table grid lines.
        # Watermark removal is intended for electronic PDFs with light gray
        # overlaid text, not for scanned images.
        # (Uncomment below if needed for specific document types)
        # try:
        #     if has_watermark(img):
        #         img = remove_watermark(img)
        #         cv2.imwrite(image_path, img)
        # except Exception:
        #     pass
        pass

                # ── Red header enhancement (for Chinese government documents) ──
        try:
            from app.pipeline.core.layout.red_header import has_red_header, enhance_red_text
            if has_red_header(img):
                img = enhance_red_text(img)
                cv2.imwrite(image_path, img)  # Update saved image for OCR
                logger.info("Page %d: red header enhanced", page_num + 1)
        except Exception:
            pass

# ── OCR full page (lazy import PaddleOCR for scanned pages) ──
        try:
            from app.pipeline.core.ocr.engine import predict_ocr
            ocr_result = predict_ocr(image_path, lang=ocr_lang)
            page_ocr = ocr_result[0] if ocr_result else None
        except Exception as exc:
            logger.error("OCR failed on page %d: %s", page_num + 1, exc)
            page_ocr = None

        # ── Table detection on the page image ──
        table_regions = []
        if enable_table:
            # Pre-check: quick scan for grid-like structure (YOLO → line-density)
            from app.pipeline.core.layout.mineru_layout import has_table_layout
            htl = has_table_layout(img, page_num + 1)
            # debug removed
            if htl:
                # Try MinerU YOLO layout detection (primary)
                try:
                    from app.pipeline.core.layout.mineru_layout import detect_table_regions_yolo
                    yolo_result = detect_table_regions_yolo(img)
                    if yolo_result:
                        yolo_tables = []
                        for (x, y, w, h) in yolo_result[:5]:
                            if h < 30 or w < 50:
                                continue
                            if w > img.shape[1] * 0.08 and h > 25:
                                yolo_tables.append((x, y, w, h))
                        if yolo_tables:
                            table_regions = yolo_tables
                            logger.info("Page %d: YOLO detected %d table regions", page_num + 1, len(table_regions))
                except Exception as exc:
                    logger.debug("YOLO table detection skipped: %s", exc)

                # Fall back to OpenCV if YOLO found nothing
                if not table_regions:
                    try:
                        from app.pipeline.core.table.extractor import detect_table_regions
                        table_regions = detect_table_regions(img)[:3]
                        # debug removed
                        logger.info("Page %d: OpenCV detected %d table regions", page_num + 1, len(table_regions))
                    except Exception as exc:
                        logger.debug("OpenCV table detection also skipped: %s", exc)
            else:
                logger.info("Page %d: pre-check — no table grid detected, skipping extraction", page_num + 1)

        # ── OCR full page (lazy import PaddleOCR for scanned pages) ──
        try:
            from app.pipeline.core.ocr.engine import predict_ocr
            ocr_result = predict_ocr(image_path, lang=ocr_lang)
            page_ocr = ocr_result[0] if ocr_result else None
        except Exception as exc:
            logger.error("OCR failed on page %d: %s", page_num + 1, exc)
            page_ocr = None

        # ── Build text elements from OCR result (now table_regions is known) ──
        if page_ocr is not None:
            text_elements = _build_text_elements_from_ocr(page_ocr, width_pt, height_pt, dpi, table_regions)
            elements.extend(text_elements)
            logger.info("Page %d: OCR extracted %d text elements", page_num + 1, len(text_elements))

        # Table elements (try RapidTable first, fall back to OpenCV)
        page_tables = []
        for tr_idx, (tx, ty, tw, th) in enumerate(table_regions[:5]):
            try:
                # Crop region and attempt RapidTable extraction
                x1, y1 = max(0, tx-10), max(0, ty-10)
                x2, y2 = min(img.shape[1], tx+tw+10), min(img.shape[0], ty+th+10)
                roi = img[y1:y2, x1:x2]
                from app.pipeline.core.table.rapid_extractor import extract_table_with_rapid_table
                table_data = extract_table_with_rapid_table(roi, page_num+1, tr_idx, output_dir)
                # debug removed
                if table_data is None:
                    table_data = _extract_table_from_region(
                        img, (tx, ty, tw, th), page_num + 1, tr_idx, dpi, output_dir,
                    )
                    # debug removed
                logger.info("Table %d extraction: %s", tr_idx,
                           f"{len(table_data.rows)}x{len(table_data.rows[0]) if table_data and table_data.rows else 0}" if table_data else "None")
                if table_data:
                    # Add table to page as element
                    elem = PageElement(
                        type=ElementType.TABLE,
                        bbox=(int(tx*72/dpi), int(ty*72/dpi), int(tw*72/dpi), int(th*72/dpi)),
                    )
                    # Store table data reference for later
                    elem._table_data = table_data
                    elements.append(elem)
                    page_tables.append(table_data)
            except Exception as exc:
                logger.error("Table extraction failed region %d on page %d: %s",
                           tr_idx, page_num + 1, exc)
        # Reading order: sort by Y
        reading_order = list(range(len(elements)))
        reading_order.sort(key=lambda i: elements[i].bbox[1])

        page_layout = PageLayout(
            page_num=page_num + 1,
            width=width_pt,
            height=height_pt,
            source=source,
            elements=elements,
            reading_order=reading_order,
        )
        pages.append(page_layout)
        all_tables.extend(page_tables)

        gc.collect()

    doc.close()

    # Cross-page table merging (only if user enabled it)
    if all_tables and enable_table_merge:
        from app.pipeline.core.table.cross_page import merge_cross_page_tables
        all_tables = merge_cross_page_tables(all_tables)

    doc_layout = DocumentLayout(pages=pages, tables=all_tables)
    logger.info(
        "Processing complete: %d pages, %d elements, %d tables",
        len(pages),
        sum(len(p.elements) for p in pages),
        len(all_tables),
    )
    return doc_layout


def _build_text_elements_from_ocr(
    page_ocr,
    width_pt: int,
    height_pt: int,
    dpi: int,
    table_regions: list,
) -> list[PageElement]:
    """
    Build text paragraph elements from OCR result.

    Text INSIDE table regions is kept as paragraphs (not filtered),
    because table extraction handles cells separately.
    This ensures no text is lost even if table extraction fails.
    """
    rec_texts = page_ocr.get("rec_texts", []) if page_ocr and hasattr(page_ocr, 'get') else (getattr(page_ocr, "rec_texts", []) or [])
    rec_scores = page_ocr.get("rec_scores", []) if page_ocr and hasattr(page_ocr, 'get') else (getattr(page_ocr, "rec_scores", []) or [])
    rec_polys = page_ocr.get("rec_polys", []) if page_ocr and hasattr(page_ocr, 'get') else (getattr(page_ocr, "rec_polys", []) or [])
    dt_polys = page_ocr.get("dt_polys", []) if page_ocr and hasattr(page_ocr, 'get') else (getattr(page_ocr, "dt_polys", []) or [])
    polys = dt_polys if dt_polys else rec_polys

    elements = []
    for i, text in enumerate(rec_texts):
        if not text or not text.strip():
            continue

        # Calculate bbox in pixels
        if i < len(polys) and len(polys[i]) >= 4:
            poly = polys[i]
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            px, py = int(min(xs)), int(min(ys))
            pw, ph = int(max(xs)-px), int(max(ys)-py)
        else:
            px, py, pw, ph = 0, 0, width_pt, 20

        # Filter out text that overlaps significantly with table regions
        if table_regions:
            tx, ty, tw, th = px, py, pw, ph
            inside_table = False
            for rx, ry, rw, rh in table_regions:
                ox = max(0, min(tx + tw, rx + rw) - max(tx, rx))
                oy = max(0, min(ty + th, ry + rh) - max(ty, ry))
                if (ox > tw * 0.1 and oy > th * 0.1) or (ox > 15 and oy > 15):
                    inside_table = True
                    break
            if inside_table:
                continue

        confidence = rec_scores[i] if i < len(rec_scores) else 0.0
        # Estimate real font size from bounding box height
        # PaddleOCR boxes include padding/line-spacing (~3x text height)
        base_pt = ph * 72.0 / dpi
        if base_pt > 40:
            font_size_pt = min(36, round(base_pt * 0.45))
        elif base_pt > 25:
            font_size_pt = min(22, round(base_pt * 0.50))
        else:
            font_size_pt = max(10, min(16, round(base_pt * 0.55)))
        if ph < 15:
            font_size_pt = 8
        span = TextSpan(text=text.strip(), font_size=font_size_pt,
                       confidence=round(float(confidence), 4))

        # Convert px to pt
        scale = 72.0 / dpi
        elem = PageElement(
            type=ElementType.PARAGRAPH,
            bbox=(int(px*scale), int(py*scale), int(pw*scale), int(ph*scale)),
            content=[span],
        )
        elements.append(elem)

    # Dedup: text that repeats across pages (page headers/footers) keep only first
    seen = set()
    deduped = []
    for elem in elements:
        text = elem.content[0].text.strip() if elem.content else ""
        if text and len(text) >= 4 and text in seen:
            continue
        if text:
            seen.add(text)
        deduped.append(elem)

    return deduped


def _extract_table_from_region(
    img, region_bbox: tuple, page_num: int, table_idx: int, dpi: int, output_dir: str,
):
    """
    Extract a complete table from a detected region.

    1. Extract line masks within the region
    2. Find grid intersections (rows/columns)
    3. Reconstruct grid with merged cell detection
    4. Crop each cell and run OCR
    """
    from app.pipeline.core.table.extractor import extract_table_lines, find_grid_intersections
    from app.pipeline.core.table.structure import reconstruct_grid, build_table_data
    from app.pipeline.core.ocr.engine import predict_ocr

    tx, ty, tw, th = region_bbox
    x1, y1, x2, y2 = tx, ty, tx + tw, ty + th

    # Extract line masks
    h_lines, v_lines = extract_table_lines(img, region_bbox)
    if h_lines is None or v_lines is None:
        return None

    # Find grid structure
    row_pos, col_pos = find_grid_intersections(h_lines, v_lines)

    if len(row_pos) < 2 or len(col_pos) < 2:
        return None  # Not enough grid lines

    # Reconstruct grid with merged cells
    grid = reconstruct_grid(row_pos, col_pos, h_lines, v_lines)
    if not grid:
        return None

    # OCR each cell
    cell_texts = {}
    for r_idx, row_cells in enumerate(grid):
        for c_idx, cell in enumerate(row_cells):
            if cell.colspan == 0 or cell.rowspan == 0:
                continue
            # Calculate cell bbox in original image
            cx = int(col_pos[c_idx])
            cy = int(row_pos[r_idx])
            cw = int(col_pos[min(c_idx + cell.colspan, len(col_pos) - 1)] - cx)
            ch = int(row_pos[min(r_idx + cell.rowspan, len(row_pos) - 1)] - cy)

            if cw <= 0 or ch <= 0:
                continue

            # Crop cell region with global offset
            cell_img = img[y1 + cy:y1 + cy + ch, x1 + cx:x1 + cx + cw]
            if cell_img.size == 0:
                continue

            # Save temp image and OCR (use new predict API)
            temp_path = os.path.join(output_dir, f"_cell_p{page_num}_t{table_idx}_r{r_idx}_c{c_idx}.png")
            cv2.imwrite(temp_path, cell_img)
            try:
                cell_results = predict_ocr(temp_path)
                if cell_results and cell_results[0]:
                    cell_result = cell_results[0]
                    cell_texts = cell_result.get("rec_texts", []) if hasattr(cell_result, 'get') else (getattr(cell_result, "rec_texts", []) or [])
                    cell.text = "".join(t for t in cell_texts if t)
            except Exception:
                cell.text = ""

    # Build TableData
    from app.pipeline.core.table.header_handler import separate_title_and_headers, make_sheet_name

    # Get text spans for title detection (from full page OCR)
    title = ""
    sheet_name = f"第{page_num}页_表格{table_idx+1}"

    return build_table_data(grid, cell_texts, title=title, sheet_name=sheet_name)


def process_image(
    image_path: str,
    output_dir: str,
    progress_callback: Optional[callable] = None,
) -> DocumentLayout:
    """Process a single image file — full pipeline with table/stamp detection."""
    if progress_callback:
        progress_callback(1, 1)

    img = cv2.imread(image_path)
    if img is None:
        logger.error("Unable to read image: %s", image_path)
        return DocumentLayout()

    height_px, width_px = img.shape[:2]
    width_pt = int(width_px * 72 / 200)
    height_pt = int(height_px * 72 / 200)

    # Table detection (MinerU YOLO)
    table_regions = []
    try:
        from app.pipeline.core.layout.mineru_layout import detect_table_regions_yolo
        table_regions = detect_table_regions_yolo(img)[:5]
    except Exception:
        pass

    # OCR
    from app.pipeline.core.ocr.engine import predict_ocr
    ocr_result = predict_ocr(image_path)
    page_ocr = ocr_result[0] if ocr_result else None

    elements = []
    if page_ocr is not None:
        elements = _build_text_elements_from_ocr(page_ocr, width_pt, height_pt, 200, table_regions)

    reading_order = list(range(len(elements)))
    reading_order.sort(key=lambda i: elements[i].bbox[1])

    return DocumentLayout(pages=[PageLayout(
        page_num=1, width=width_pt, height=height_pt,
        source=PageSource.SCANNED,
        elements=elements, reading_order=reading_order,
    )])


def _to_page_source(page_type: str) -> PageSource:
    if page_type == "electronic":
        return PageSource.ELECTRONIC
    elif page_type == "scanned":
        return PageSource.SCANNED
    else:
        return PageSource.DUAL_LAYER


def _extract_electronic_page_with_tables(
    page, page_num: int, enable_table: bool = True, strategy: str = "auto",
    output_dir: str = "/tmp",
    is_scanned: bool = True,
) -> tuple[PageLayout, list[TableData]]:
    """
    Extract page content from electronic PDF with table detection.

    Uses PyMuPDF's built-in find_tables() for table detection, then
    extracts text blocks outside table regions as paragraphs.

    Args:
        page: PyMuPDF Page object.
        page_num: Page number (1-based).
        enable_table: If False, skip table detection entirely.
        strategy: PyMuPDF table detection strategy.
                 "lines" = detect by vector lines (best for bordered tables)
                 "text" = detect by text gaps (best for borderless tables)
                 "auto" = combined (default)

    Returns (PageLayout, list of TableData).
    """
    elements: list[PageElement] = []
    tables: list[TableData] = []
    table_bboxes: list[tuple] = []  # (x0, y0, x1, y1) for exclusion from paragraphs

    width_pt = int(page.rect.width)
    height_pt = int(page.rect.height)

    # ── Step 1: Detect tables using MinerU YOLO layout (primary) ──
    # Render page for YOLO
    yolo_image = None
    if enable_table:
        try:
            pix = page.get_pixmap(dpi=200)
            img_path = os.path.join(output_dir or "/tmp", f"_yolo_p{page_num}.png")
            pix.save(img_path)
            import cv2
            yolo_image = cv2.imread(img_path)
        except Exception:
            pass

    yolo_regions = []
    if enable_table and yolo_image is not None:  # Run YOLO on all pages
        # Pre-flight: check if page has table structures (informational only)
        has_t = has_tables(page)
        logger.debug("Page %d: pre-flight table check = %s", page_num, has_t)
        if True:  # Always run YOLO
            from app.pipeline.core.layout.mineru_layout import detect_table_regions_yolo
            from app.pipeline.core.table.rapid_extractor import extract_table_with_rapid_table

            _ys = _time.time()
            yolo_regions = detect_table_regions_yolo(yolo_image)
            yolo_regions = yolo_regions[:5]
            print(f"[TIMING] Page {page_num}: YOLO done ({_time.time()-_ys:.1f}s, {len(yolo_regions)} tables)", flush=True)  # Cap at 5 regions per page
        logger.info("Page %d: YOLO detected %d table regions", page_num, len(yolo_regions))

        for y_idx, (x, y, w, h) in enumerate(yolo_regions):
            try:
                roi = yolo_image[y:y+h, x:x+w]
                td = extract_table_with_rapid_table(roi, page_num, y_idx, output_dir or "/tmp")
                if td:
                    tables.append(td)
                else:
                    # RapidTable failed — still keep table as placeholder
                    td = TableData(rows=[[TableCell(row=0,col=0,text="[表格结构未识别]")]], 
                                   title="", sheet_name=f"第{page_num}页_表格{y_idx+1}")
                    tables.append(td)
                elem = PageElement(type=ElementType.TABLE, bbox=(x, y, w, h))
                elem._table_data = td
                elements.append(elem)
                table_bboxes.append((x, y, x+w, y+h))
            except Exception as exc:
                logger.debug("RapidTable failed on page %d region %d: %s", page_num, y_idx, exc)




    # ── Step 2: Extract text blocks outside table regions ──    # ── Step 2: Extract text blocks outside table regions ──
    text_dict = page.get_text("dict")
    blocks = text_dict.get("blocks", [])

    for block in blocks:
        if block.get("type") != 0:  # Skip images
            continue
        bbox = block.get("bbox", (0, 0, 0, 0))
        bx, by, bx2, by2 = bbox

        # Skip header/footer blocks on page 2+ (short text in top/bottom 5%)
        page_h = page.rect.height
        in_header = by < page_h * 0.04
        in_footer = by2 > page_h * 0.96
        if page_num > 1 and (in_header or in_footer):
            spans = [s for line in block.get("lines",[]) for s in line.get("spans",[])]
            total_text = "".join([s.get("text","").strip() for s in spans])
            if len(total_text) < 10:
                continue

        # Skip if this block is inside any detected table
        inside_table = False
        for tx0, ty0, tx1, ty1 in table_bboxes:
            # If block overlaps significantly with table, skip
            overlap_x = max(0, min(bx2, tx1) - max(bx, tx0))
            overlap_y = max(0, min(by2, ty1) - max(by, ty0))
            if overlap_x > 0 and overlap_y > 0:
                inside_table = True
                break
        if inside_table:
            continue

        lines = block.get("lines", [])
        if not lines:
            continue

        para_spans = []
        for line in lines:
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if not text:
                    continue
                font_name = span.get("font", "SimSun")
                font_size = round(span.get("size", 12))
                is_bold = "Bold" in font_name or span.get("flags", 0) & 2
                color_int = span.get("color", 0)
                r, g, b = (color_int>>16)&0xFF, (color_int>>8)&0xFF, color_int&0xFF
                ts = TextSpan(text=text, font_name=font_name,
                              font_size=font_size, is_bold=is_bold,
                              color=f"#{r:02x}{g:02x}{b:02x}")
                para_spans.append(ts)

        if para_spans:
            elements.append(PageElement(
                type=ElementType.PARAGRAPH,
                bbox=(int(bx), int(by), int(bx2-bx), int(by2-by)),
                content=para_spans,
            ))

    # Reading order: sort by Y then X
    reading_order = list(range(len(elements)))
    reading_order.sort(key=lambda i: (elements[i].bbox[1], elements[i].bbox[0]))

    return PageLayout(
        page_num=page_num, width=width_pt, height=height_pt,
        source=PageSource.ELECTRONIC, elements=elements, reading_order=reading_order,
    ), tables


def _extract_electronic_page(page, page_num: int) -> PageLayout:
    """Extract page content from PDF text layer with full formatting."""
    text_dict = page.get_text("dict")
    blocks = text_dict.get("blocks", [])
    elements: list[PageElement] = []

    for block in blocks:
        if block.get("type") == 1:
            continue
        if block.get("type") != 0:
            continue
        bbox = block.get("bbox", (0, 0, 0, 0))
        bx, by, bx2, by2 = bbox
        lines = block.get("lines", [])
        if not lines:
            continue

        para_spans = []
        for line in lines:
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if not text:
                    continue
                font_name = span.get("font", "SimSun")
                font_size = round(span.get("size", 12))
                is_bold = "Bold" in font_name or span.get("flags", 0) & 2
                color_int = span.get("color", 0)
                r, g, b = (color_int>>16)&0xFF, (color_int>>8)&0xFF, color_int&0xFF
                ts = TextSpan(text=text, font_name=font_name,
                              font_size=font_size, is_bold=is_bold,
                              color=f"#{r:02x}{g:02x}{b:02x}")
                para_spans.append(ts)

        if para_spans:
            elements.append(PageElement(
                type=ElementType.PARAGRAPH,
                bbox=(int(bx), int(by), int(bx2-bx), int(by2-by)),
                content=para_spans,
            ))

    reading_order = list(range(len(elements)))
    reading_order.sort(key=lambda i: (elements[i].bbox[1], elements[i].bbox[0]))

    return PageLayout(
        page_num=page_num, width=int(page.rect.width), height=int(page.rect.height),
        source=PageSource.ELECTRONIC, elements=elements, reading_order=reading_order,
    )


    return elements


def _extract_table_from_region(
    img, region_bbox: tuple, page_num: int, table_idx: int, dpi: int, output_dir: str,
):
    """
    Extract a complete table from a detected region.

    1. Extract line masks within the region
    2. Find grid intersections (rows/columns)
    3. Reconstruct grid with merged cell detection
    4. Crop each cell and run OCR
    """
    from app.pipeline.core.table.extractor import extract_table_lines, find_grid_intersections
    from app.pipeline.core.table.structure import reconstruct_grid, build_table_data
    from app.pipeline.core.ocr.engine import predict_ocr

    tx, ty, tw, th = region_bbox
    x1, y1, x2, y2 = tx, ty, tx + tw, ty + th

    # Extract line masks
    h_lines, v_lines = extract_table_lines(img, region_bbox)
    if h_lines is None or v_lines is None:
        return None

    # Find grid structure
    row_pos, col_pos = find_grid_intersections(h_lines, v_lines)

    if len(row_pos) < 2 or len(col_pos) < 2:
        return None  # Not enough grid lines

    # Reconstruct grid with merged cells
    grid = reconstruct_grid(row_pos, col_pos, h_lines, v_lines)
    if not grid:
        return None

    # OCR each cell
    cell_texts = {}
    for r_idx, row_cells in enumerate(grid):
        for c_idx, cell in enumerate(row_cells):
            if cell.colspan == 0 or cell.rowspan == 0:
                continue
            # Calculate cell bbox in original image
            cx = int(col_pos[c_idx])
            cy = int(row_pos[r_idx])
            cw = int(col_pos[min(c_idx + cell.colspan, len(col_pos) - 1)] - cx)
            ch = int(row_pos[min(r_idx + cell.rowspan, len(row_pos) - 1)] - cy)

            if cw <= 0 or ch <= 0:
                continue

            # Crop cell region with global offset
            cell_img = img[y1 + cy:y1 + cy + ch, x1 + cx:x1 + cx + cw]
            if cell_img.size == 0:
                continue

            # Save temp image and OCR (use new predict API)
            temp_path = os.path.join(output_dir, f"_cell_p{page_num}_t{table_idx}_r{r_idx}_c{c_idx}.png")
            cv2.imwrite(temp_path, cell_img)
            try:
                cell_results = predict_ocr(temp_path)
                if cell_results and cell_results[0]:
                    cell_result = cell_results[0]
                    cell_texts = cell_result.get("rec_texts", []) if hasattr(cell_result, 'get') else (getattr(cell_result, "rec_texts", []) or [])
                    cell.text = "".join(t for t in cell_texts if t)
            except Exception:
                cell.text = ""

    # Build TableData
    from app.pipeline.core.table.header_handler import separate_title_and_headers, make_sheet_name

    # Get text spans for title detection (from full page OCR)
    title = ""
    sheet_name = f"第{page_num}页_表格{table_idx+1}"

    return build_table_data(grid, cell_texts, title=title, sheet_name=sheet_name)


def process_image(
    image_path: str,
    output_dir: str,
    progress_callback: Optional[callable] = None,
) -> DocumentLayout:
    """Process a single image file — full pipeline with table/stamp detection."""
    if progress_callback:
        progress_callback(1, 1)

    img = cv2.imread(image_path)
    if img is None:
        logger.error("Unable to read image: %s", image_path)
        return DocumentLayout()

    height_px, width_px = img.shape[:2]
    width_pt = int(width_px * 72 / 200)
    height_pt = int(height_px * 72 / 200)

    # Table detection (MinerU YOLO)
    table_regions = []
    try:
        from app.pipeline.core.layout.mineru_layout import detect_table_regions_yolo
        table_regions = detect_table_regions_yolo(img)[:5]
    except Exception:
        pass

    # OCR
    from app.pipeline.core.ocr.engine import predict_ocr
    ocr_result = predict_ocr(image_path)
    page_ocr = ocr_result[0] if ocr_result else None

    elements = []
    if page_ocr is not None:
        elements = _build_text_elements_from_ocr(page_ocr, width_pt, height_pt, 200, table_regions)

    reading_order = list(range(len(elements)))
    reading_order.sort(key=lambda i: elements[i].bbox[1])

    return DocumentLayout(pages=[PageLayout(
        page_num=1, width=width_pt, height=height_pt,
        source=PageSource.SCANNED,
        elements=elements, reading_order=reading_order,
    )])


def _to_page_source(page_type: str) -> PageSource:
    if page_type == "electronic":
        return PageSource.ELECTRONIC
    elif page_type == "scanned":
        return PageSource.SCANNED
    else:
        return PageSource.DUAL_LAYER


def _extract_electronic_page_with_tables(
    page, page_num: int, enable_table: bool = True, strategy: str = "auto",
    output_dir: str = "/tmp",
    is_scanned: bool = True,
) -> tuple[PageLayout, list[TableData]]:
    """
    Extract page content from electronic PDF with table detection.

    Uses PyMuPDF's built-in find_tables() for table detection, then
    extracts text blocks outside table regions as paragraphs.

    Args:
        page: PyMuPDF Page object.
        page_num: Page number (1-based).
        enable_table: If False, skip table detection entirely.
        strategy: PyMuPDF table detection strategy.
                 "lines" = detect by vector lines (best for bordered tables)
                 "text" = detect by text gaps (best for borderless tables)
                 "auto" = combined (default)

    Returns (PageLayout, list of TableData).
    """
    elements: list[PageElement] = []
    tables: list[TableData] = []
    table_bboxes: list[tuple] = []  # (x0, y0, x1, y1) for exclusion from paragraphs

    width_pt = int(page.rect.width)
    height_pt = int(page.rect.height)

    # ── Step 1: Detect tables using MinerU YOLO layout (primary) ──
    # Render page for YOLO
    yolo_image = None
    if enable_table:
        try:
            pix = page.get_pixmap(dpi=200)
            img_path = os.path.join(output_dir or "/tmp", f"_yolo_p{page_num}.png")
            pix.save(img_path)
            import cv2
            yolo_image = cv2.imread(img_path)
        except Exception:
            pass

    yolo_regions = []
    if enable_table and yolo_image is not None:  # Run YOLO on all pages
        # Pre-flight: check if page has table structures (informational only)
        has_t = has_tables(page)
        logger.debug("Page %d: pre-flight table check = %s", page_num, has_t)
        if True:  # Always run YOLO
            from app.pipeline.core.layout.mineru_layout import detect_table_regions_yolo
            from app.pipeline.core.table.rapid_extractor import extract_table_with_rapid_table

            _ys = _time.time()
            yolo_regions = detect_table_regions_yolo(yolo_image)
            yolo_regions = yolo_regions[:5]
            print(f"[TIMING] Page {page_num}: YOLO done ({_time.time()-_ys:.1f}s, {len(yolo_regions)} tables)", flush=True)  # Cap at 5 regions per page
        logger.info("Page %d: YOLO detected %d table regions", page_num, len(yolo_regions))

        for y_idx, (x, y, w, h) in enumerate(yolo_regions):
            try:
                roi = yolo_image[y:y+h, x:x+w]
                td = extract_table_with_rapid_table(roi, page_num, y_idx, output_dir or "/tmp")
                if td:
                    tables.append(td)
                else:
                    # RapidTable failed — still keep table as placeholder
                    td = TableData(rows=[[TableCell(row=0,col=0,text="[表格结构未识别]")]], 
                                   title="", sheet_name=f"第{page_num}页_表格{y_idx+1}")
                    tables.append(td)
                elem = PageElement(type=ElementType.TABLE, bbox=(x, y, w, h))
                elem._table_data = td
                elements.append(elem)
                table_bboxes.append((x, y, x+w, y+h))
            except Exception as exc:
                logger.debug("RapidTable failed on page %d region %d: %s", page_num, y_idx, exc)




    # ── Step 2: Extract text blocks outside table regions ──    # ── Step 2: Extract text blocks outside table regions ──
    text_dict = page.get_text("dict")
    blocks = text_dict.get("blocks", [])

    for block in blocks:
        if block.get("type") != 0:  # Skip images
            continue
        bbox = block.get("bbox", (0, 0, 0, 0))
        bx, by, bx2, by2 = bbox

        # Skip header/footer blocks on page 2+ (short text in top/bottom 5%)
        page_h = page.rect.height
        in_header = by < page_h * 0.04
        in_footer = by2 > page_h * 0.96
        if page_num > 1 and (in_header or in_footer):
            spans = [s for line in block.get("lines",[]) for s in line.get("spans",[])]
            total_text = "".join([s.get("text","").strip() for s in spans])
            if len(total_text) < 10:
                continue

        # Skip if this block is inside any detected table
        inside_table = False
        for tx0, ty0, tx1, ty1 in table_bboxes:
            # If block overlaps significantly with table, skip
            overlap_x = max(0, min(bx2, tx1) - max(bx, tx0))
            overlap_y = max(0, min(by2, ty1) - max(by, ty0))
            if overlap_x > 0 and overlap_y > 0:
                inside_table = True
                break
        if inside_table:
            continue

        lines = block.get("lines", [])
        if not lines:
            continue

        para_spans = []
        for line in lines:
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if not text:
                    continue
                font_name = span.get("font", "SimSun")
                font_size = round(span.get("size", 12))
                is_bold = "Bold" in font_name or span.get("flags", 0) & 2
                color_int = span.get("color", 0)
                r, g, b = (color_int>>16)&0xFF, (color_int>>8)&0xFF, color_int&0xFF
                ts = TextSpan(text=text, font_name=font_name,
                              font_size=font_size, is_bold=is_bold,
                              color=f"#{r:02x}{g:02x}{b:02x}")
                para_spans.append(ts)

        if para_spans:
            elements.append(PageElement(
                type=ElementType.PARAGRAPH,
                bbox=(int(bx), int(by), int(bx2-bx), int(by2-by)),
                content=para_spans,
            ))

    # Reading order: sort by Y then X
    reading_order = list(range(len(elements)))
    reading_order.sort(key=lambda i: (elements[i].bbox[1], elements[i].bbox[0]))

    return PageLayout(
        page_num=page_num, width=width_pt, height=height_pt,
        source=PageSource.ELECTRONIC, elements=elements, reading_order=reading_order,
    ), tables


def _extract_electronic_page(page, page_num: int) -> PageLayout:
    """Extract page content from PDF text layer with full formatting."""
    text_dict = page.get_text("dict")
    blocks = text_dict.get("blocks", [])
    elements: list[PageElement] = []

    for block in blocks:
        if block.get("type") == 1:
            continue
        if block.get("type") != 0:
            continue
        bbox = block.get("bbox", (0, 0, 0, 0))
        bx, by, bx2, by2 = bbox
        lines = block.get("lines", [])
        if not lines:
            continue

        para_spans = []
        for line in lines:
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if not text:
                    continue
                font_name = span.get("font", "SimSun")
                font_size = round(span.get("size", 12))
                is_bold = "Bold" in font_name or span.get("flags", 0) & 2
                color_int = span.get("color", 0)
                r, g, b = (color_int>>16)&0xFF, (color_int>>8)&0xFF, color_int&0xFF
                ts = TextSpan(text=text, font_name=font_name,
                              font_size=font_size, is_bold=is_bold,
                              color=f"#{r:02x}{g:02x}{b:02x}")
                para_spans.append(ts)

        if para_spans:
            elements.append(PageElement(
                type=ElementType.PARAGRAPH,
                bbox=(int(bx), int(by), int(bx2-bx), int(by2-by)),
                content=para_spans,
            ))

    reading_order = list(range(len(elements)))
    reading_order.sort(key=lambda i: (elements[i].bbox[1], elements[i].bbox[0]))

    return PageLayout(
        page_num=page_num, width=int(page.rect.width), height=int(page.rect.height),
        source=PageSource.ELECTRONIC, elements=elements, reading_order=reading_order,
    )
