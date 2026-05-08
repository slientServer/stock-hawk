"use client";

import { useState, useEffect } from "react";
import {
  Alert, App, Button, Card, Row, Col, Statistic, Table, Tag, Typography, Spin, Input, Descriptions, Empty, Space, Progress, List,
} from "antd";
import {
  DatabaseOutlined, LineChartOutlined, FundOutlined,
  FileTextOutlined, SearchOutlined, PlayCircleOutlined, ReloadOutlined,
  CheckCircleOutlined, CloseCircleOutlined, ThunderboltOutlined,
} from "@ant-design/icons";
import { useRouter } from "next/navigation";
import { getDataCollectStatus, getDataCompleteness, getDataPreview, getDataStatsDetail, getStocks, triggerDataCollect } from "@/lib/api";

const { Title, Text } = Typography;
const { Search } = Input;

const collectTasks = [
  { key: "collect_all", label: "⚡ 一键采集全部", danger: true },
  { key: "schema", label: "初始化表结构", danger: false },
  { key: "seed_stocks", label: "写入种子股票", danger: false },
  { key: "seed_graph", label: "灌入知识图谱", danger: false },
  { key: "focus_all", label: "重点股票补采", danger: false },
  { key: "seed_klines", label: "采集种子K线", danger: false },
  { key: "fund_flow", label: "采集北向资金", danger: false },
  { key: "seed_shareholders", label: "采集股东户数", danger: false },
  { key: "seed_financials", label: "采集财报", danger: false },
  { key: "news_events", label: "采集新闻事件", danger: false },
  { key: "commodity_prices", label: "采集商品价格", danger: false },
  { key: "overseas_stocks", label: "采集海外行情", danger: false },
  { key: "institutional_holdings", label: "采集机构持仓", danger: false },
  { key: "stock_detail", label: "采集市值/上市日期", danger: false },
  { key: "seed_all", label: "一键种子初始化", danger: true },
];

export default function DataPage() {
  const { message } = App.useApp();
  const router = useRouter();
  const [stats, setStats] = useState<any>(null);
  const [stocks, setStocks] = useState<any[]>([]);
  const [collectStatus, setCollectStatus] = useState<any>({});
  const [completeness, setCompleteness] = useState<any>(null);
  const [preview, setPreview] = useState<any>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewSource, setPreviewSource] = useState<string | null>(null);
  const [stockLoading, setStockLoading] = useState(false);
  const [loading, setLoading] = useState(true);

  const loadData = () => {
    setLoading(true);
    Promise.all([
      getDataStatsDetail().catch(() => null),
      getStocks({ limit: 50 }).catch(() => []),
      getDataCollectStatus().catch(() => ({})),
      getDataCompleteness().catch(() => null),
    ]).then(([s, st, cs, comp]) => {
      setStats(s);
      setStocks(st);
      setCollectStatus(cs);
      setCompleteness(comp);
      setLoading(false);
    });
  };

  useEffect(() => { loadData(); }, []);

  useEffect(() => {
    if (!collectStatus?.running) return;
    const timer = setInterval(() => {
      getDataCollectStatus()
        .then((status) => {
          setCollectStatus(status);
          if (!status.running) loadData();
        })
        .catch(() => {});
    }, 2000);
    return () => clearInterval(timer);
  }, [collectStatus?.running]);

  const handleSearch = async (keyword: string) => {
    setStockLoading(true);
    try {
      const res = await getStocks({ keyword, limit: 100 });
      setStocks(res);
    } catch {
      setStocks([]);
    } finally {
      setStockLoading(false);
    }
  };

  const handleCollect = async (task: string) => {
    try {
      const res = await triggerDataCollect({ task, days: 365, years: 3 });
      if (res.status === "already_running") {
        message.warning(res.message);
      } else {
        message.success("采集任务已启动");
        setCollectStatus({ running: true, task, status: "running", progress: "starting" });
      }
    } catch (e: any) {
      message.error(`启动失败: ${e.message}`);
    }
  };

  const handlePreview = async (source: string) => {
    if (previewSource === source) {
      setPreviewSource(null);
      setPreview(null);
      return;
    }
    setPreviewLoading(true);
    setPreviewSource(source);
    try {
      const res = await getDataPreview(source, 20);
      setPreview(res);
    } catch {
      setPreview(null);
      message.error("预览加载失败");
    } finally {
      setPreviewLoading(false);
    }
  };

  if (loading) return <Spin size="large" style={{ display: "block", margin: "100px auto" }} />;

  const stockColumns = [
    {
      title: "代码",
      dataIndex: "code",
      key: "code",
      width: 100,
      render: (v: string) => (
        <a onClick={() => router.push(`/stock/${v}`)}>{v}</a>
      ),
    },
    { title: "名称", dataIndex: "name", key: "name", width: 120 },
    {
      title: "行业",
      dataIndex: "industry",
      key: "industry",
      width: 120,
      render: (v: string) => v ? <Tag>{v}</Tag> : "-",
    },
    {
      title: "市场",
      dataIndex: "market",
      key: "market",
      width: 80,
      render: (v: string) => v ? <Tag color={v === "沪" ? "red" : "blue"}>{v}</Tag> : "-",
    },
    {
      title: "市值(亿)",
      dataIndex: "market_cap",
      key: "market_cap",
      width: 100,
      render: (v: number) => v ? (v / 1e8).toFixed(1) : "-",
      sorter: (a: any, b: any) => (a.market_cap || 0) - (b.market_cap || 0),
    },
    {
      title: "ST",
      dataIndex: "is_st",
      key: "is_st",
      width: 60,
      render: (v: boolean) => v ? <Tag color="red">ST</Tag> : null,
    },
  ];

  const recentKlineColumns = [
    { title: "日期", dataIndex: "date", key: "date", width: 120 },
    {
      title: "记录数",
      dataIndex: "count",
      key: "count",
      width: 100,
      render: (v: number) => <Text strong>{v.toLocaleString()}</Text>,
    },
  ];

  return (
    <div>
      <Title level={3}>数据管理</Title>
      <Text type="secondary">查看系统各维度数据详细情况</Text>

      <Card title="数据采集" style={{ marginTop: 16 }}>
        {stats?.status === "degraded" && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 12 }}
            title="数据库表可能尚未初始化"
          />
        )}
        {collectStatus?.running && (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            title={`正在执行: ${collectStatus.task || "-"}`}
            description={`当前步骤: ${collectStatus.progress || "-"} · 开始时间: ${collectStatus.started_at || "-"}`}
          />
        )}
        {!collectStatus?.running && collectStatus?.status === "completed" && (
          <Alert
            type="success"
            showIcon
            closable
            style={{ marginBottom: 12 }}
            title={`上次任务完成: ${collectStatus.task || "-"}`}
            description={collectStatus.finished_at || ""}
          />
        )}
        {!collectStatus?.running && collectStatus?.status === "failed" && (
          <Alert
            type="error"
            showIcon
            style={{ marginBottom: 12 }}
            title={`上次任务失败: ${collectStatus.task || "-"}`}
            description={collectStatus.error || ""}
          />
        )}
        <Space wrap>
          {collectTasks.map((task) => (
            <Button
              key={task.key}
              type={task.danger ? "primary" : "default"}
              danger={task.danger}
              icon={<PlayCircleOutlined />}
              loading={collectStatus?.running && collectStatus?.task === task.key}
              disabled={collectStatus?.running}
              onClick={() => handleCollect(task.key)}
            >
              {task.label}
            </Button>
          ))}
          <Button icon={<ReloadOutlined />} onClick={loadData} disabled={loading || collectStatus?.running}>
            刷新状态
          </Button>
        </Space>
        {collectStatus?.result && (
          <pre
            style={{
              marginTop: 12,
              padding: 12,
              background: "#f5f5f5",
              borderRadius: 6,
              whiteSpace: "pre-wrap",
              maxHeight: 240,
              overflow: "auto",
            }}
          >
            {JSON.stringify(collectStatus.result, null, 2)}
          </pre>
        )}
      </Card>

      {/* 数据完备性分析 */}
      {completeness && (
        <Card title={<Space><ThunderboltOutlined />数据完备性分析</Space>} style={{ marginTop: 16 }}>
          <Row gutter={16} align="middle">
            <Col span={4}>
              <Progress type="circle" percent={completeness.overall_score} size={80} />
              <div style={{ textAlign: "center", marginTop: 4 }}>
                <Text type="secondary" style={{ fontSize: 12 }}>综合评分</Text>
              </div>
            </Col>
            <Col span={20}>
              <div style={{ marginBottom: 12 }}>
                <Text strong>信号就绪状态</Text>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 8 }}>
                  {(completeness.signals || []).map((s: any) => (
                    <Tag
                      key={s.signal_type}
                      icon={s.ready ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
                      color={s.ready ? "success" : "error"}
                    >
                      {s.name}({s.weight})
                    </Tag>
                  ))}
                </div>
              </div>
              {completeness.recommendations?.length > 0 && (
                <div>
                  <Text strong>修复建议</Text>
                  <List
                    size="small"
                    style={{ marginTop: 4 }}
                    dataSource={completeness.recommendations}
                    renderItem={(item: any) => (
                      <List.Item
                        actions={[
                          <Button
                            key="fix"
                            size="small"
                            type="link"
                            disabled={collectStatus?.running}
                            onClick={() => handleCollect(item.task)}
                          >
                            一键修复
                          </Button>,
                        ]}
                      >
                        <List.Item.Meta
                          title={<><Tag color={item.priority === "P0" ? "red" : "orange"}>{item.priority}</Tag>{item.action}</>}
                          description={item.impact}
                        />
                      </List.Item>
                    )}
                  />
                </div>
              )}
            </Col>
          </Row>
          {/* 新数据维度覆盖 - 点击可预览 */}
          <Row gutter={12} style={{ marginTop: 16 }}>
            <Col span={6}>
              <Card size="small" hoverable onClick={() => handlePreview("commodity_prices")} style={{ cursor: "pointer", borderColor: previewSource === "commodity_prices" ? "#1677ff" : undefined }}>
                <Statistic title="商品价格" value={completeness.data_sources?.commodity_prices?.records || 0} suffix={`/ ${completeness.data_sources?.commodity_prices?.products || 0}品种`} styles={{ content: { fontSize: 16 } }} />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small" hoverable onClick={() => handlePreview("news_events")} style={{ cursor: "pointer", borderColor: previewSource === "news_events" ? "#1677ff" : undefined }}>
                <Statistic title="新闻事件" value={completeness.data_sources?.news_events?.records || 0} suffix={`今日${completeness.data_sources?.news_events?.today_count || 0}`} styles={{ content: { fontSize: 16 } }} />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small" hoverable onClick={() => handlePreview("overseas_stocks")} style={{ cursor: "pointer", borderColor: previewSource === "overseas_stocks" ? "#1677ff" : undefined }}>
                <Statistic title="海外行情" value={completeness.data_sources?.overseas_stocks?.records || 0} suffix={`/ ${completeness.data_sources?.overseas_stocks?.symbols || 0}标的`} styles={{ content: { fontSize: 16 } }} />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small" hoverable onClick={() => handlePreview("institutional_holdings")} style={{ cursor: "pointer", borderColor: previewSource === "institutional_holdings" ? "#1677ff" : undefined }}>
                <Statistic title="机构持仓" value={completeness.data_sources?.institutional_holdings?.records || 0} suffix={`覆盖${completeness.data_sources?.institutional_holdings?.stock_coverage || 0}只`} styles={{ content: { fontSize: 16 } }} />
              </Card>
            </Col>
          </Row>
          {/* 数据预览 */}
          {previewSource && (
            <div style={{ marginTop: 12 }}>
              {previewLoading ? (
                <Spin style={{ display: "block", margin: "20px auto" }} />
              ) : preview?.items?.length > 0 ? (
                <Table
                  dataSource={preview.items}
                  columns={Object.keys(preview.items[0]).map((key) => ({
                    title: key,
                    dataIndex: key,
                    key,
                    ellipsis: true,
                    render: (v: any) => v == null ? "-" : typeof v === "object" ? JSON.stringify(v) : String(v),
                  }))}
                  rowKey={(_, i) => String(i)}
                  size="small"
                  pagination={false}
                  scroll={{ x: "max-content" }}
                  style={{ fontSize: 12 }}
                />
              ) : (
                <Empty description="暂无数据，请先执行采集" />
              )}
            </div>
          )}
        </Card>
      )}

      {/* 总量概览 */}
      <Row gutter={16} style={{ marginTop: 24 }}>
        <Col xs={12} sm={6}>
          <Card>
            <Statistic
              title="股票总数"
              value={stats?.stocks?.total || 0}
              prefix={<DatabaseOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card>
            <Statistic
              title="K线记录"
              value={stats?.klines?.total || 0}
              prefix={<LineChartOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card>
            <Statistic
              title="资金流水"
              value={stats?.fund_flow?.total || 0}
              prefix={<FundOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card>
            <Statistic
              title="财报数据"
              value={stats?.financials?.total || 0}
              prefix={<FileTextOutlined />}
            />
          </Card>
        </Col>
      </Row>

      {/* K线数据详情 */}
      <Card title="K线数据" style={{ marginTop: 16 }}>
        <Descriptions column={3} size="small" bordered>
          <Descriptions.Item label="覆盖股票数">
            {stats?.klines?.stock_coverage?.toLocaleString() || 0} 只
          </Descriptions.Item>
          <Descriptions.Item label="起始日期">
            {stats?.klines?.date_from || "-"}
          </Descriptions.Item>
          <Descriptions.Item label="截止日期">
            {stats?.klines?.date_to || "-"}
          </Descriptions.Item>
        </Descriptions>

        {stats?.klines?.recent_daily?.length > 0 && (
          <div style={{ marginTop: 16 }}>
            <Text strong>最近采集记录（按交易日）</Text>
            <Table
              dataSource={stats.klines.recent_daily}
              columns={recentKlineColumns}
              rowKey="date"
              size="small"
              pagination={false}
              style={{ marginTop: 8 }}
            />
          </div>
        )}
      </Card>

      {/* 资金流数据 */}
      <Card title="资金流数据" style={{ marginTop: 16 }}>
        <Descriptions column={3} size="small" bordered>
          <Descriptions.Item label="总记录数">
            {stats?.fund_flow?.total?.toLocaleString() || 0}
          </Descriptions.Item>
          <Descriptions.Item label="起始日期">
            {stats?.fund_flow?.date_from || "-"}
          </Descriptions.Item>
          <Descriptions.Item label="截止日期">
            {stats?.fund_flow?.date_to || "-"}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {/* 财报数据 */}
      <Card title="财报数据" style={{ marginTop: 16 }}>
        <Descriptions column={3} size="small" bordered>
          <Descriptions.Item label="总记录数">
            {stats?.financials?.total?.toLocaleString() || 0}
          </Descriptions.Item>
          <Descriptions.Item label="覆盖股票数">
            {stats?.financials?.stock_coverage?.toLocaleString() || 0} 只
          </Descriptions.Item>
          <Descriptions.Item label="缺披露日">
            {stats?.financials?.missing_publish_date?.toLocaleString() || 0}
          </Descriptions.Item>
          <Descriptions.Item label="起始报告期">
            {stats?.financials?.date_from || "-"}
          </Descriptions.Item>
          <Descriptions.Item label="最新报告期">
            {stats?.financials?.date_to || "-"}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {/* 行业分布 */}
      {stats?.stocks?.industries?.length > 0 && (
        <Card title="行业分布（Top 20）" style={{ marginTop: 16 }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {stats.stocks.industries.map((item: any) => (
              <Tag key={item.industry} color="blue" style={{ padding: "4px 12px", fontSize: 13 }}>
                {item.industry}: {item.count}
              </Tag>
            ))}
          </div>
        </Card>
      )}

      {/* 股票列表 */}
      <Card title="股票列表" style={{ marginTop: 16 }}>
        <Search
          placeholder="搜索股票代码或名称"
          allowClear
          enterButton={<SearchOutlined />}
          style={{ maxWidth: 400, marginBottom: 16 }}
          onSearch={handleSearch}
        />
        <Table
          dataSource={stocks}
          columns={stockColumns}
          rowKey="code"
          loading={stockLoading}
          size="small"
          pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (t) => `共 ${t} 只` }}
          locale={{ emptyText: <Empty description="无数据" /> }}
        />
      </Card>
    </div>
  );
}
