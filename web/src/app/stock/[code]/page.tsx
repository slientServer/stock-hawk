"use client";

import { useEffect, useState } from "react";
import {
  Alert,
  Breadcrumb,
  Card,
  Col,
  Descriptions,
  Empty,
  Row,
  Space,
  Spin,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";
import { ArrowDownOutlined, ArrowUpOutlined } from "@ant-design/icons";
import { useParams, useRouter } from "next/navigation";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getFinancials, getKline, getStock, getStockSnapshot } from "@/lib/api";
import { formatSignalType } from "@/lib/labels";

const { Title, Text } = Typography;

function formatPct(value?: number | null) {
  return value == null ? "-" : `${Number(value).toFixed(2)}%`;
}

function formatMoney(value?: number | null) {
  if (value == null) return "-";
  if (Math.abs(value) >= 100000000) return `${(value / 100000000).toFixed(2)}亿`;
  if (Math.abs(value) >= 10000) return `${(value / 10000).toFixed(2)}万`;
  return Number(value).toFixed(2);
}

function shortDate(value?: string | null) {
  return value ? value.slice(5, 10) : "-";
}

export default function StockDetailPage() {
  const params = useParams();
  const router = useRouter();
  const code = params.code as string;

  const [snapshot, setSnapshot] = useState<any>(null);
  const [stock, setStock] = useState<any>(null);
  const [kline, setKline] = useState<any[]>([]);
  const [financials, setFinancials] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      getStockSnapshot(code).catch(() => null),
      getStock(code).catch(() => null),
      getKline(code, 120).catch(() => []),
      getFinancials(code, 8).catch(() => []),
    ]).then(([snap, s, k, f]) => {
      setSnapshot(snap);
      setStock(snap?.stock ?? s);
      setKline(k);
      setFinancials(snap?.financial_history?.filter(Boolean) ?? f);
      setLoading(false);
    });
  }, [code]);

  if (loading) return <Spin size="large" style={{ display: "block", margin: "100px auto" }} />;
  if (!stock) return <Empty description={`未找到股票 ${code}`} />;

  const metrics = snapshot?.metrics ?? {};
  const latestFinancial = snapshot?.latest_financial ?? financials[0];
  const latestClose = metrics.latest_close ?? kline.at(-1)?.close;
  const return5d = metrics.return_5d;
  const exposure = snapshot?.chain_exposure ?? [];
  const signals = snapshot?.recent_signals ?? [];
  const dataQuality = snapshot?.data_quality ?? {};
  const dataGaps = snapshot?.data_gaps ?? [];
  const chartData = kline.map((item) => ({
    date: item.trade_date,
    label: shortDate(item.trade_date),
    close: Number(item.close ?? 0),
  }));

  const signalColumns = [
    {
      title: "类型",
      dataIndex: "signal_type",
      key: "signal_type",
      width: 120,
      render: (v: string) => <Tag color="blue">{formatSignalType(v)}</Tag>,
    },
    {
      title: "产业链",
      dataIndex: "chain_id",
      key: "chain_id",
      width: 150,
      render: (v: string) => v ? <a onClick={() => router.push(`/chain/${encodeURIComponent(v)}`)}>{v}</a> : "-",
    },
    {
      title: "描述",
      dataIndex: "detail",
      key: "detail",
      render: (v: string) => <span style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{v || "-"}</span>,
    },
    { title: "强度", dataIndex: "strength", key: "strength", width: 80, render: (v: number) => Number(v ?? 0).toFixed(2) },
    { title: "日期", dataIndex: "trigger_date", key: "trigger_date", width: 110, render: (v: string) => v?.slice(0, 10) || "-" },
  ];

  const finColumns = [
    { title: "报告期", dataIndex: "report_date", key: "report_date", width: 110, render: (v: string) => v?.slice(0, 10) || "-" },
    { title: "营收", dataIndex: "revenue", key: "revenue", width: 110, render: (v: number) => formatMoney(v) },
    { title: "营收同比", dataIndex: "revenue_yoy", key: "revenue_yoy", width: 100, render: (v: number) => formatPct(v) },
    { title: "净利润", dataIndex: "net_profit", key: "net_profit", width: 110, render: (v: number) => formatMoney(v) },
    { title: "净利同比", dataIndex: "net_profit_yoy", key: "net_profit_yoy", width: 100, render: (v: number) => formatPct(v) },
    { title: "毛利率", dataIndex: "gross_margin", key: "gross_margin", width: 90, render: (v: number) => formatPct(v) },
    { title: "ROE", dataIndex: "roe", key: "roe", width: 80, render: (v: number) => formatPct(v) },
    { title: "PE", dataIndex: "pe_ratio", key: "pe_ratio", width: 80, render: (v: number) => v != null ? Number(v).toFixed(1) : "-" },
  ];

  return (
    <div>
      <Breadcrumb
        items={[
          { title: <a onClick={() => router.push("/")}>总览</a> },
          { title: `${stock.name || ""} (${code})` },
        ]}
        style={{ marginBottom: 16 }}
      />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16 }}>
        <div>
          <Title level={3} style={{ marginBottom: 4 }}>{stock.name} <Text type="secondary">{code}</Text></Title>
          <Space wrap>
            {stock.industry && <Tag>{stock.industry}</Tag>}
            {stock.market && <Tag>{stock.market}</Tag>}
            {stock.is_st && <Tag color="error">ST</Tag>}
            <Tag color={snapshot?.confidence === "low" ? "orange" : "green"}>置信度 {snapshot?.confidence ?? "-"}</Tag>
          </Space>
        </div>
      </div>
      {dataGaps.length > 0 && (
        <Alert
          type="info"
          showIcon
          style={{ marginTop: 16 }}
          title="数据限制"
          description={dataGaps.join("；")}
        />
      )}

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={12} lg={6}>
          <Card><Statistic title="最新价" value={latestClose ?? "-"} precision={2} /></Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card>
            <Statistic
              title="近5日涨跌"
              value={return5d ?? "-"}
              precision={2}
              suffix={return5d == null ? "" : "%"}
              prefix={(return5d ?? 0) >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
              styles={{ content: { color: (return5d ?? 0) >= 0 ? "#cf1322" : "#3f8600" } }}
            />
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card><Statistic title="近20日涨跌" value={formatPct(metrics.return_20d)} /></Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card><Statistic title="60日回撤" value={formatPct(metrics.drawdown_60d)} /></Card>
        </Col>
      </Row>

      <Card title="图谱归属和数据覆盖" style={{ marginTop: 16 }}>
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Space wrap>
            {exposure.length === 0 ? (
              <Text type="secondary">暂无图谱归属</Text>
            ) : exposure.map((item: any) => (
              <Tag
                key={`${item.chain_name}-${item.segment_name}`}
                color="blue"
                style={{ cursor: "pointer" }}
                onClick={() => router.push(`/chain/${encodeURIComponent(item.chain_name)}`)}
              >
                {item.chain_name} · {item.position || "-"} · {item.segment_name || "-"}
              </Tag>
            ))}
          </Space>
          <Space wrap>
            <Tag color={dataQuality.has_graph ? "green" : "default"}>图谱</Tag>
            <Tag color={dataQuality.has_signal ? "green" : "default"}>信号</Tag>
            <Tag color={dataQuality.has_kline ? "green" : "default"}>K线</Tag>
            <Tag color={dataQuality.has_financial ? "green" : "default"}>财报</Tag>
            <Text type="secondary">市值 {formatMoney(stock.market_cap)} · 最新行情日 {metrics.latest_trade_date ?? "-"}</Text>
          </Space>
        </Space>
      </Card>

      {latestFinancial && (
        <Card title="最新财务" style={{ marginTop: 16 }}>
          <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 4 }}>
            <Descriptions.Item label="报告期">{latestFinancial.report_date ?? "-"}</Descriptions.Item>
            <Descriptions.Item label="营收">{formatMoney(latestFinancial.revenue)}</Descriptions.Item>
            <Descriptions.Item label="营收同比">{formatPct(latestFinancial.revenue_yoy)}</Descriptions.Item>
            <Descriptions.Item label="净利润">{formatMoney(latestFinancial.net_profit)}</Descriptions.Item>
            <Descriptions.Item label="净利同比">{formatPct(latestFinancial.net_profit_yoy)}</Descriptions.Item>
            <Descriptions.Item label="毛利率">{formatPct(latestFinancial.gross_margin)}</Descriptions.Item>
            <Descriptions.Item label="ROE">{formatPct(latestFinancial.roe)}</Descriptions.Item>
            <Descriptions.Item label="PE/PB">
              {latestFinancial.pe_ratio ?? "-"} / {latestFinancial.pb_ratio ?? "-"}
            </Descriptions.Item>
          </Descriptions>
        </Card>
      )}

      {chartData.length > 0 && (
        <Card title="近120日走势" style={{ marginTop: 16 }}>
          <div style={{ height: 260 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis
                  dataKey="label"
                  minTickGap={24}
                  tick={{ fontSize: 12 }}
                />
                <YAxis domain={["dataMin", "dataMax"]} tick={{ fontSize: 12 }} width={48} />
                <Tooltip labelFormatter={(_, items) => items?.[0]?.payload?.date ?? "-"} />
                <Line type="monotone" dataKey="close" name="收盘价" stroke="#1677ff" dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
      )}

      <Title level={4} style={{ marginTop: 24 }}>近期信号</Title>
      <Table
        dataSource={signals}
        columns={signalColumns}
        rowKey={(row: any, index) => `${row.id ?? row.signal_type}-${index}`}
        pagination={false}
        locale={{ emptyText: <Empty description="暂无近期信号" /> }}
        scroll={{ x: 760 }}
        size="small"
      />

      <Title level={4} style={{ marginTop: 24 }}>财务报告</Title>
      <Table
        dataSource={financials}
        columns={finColumns}
        rowKey={(row: any) => row.report_date}
        pagination={false}
        locale={{ emptyText: <Empty description="暂无财务数据" /> }}
        scroll={{ x: 780 }}
        size="small"
      />
    </div>
  );
}
