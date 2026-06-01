"""
Author: sizhchan
Org: dgaudit
Version: v0.1.2
Date: 2026-06-01
"""

"""
Table structure reconstruction from grid lines.

Given detected row and column positions, reconstructs the table grid
and identifies merged cells (rowspan/colspan).

Merged cell detection:
  - A cell is merged horizontally if no vertical line exists between
    adjacent columns at that row.
  - A cell is merged vertically if no horizontal line exists between
    adjacent rows at that column.
  - Diagonal text or slanted headers are identified by checking if
    text bounding boxes cross cell boundaries.
"""

import logging

from app.pipeline.ir.types import TableCell, TableData

logger = logging.getLogger(__name__)


def reconstruct_grid(
    row_positions: list[float],
    col_positions: list[float],
    h_lines: 'np.ndarray',
    v_lines: 'np.ndarray',
) -> list[list[TableCell]]:
    """
    Reconstruct a table grid from line positions.

    Args:
        row_positions: Y coordinates of horizontal grid lines.
        col_positions: X coordinates of vertical grid lines.
        h_lines: Binary mask of horizontal lines.
        v_lines: Binary mask of vertical lines.

    Returns:
        2D list of TableCell objects, including rowspan/colspan for merged cells.
    """
    import numpy as np

    n_rows = len(row_positions) - 1
    n_cols = len(col_positions) - 1

    if n_rows <= 0 or n_cols <= 0:
        return []

    # Initialize grid
    grid = []
    for r in range(n_rows):
        grid_row = []
        for c in range(n_cols):
            grid_row.append(TableCell(row=r, col=c, rowspan=1, colspan=1))
        grid.append(grid_row)

    # Detect merged cells by checking for missing grid lines
    _detect_horizontal_merges(grid, row_positions, col_positions, v_lines)
    _detect_vertical_merges(grid, row_positions, col_positions, h_lines)

    return grid


def _detect_horizontal_merges(
    grid: list[list[TableCell]],
    row_positions: list[float],
    col_positions: list[float],
    v_lines: 'np.ndarray',
) -> None:
    """Detect horizontally merged cells (colspan > 1)."""
    import numpy as np

    n_rows = len(grid)
    n_cols = len(grid[0]) if n_rows > 0 else 0

    for r in range(n_rows):
        y1 = int(row_positions[r])
        y2 = int(row_positions[r + 1])
        for c in range(n_cols - 1):
            x_mid = int(col_positions[c + 1])
            # Check if vertical line exists at this column boundary
            if y2 > y1 and 0 <= x_mid < v_lines.shape[1]:
                line_slice = v_lines[y1:y2, x_mid]
                has_line = np.any(line_slice > 0) if line_slice.size > 0 else False
            else:
                has_line = False

            if not has_line and grid[r][c].colspan == 1:
                # Merge with next cell
                grid[r][c].colspan += 1
                # Mark next cell as absorbed (colspan=0 means absorbed)
                if c + 1 < n_cols:
                    grid[r][c + 1].colspan = 0


def _detect_vertical_merges(
    grid: list[list[TableCell]],
    row_positions: list[float],
    col_positions: list[float],
    h_lines: 'np.ndarray',
) -> None:
    """Detect vertically merged cells (rowspan > 1)."""
    import numpy as np

    n_rows = len(grid)
    n_cols = len(grid[0]) if n_rows > 0 else 0

    for r in range(n_rows - 1):
        y_mid = int(row_positions[r + 1])
        for c in range(n_cols):
            x1 = int(col_positions[c])
            x2 = int(col_positions[c + 1])
            # Check if horizontal line exists at this row boundary
            if x2 > x1 and 0 <= y_mid < h_lines.shape[0]:
                line_slice = h_lines[y_mid, x1:x2]
                has_line = np.any(line_slice > 0) if line_slice.size > 0 else False
            else:
                has_line = False

            if not has_line and grid[r][c].rowspan == 1 and grid[r][c].colspan >= 1:
                grid[r][c].rowspan += 1
                if r + 1 < n_rows:
                    grid[r + 1][c].rowspan = 0


def build_table_data(
    grid: list[list[TableCell]],
    cell_texts: dict | None = None,
    title: str = "",
    sheet_name: str = "",
) -> TableData:
    """
    Convert a raw grid with optional cell texts into a TableData object.

    Args:
        grid: 2D list of TableCell objects.
        cell_texts: Optional dict mapping (row, col) → text strings.
        title: Table title.
        sheet_name: Excel sheet name.

    Returns:
        TableData ready for export.
    """
    # Fill in texts if provided
    if cell_texts:
        for r, row_cells in enumerate(grid):
            for c, cell in enumerate(row_cells):
                if cell.colspan == 0 or cell.rowspan == 0:
                    continue
                key = (r, c)
                if key in cell_texts:
                    cell.text = cell_texts[key]

    # Filter out absorbed cells (rowspan=0 or colspan=0)
    filtered_rows = []
    for row_cells in grid:
        visible = [c for c in row_cells if c.colspan > 0 and c.rowspan > 0]
        if visible:
            filtered_rows.append(visible)

    has_merged = any(
        cell.rowspan > 1 or cell.colspan > 1
        for row in filtered_rows
        for cell in row
    )

    return TableData(
        title=title,
        sheet_name=sheet_name,
        headers=[],
        rows=filtered_rows,
        has_merged_cells=has_merged,
    )
