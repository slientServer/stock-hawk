"use client";

import { useState, useEffect } from "react";
import {
  Row,
  Col,
  Card,
  Tag,
  Typography,
  Spin,
  Empty,
  Breadcrumb,
  Descriptions,
  Table,
  Timeline,
  Statistic,
} from "antd";
import { useParams, useRouter } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getReportDetail } from "@/lib/api";
import { formatSignalType, formatTrendType, formatStage, formatConfidence } from "@/lib/labels";
import AddHoldingButton from "@/components/AddHoldingButton";

const { Title, Text } = Typography;

const STAGE_COLORS: Record<string, string> = {
  seed: "default",
  verification: "processing",
  consensus: "warning",
  overheated: "error",
  watching: "default",
};

const MATURITY_COLORS: Record<string, string> = {
  emerging: "cyan",
  growth: "blue",
  mature: "green",
  declining: "orange",
};

const TREND_COLORS: Record<string, string> = {
  rising: "red",
  stable: "default",
  falling: "green",
};

export default function ReportDetailPage() {
  const params = useParams();
  const router = useRouter();
  const reportId = params.id as string;

  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getReportDetail(reportId)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [reportId]);

  if (loading) return <Spin size="large" style={{ display: "block", margin: "100px auto" }} />;
  if (!data) return <Empty description="研报不存在" style={{ marginTop: 100 }} />;

  const { background, structured } = data;

  return (
    <div>
      <Breadcrumb
        style={{ marginBottom: 16 }}
        items={[
          { title: <a onClick={() => router.push("/reports")}>研报库</a> },
          { title: data.agent_id || "报告详情" },
        ]}
      />

      <div style={{ marginBottom: 16 }}>
        <Title level={4} style={{ marginBottom: 8 }}>
          {_reportTitle(data)}
        </Title>
        <span>
          <Tag color="blue">{data.workflow_type}</Tag>
          {data.agent_id && <Tag>{data.agent_id}</Tag>}
          {data.status && (
            <Tag color={data.status === "completed" ? "green" : data.status === "failed" ? "red" : "orange"}>
              {data.status}
            </Tag>
          )}
        </span>
        <Text type="secondary" style={{ marginLeft: 12, fontSize: 12 }}>
          {data.created_at?.slice(0, 19)} {data.duration_ms ? `· ${data.duration_ms}ms` : ""}
        </Text>
      </div>

      <Row gutter={24}>
        {/* 左侧：报告正文 */}
        <Col xs={24} lg={background ? 16 : 24}>
          <Card title="报告正文" style={{ marginBottom: 24 }}>
            <div className="markdown-body">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{data.output_text || "暂无内容"}</ReactMarkdown>
            </div>
          </Card>
        </Col>

        {/* 右侧：背景信息面板 */}
        {background && (
          <Col xs={24} lg={8}>
            <BackgroundPanel background={background} structured={structured} />
          </Col>
        )}
      </Row>

      {/* 下方：结构化数据展示 */}
      {structured && structured.type !== "unknown" && (
        <StructuredDataSection structured={structured} />
      )}
    </div>
  );
}

function _reportTitle(data: any): string {
  const output = data.output_text || "";
  const firstLine = output.split("\n").find((l: string) => l.trim());
  if (firstLine && firstLine.startsWith("#")) {
    return firstLine.replace(/^#+\s*/, "");
  }
  const chainId = data.structured?.type === "chain_analysis" ? (data.background?.chain?.name || "") : "";
  if (chainId) return `${chainId} - 分析报告`;
  return `${data.workflow_type || "研报"} 报告`;
}

/* ==================== 背景面板 ==================== */

function BackgroundPanel({ background, structured }: { background: any; structured: any }) {
  const chain = background.chain || {};
  const segments = background.segments || [];
  const technologies = background.technologies || [];
  const products = background.products || [];

  return (
    <div>
      {/* 产业链概况 */}
      <Card title="产业链背景" size="small" style={{ marginBottom: 16 }}>
        <Descriptions column={1} size="small">
          <Descriptions.Item label="名称">{chain.name || "-"}</Descriptions.Item>
          <Descriptions.Item label="描述">
            <Text style={{ fontSize: 12 }}>{chain.description || "暂无描述"}</Text>
          </Descriptions.Item>
          {structured?.current_stage && (
            <Descriptions.Item label="当前阶段">
              <Tag color={STAGE_COLORS[structured.current_stage] || "default"}>
                {formatStage(structured.current_stage)}
              </Tag>
            </Descriptions.Item>
          )}
          {structured?.trend_type && (
            <Descriptions.Item label="趋势类型">{formatTrendType(structured.trend_type)}</Descriptions.Item>
          )}
          {structured?.score != null && (
            <Descriptions.Item label="评分">
              <Text strong>{structured.score}</Text>
            </Descriptions.Item>
          )}
          {structured?.confidence && (
            <Descriptions.Item label="置信度">{formatConfidence(structured.confidence)}</Descriptions.Item>
          )}
        </Descriptions>
      </Card>

      {/* 关键技术 */}
      {technologies.length > 0 && (
        <Card title="关键技术" size="small" style={{ marginBottom: 16 }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {technologies.map((t: any, i: number) => (
              <Tag key={i} color={MATURITY_COLORS[t.maturity_stage] || "default"}>
                {t.name} {t.maturity_stage ? `(${t.maturity_stage})` : ""}
              </Tag>
            ))}
          </div>
        </Card>
      )}

      {/* 关键产品 */}
      {products.length > 0 && (
        <Card title="关键产品" size="small" style={{ marginBottom: 16 }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {products.map((p: any, i: number) => (
              <Tag key={i} color={TREND_COLORS[p.price_trend] || "default"}>
                {p.name} {p.price_trend === "rising" ? "↑" : p.price_trend === "falling" ? "↓" : ""}
              </Tag>
            ))}
          </div>
        </Card>
      )}

      {/* 上中下游结构 */}
      {segments.length > 0 && (
        <Card title="产业链结构" size="small">
          {["上游", "中游", "下游"].map((pos) => {
            const segs = segments.filter((s: any) => s.position === pos);
            if (segs.length === 0) return null;
            return (
              <div key={pos} style={{ marginBottom: 8 }}>
                <Text strong style={{ fontSize: 12 }}>{pos}</Text>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 4 }}>
                  {segs.map((s: any, i: number) => (
                    <Tag key={i} style={{ fontSize: 11 }}>
                      {s.segment_name || s.name}
                      {s.company_count ? ` (${s.company_count}家)` : ""}
                    </Tag>
                  ))}
                </div>
              </div>
            );
          })}
          {background.company_count > 0 && (
            <Text type="secondary" style={{ fontSize: 11, display: "block", marginTop: 8 }}>
              共覆盖 {background.company_count} 家公司
            </Text>
          )}
        </Card>
      )}
    </div>
  );
}

/* ==================== 结构化数据区 ==================== */

function StructuredDataSection({ structured }: { structured: any }) {
  if (structured.type === "chain_analysis") {
    return <ChainAnalysisSection data={structured} />;
  }
  if (structured.type === "stock_screening") {
    return <StockScreeningSection data={structured} />;
  }
  return null;
}

function ChainAnalysisSection({ data }: { data: any }) {
  const path = data.transmission_path || [];
  const signals = data.signal_summary?.latest || [];
  const financial = data.financial_summary;
  const dataGaps = data.data_gaps || [];

  return (
    <>
      {/* 传导路径 */}
      {path.length > 0 && (
        <Card title="传导路径" style={{ marginBottom: 24 }}>
          <Timeline
            items={path.map((item: any) => ({
              color: item.status === "confirmed" ? "green" : item.status === "transmitting" ? "blue" : "gray",
              children: (
                <span>
                  <Tag>{item.position}</Tag>
                  <Text strong>{item.segment}</Text>
                  <Text type="secondary" style={{ marginLeft: 8 }}>
                    {item.signal_count || 0} 个信号, {item.company_count || 0} 家公司
                  </Text>
                  <Tag
                    color={item.status === "confirmed" ? "green" : item.status === "transmitting" ? "blue" : "default"}
                    style={{ marginLeft: 8 }}
                  >
                    {item.status === "confirmed" ? "已确认" : item.status === "transmitting" ? "传导中" : "未传导"}
                  </Tag>
                </span>
              ),
            }))}
          />
        </Card>
      )}

      {/* 近期信号 */}
      {signals.length > 0 && (
        <Card title="触发信号" style={{ marginBottom: 24 }}>
          <Table
            dataSource={signals}
            rowKey={(_, i) => String(i)}
            pagination={false}
            size="small"
            columns={[
              {
                title: "类型",
                dataIndex: "signal_type",
                width: 100,
                render: (v: string) => <Tag color="blue">{formatSignalType(v)}</Tag>,
              },
              { title: "详情", dataIndex: "detail", ellipsis: true },
              {
                title: "强度",
                dataIndex: "strength",
                width: 70,
                render: (v: number) => (v != null ? v.toFixed(1) : "-"),
              },
              {
                title: "置信度",
                dataIndex: "confidence",
                width: 70,
                render: (v: number) => (v != null ? v.toFixed(1) : "-"),
              },
              { title: "来源", dataIndex: "source", width: 100 },
              {
                title: "触发时间",
                dataIndex: "trigger_date",
                width: 120,
                render: (v: string) => v?.slice(0, 10) || "-",
              },
            ]}
          />
        </Card>
      )}

      <Row gutter={24}>
        {/* 财务摘要 */}
        {financial && (
          <Col xs={24} md={12}>
            <Card title="财务摘要" size="small" style={{ marginBottom: 24 }}>
              <Row gutter={16}>
                <Col span={12}>
                  <Statistic title="覆盖公司数" value={financial.covered_companies || 0} />
                </Col>
                <Col span={12}>
                  <Statistic
                    title="平均营收增速"
                    value={financial.avg_revenue_yoy || 0}
                    suffix="%"
                    precision={1}
                  />
                </Col>
                <Col span={12} style={{ marginTop: 16 }}>
                  <Statistic
                    title="平均利润增速"
                    value={financial.avg_net_profit_yoy || 0}
                    suffix="%"
                    precision={1}
                  />
                </Col>
                <Col span={12} style={{ marginTop: 16 }}>
                  <Statistic title="最新报告期" value={financial.latest_report_date || "-"} />
                </Col>
              </Row>
            </Card>
          </Col>
        )}

        {/* 数据缺口 */}
        {dataGaps.length > 0 && (
          <Col xs={24} md={12}>
            <Card title="数据缺口" size="small" style={{ marginBottom: 24 }}>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {dataGaps.map((gap: string, i: number) => (
                  <Tag key={i} color="orange">{gap}</Tag>
                ))}
              </div>
            </Card>
          </Col>
        )}
      </Row>
    </>
  );
}

function StockScreeningSection({ data }: { data: any }) {
  const recs = data.recommendations || {};
  const dataGaps = data.data_gaps || [];

  const columns = [
    { title: "代码", dataIndex: "code", width: 80 },
    { title: "名称", dataIndex: "name", width: 100 },
    {
      title: "持仓",
      key: "portfolio",
      width: 90,
      render: (_: any, row: any) => (
        <AddHoldingButton code={row.code} name={row.name} source="report_screening" compact />
      ),
    },
    {
      title: "评分",
      dataIndex: "score",
      width: 70,
      render: (v: number) => <Text strong>{v?.toFixed(1)}</Text>,
    },
    {
      title: "所属环节",
      dataIndex: "segments",
      width: 120,
      render: (v: string[]) => v?.join("、") || "-",
    },
    { title: "推荐逻辑", dataIndex: "logic", ellipsis: true },
    {
      title: "风险",
      dataIndex: "risk_flags",
      width: 100,
      render: (v: string[]) =>
        v?.length ? v.map((f, i) => <Tag key={i} color="red">{f}</Tag>) : <Tag color="green">无</Tag>,
    },
  ];

  return (
    <>
      {["core", "satellite", "watchlist"].map((tier) => {
        const items = recs[tier];
        if (!items || items.length === 0) return null;
        const label = tier === "core" ? "核心推荐" : tier === "satellite" ? "卫星标的" : "观察列表";
        const color = tier === "core" ? "red" : tier === "satellite" ? "orange" : "default";
        return (
          <Card
            key={tier}
            title={<span><Tag color={color}>{label}</Tag> ({items.length})</span>}
            style={{ marginBottom: 24 }}
          >
            <Table
              dataSource={items}
              rowKey="code"
              pagination={false}
              size="small"
              columns={columns}
            />
          </Card>
        );
      })}

      {dataGaps.length > 0 && (
        <Card title="数据缺口" size="small" style={{ marginBottom: 24 }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {dataGaps.map((gap: string, i: number) => (
              <Tag key={i} color="orange">{gap}</Tag>
            ))}
          </div>
        </Card>
      )}
    </>
  );
}
