"use client";

import { useState, useEffect } from "react";
import {
  Card, Table, Tag, Typography, Form,
  DatePicker, Select, Input, Button, Empty, App, Descriptions,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { getBacktestResults, runBacktest, getSignalTypes } from "@/lib/api";
import { formatSignalType } from "@/lib/labels";

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;
const FORWARD_WINDOWS = [5, 10, 20, 30, 60, 90];
const RANGE_PRESETS: { label: string; value: [Dayjs, Dayjs] }[] = [
  { label: "近7日", value: [dayjs().subtract(7, "day"), dayjs()] },
  { label: "近30日", value: [dayjs().subtract(30, "day"), dayjs()] },
  { label: "近90日", value: [dayjs().subtract(90, "day"), dayjs()] },
  { label: "近180日", value: [dayjs().subtract(180, "day"), dayjs()] },
  { label: "今年", value: [dayjs().startOf("year"), dayjs()] },
];

export default function BacktestPage() {
  const { message } = App.useApp();
  const [results, setResults] = useState<any[]>([]);
  const [types, setTypes] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm();

  const loadData = () => {
    setLoading(true);
    Promise.all([
      getBacktestResults({ limit: 30 }).catch(() => []),
      getSignalTypes().catch(() => []),
    ]).then(([r, t]) => {
      setResults(r);
      setTypes(t);
      setLoading(false);
    });
  };

  useEffect(() => { loadData(); }, []);

  const onFinish = async (values: any) => {
    setSubmitting(true);
    try {
      const result = await runBacktest({
        start_date: values.dateRange[0].format("YYYY-MM-DD"),
        end_date: values.dateRange[1].format("YYYY-MM-DD"),
        signal_type: values.signal_type || undefined,
        chain_id: values.chain_id || undefined,
      });
      message.success(`回测完成: ${result.valid_signals ?? 0} 个有效样本`);
      loadData();
    } catch (e: any) {
      message.error(`回测失败: ${e.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const pctRender = (v: number | null | undefined) => {
    if (v == null || v === 0) return <Text type="secondary">-</Text>;
    return <Text type={v >= 0 ? "danger" : "success"}>{(v * 100).toFixed(2)}%</Text>;
  };

  const columns = [
    {
      title: "信号类型",
      dataIndex: "signal_type",
      key: "signal_type",
      width: 120,
      render: (v: string) => <Tag color="blue">{v ? formatSignalType(v) : "全部"}</Tag>,
    },
    { title: "区间", key: "range", width: 200, render: (_: any, r: any) => `${r.start_date} ~ ${r.end_date}` },
    { title: "信号数", dataIndex: "total_signals", key: "total_signals", width: 70 },
    {
      title: "胜率",
      dataIndex: "win_rate",
      key: "win_rate",
      width: 80,
      render: (v: number) => v ? `${(v * 100).toFixed(1)}%` : "-",
    },
    {
      title: "最大回撤",
      dataIndex: "max_drawdown",
      key: "max_drawdown",
      width: 90,
      render: (v: number) => v ? `${(v * 100).toFixed(1)}%` : "-",
    },
    {
      title: "30日收益",
      dataIndex: "avg_return_30d",
      key: "avg_return_30d",
      width: 90,
      render: pctRender,
    },
    {
      title: "60日收益",
      dataIndex: "avg_return_60d",
      key: "avg_return_60d",
      width: 90,
      render: pctRender,
    },
    {
      title: "90日收益",
      dataIndex: "avg_return_90d",
      key: "avg_return_90d",
      width: 90,
      render: pctRender,
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 160,
      render: (v: string) => v?.slice(0, 19) || "-",
    },
  ];

  const expandedRowRender = (record: any) => {
    const detail = record.result_detail;
    if (!detail?.stats) return <Text type="secondary">无详细数据</Text>;
    const stats = detail.stats;
    const winRate = stats.win_rate || {};
    const avgReturn = stats.avg_return || {};
    const samples = detail.samples || detail.samples_preview || [];
    const hasOnlyPreview = !detail.samples && (detail.sample_count || 0) > samples.length;

    return (
      <Card size="small">
        <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 4 }}>
          <Descriptions.Item label="有效样本">{stats.valid_signals ?? 0} / {stats.total_signals ?? 0}</Descriptions.Item>
          <Descriptions.Item label="平均回撤">{stats.avg_drawdown ? `${(stats.avg_drawdown * 100).toFixed(1)}%` : "-"}</Descriptions.Item>
          <Descriptions.Item label="盈亏比">{stats.profit_loss_ratio ? stats.profit_loss_ratio.toFixed(2) : "-"}</Descriptions.Item>
          <Descriptions.Item label="夏普比率">{stats.sharpe_ratio ? stats.sharpe_ratio.toFixed(2) : "-"}</Descriptions.Item>
        </Descriptions>
        <Table
          size="small"
          pagination={false}
          style={{ marginTop: 12 }}
          dataSource={FORWARD_WINDOWS.map((w) => ({
            key: w,
            window: `${w}日`,
            win_rate: winRate[w],
            avg_return: avgReturn[w],
            median_return: (stats.median_return || {})[w],
          }))}
          columns={[
            { title: "窗口", dataIndex: "window", width: 70 },
            { title: "胜率", dataIndex: "win_rate", render: (v: number) => v != null ? `${(v * 100).toFixed(1)}%` : "-" },
            { title: "平均收益", dataIndex: "avg_return", render: pctRender },
            { title: "中位数收益", dataIndex: "median_return", render: pctRender },
          ]}
        />
        {(stats.strength_buckets || []).length > 0 && (
          <>
            <Text strong style={{ display: "block", marginTop: 12, marginBottom: 4 }}>信号强度分桶</Text>
            <Table
              size="small"
              pagination={false}
              dataSource={stats.strength_buckets}
              rowKey="strength_range"
              columns={[
                { title: "分桶", dataIndex: "strength_range", width: 100 },
                { title: "样本数", dataIndex: "count", width: 80 },
                { title: "胜率", dataIndex: "win_rate", render: (v: number) => v ? `${(v * 100).toFixed(1)}%` : "-" },
                { title: "平均收益", dataIndex: "avg_return", render: pctRender },
              ]}
            />
          </>
        )}
        <Text strong style={{ display: "block", marginTop: 12, marginBottom: 4 }}>个股明细</Text>
        {hasOnlyPreview && (
          <Text type="secondary" style={{ display: "block", marginBottom: 8 }}>
            旧回测记录仅保留前 {samples.length} 条明细，重新回测后可查看全部 {detail.sample_count} 条。
          </Text>
        )}
        <Table
          size="small"
          dataSource={samples}
          rowKey={(sample: any, index) => `${sample.signal_id}-${sample.target_code}-${index}`}
          pagination={{ pageSize: 10, showSizeChanger: true }}
          scroll={{ x: 1040 }}
          locale={{ emptyText: <Empty description="暂无个股明细" /> }}
          columns={[
            {
              title: "股票",
              dataIndex: "target_code",
              width: 130,
              fixed: "left",
              render: (v: string, sample: any) => (
                sample.stock_name ? (
                  <>
                    <Text strong>{sample.stock_name}</Text>
                    <br />
                    <Text type="secondary">{v || "-"}</Text>
                  </>
                ) : (
                  <Text strong>{v || "-"}</Text>
                )
              ),
            },
            {
              title: "信号",
              dataIndex: "signal_type",
              width: 110,
              render: (v: string) => <Tag color="blue">{formatSignalType(v)}</Tag>,
            },
            { title: "产业链", dataIndex: "chain_id", width: 140, render: (v: string) => v || "-" },
            { title: "触发日", dataIndex: "trigger_date", width: 100 },
            {
              title: "入场价",
              dataIndex: "entry_price",
              width: 90,
              align: "right",
              render: (v: number) => v ? v.toFixed(2) : "-",
            },
            ...FORWARD_WINDOWS.map((window) => ({
              title: `${window}日`,
              key: `return_${window}`,
              width: 80,
              align: "right" as const,
              render: (_: unknown, sample: any) => pctRender(sample.returns?.[window]),
            })),
            {
              title: "最大回撤",
              dataIndex: "max_drawdown",
              width: 90,
              align: "right",
              render: (v: number) => v ? `${(v * 100).toFixed(1)}%` : "-",
            },
            {
              title: "状态",
              dataIndex: "valid",
              width: 80,
              render: (v: boolean) => <Tag color={v ? "green" : "default"}>{v ? "有效" : "待验证"}</Tag>,
            },
          ]}
        />
      </Card>
    );
  };

  return (
    <div>
      <Title level={3}>回测面板</Title>
      <Text type="secondary">信号历史验证与统计（回测时自动补采缺失K线数据）</Text>

      <Card title="触发回测" style={{ marginTop: 16 }}>
        <Form form={form} layout="inline" onFinish={onFinish}>
          <Form.Item name="dateRange" label="日期区间" rules={[{ required: true, message: "请选择日期" }]}>
            <RangePicker presets={RANGE_PRESETS} />
          </Form.Item>
          <Form.Item name="signal_type" label="信号类型">
            <Select
              allowClear
              placeholder="全部"
              style={{ width: 180 }}
              options={types.map((t: any) => ({ label: formatSignalType(t.signal_type), value: t.signal_type }))}
            />
          </Form.Item>
          <Form.Item name="chain_id" label="产业链">
            <Input placeholder="可选" allowClear style={{ width: 150 }} />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={submitting}>
              开始回测
            </Button>
          </Form.Item>
        </Form>
      </Card>

      <Title level={4} style={{ marginTop: 24 }}>回测结果</Title>
      <Table
        dataSource={results}
        columns={columns}
        rowKey="id"
        loading={loading}
        locale={{ emptyText: <Empty description="暂无回测结果" /> }}
        pagination={{ pageSize: 10 }}
        scroll={{ x: 1000 }}
        expandable={{ expandedRowRender }}
      />
    </div>
  );
}
