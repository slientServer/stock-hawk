"use client";

import { useState, useEffect } from "react";
import { Row, Col, Card, Typography, Spin, Empty, Button, Space, Alert, Tag, message, Collapse } from "antd";
import { ApartmentOutlined, SyncOutlined } from "@ant-design/icons";
import { useRouter } from "next/navigation";
import { getChainDiscoveryStatus, getGraphChains, triggerChainDiscovery } from "@/lib/api";

const { Title, Text, Paragraph } = Typography;

export default function GraphPage() {
  const [chains, setChains] = useState<any>(null);
  const [discovery, setDiscovery] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [discovering, setDiscovering] = useState(false);
  const router = useRouter();

  const refresh = () => {
    getGraphChains()
      .then(setChains)
      .catch(() => setChains(null))
      .finally(() => setLoading(false));
    getChainDiscoveryStatus().then(setDiscovery).catch(() => setDiscovery(null));
  };

  useEffect(() => {
    refresh();
  }, []);

  if (loading) return <Spin size="large" style={{ display: "block", margin: "100px auto" }} />;

  const chainList: any[] = chains?.chains ?? (Array.isArray(chains) ? chains : []);
  const discoveryResult = discovery?.result;
  const discoveryStatus = discoveryResult?.status;
  const sourceAssessment = discoveryResult?.source_assessment;
  const sourceMode = discoveryResult?.source_mode;
  const sourceEntries = Object.entries(discoveryResult?.diagnostics?.sources ?? {});
  const failedSourceEntries = sourceEntries.filter(([, value]: [string, any]) => !value?.success);
  const resolutionSteps: string[] = sourceAssessment?.resolution_steps ?? [];
  const actionRequired = Boolean(sourceAssessment?.action_required) || discoveryStatus === "market_source_unavailable";
  const discoveryBlocked = discoveryStatus === "market_source_unavailable" || sourceMode === "market_unavailable";
  const hotBoardNames = (discoveryResult?.hot_boards ?? [])
    .map((item: any) => typeof item === "string" ? item : item?.board_name ?? item?.name ?? item?.["板块名称"])
    .filter(Boolean);
  const blockingStatuses = ["market_source_unavailable", "llm_unavailable", "data_unavailable", "no_constituents"];
  const warningStatuses = ["degraded", "no_hot_boards", "no_new_chains"];
  const alertType =
    discovery?.error || actionRequired || blockingStatuses.includes(discoveryStatus)
      ? "error"
      : discovery?.running
        ? "info"
        : warningStatuses.includes(discoveryStatus) || sourceMode === "local_fallback"
          ? "warning"
          : "success";

  const taskLabel = () => {
    if (discovery?.running) return "运行中";
    if (discovery?.error) return "失败";
    if (discoveryStatus === "market_source_unavailable" || sourceMode === "market_unavailable") return "数据源待修复";
    if (discoveryStatus === "llm_unavailable") return "LLM 阻塞";
    if (actionRequired) return "需要处理";
    if (blockingStatuses.includes(discoveryStatus)) return "阻塞";
    if (discovery?.from_history) return "最近结果";
    return "空闲";
  };

  const taskTagColor = () => {
    if (discovery?.running) return "processing";
    if (discovery?.error || actionRequired || blockingStatuses.includes(discoveryStatus)) return "red";
    if (warningStatuses.includes(discoveryStatus)) return "orange";
    return "default";
  };

  const sourceModeColor = () => {
    if (sourceMode === "market_unavailable") return "red";
    if (sourceMode === "local_fallback") return "orange";
    return "blue";
  };

  const confidenceColor = () => {
    if (sourceAssessment?.confidence === "none") return "red";
    if (sourceAssessment?.confidence === "low") return "orange";
    return "green";
  };

  const sourceLabel = (key: string) => {
    if (key === "concept") return "概念";
    if (key === "industry") return "行业";
    if (key === "local_industry") return "本地行业";
    return key;
  };

  const summarizeSourceError = (error?: string) => {
    const text = error || "";
    if (!text) return "接口无返回";
    if (text.includes("RemoteDisconnected")) {
      return "东方财富/AKShare 连接被远端断开。通常是当前网络出口、代理、反爬或临时限流导致。";
    }
    if (text.includes("Failed to fetch")) {
      return "浏览器兜底也无法访问东方财富 push2 域名。当前运行机器到行情源不可达。";
    }
    if (text.toLowerCase().includes("timeout")) {
      return "行情源请求超时。请稍后重试，或检查代理和网络出口。";
    }
    return text.length > 160 ? `${text.slice(0, 160)}...` : text;
  };

  const diagnosticItems = [
    ...failedSourceEntries.map(([key, value]: [string, any]) => ({
      key,
      label: `${sourceLabel(key)}数据源诊断`,
      children: (
        <Space orientation="vertical" size={6} style={{ display: "flex" }}>
          <Text type="danger">{summarizeSourceError(value?.error)}</Text>
          <Paragraph
            type="secondary"
            style={{
              marginBottom: 0,
              maxHeight: 220,
              overflow: "auto",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              fontSize: 12,
            }}
          >
            {value?.error || "接口无返回"}
          </Paragraph>
        </Space>
      ),
    })),
    ...(resolutionSteps.length > 0
      ? [{
          key: "resolution_steps",
          label: "建议修复步骤",
          children: (
            <ol style={{ margin: "0 0 0 20px", padding: 0 }}>
              {resolutionSteps.map((step) => (
                <li key={step}>
                  <Text type="secondary">{step}</Text>
                </li>
              ))}
            </ol>
          ),
        }]
      : []),
  ];

  const runDiscovery = async () => {
    setDiscovering(true);
    try {
      await triggerChainDiscovery({ top_n: 20, min_change_pct: 0, dry_run: false });
      message.success("产业链发现已启动");
      setTimeout(refresh, 1200);
    } catch (e: any) {
      message.error(e?.message || "启动失败");
    } finally {
      setDiscovering(false);
    }
  };

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16 }}>
        <div>
          <Title level={3} style={{ marginBottom: 4 }}>知识图谱</Title>
          <Text type="secondary">产业链拓扑结构</Text>
        </div>
        <Space>
          <Button icon={<SyncOutlined />} onClick={refresh}>刷新</Button>
          <Button type="primary" loading={discovering || discovery?.running} onClick={runDiscovery}>
            自动发现产业链
          </Button>
        </Space>
      </div>

      <Alert
        style={{ marginTop: 16 }}
        type={alertType}
        showIcon
        title={
          <Space wrap>
            <span>发现任务</span>
            <Tag color={taskTagColor()}>{taskLabel()}</Tag>
            {discoveryStatus && <Tag>{discoveryStatus}</Tag>}
            {sourceMode && <Tag color={sourceModeColor()}>{sourceMode}</Tag>}
            {sourceAssessment?.confidence && (
              <Tag color={confidenceColor()}>
                置信度 {sourceAssessment.confidence}
              </Tag>
            )}
          </Space>
        }
        description={
          <Space orientation="vertical" size={4}>
            <Paragraph style={{ marginBottom: 0 }}>
              {discoveryBlocked
                ? "本次自动发现没有可用的实时市场板块源，任务未生成候选板块，也没有写入新图谱。下方图谱列表来自已保存的 Neo4j 图谱，不是这次失败任务生成的数据。"
                : discovery?.error
                ? discovery.error
                : sourceAssessment?.explanation ||
                  discoveryResult?.message ||
                  "会扫描外部概念/行业板块，调用已配置的 LLM 生成产业链，并写入 Neo4j。"}
            </Paragraph>
            {discoveryBlocked && (
              <Text type="secondary">
                置信度结论：仅本次“自动发现任务”为 none；已保存图谱不受此次失败影响。
              </Text>
            )}
            {sourceAssessment?.recommended_usage && (
              <Text type={actionRequired ? "danger" : sourceAssessment.confidence === "low" ? "warning" : "secondary"}>
                {actionRequired ? "处理要求" : "使用边界"}：{sourceAssessment.recommended_usage}
              </Text>
            )}
            {sourceAssessment && (
              <Text type="secondary">
                数据性质：
                {sourceAssessment.is_simulated ? "模拟数据" : "非模拟数据"} ·
                {sourceAssessment.is_realtime_market ? "实时市场源" : "非实时市场源"} ·
                {sourceAssessment.is_market_hot ? "可代表热门板块" : "不可代表热门板块"}
              </Text>
            )}
            {discoveryResult?.source_summary && (
              <Text type="secondary">
                市场源成功 {discoveryResult.source_summary.market_sources_succeeded ?? 0} 个 ·
                {(discoveryResult.source_summary.cached_market_sources ?? 0) > 0
                  ? `短期缓存 ${discoveryResult.source_summary.cached_market_sources} 个 ·`
                  : ""}
                候选板块 {discoveryResult.source_summary.candidate_boards ?? 0} 个 ·
                {sourceMode === "local_fallback"
                  ? "本地行业分组不含实时涨幅"
                  : `最低涨幅 ${discoveryResult.source_summary.min_change_pct ?? 0}%`}
                {discoveryResult.source_summary.local_fallback_available != null
                  ? ` · 本地行业${discoveryResult.source_summary.local_fallback_available ? "可用" : "不可用"}`
                  : ""}
                {discoveryResult.source_summary.local_fallback_enabled
                  ? " · 已显式启用本地降级"
                  : discoveryResult.source_summary.local_fallback_available
                    ? " · 默认不启用本地降级"
                    : ""}
              </Text>
            )}
            {discovery?.latest?.created_at && (
              <Text type="secondary">
                最近执行 {discovery.latest.created_at}
                {discovery.latest.duration_ms != null ? ` · 用时 ${discovery.latest.duration_ms}ms` : ""}
              </Text>
            )}
            {hotBoardNames.length > 0 && (
              <Text type="secondary">
                候选板块: {hotBoardNames.slice(0, 8).join("、")}
                {hotBoardNames.length > 8 ? "..." : ""}
              </Text>
            )}
            {sourceEntries.length > 0 && (
              <Space wrap>
                {sourceEntries.map(([key, value]: [string, any]) => (
                  <Tag key={key} color={value?.success ? "green" : "red"}>
                    {sourceLabel(key)}{value?.success ? "可用" : "失败"}
                    {value?.cache_info?.used ? "（缓存）" : ""}
                  </Tag>
                ))}
              </Space>
            )}
            {diagnosticItems.length > 0 && (
              <Collapse
                size="small"
                items={diagnosticItems}
                style={{ maxWidth: "100%" }}
              />
            )}
          </Space>
        }
      />

      {chainList.length === 0 ? (
        <Empty description="暂无图谱数据 — 请先构建知识图谱" style={{ marginTop: 48 }} />
      ) : (
        <Row gutter={[16, 16]} style={{ marginTop: 24 }}>
          {chainList.map((c: any) => {
            const name = typeof c === "string" ? c : c.name ?? c.chain_name ?? c.chain_id;
            return (
              <Col xs={24} sm={12} lg={8} key={name}>
                <Card
                  hoverable
                  onClick={() => router.push(`/chain/${encodeURIComponent(name)}`)}
                  actions={[
                    <a key="detail" onClick={(e) => { e.stopPropagation(); router.push(`/chain/${encodeURIComponent(name)}`); }}>详情</a>,
                    <a key="signals" onClick={(e) => { e.stopPropagation(); router.push(`/signals?chain_id=${encodeURIComponent(name)}`); }}>信号</a>,
                    <a key="advisor" onClick={(e) => { e.stopPropagation(); router.push(`/advisor?chain=${encodeURIComponent(name)}`); }}>投研</a>,
                  ]}
                >
                  <Card.Meta
                    avatar={<ApartmentOutlined style={{ fontSize: 24, color: "#1677ff" }} />}
                    title={name}
                    description={
                      typeof c === "object"
                        ? `${c.description ?? ""} — ${c.segment_count ?? "?"} 个环节 · ${c.company_count ?? "?"} 家公司`
                        : "查看拓扑"
                    }
                  />
                </Card>
              </Col>
            );
          })}
        </Row>
      )}
    </div>
  );
}
