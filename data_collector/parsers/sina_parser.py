import re
from datetime import datetime

from common.logger import get_logger

logger = get_logger(__name__)


class SinaParser:
    """新浪实时行情数据解析器"""

    # 正则匹配 var hq_str_sh600519="...";
    _LINE_PATTERN = re.compile(r'var hq_str_(\w+)="(.*)";')

    @staticmethod
    def build_codes_param(codes: list[str]) -> str:
        """将股票代码列表转为新浪API参数格式

        内部代码 "600519" -> "sh600519"
        内部代码 "000001" -> "sz000001"
        """
        result = []
        for code in codes:
            code = code.strip()
            if code.startswith(("sh", "sz")):
                result.append(code)
            elif code.startswith("6"):
                result.append(f"sh{code}")
            else:
                result.append(f"sz{code}")
        return ",".join(result)

    @staticmethod
    def parse_realtime_response(response_text: str) -> list[dict]:
        """解析新浪实时行情响应文本，返回行情字典列表

        新浪格式每行:
        var hq_str_sh600519="贵州茅台,今开,昨收,当前价,最高,最低,买一价,卖一价,成交量(股),成交额,买一量,买一价,...,日期,时间,...";
        字段顺序: [0]名称, [1]今开, [2]昨收, [3]当前价, [4]最高, [5]最低,
                  [6]买一价, [7]卖一价, [8]成交量(股), [9]成交额,
                  [10]买一量, [11]买一价, ..., [30]日期, [31]时间
        """
        results = []
        for line in response_text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            match = SinaParser._LINE_PATTERN.match(line)
            if not match:
                continue

            symbol = match.group(1)  # e.g. sh600519
            data_str = match.group(2)
            if not data_str:
                continue

            fields = data_str.split(",")
            if len(fields) < 32:
                logger.warning(f"新浪行情数据字段不足: {symbol}, fields={len(fields)}")
                continue

            # 提取纯数字代码
            code = symbol[2:]  # 去掉 sh/sz 前缀

            try:
                timestamp_str = f"{fields[30]} {fields[31]}"
                try:
                    timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                except (ValueError, IndexError):
                    timestamp = datetime.now()

                quote = {
                    "code": code,
                    "name": fields[0],
                    "price": float(fields[3]) if fields[3] else 0.0,
                    "open": float(fields[1]) if fields[1] else 0.0,
                    "yesterday_close": float(fields[2]) if fields[2] else 0.0,
                    "high": float(fields[4]) if fields[4] else 0.0,
                    "low": float(fields[5]) if fields[5] else 0.0,
                    "volume": int(float(fields[8])) if fields[8] else 0,
                    "amount": float(fields[9]) if fields[9] else 0.0,
                    "bid_price": float(fields[6]) if fields[6] else 0.0,
                    "ask_price": float(fields[7]) if fields[7] else 0.0,
                    "timestamp": timestamp.isoformat(),
                    "source": "sina",
                }
                results.append(quote)
            except (ValueError, IndexError) as e:
                logger.warning(f"解析新浪行情失败: {symbol}, error={e}")
                continue

        return results
