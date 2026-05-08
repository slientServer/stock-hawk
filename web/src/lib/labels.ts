export const SIGNAL_TYPE_LABELS: Record<string, string> = {
  demand_inflection: "需求拐点",
  supply_shortage: "供需紧张",
  earnings_inflection: "业绩拐点",
  chip_concentration: "筹码集中",
  overseas_mapping: "海外映射",
  catalyst: "事件催化",
  north_flow_stock: "北向增持",
  sector_linkage: "板块联动",
  valuation_percentile: "估值低位",
};

export const TREND_TYPE_LABELS: Record<string, string> = {
  structural: "结构性趋势",
  cyclical: "周期波动",
  event_driven: "事件驱动",
  market_momentum: "市场动量",
  data_insufficient: "数据不足",
};

export const STAGE_LABELS: Record<string, string> = {
  seed: "萌芽期",
  verification: "验证期",
  consensus: "共识期",
  overheated: "过热期",
  watching: "观察期",
};

export const CONFIDENCE_LABELS: Record<string, string> = {
  high: "高",
  medium: "中",
  low: "低",
  none: "无",
};

function fallbackLabel(value?: string | null) {
  return value ? value.replaceAll("_", " ") : "-";
}

export function formatSignalType(value?: string | null) {
  return value ? SIGNAL_TYPE_LABELS[value] ?? fallbackLabel(value) : "-";
}

export function formatTrendType(value?: string | null) {
  return value ? TREND_TYPE_LABELS[value] ?? fallbackLabel(value) : "-";
}

export function formatStage(value?: string | null) {
  return value ? STAGE_LABELS[value] ?? fallbackLabel(value) : "-";
}

export function formatConfidence(value?: string | null) {
  return value ? CONFIDENCE_LABELS[value] ?? fallbackLabel(value) : "-";
}

export function formatScanProgress(value?: string | null) {
  if (!value || value === "idle") return "待扫描";
  if (value === "starting") return "正在启动";
  if (value === "completed") return "扫描完成";
  if (value === "failed") return "扫描失败";
  if (value.startsWith("scanning:")) {
    return `正在扫描：${value.slice("scanning:".length) || "-"}`;
  }
  return fallbackLabel(value);
}
