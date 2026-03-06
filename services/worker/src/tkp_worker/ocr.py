"""OCR 文字识别服务。

支持多种 OCR 引擎：Tesseract、PaddleOCR、云服务 API。
"""

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("tkp_worker.ocr")


class OCRResult:
    """OCR 识别结果。"""

    def __init__(
        self,
        *,
        text: str,
        confidence: float,
        boxes: list[dict[str, Any]] | None = None,
    ):
        """初始化 OCR 结果。

        Args:
            text: 识别的文本
            confidence: 置信度（0-1）
            boxes: 文本框位置信息
        """
        self.text = text
        self.confidence = confidence
        self.boxes = boxes or []


class TesseractOCR:
    """Tesseract OCR 引擎。"""

    def __init__(self, lang: str = "eng+chi_sim"):
        """初始化 Tesseract OCR。

        Args:
            lang: 语言代码（eng=英文, chi_sim=简体中文）
        """
        try:
            import pytesseract
        except ImportError as exc:
            raise RuntimeError("Tesseract OCR requires 'pytesseract' package") from exc

        self.lang = lang
        logger.info("tesseract ocr initialized: lang=%s", lang)

    def recognize(self, image_path: Path) -> OCRResult:
        """识别图片中的文字。

        Args:
            image_path: 图片路径

        Returns:
            OCR 识别结果
        """
        import pytesseract
        from PIL import Image

        try:
            # 打开图片
            image = Image.open(image_path)

            # 执行 OCR
            text = pytesseract.image_to_string(image, lang=self.lang)

            # 获取详细信息（包含置信度）
            data = pytesseract.image_to_data(image, lang=self.lang, output_type=pytesseract.Output.DICT)

            # 计算平均置信度
            confidences = [float(conf) for conf in data["conf"] if conf != "-1"]
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

            # 提取文本框信息
            boxes = []
            for i in range(len(data["text"])):
                if data["text"][i].strip():
                    boxes.append(
                        {
                            "text": data["text"][i],
                            "confidence": float(data["conf"][i]) / 100.0,
                            "x": data["left"][i],
                            "y": data["top"][i],
                            "width": data["width"][i],
                            "height": data["height"][i],
                        }
                    )

            logger.info(
                "tesseract ocr completed: text_length=%d, confidence=%.2f",
                len(text),
                avg_confidence,
            )

            return OCRResult(
                text=text.strip(),
                confidence=avg_confidence / 100.0,
                boxes=boxes,
            )
        except Exception as exc:
            logger.exception("tesseract ocr failed: %s", exc)
            return OCRResult(text="", confidence=0.0)


class PaddleOCR:
    """PaddleOCR 引擎。"""

    def __init__(self, lang: str = "ch"):
        """初始化 PaddleOCR。

        Args:
            lang: 语言代码（ch=中文, en=英文）
        """
        try:
            from paddleocr import PaddleOCR as _PaddleOCR
        except ImportError as exc:
            raise RuntimeError("PaddleOCR requires 'paddleocr' package") from exc

        self.ocr = _PaddleOCR(use_angle_cls=True, lang=lang, show_log=False)
        logger.info("paddleocr initialized: lang=%s", lang)

    def recognize(self, image_path: Path) -> OCRResult:
        """识别图片中的文字。

        Args:
            image_path: 图片路径

        Returns:
            OCR 识别结果
        """
        try:
            # 执行 OCR
            result = self.ocr.ocr(str(image_path), cls=True)

            if not result or not result[0]:
                return OCRResult(text="", confidence=0.0)

            # 提取文本和置信度
            texts = []
            confidences = []
            boxes = []

            for line in result[0]:
                box, (text, confidence) = line
                texts.append(text)
                confidences.append(confidence)

                # 提取文本框坐标
                boxes.append(
                    {
                        "text": text,
                        "confidence": confidence,
                        "box": box,
                    }
                )

            full_text = "\n".join(texts)
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

            logger.info(
                "paddleocr completed: text_length=%d, confidence=%.2f",
                len(full_text),
                avg_confidence,
            )

            return OCRResult(
                text=full_text,
                confidence=avg_confidence,
                boxes=boxes,
            )
        except Exception as exc:
            logger.exception("paddleocr failed: %s", exc)
            return OCRResult(text="", confidence=0.0)


class OCRService:
    """OCR 服务。"""

    def __init__(self, engine: str = "tesseract", lang: str = "eng+chi_sim"):
        """初始化 OCR 服务。

        Args:
            engine: OCR 引擎（tesseract/paddleocr）
            lang: 语言代码
        """
        self.engine = engine

        if engine == "tesseract":
            self.ocr = TesseractOCR(lang=lang)
        elif engine == "paddleocr":
            # PaddleOCR 使用不同的语言代码
            paddle_lang = "ch" if "chi" in lang else "en"
            self.ocr = PaddleOCR(lang=paddle_lang)
        else:
            raise ValueError(f"Unsupported OCR engine: {engine}")

        logger.info("ocr service initialized: engine=%s, lang=%s", engine, lang)

    def recognize_image(self, image_path: Path) -> OCRResult:
        """识别图片中的文字。"""
        return self.ocr.recognize(image_path)

    def recognize_pdf_page(self, pdf_path: Path, page_num: int) -> OCRResult:
        """识别 PDF 页面中的文字。

        Args:
            pdf_path: PDF 文件路径
            page_num: 页码（从 0 开始）

        Returns:
            OCR 识别结果
        """
        try:
            from pdf2image import convert_from_path
            import tempfile

            # 转换 PDF 页面为图片
            images = convert_from_path(
                pdf_path,
                first_page=page_num + 1,
                last_page=page_num + 1,
            )

            if not images:
                return OCRResult(text="", confidence=0.0)

            # 保存临时图片
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                temp_image_path = Path(f.name)
                images[0].save(temp_image_path, "PNG")

            try:
                # 执行 OCR
                result = self.recognize_image(temp_image_path)
                return result
            finally:
                # 清理临时文件
                temp_image_path.unlink(missing_ok=True)

        except Exception as exc:
            logger.exception("pdf page ocr failed: %s", exc)
            return OCRResult(text="", confidence=0.0)


def create_ocr_service(engine: str = "tesseract", lang: str = "eng+chi_sim") -> OCRService:
    """创建 OCR 服务的工厂函数。"""
    return OCRService(engine=engine, lang=lang)
