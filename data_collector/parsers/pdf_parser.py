from pathlib import Path

from common.logger import get_logger

logger = get_logger(__name__)


class PDFParser:
    """PDF文档解析器"""

    def parse_to_text(self, file_path: str | Path) -> str:
        """将PDF文件解析为纯文本"""
        try:
            import pdfplumber

            text_parts = []
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
            return "\n".join(text_parts)
        except ImportError:
            logger.error("pdfplumber未安装，请执行 pip install pdfplumber")
            return ""
        except Exception as e:
            logger.error(f"PDF解析失败 {file_path}: {e}")
            return ""

    def parse_tables(self, file_path: str | Path) -> list[list[list[str]]]:
        """从PDF中提取表格数据"""
        try:
            import pdfplumber

            tables = []
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    page_tables = page.extract_tables()
                    if page_tables:
                        tables.extend(page_tables)
            return tables
        except ImportError:
            logger.error("pdfplumber未安装")
            return []
        except Exception as e:
            logger.error(f"PDF表格提取失败 {file_path}: {e}")
            return []
