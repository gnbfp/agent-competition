"""Read external activity CSVs without silently replacing undecodable bytes."""

from __future__ import annotations

import codecs
import csv
import io
from pathlib import Path


class CsvInputError(ValueError):
    """The input cannot be read as an activity CSV."""


def read_csv(path: Path) -> tuple[list[str], list[dict], str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CsvInputError(f"无法读取 CSV：{exc.strerror}") from None
    if b"\0" in raw:
        raise CsvInputError("CSV 含空字节，请另存为 UTF-8 或 GBK")
    encoding = "UTF-8 BOM" if raw.startswith(codecs.BOM_UTF8) else "UTF-8"
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        if encoding == "UTF-8 BOM":
            raise CsvInputError("带 BOM 的 CSV 不是有效的 UTF-8") from None
        try:
            content = raw.decode("gbk")
        except UnicodeDecodeError:
            raise CsvInputError("CSV 不是有效的 UTF-8 或 GBK") from None
        encoding = "GBK"
    reader = csv.DictReader(io.StringIO(content, newline=""), strict=True)
    try:
        if reader.fieldnames is None:
            raise CsvInputError("CSV 为空，没有表头")
        return reader.fieldnames, list(reader), encoding
    except csv.Error:
        raise CsvInputError(f"CSV 格式错误，请检查第 {reader.line_num} 行附近的分隔符和引号") from None
