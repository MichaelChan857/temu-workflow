"""通用文件解析器 — 支持 CSV 和 XLSX

W3-D1: 把文件解析与标准化/去重/评分分离
"""
import csv
import io
from typing import Iterator
from openpyxl import load_workbook


def parse_csv(content: bytes) -> Iterator[dict]:
    """解析 CSV（自动识别 UTF-8/GBK）"""
    try:
        text = content.decode("utf-8-sig")  # 兼容 BOM
    except UnicodeDecodeError:
        text = content.decode("gbk", errors="replace")

    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        yield {k: (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k is not None}


def parse_xlsx(content: bytes) -> Iterator[dict]:
    """解析 XLSX

    假设第一行为表头
    多 sheet 文件只取第一个 sheet（MVP）
    """
    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active

    rows = ws.iter_rows(values_only=True)
    try:
        headers = [str(h).strip() if h else "" for h in next(rows)]
    except StopIteration:
        return

    for row in rows:
        # 跳过全空行
        if all(v is None or v == "" for v in row):
            continue
        yield {headers[i]: (row[i] if row[i] is not None else "") for i in range(len(headers))}


def parse_file(filename: str, content: bytes) -> Iterator[dict]:
    """按扩展名分发"""
    fn = filename.lower()
    if fn.endswith(".csv"):
        return parse_csv(content)
    elif fn.endswith(".xlsx"):
        return parse_xlsx(content)
    elif fn.endswith(".xls"):
        raise ValueError("XLS (old format) not supported; please use XLSX")
    else:
        raise ValueError(f"unsupported file format: {filename}")