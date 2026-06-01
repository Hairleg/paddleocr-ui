"""
Dead code backup from pipeline.py
Functions:
  _extract_electronic_page (duplicate, 0 calls)
  _extract_table_from_region (duplicate)
  process_image (duplicate, 0 calls)
  _to_page_source (duplicate)
  _extract_electronic_page_with_tables (duplicate)
"""

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
