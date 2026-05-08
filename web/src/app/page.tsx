"use client";

import { useState, useEffect } from "react";
import { Alert, Row, Col, Card, Descriptions, Statistic, Tag, Spin, Empty, Typography, Space, Button } from "antd";
import {
  BarChartOutlined,
  DatabaseOutlined,
  FileSearchOutlined,
  LineChartOutlined,
  StockOutlined,
  ThunderboltOutlined,
  SwapOutlined,
} from "@ant-design/icons";
import { useRouter } from "next/navigation";
import { getAdvisorOverview, getChains, getSignals, getDataStats } from "@/lib/api";
import { formatSignalType } from "@/lib/labels";

const { Title, Text } = Typography;

function scoreColor(score: number) {
  if (score >= 80) return "#f5222d";
  if (score >= 60) return "#fa8c16";
  if (score >= 40) return "#faad14";
  return "#8c8c8c";
}

function scoreLevel(score: number) {
  if (score >= 80) return { text: "强烈关注", color: "red" as const };
  if (score >= 60) return { text: "持续跟踪", color: "orange" as const };
  if (score >= 40) return { text: "观察池", color: "gold" as const };
  return { text: "暂不关注", color: "default" as const };
}

function getScore(chain: any) {
  const latest = chain.latest_score;
  if (typeof latest === "object" && latest !== null) return Number(latest.score ?? chain.score ?? 0);
  return Number(latest ?? chain.score ?? 0);
}

const statusColor: Record<string, string> = {
  ready: "green",
  configured: "blue",
  not_configured: "default",
  blocked: "red",
};

function ResearchDataFoundation({ overview }: { overview: any }) {
  if (!overview) return null;
  return (
    <>
      {(overview?.blockers ?? []).length > 0 && (
        <Alert
          style={{ marginTop: 16 }}
          type="warning"
          showIcon
          title="投研能力缺口"
          description={(overview.blockers ?? []).join("；")}
        />
      )}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        {(overview?.capabilities ?? []).map((item: any) => (
          <Col xs={24} sm={12} lg={6} key={item.key}>
            <Card size="small">
              <Space orientation="vertical" size={6}>
                <Space>
                  {item.key === "data" && <DatabaseOutlined />}
                  {item.key === "graph" && <BarChartOutlined />}
                  {item.key === "selection" && <StockOutlined />}
                  {item.key === "llm" && <FileSearchOutlined />}
                  <Text strong>{item.name}</Text>
                </Space>
                <Tag color={statusColor[item.status] ?? "default"}>{item.status}</Tag>
                <Text type="secondary">{item.detail}</Text>
              </Space>
            </Card>
          </Col>
        ))}
      </Row>
      <Card title="数据覆盖" style={{ marginTop: 16 }}>
        <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 4 }}>
          <Descriptions.Item label="股票">{overview?.counts?.stock_count ?? 0}</Descriptions.Item>
          <Descriptions.Item label="候选池">{overview?.counts?.candidate_count ?? 0}</Descriptions.Item>
          <Descriptions.Item label="候选K线">
            {overview?.counts?.candidate_kline_coverage ?? 0}/{overview?.counts?.candidate_count ?? 0}
          </Descriptions.Item>
          <Descriptions.Item label="候选财报">
            {overview?.counts?.candidate_financial_coverage ?? 0}/{overview?.counts?.candidate_count ?? 0}
          </Descriptions.Item>
          <Descriptions.Item label="全市场K线">{overview?.counts?.kline_stock_coverage ?? 0}</Descriptions.Item>
          <Descriptions.Item label="全市场财报">{overview?.counts?.financial_stock_coverage ?? 0}</Descriptions.Item>
          <Descriptions.Item label="产业链">{overview?.counts?.chain_count ?? 0}</Descriptions.Item>
          <Descriptions.Item label="信号">{overview?.counts?.signal_count ?? 0}</Descriptions.Item>
          <Descriptions.Item label="最新行情日">{overview?.counts?.latest_kline_date ?? "-"}</Descriptions.Item>
          <Descriptions.Item label="发现任务">{overview?.latest_discovery?.output?.status ?? "-"}</Descriptions.Item>
        </Descriptions>
      </Card>
    </>
  );
}

export default function HomePage() {
  const [chains, setChains] = useState<any[]>([]);
  const [signals, setSignals] = useState<any[]>([]);
  const [stats, setStats] = useState<any>(null);
  const [advisorOverview, setAdvisorOverview] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    Promise.all([
      getChains(20).catch(() => []),
      getSignals({ limit: 10 }).then((r) => r.items ?? []).catch(() => []),
      getDataStats().catch(() => null),
      getAdvisorOverview().catch(() => null),
    ]).then(([c, s, st, advisor]) => {
      setChains(c);
      setSignals(s);
      setStats(st);
      setAdvisorOverview(advisor);
      setLoading(false);
    });
  }, []);

  if (loading) return <Spin size="large" style={{ display: "block", margin: "100px auto" }} />;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16 }}>
        <div>
          <Title level={3} style={{ marginBottom: 4 }}>产业链总览</Title>
          <Text type="secondary">跟踪 {chains.length} 条产业链信号评分</Text>
        </div>
        <Space wrap>
          <Button onClick={() => router.push("/graph")}>图谱</Button>
          <Button onClick={() => router.push("/signals")}>信号中心</Button>
          <Button type="primary" onClick={() => router.push("/advisor")}>投研</Button>
        </Space>
      </div>

      <ResearchDataFoundation overview={advisorOverview} />

      {/* 数据概览 */}
      {stats && (
        <Row gutter={16} style={{ marginTop: 16 }}>
          <Col xs={12} sm={6}>
            <Card size="small">
              <Statistic title="股票总数" value={stats.stock_count} prefix={<DatabaseOutlined />} />
            </Card>
          </Col>
          <Col xs={12} sm={6}>
            <Card size="small">
              <Statistic title="K线记录" value={stats.kline_count} prefix={<LineChartOutlined />} />
            </Card>
          </Col>
          <Col xs={12} sm={6}>
            <Card size="small">
              <Statistic title="活跃信号" value={stats.signal_count} prefix={<ThunderboltOutlined />} />
            </Card>
          </Col>
          <Col xs={12} sm={6}>
            <Card size="small">
              <Statistic title="北向资金" value={stats.fund_flow_count} suffix="条" prefix={<SwapOutlined />} />
            </Card>
          </Col>
        </Row>
      )}

      {/* 产业链评分卡片 */}
      {chains.length === 0 ? (
        <Empty description="暂无产业链数据 — 请先运行数据采集" style={{ marginTop: 48 }} />
      ) : (
        <Row gutter={[16, 16]} style={{ marginTop: 24 }}>
          {chains.map((c: any) => {
            const score = getScore(c);
            const level = scoreLevel(score);
            const delta = c.score_delta == null ? null : Number(c.score_delta);
            return (
              <Col xs={24} sm={12} lg={8} key={c.chain_id ?? c.id ?? c.name}>
                <Card
                  hoverable
                  onClick={() => router.push(`/chain/${encodeURIComponent(c.chain_id ?? c.id ?? c.name)}`)}
                >
                  <Statistic
                    title={c.chain_name ?? c.name ?? c.chain_id}
                    value={score.toFixed(0)}
                    styles={{ content: { color: scoreColor(score), fontSize: 32 } }}
                    suffix={<Tag color={level.color}>{level.text}</Tag>}
                  />
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    活跃信号: {c.signal_count ?? 0}
                    {delta != null && <> · 变化: {delta > 0 ? "+" : ""}{delta.toFixed(0)}</>}
                    {" · "}评分日期: {c.score_date || "-"}
                  </Text>
                </Card>
              </Col>
            );
          })}
        </Row>
      )}

      {/* 最新信号 */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 32 }}>
        <Title level={4} style={{ margin: 0 }}>最新信号</Title>
        <Button size="small" onClick={() => router.push("/signals")}>全部信号</Button>
      </div>
      {signals.length === 0 ? (
        <Card style={{ marginTop: 12 }}>
          <Empty description="暂无信号 — 信号将在检测器发现产业链异动时自动生成" />
        </Card>
      ) : (
        <Space orientation="vertical" size={8} style={{ width: "100%", marginTop: 12 }}>
          {signals.map((s: any, index: number) => (
            <Card size="small" key={`${s.signal_type}-${s.chain_id}-${s.trigger_date}-${index}`}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 16 }}>
                <div>
                  <div style={{ marginBottom: 4 }}>
                    <Tag>{formatSignalType(s.signal_type)}</Tag>
                    {s.chain_id ? (
                      <a onClick={() => router.push(`/chain/${encodeURIComponent(s.chain_id)}`)}>{s.chain_id}</a>
                    ) : (
                      <Text strong>-</Text>
                    )}
                  </div>
                  <Text type="secondary">{s.detail || "-"}</Text>
                </div>
                <div style={{ whiteSpace: "nowrap" }}>
                  <Text style={{ marginRight: 16 }}>强度 {Number(s.strength ?? 0).toFixed(2)}</Text>
                  <Text type="secondary">{s.trigger_date?.slice(0, 10)}</Text>
                </div>
              </div>
            </Card>
          ))}
        </Space>
      )}
    </div>
  );
}
