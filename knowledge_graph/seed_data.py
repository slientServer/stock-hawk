"""产业链骨架种子数据：光通信 / AI算力 / 新能源车"""
from typing import Any


def _uid(chain: str, seg: str) -> str:
    return f"{chain}::{seg}"


# ====================================================================
#  光通信产业链
# ====================================================================

OPTICAL_CHAIN: dict[str, Any] = {
    "chain": {
        "name": "光通信产业链",
        "description": "以光模块为核心，涵盖光芯片到数通设备的通信产业链",
        "status": "active",
        "_source": "manual_verified",
        "_is_usable_for_discovery": True,
    },
    "segments": [
        {"uid": _uid("光通信产业链", "光芯片"), "name": "光芯片", "position": "上游", "chain_name": "光通信产业链"},
        {"uid": _uid("光通信产业链", "光器件"), "name": "光器件", "position": "上游", "chain_name": "光通信产业链"},
        {"uid": _uid("光通信产业链", "光模块"), "name": "光模块", "position": "中游", "chain_name": "光通信产业链"},
        {"uid": _uid("光通信产业链", "数通设备商"), "name": "数通设备商", "position": "下游", "chain_name": "光通信产业链"},
        {"uid": _uid("光通信产业链", "运营商"), "name": "运营商", "position": "下游", "chain_name": "光通信产业链"},
    ],
    "companies": [
        {"code": "300308", "name": "中际旭创", "market_cap": 1800.0, "industry": "光模块"},
        {"code": "300502", "name": "新易盛", "market_cap": 600.0, "industry": "光模块"},
        {"code": "300394", "name": "天孚通信", "market_cap": 500.0, "industry": "光器件"},
        {"code": "688498", "name": "源杰科技", "market_cap": 120.0, "industry": "光芯片"},
        {"code": "688048", "name": "长光华芯", "market_cap": 150.0, "industry": "光芯片"},
        {"code": "002281", "name": "光迅科技", "market_cap": 300.0, "industry": "光模块"},
        {"code": "000988", "name": "华工科技", "market_cap": 250.0, "industry": "光器件"},
        {"code": "688195", "name": "腾景科技", "market_cap": 60.0, "industry": "光学元件"},
    ],
    "technologies": [
        {"name": "硅光技术", "maturity_stage": "成长期"},
        {"name": "EML激光器", "maturity_stage": "成熟期"},
        {"name": "VCSEL", "maturity_stage": "成熟期"},
        {"name": "CPO共封装光学", "maturity_stage": "导入期"},
        {"name": "LPO线性直驱", "maturity_stage": "导入期"},
    ],
    "products": [
        {"name": "800G光模块", "specs": "800Gbps DR8/FR4", "price_trend": "下跌"},
        {"name": "400G光模块", "specs": "400Gbps DR4", "price_trend": "持平"},
        {"name": "1.6T光模块", "specs": "1.6Tbps", "price_trend": "上涨"},
        {"name": "CW激光器芯片", "specs": "连续波激光器", "price_trend": "上涨"},
        {"name": "光纤连接器", "specs": "MPO/MTP", "price_trend": "持平"},
        {"name": "光学透镜", "specs": "精密光学透镜", "price_trend": "持平"},
        {"name": "光放大器", "specs": "EDFA", "price_trend": "持平"},
    ],
}

# ====================================================================
#  AI算力产业链
# ====================================================================

AI_CHAIN: dict[str, Any] = {
    "chain": {
        "name": "AI算力产业链",
        "description": "以AI芯片和服务器为核心的算力基础设施产业链",
        "status": "active",
        "_source": "manual_verified",
        "_is_usable_for_discovery": True,
    },
    "segments": [
        {"uid": _uid("AI算力产业链", "芯片设计"), "name": "芯片设计", "position": "上游", "chain_name": "AI算力产业链"},
        {"uid": _uid("AI算力产业链", "先进封装"), "name": "先进封装", "position": "上游", "chain_name": "AI算力产业链"},
        {"uid": _uid("AI算力产业链", "AI服务器"), "name": "AI服务器", "position": "中游", "chain_name": "AI算力产业链"},
        {"uid": _uid("AI算力产业链", "云厂商"), "name": "云厂商", "position": "下游", "chain_name": "AI算力产业链"},
        {"uid": _uid("AI算力产业链", "互联网应用"), "name": "互联网应用", "position": "下游", "chain_name": "AI算力产业链"},
    ],
    "companies": [
        {"code": "688256", "name": "寒武纪", "market_cap": 2000.0, "industry": "AI芯片"},
        {"code": "688041", "name": "海光信息", "market_cap": 1500.0, "industry": "CPU/GPU"},
        {"code": "603019", "name": "中科曙光", "market_cap": 800.0, "industry": "AI服务器"},
        {"code": "000977", "name": "浪潮信息", "market_cap": 600.0, "industry": "AI服务器"},
        {"code": "000938", "name": "紫光股份", "market_cap": 500.0, "industry": "IT基础设施"},
        {"code": "688047", "name": "龙芯中科", "market_cap": 300.0, "industry": "CPU"},
        {"code": "300474", "name": "景嘉微", "market_cap": 200.0, "industry": "GPU"},
        {"code": "688981", "name": "中芯国际", "market_cap": 4000.0, "industry": "晶圆代工"},
    ],
    "technologies": [
        {"name": "Chiplet封装", "maturity_stage": "成长期"},
        {"name": "CoWoS封装", "maturity_stage": "成长期"},
        {"name": "HBM高带宽内存", "maturity_stage": "成长期"},
        {"name": "液冷散热", "maturity_stage": "导入期"},
        {"name": "RISC-V架构", "maturity_stage": "研发期"},
    ],
    "products": [
        {"name": "AI训练卡", "specs": "思元系列/深算系列", "price_trend": "上涨"},
        {"name": "AI推理卡", "specs": "推理加速卡", "price_trend": "上涨"},
        {"name": "AI服务器整机", "specs": "GPU服务器", "price_trend": "上涨"},
        {"name": "交换芯片", "specs": "数据中心交换芯片", "price_trend": "持平"},
        {"name": "液冷模组", "specs": "冷板式/浸没式", "price_trend": "上涨"},
    ],
}

# ====================================================================
#  新能源车产业链
# ====================================================================

NEV_CHAIN: dict[str, Any] = {
    "chain": {
        "name": "新能源车产业链",
        "description": "以动力电池为核心的新能源汽车产业链",
        "status": "active",
        "_source": "manual_verified",
        "_is_usable_for_discovery": True,
    },
    "segments": [
        {"uid": _uid("新能源车产业链", "锂矿资源"), "name": "锂矿资源", "position": "上游", "chain_name": "新能源车产业链"},
        {"uid": _uid("新能源车产业链", "正负极材料"), "name": "正负极材料", "position": "上游", "chain_name": "新能源车产业链"},
        {"uid": _uid("新能源车产业链", "电池"), "name": "电池", "position": "中游", "chain_name": "新能源车产业链"},
        {"uid": _uid("新能源车产业链", "整车"), "name": "整车", "position": "下游", "chain_name": "新能源车产业链"},
        {"uid": _uid("新能源车产业链", "充电桩"), "name": "充电桩", "position": "下游", "chain_name": "新能源车产业链"},
    ],
    "companies": [
        {"code": "002466", "name": "天齐锂业", "market_cap": 800.0, "industry": "锂矿"},
        {"code": "002460", "name": "赣锋锂业", "market_cap": 700.0, "industry": "锂矿"},
        {"code": "300750", "name": "宁德时代", "market_cap": 10000.0, "industry": "动力电池"},
        {"code": "002594", "name": "比亚迪", "market_cap": 8000.0, "industry": "整车+电池"},
        {"code": "300014", "name": "亿纬锂能", "market_cap": 600.0, "industry": "动力电池"},
        {"code": "002812", "name": "恩捷股份", "market_cap": 400.0, "industry": "隔膜"},
        {"code": "603659", "name": "璞泰来", "market_cap": 300.0, "industry": "负极材料"},
        {"code": "300073", "name": "当升科技", "market_cap": 250.0, "industry": "正极材料"},
    ],
    "technologies": [
        {"name": "固态电池", "maturity_stage": "研发期"},
        {"name": "钠离子电池", "maturity_stage": "导入期"},
        {"name": "4680大圆柱", "maturity_stage": "导入期"},
        {"name": "CTP/CTC一体化", "maturity_stage": "成长期"},
        {"name": "800V高压平台", "maturity_stage": "成长期"},
    ],
    "products": [
        {"name": "磷酸铁锂电芯", "specs": "LFP方形电芯", "price_trend": "下跌"},
        {"name": "三元锂电芯", "specs": "NCM811/NCA", "price_trend": "下跌"},
        {"name": "碳酸锂", "specs": "电池级碳酸锂", "price_trend": "下跌"},
        {"name": "锂电隔膜", "specs": "湿法隔膜", "price_trend": "下跌"},
        {"name": "负极材料", "specs": "人造石墨/硅碳", "price_trend": "持平"},
        {"name": "正极材料", "specs": "磷酸铁锂/三元材料", "price_trend": "下跌"},
    ],
}

ALL_CHAINS = [OPTICAL_CHAIN, AI_CHAIN, NEV_CHAIN]


# ====================================================================
#  汇总接口
# ====================================================================

def get_all_nodes() -> dict[str, list[dict[str, Any]]]:
    """返回所有节点，按标签分组"""
    nodes: dict[str, list[dict]] = {
        "IndustryChain": [],
        "Segment": [],
        "Company": [],
        "Technology": [],
        "Product": [],
    }
    for chain in ALL_CHAINS:
        nodes["IndustryChain"].append(chain["chain"])
        nodes["Segment"].extend(chain["segments"])
        nodes["Company"].extend(chain["companies"])
        nodes["Technology"].extend(chain["technologies"])
        nodes["Product"].extend(chain["products"])
    return nodes


def _rel(from_label: str, from_kf: str, from_kv: Any,
         to_label: str, to_kf: str, to_kv: Any,
         rel_type: str, props: dict | None = None) -> dict[str, Any]:
    return {
        "from_label": from_label, "from_key_field": from_kf, "from_key_value": from_kv,
        "to_label": to_label, "to_key_field": to_kf, "to_key_value": to_kv,
        "rel_type": rel_type, "properties": props or {},
    }


def get_all_relationships() -> list[dict[str, Any]]:
    """返回所有关系"""
    rels: list[dict[str, Any]] = []

    # ==================== 光通信 ====================

    # BELONGS_TO: Company → Segment
    rels.append(_rel("Company", "code", "300308", "Segment", "uid", _uid("光通信产业链", "光模块"), "BELONGS_TO", {"role": "龙头"}))
    rels.append(_rel("Company", "code", "300502", "Segment", "uid", _uid("光通信产业链", "光模块"), "BELONGS_TO"))
    rels.append(_rel("Company", "code", "002281", "Segment", "uid", _uid("光通信产业链", "光模块"), "BELONGS_TO"))
    rels.append(_rel("Company", "code", "300394", "Segment", "uid", _uid("光通信产业链", "光器件"), "BELONGS_TO", {"role": "龙头"}))
    rels.append(_rel("Company", "code", "000988", "Segment", "uid", _uid("光通信产业链", "光器件"), "BELONGS_TO"))
    rels.append(_rel("Company", "code", "688195", "Segment", "uid", _uid("光通信产业链", "光器件"), "BELONGS_TO"))
    rels.append(_rel("Company", "code", "688498", "Segment", "uid", _uid("光通信产业链", "光芯片"), "BELONGS_TO"))
    rels.append(_rel("Company", "code", "688048", "Segment", "uid", _uid("光通信产业链", "光芯片"), "BELONGS_TO"))

    # PRODUCES: Company → Product
    rels.append(_rel("Company", "code", "300308", "Product", "name", "800G光模块", "PRODUCES"))
    rels.append(_rel("Company", "code", "300308", "Product", "name", "400G光模块", "PRODUCES"))
    rels.append(_rel("Company", "code", "300502", "Product", "name", "800G光模块", "PRODUCES"))
    rels.append(_rel("Company", "code", "300502", "Product", "name", "1.6T光模块", "PRODUCES"))
    rels.append(_rel("Company", "code", "002281", "Product", "name", "400G光模块", "PRODUCES"))
    rels.append(_rel("Company", "code", "002281", "Product", "name", "光放大器", "PRODUCES"))
    rels.append(_rel("Company", "code", "300394", "Product", "name", "光纤连接器", "PRODUCES"))
    rels.append(_rel("Company", "code", "300394", "Product", "name", "光学透镜", "PRODUCES"))
    rels.append(_rel("Company", "code", "000988", "Product", "name", "光纤连接器", "PRODUCES"))
    rels.append(_rel("Company", "code", "688195", "Product", "name", "光学透镜", "PRODUCES"))
    rels.append(_rel("Company", "code", "688498", "Product", "name", "CW激光器芯片", "PRODUCES"))
    rels.append(_rel("Company", "code", "688048", "Product", "name", "CW激光器芯片", "PRODUCES"))

    # USES: Product → Technology
    rels.append(_rel("Product", "name", "800G光模块", "Technology", "name", "硅光技术", "USES"))
    rels.append(_rel("Product", "name", "800G光模块", "Technology", "name", "EML激光器", "USES"))
    rels.append(_rel("Product", "name", "1.6T光模块", "Technology", "name", "CPO共封装光学", "USES"))
    rels.append(_rel("Product", "name", "1.6T光模块", "Technology", "name", "LPO线性直驱", "USES"))
    rels.append(_rel("Product", "name", "CW激光器芯片", "Technology", "name", "EML激光器", "USES"))
    rels.append(_rel("Product", "name", "400G光模块", "Technology", "name", "VCSEL", "USES"))

    # SUPPLIES_TO: Company → Company
    rels.append(_rel("Company", "code", "688498", "Company", "code", "300308", "SUPPLIES_TO", {"product": "CW激光器芯片"}))
    rels.append(_rel("Company", "code", "688048", "Company", "code", "300502", "SUPPLIES_TO", {"product": "CW激光器芯片"}))
    rels.append(_rel("Company", "code", "688498", "Company", "code", "002281", "SUPPLIES_TO", {"product": "CW激光器芯片"}))
    rels.append(_rel("Company", "code", "300394", "Company", "code", "300308", "SUPPLIES_TO", {"product": "光纤连接器"}))
    rels.append(_rel("Company", "code", "300394", "Company", "code", "300502", "SUPPLIES_TO", {"product": "光纤连接器"}))
    rels.append(_rel("Company", "code", "000988", "Company", "code", "300308", "SUPPLIES_TO", {"product": "光纤连接器"}))
    rels.append(_rel("Company", "code", "688195", "Company", "code", "300308", "SUPPLIES_TO", {"product": "光学透镜"}))
    rels.append(_rel("Company", "code", "688195", "Company", "code", "300502", "SUPPLIES_TO", {"product": "光学透镜"}))

    # COMPETES_WITH
    rels.append(_rel("Company", "code", "300308", "Company", "code", "300502", "COMPETES_WITH", {"field": "光模块"}))
    rels.append(_rel("Company", "code", "300308", "Company", "code", "002281", "COMPETES_WITH", {"field": "光模块"}))
    rels.append(_rel("Company", "code", "300502", "Company", "code", "002281", "COMPETES_WITH", {"field": "光模块"}))
    rels.append(_rel("Company", "code", "688498", "Company", "code", "688048", "COMPETES_WITH", {"field": "光芯片"}))
    rels.append(_rel("Company", "code", "300394", "Company", "code", "000988", "COMPETES_WITH", {"field": "光器件"}))
    rels.append(_rel("Company", "code", "300394", "Company", "code", "688195", "COMPETES_WITH", {"field": "光器件"}))

    # TRANSMITS_TO: 下游需求传导到上游
    rels.append(_rel("Segment", "uid", _uid("光通信产业链", "运营商"), "Segment", "uid", _uid("光通信产业链", "数通设备商"), "TRANSMITS_TO"))
    rels.append(_rel("Segment", "uid", _uid("光通信产业链", "数通设备商"), "Segment", "uid", _uid("光通信产业链", "光模块"), "TRANSMITS_TO"))
    rels.append(_rel("Segment", "uid", _uid("光通信产业链", "光模块"), "Segment", "uid", _uid("光通信产业链", "光器件"), "TRANSMITS_TO"))
    rels.append(_rel("Segment", "uid", _uid("光通信产业链", "光模块"), "Segment", "uid", _uid("光通信产业链", "光芯片"), "TRANSMITS_TO"))
    rels.append(_rel("Segment", "uid", _uid("光通信产业链", "光器件"), "Segment", "uid", _uid("光通信产业链", "光芯片"), "TRANSMITS_TO"))

    # DRIVES
    rels.append(_rel("Segment", "uid", _uid("光通信产业链", "数通设备商"), "Segment", "uid", _uid("光通信产业链", "光模块"), "DRIVES", {"driver": "AI训练需求驱动光模块放量"}))
    rels.append(_rel("Segment", "uid", _uid("光通信产业链", "光模块"), "Segment", "uid", _uid("光通信产业链", "光芯片"), "DRIVES", {"driver": "高速光模块拉动光芯片需求"}))

    # ==================== AI算力 ====================

    # BELONGS_TO
    rels.append(_rel("Company", "code", "688256", "Segment", "uid", _uid("AI算力产业链", "芯片设计"), "BELONGS_TO", {"role": "龙头"}))
    rels.append(_rel("Company", "code", "688041", "Segment", "uid", _uid("AI算力产业链", "芯片设计"), "BELONGS_TO"))
    rels.append(_rel("Company", "code", "688047", "Segment", "uid", _uid("AI算力产业链", "芯片设计"), "BELONGS_TO"))
    rels.append(_rel("Company", "code", "300474", "Segment", "uid", _uid("AI算力产业链", "芯片设计"), "BELONGS_TO"))
    rels.append(_rel("Company", "code", "688981", "Segment", "uid", _uid("AI算力产业链", "先进封装"), "BELONGS_TO", {"role": "龙头"}))
    rels.append(_rel("Company", "code", "603019", "Segment", "uid", _uid("AI算力产业链", "AI服务器"), "BELONGS_TO", {"role": "龙头"}))
    rels.append(_rel("Company", "code", "000977", "Segment", "uid", _uid("AI算力产业链", "AI服务器"), "BELONGS_TO"))
    rels.append(_rel("Company", "code", "000938", "Segment", "uid", _uid("AI算力产业链", "云厂商"), "BELONGS_TO"))

    # PRODUCES
    rels.append(_rel("Company", "code", "688256", "Product", "name", "AI训练卡", "PRODUCES"))
    rels.append(_rel("Company", "code", "688256", "Product", "name", "AI推理卡", "PRODUCES"))
    rels.append(_rel("Company", "code", "688041", "Product", "name", "AI训练卡", "PRODUCES"))
    rels.append(_rel("Company", "code", "300474", "Product", "name", "AI推理卡", "PRODUCES"))
    rels.append(_rel("Company", "code", "603019", "Product", "name", "AI服务器整机", "PRODUCES"))
    rels.append(_rel("Company", "code", "000977", "Product", "name", "AI服务器整机", "PRODUCES"))
    rels.append(_rel("Company", "code", "000938", "Product", "name", "交换芯片", "PRODUCES"))
    rels.append(_rel("Company", "code", "603019", "Product", "name", "液冷模组", "PRODUCES"))

    # USES
    rels.append(_rel("Product", "name", "AI训练卡", "Technology", "name", "Chiplet封装", "USES"))
    rels.append(_rel("Product", "name", "AI训练卡", "Technology", "name", "CoWoS封装", "USES"))
    rels.append(_rel("Product", "name", "AI训练卡", "Technology", "name", "HBM高带宽内存", "USES"))
    rels.append(_rel("Product", "name", "AI服务器整机", "Technology", "name", "液冷散热", "USES"))
    rels.append(_rel("Product", "name", "AI推理卡", "Technology", "name", "RISC-V架构", "USES"))

    # SUPPLIES_TO
    rels.append(_rel("Company", "code", "688256", "Company", "code", "603019", "SUPPLIES_TO", {"product": "AI训练卡"}))
    rels.append(_rel("Company", "code", "688256", "Company", "code", "000977", "SUPPLIES_TO", {"product": "AI训练卡"}))
    rels.append(_rel("Company", "code", "688041", "Company", "code", "603019", "SUPPLIES_TO", {"product": "CPU"}))
    rels.append(_rel("Company", "code", "688041", "Company", "code", "000977", "SUPPLIES_TO", {"product": "CPU"}))
    rels.append(_rel("Company", "code", "688981", "Company", "code", "688256", "SUPPLIES_TO", {"product": "晶圆代工"}))
    rels.append(_rel("Company", "code", "688981", "Company", "code", "688041", "SUPPLIES_TO", {"product": "晶圆代工"}))
    rels.append(_rel("Company", "code", "603019", "Company", "code", "000938", "SUPPLIES_TO", {"product": "AI服务器"}))
    rels.append(_rel("Company", "code", "000977", "Company", "code", "000938", "SUPPLIES_TO", {"product": "AI服务器"}))

    # COMPETES_WITH
    rels.append(_rel("Company", "code", "688256", "Company", "code", "688041", "COMPETES_WITH", {"field": "AI芯片"}))
    rels.append(_rel("Company", "code", "688256", "Company", "code", "300474", "COMPETES_WITH", {"field": "GPU"}))
    rels.append(_rel("Company", "code", "688041", "Company", "code", "688047", "COMPETES_WITH", {"field": "CPU"}))
    rels.append(_rel("Company", "code", "603019", "Company", "code", "000977", "COMPETES_WITH", {"field": "AI服务器"}))

    # TRANSMITS_TO
    rels.append(_rel("Segment", "uid", _uid("AI算力产业链", "互联网应用"), "Segment", "uid", _uid("AI算力产业链", "云厂商"), "TRANSMITS_TO"))
    rels.append(_rel("Segment", "uid", _uid("AI算力产业链", "云厂商"), "Segment", "uid", _uid("AI算力产业链", "AI服务器"), "TRANSMITS_TO"))
    rels.append(_rel("Segment", "uid", _uid("AI算力产业链", "AI服务器"), "Segment", "uid", _uid("AI算力产业链", "先进封装"), "TRANSMITS_TO"))
    rels.append(_rel("Segment", "uid", _uid("AI算力产业链", "AI服务器"), "Segment", "uid", _uid("AI算力产业链", "芯片设计"), "TRANSMITS_TO"))
    rels.append(_rel("Segment", "uid", _uid("AI算力产业链", "先进封装"), "Segment", "uid", _uid("AI算力产业链", "芯片设计"), "TRANSMITS_TO"))

    # DRIVES
    rels.append(_rel("Segment", "uid", _uid("AI算力产业链", "云厂商"), "Segment", "uid", _uid("AI算力产业链", "AI服务器"), "DRIVES", {"driver": "大模型训练驱动AI服务器采购"}))
    rels.append(_rel("Segment", "uid", _uid("AI算力产业链", "AI服务器"), "Segment", "uid", _uid("AI算力产业链", "芯片设计"), "DRIVES", {"driver": "AI服务器需求拉动国产AI芯片"}))
    rels.append(_rel("Segment", "uid", _uid("AI算力产业链", "AI服务器"), "Segment", "uid", _uid("AI算力产业链", "先进封装"), "DRIVES", {"driver": "高算力芯片拉动先进封装需求"}))

    # ==================== 新能源车 ====================

    # BELONGS_TO
    rels.append(_rel("Company", "code", "002466", "Segment", "uid", _uid("新能源车产业链", "锂矿资源"), "BELONGS_TO", {"role": "龙头"}))
    rels.append(_rel("Company", "code", "002460", "Segment", "uid", _uid("新能源车产业链", "锂矿资源"), "BELONGS_TO"))
    rels.append(_rel("Company", "code", "300073", "Segment", "uid", _uid("新能源车产业链", "正负极材料"), "BELONGS_TO"))
    rels.append(_rel("Company", "code", "603659", "Segment", "uid", _uid("新能源车产业链", "正负极材料"), "BELONGS_TO"))
    rels.append(_rel("Company", "code", "002812", "Segment", "uid", _uid("新能源车产业链", "正负极材料"), "BELONGS_TO"))
    rels.append(_rel("Company", "code", "300750", "Segment", "uid", _uid("新能源车产业链", "电池"), "BELONGS_TO", {"role": "龙头"}))
    rels.append(_rel("Company", "code", "300014", "Segment", "uid", _uid("新能源车产业链", "电池"), "BELONGS_TO"))
    rels.append(_rel("Company", "code", "002594", "Segment", "uid", _uid("新能源车产业链", "整车"), "BELONGS_TO", {"role": "龙头"}))

    # PRODUCES
    rels.append(_rel("Company", "code", "002466", "Product", "name", "碳酸锂", "PRODUCES"))
    rels.append(_rel("Company", "code", "002460", "Product", "name", "碳酸锂", "PRODUCES"))
    rels.append(_rel("Company", "code", "300073", "Product", "name", "正极材料", "PRODUCES"))
    rels.append(_rel("Company", "code", "603659", "Product", "name", "负极材料", "PRODUCES"))
    rels.append(_rel("Company", "code", "002812", "Product", "name", "锂电隔膜", "PRODUCES"))
    rels.append(_rel("Company", "code", "300750", "Product", "name", "磷酸铁锂电芯", "PRODUCES"))
    rels.append(_rel("Company", "code", "300750", "Product", "name", "三元锂电芯", "PRODUCES"))
    rels.append(_rel("Company", "code", "300014", "Product", "name", "磷酸铁锂电芯", "PRODUCES"))
    rels.append(_rel("Company", "code", "300014", "Product", "name", "三元锂电芯", "PRODUCES"))
    rels.append(_rel("Company", "code", "002594", "Product", "name", "磷酸铁锂电芯", "PRODUCES"))

    # USES
    rels.append(_rel("Product", "name", "磷酸铁锂电芯", "Technology", "name", "CTP/CTC一体化", "USES"))
    rels.append(_rel("Product", "name", "三元锂电芯", "Technology", "name", "4680大圆柱", "USES"))
    rels.append(_rel("Product", "name", "磷酸铁锂电芯", "Technology", "name", "固态电池", "USES"))
    rels.append(_rel("Product", "name", "三元锂电芯", "Technology", "name", "钠离子电池", "USES"))

    # SUPPLIES_TO
    rels.append(_rel("Company", "code", "002466", "Company", "code", "300750", "SUPPLIES_TO", {"product": "碳酸锂"}))
    rels.append(_rel("Company", "code", "002460", "Company", "code", "300750", "SUPPLIES_TO", {"product": "碳酸锂"}))
    rels.append(_rel("Company", "code", "002466", "Company", "code", "300014", "SUPPLIES_TO", {"product": "碳酸锂"}))
    rels.append(_rel("Company", "code", "300073", "Company", "code", "300750", "SUPPLIES_TO", {"product": "正极材料"}))
    rels.append(_rel("Company", "code", "603659", "Company", "code", "300750", "SUPPLIES_TO", {"product": "负极材料"}))
    rels.append(_rel("Company", "code", "002812", "Company", "code", "300750", "SUPPLIES_TO", {"product": "隔膜"}))
    rels.append(_rel("Company", "code", "300750", "Company", "code", "002594", "SUPPLIES_TO", {"product": "动力电池"}))
    rels.append(_rel("Company", "code", "300014", "Company", "code", "002594", "SUPPLIES_TO", {"product": "动力电池"}))

    # COMPETES_WITH
    rels.append(_rel("Company", "code", "002466", "Company", "code", "002460", "COMPETES_WITH", {"field": "锂矿"}))
    rels.append(_rel("Company", "code", "300750", "Company", "code", "300014", "COMPETES_WITH", {"field": "动力电池"}))
    rels.append(_rel("Company", "code", "300750", "Company", "code", "002594", "COMPETES_WITH", {"field": "动力电池"}))
    rels.append(_rel("Company", "code", "300073", "Company", "code", "603659", "COMPETES_WITH", {"field": "极板材料"}))

    # TRANSMITS_TO
    rels.append(_rel("Segment", "uid", _uid("新能源车产业链", "整车"), "Segment", "uid", _uid("新能源车产业链", "电池"), "TRANSMITS_TO"))
    rels.append(_rel("Segment", "uid", _uid("新能源车产业链", "电池"), "Segment", "uid", _uid("新能源车产业链", "正负极材料"), "TRANSMITS_TO"))
    rels.append(_rel("Segment", "uid", _uid("新能源车产业链", "正负极材料"), "Segment", "uid", _uid("新能源车产业链", "锂矿资源"), "TRANSMITS_TO"))
    rels.append(_rel("Segment", "uid", _uid("新能源车产业链", "整车"), "Segment", "uid", _uid("新能源车产业链", "充电桩"), "TRANSMITS_TO"))

    # DRIVES
    rels.append(_rel("Segment", "uid", _uid("新能源车产业链", "整车"), "Segment", "uid", _uid("新能源车产业链", "电池"), "DRIVES", {"driver": "新能源车销量增长拉动电池需求"}))
    rels.append(_rel("Segment", "uid", _uid("新能源车产业链", "电池"), "Segment", "uid", _uid("新能源车产业链", "正负极材料"), "DRIVES", {"driver": "电池产能扩张拉动材料需求"}))
    rels.append(_rel("Segment", "uid", _uid("新能源车产业链", "整车"), "Segment", "uid", _uid("新能源车产业链", "充电桩"), "DRIVES", {"driver": "新能源车保有量增长驱动充电基建"}))

    return rels
