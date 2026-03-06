"""表格提取模块。

从 PDF、图片中提取表格数据。
"""

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("tkp_worker.table_extractor")


class TableData:
    """表格数据。"""

    def __init__(
        self,
        *,
        headers: list[str],
        rows: list[list[str]],
        page_num: int | None = None,
    ):
        """初始化表格数据。"""
        self.headers = headers
        self.rows = rows
        self.page_num = page_num

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "headers": self.headers,
            "rows": self.rows,
            "page_num": self.page_num,
        }

    def to_markdown(self) -> str:
        """转换为 Markdown 表格。"""
        if not self.headers and not self.rows:
            return ""

        lines = []

        # 表头
        if self.headers:
            lines.append("| " + " | ".join(self.headers) + " |")
            lines.append("| " + " | ".join(["---"] * len(self.headers)) + " |")

        # 数据行
        for row in self.rows:
            lines.append("| " + " | ".join(row) + " |")

        return "\n".join(lines)

    def to_csv(self) -> str:
        """转换为 CSV 格式。"""
        import csv
        import io

        output = io.StringIO()
        writer = csv.writer(output)

        if self.headers:
            writer.writerow(self.headers)

        for row in self.rows:
            writer.writerow(row)

        return output.getvalue()


class TableExtractor:
    """表格提取器。"""

    def __init__(self, method: str = "camelot"):
        """初始化表格提取器。

        Args:
            method: 提取方法（camelot/tabula）
        """
        self.method = method

        if method == "camelot":
            try:
                import camelot
            except ImportError as exc:
                raise RuntimeError("Camelot requires 'camelot-py' package") from exc
        elif method == "tabula":
            try:
                import tabula
            except ImportError as exc:
                raise RuntimeError("Tabula requires 'tabula-py' package") from exc
        else:
            raise ValueError(f"Unsupported table extraction method: {method}")

        logger.info("table extractor initialized: method=%s", method)

    def extract_from_pdf(self, pdf_path: Path, pages: str = "all") -> list[TableData]:
        """从 PDF 中提取表格。

        Args:
            pdf_path: PDF 文件路径
            pages: 页码范围（如 "1-3" 或 "all"）

        Returns:
            表格数据列表
        """
        if self.method == "camelot":
            return self._extract_with_camelot(pdf_path, pages)
        elif self.method == "tabula":
            return self._extract_with_tabula(pdf_path, pages)
        else:
            return []

    def _extract_with_camelot(self, pdf_path: Path, pages: str) -> list[TableData]:
        """使用 Camelot 提取表格。"""
        import camelot

        try:
            # 提取表格
            tables = camelot.read_pdf(str(pdf_path), pages=pages, flavor="lattice")

            results = []
            for i, table in enumerate(tables):
                df = table.df

                # 提取表头和数据
                if len(df) > 0:
                    headers = df.iloc[0].tolist()
                    rows = df.iloc[1:].values.tolist()

                    results.append(
                        TableData(
                            headers=headers,
                            rows=rows,
                            page_num=table.page,
                        )
                    )

            logger.info("extracted %d tables with camelot", len(results))
            return results
        except Exception as exc:
            logger.exception("camelot extraction failed: %s", exc)
            return []

    def _extract_with_tabula(self, pdf_path: Path, pages: str) -> list[TableData]:
        """使用 Tabula 提取表格。"""
        import tabula

        try:
            # 提取表格
            dfs = tabula.read_pdf(str(pdf_path), pages=pages, multiple_tables=True)

            results = []
            for i, df in enumerate(dfs):
                if len(df) > 0:
                    # 提取表头和数据
                    headers = df.columns.tolist()
                    rows = df.values.tolist()

                    results.append(
                        TableData(
                            headers=headers,
                            rows=rows,
                            page_num=None,  # Tabula 不提供页码信息
                        )
                    )

            logger.info("extracted %d tables with tabula", len(results))
            return results
        except Exception as exc:
            logger.exception("tabula extraction failed: %s", exc)
            return []

    def extract_from_image(self, image_path: Path, ocr_service) -> list[TableData]:
        """从图片中提取表格（使用 OCR + 结构分析）。

        Args:
            image_path: 图片路径
            ocr_service: OCR 服务实例

        Returns:
            表格数据列表
        """
        try:
            # 使用 OCR 识别文字
            ocr_result = ocr_service.recognize_image(image_path)

            if not ocr_result.boxes:
                return []

            # 简单的表格检测：根据文本框位置推断表格结构
            # 这里使用简化的启发式方法
            boxes = sorted(ocr_result.boxes, key=lambda b: (b.get("y", 0), b.get("x", 0)))

            # 按行分组
            rows = []
            current_row = []
            current_y = None
            y_threshold = 20  # 同一行的 y 坐标差异阈值

            for box in boxes:
                y = box.get("y", 0)

                if current_y is None:
                    current_y = y
                    current_row.append(box["text"])
                elif abs(y - current_y) < y_threshold:
                    current_row.append(box["text"])
                else:
                    if current_row:
                        rows.append(current_row)
                    current_row = [box["text"]]
                    current_y = y

            if current_row:
                rows.append(current_row)

            # 如果检测到多行，假设第一行是表头
            if len(rows) > 1:
                headers = rows[0]
                data_rows = rows[1:]

                return [
                    TableData(
                        headers=headers,
                        rows=data_rows,
                        page_num=None,
                    )
                ]

            return []
        except Exception as exc:
            logger.exception("failed to extract table from image: %s", exc)
            return []


def create_table_extractor(method: str = "camelot") -> TableExtractor:
    """创建表格提取器的工厂函数。"""
    return TableExtractor(method=method)
