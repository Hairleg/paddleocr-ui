"""
Author: sizhchan
Org: dgaudit
Version: v0.1
Date: 2026-05-27
"""

#!/usr/bin/env python3
"""Full pipeline run on all 3 test files."""
import os, sys, logging
logging.basicConfig(level=logging.WARN)
os.environ['PADDLE_PDX_MODEL_SOURCE'] = 'modelscope'
os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'

sys.path.insert(0, '/mnt/workspace/project/paddleocr-ui')
os.chdir('/mnt/workspace/project/paddleocr-ui')

from app.pipeline.core.pipeline import process_pdf
from app.pipeline.export.word_writer import write_word
from app.pipeline.export.excel_writer import write_excel

os.makedirs('output', exist_ok=True)

results = []
for name, pdf in [('ht1','江苏南通合同1'), ('ht2','江苏南通合同2'), ('wl','浙江温岭合同')]:
    print(f"Processing {pdf}...", flush=True)
    dl = process_pdf(f'example/{pdf}.pdf', f'/tmp/mineru_final_{name}')
    write_word(dl, f'output/{pdf}_mineru.docx')
    write_excel(dl.tables, f'output/{pdf}_tables.xlsx')
    results.append((name, len(dl.pages), len(dl.tables)))
    print(f"  DONE {name}: {len(dl.pages)}p, {len(dl.tables)}t", flush=True)

print("\n=== FINAL RESULTS ===", flush=True)
for name, pages, tables in results:
    print(f"  {name}: {pages} pages, {tables} tables", flush=True)
