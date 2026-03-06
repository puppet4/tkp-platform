"""图片解析模块。

提取图片元数据、缩略图生成、图片描述生成。
"""

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("tkp_worker.image_parser")


class ImageMetadata:
    """图片元数据。"""

    def __init__(
        self,
        *,
        width: int,
        height: int,
        format: str,
        mode: str,
        size_bytes: int,
        exif: dict[str, Any] | None = None,
    ):
        """初始化图片元数据。"""
        self.width = width
        self.height = height
        self.format = format
        self.mode = mode
        self.size_bytes = size_bytes
        self.exif = exif or {}

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "width": self.width,
            "height": self.height,
            "format": self.format,
            "mode": self.mode,
            "size_bytes": self.size_bytes,
            "exif": self.exif,
        }


class ImageParser:
    """图片解析器。"""

    def __init__(self):
        """初始化图片解析器。"""
        try:
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError("Image parser requires 'Pillow' package") from exc

        logger.info("image parser initialized")

    def extract_metadata(self, image_path: Path) -> ImageMetadata:
        """提取图片元数据。

        Args:
            image_path: 图片路径

        Returns:
            图片元数据
        """
        from PIL import Image
        from PIL.ExifTags import TAGS

        try:
            with Image.open(image_path) as img:
                # 基本信息
                width, height = img.size
                format = img.format or "unknown"
                mode = img.mode
                size_bytes = image_path.stat().st_size

                # EXIF 信息
                exif_data = {}
                if hasattr(img, "_getexif") and img._getexif():
                    exif = img._getexif()
                    for tag_id, value in exif.items():
                        tag = TAGS.get(tag_id, tag_id)
                        exif_data[tag] = str(value)

                logger.info(
                    "extracted image metadata: %dx%d, format=%s, size=%d",
                    width,
                    height,
                    format,
                    size_bytes,
                )

                return ImageMetadata(
                    width=width,
                    height=height,
                    format=format,
                    mode=mode,
                    size_bytes=size_bytes,
                    exif=exif_data,
                )
        except Exception as exc:
            logger.exception("failed to extract image metadata: %s", exc)
            raise

    def generate_thumbnail(
        self,
        image_path: Path,
        output_path: Path,
        max_size: tuple[int, int] = (300, 300),
    ) -> bool:
        """生成缩略图。

        Args:
            image_path: 原始图片路径
            output_path: 输出路径
            max_size: 最大尺寸（宽, 高）

        Returns:
            是否生成成功
        """
        from PIL import Image

        try:
            with Image.open(image_path) as img:
                # 保持宽高比缩放
                img.thumbnail(max_size, Image.Resampling.LANCZOS)

                # 保存缩略图
                img.save(output_path, format=img.format or "JPEG")

                logger.info(
                    "generated thumbnail: %s -> %s, size=%s",
                    image_path.name,
                    output_path.name,
                    img.size,
                )

                return True
        except Exception as exc:
            logger.exception("failed to generate thumbnail: %s", exc)
            return False

    def describe_image(self, image_path: Path, openai_api_key: str) -> str:
        """使用 GPT-4 Vision 生成图片描述。

        Args:
            image_path: 图片路径
            openai_api_key: OpenAI API 密钥

        Returns:
            图片描述
        """
        try:
            from openai import OpenAI
            import base64

            client = OpenAI(api_key=openai_api_key)

            # 读取图片并编码为 base64
            with open(image_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")

            # 调用 GPT-4 Vision
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Please describe this image in detail. Focus on the main content, objects, text, and any important information.",
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_data}",
                                },
                            },
                        ],
                    }
                ],
                max_tokens=500,
            )

            description = response.choices[0].message.content.strip()

            logger.info("generated image description: length=%d", len(description))

            return description
        except Exception as exc:
            logger.exception("failed to describe image: %s", exc)
            return ""

    def extract_text_from_image(self, image_path: Path, ocr_service) -> str:
        """从图片中提取文字（使用 OCR）。

        Args:
            image_path: 图片路径
            ocr_service: OCR 服务实例

        Returns:
            提取的文字
        """
        try:
            result = ocr_service.recognize_image(image_path)
            return result.text
        except Exception as exc:
            logger.exception("failed to extract text from image: %s", exc)
            return ""


def create_image_parser() -> ImageParser:
    """创建图片解析器的工厂函数。"""
    return ImageParser()
