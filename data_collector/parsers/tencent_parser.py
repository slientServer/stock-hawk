import re
from datetime import datetime

from common.logger import get_logger

logger = get_logger(__name__)


class TencentParser:
    """腾讯实时行情数据解析器"""

    # 正则匹配 v_sh600519="...";
    _LINE_PATTERN = re.compile(r'v_(\w+)="(.*)";')

    @staticmethod
    def build_codes_param(codes: list[str]) -> str:
        """将股票代码列表转为腾讯API参数格式

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
        """解析腾讯实时行情响应文本，返回行情字典列表

        腾讯格式每行:
        v_sh600519="1~贵州茅台~600519~1860.50~1850.00~1849.00~12345~6789~5678~1860.50~100~...";
        字段通过~分隔:
        [1]=名称, [2]=代码, [3]=当前价, [4]=昨收, [5]=今开,
        [6]=成交量(手), [30]=最高, [32]=最低, [36]=成交额(万), [31]=日期时间
        """
        results = []
        for line in response_text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            match = TencentParser._LINE_PATTERN.match(line)
            if not match:
                continue

            data_str = match.group(2)
            if not data_str:
                continue

            fields = data_str.split("~")
            if len(fields) < 37:
                logger.warning(f"腾讯行情数据字段不足: fields={len(fields)}")
                continue

            try:
                code = fields[2]
                name = fields[1]
                price = float(fields[3]) if fields[3] else 0.0
                yesterday_close = float(fields[4]) if fields[4] else 0.0
                open_price = float(fields[5]) if fields[5] else 0.0
                volume = int(float(fields[6]) * 100) if fields[6] else 0  # 手->股
                high = float(fields[30]) if fields[30] else 0.0
                low = float(fields[32]) if fields[32] else 0.0
                amount = float(fields[36]) * 10000 if fields[36] else 0.0  # 万->元

                # 日期时间在字段[30]后面，通常在字段[30]是最高价
                # 时间戳通常在 fields[30] 相关位置，尝试解析 fields[30] 附近
                timestamp_str = fields[30] if len(fields) > 30 else ""
                try:
                    # 腾讯时间格式一般在 fields[30] 是日期 yyyyMMddHHmmss
                    if len(fields) > 30 and len(fields[30]) == 14:
                        timestamp = datetime.strptime(fields[30], "%Y%m%d%H%M%S")
                    else:
                        timestamp = datetime.now()
                except (ValueError, IndexError):
                    timestamp = datetime.now()

                # 腾讯没有直接给出买一卖一价，用当前价代替
                bid_price = float(fields[9]) if len(fields) > 9 and fields[9] else price
                ask_price = float(fields[19]) if len(fields) > 19 and fields[19] else price

                quote = {
                    "code": code,
                    "name": name,
                    "price": price,
                    "open": open_price,
                    "yesterday_close": yesterday_close,
                    "high": high,
                    "low": low,
                    "volume": volume,
                    "amount": amount,
                    "bid_price": bid_price,
                    "ask_price": ask_price,
                    "timestamp": timestamp.isoformat(),
                    "source": "tencent",
                }
                results.append(quote)
            except (ValueError, IndexError) as e:
                logger.warning(f"解析腾讯行情失败: error={e}")
                continue

        return results
