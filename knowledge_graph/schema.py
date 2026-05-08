"""知识图谱 Schema 定义：节点类型、关系类型。"""

from enum import Enum


class NodeLabel(str, Enum):
    INDUSTRY_CHAIN = "IndustryChain"
    SEGMENT = "Segment"
    COMPANY = "Company"
    TECHNOLOGY = "Technology"
    PRODUCT = "Product"


class RelationType(str, Enum):
    BELONGS_TO = "BELONGS_TO"
    PRODUCES = "PRODUCES"
    USES = "USES"
    SUPPLIES_TO = "SUPPLIES_TO"
    COMPETES_WITH = "COMPETES_WITH"
    TRANSMITS_TO = "TRANSMITS_TO"
    DRIVES = "DRIVES"


class SegmentPosition(str, Enum):
    UPSTREAM = "上游"
    MIDSTREAM = "中游"
    DOWNSTREAM = "下游"


NODE_KEY_FIELDS = {
    NodeLabel.INDUSTRY_CHAIN: "name",
    NodeLabel.SEGMENT: "uid",
    NodeLabel.COMPANY: "code",
    NodeLabel.TECHNOLOGY: "name",
    NodeLabel.PRODUCT: "name",
}
