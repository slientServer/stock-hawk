"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  App, Button, Card, Col, Empty, Form, Input, InputNumber, Modal, Row, Space,
  Spin, Statistic, Table, Tag, Typography,
} from "antd";
import { CheckCircleOutlined, CloseCircleOutlined, EditOutlined, ReloadOutlined } from "@ant-design/icons";
import { useRouter } from "next/navigation";
import type { ColumnsType } from "antd/es/table";
import AddHoldingButton from "@/components/AddHoldingButton";
import {
  closePortfolioPosition,
  getPortfolioPositions,
  getPortfolioTransactions,
  updatePortfolioPosition,
} from "@/lib/api";

const { Title, Text, Paragraph } = Typography;

function money(value?: number | null) {
  if (value == null) return "-";
  const sign = value > 0 ? "+" : "";
  if (Math.abs(value) >= 100000000) return `${sign}${(value / 100000000).toFixed(2)}亿`;
  if (Math.abs(value) >= 10000) return `${sign}${(value / 10000).toFixed(2)}万`;
  return `${sign}${Number(value).toFixed(2)}`;
}

function price(value?: number | null) {
  return value == null ? "-" : Number(value).toFixed(2);
}

function pct(value?: number | null) {
  return value == null ? "-" : `${value > 0 ? "+" : ""}${Number(value).toFixed(2)}%`;
}

function shortTime(value?: string | null) {
  if (!value) return "-";
  return value.length > 10 ? value.slice(5, 16).replace("T", " ") : value;
}

function thresholdTag(status?: string) {
  if (status === "take_profit") return <Tag color="red" icon={<CheckCircleOutlined />}>止盈</Tag>;
  if (status === "stop_loss") return <Tag color="green" icon={<CloseCircleOutlined />}>止损</Tag>;
  if (status === "data_missing") return <Tag color="orange">缺行情</Tag>;
  return <Tag color="blue">持有</Tag>;
}

function actionLabel(action?: string) {
  const labels: Record<string, string> = {
    buy: "买入",
    add_buy: "加仓",
    update: "修改",
    sell: "减仓",
    close: "平仓",
  };
  return labels[action || ""] || action || "-";
}

export default function PortfolioPage() {
  const { message } = App.useApp();
  const router = useRouter();
  const [data, setData] = useState<any>({ items: [], summary: {} });
  const [history, setHistory] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [includeClosed, setIncludeClosed] = useState(false);
  const [quickCode, setQuickCode] = useState("");
  const [editing, setEditing] = useState<any>(null);
  const [closing, setClosing] = useState<any>(null);
  const [saving, setSaving] = useState(false);
  const [editForm] = Form.useForm();
  const [closeForm] = Form.useForm();

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([
      getPortfolioPositions({ include_closed: includeClosed }).catch(() => ({ items: [], summary: {} })),
      getPortfolioTransactions({ limit: 80 }).catch(() => []),
    ]).then(([positions, tx]) => {
      setData(positions);
      setHistory(tx);
      setLoading(false);
    });
  }, [includeClosed]);

  useEffect(() => { load(); }, [load]);

  const openEdit = useCallback((row: any) => {
    setEditing(row);
    editForm.setFieldsValue({
      quantity: row.quantity,
      avg_cost: row.avg_cost,
      target_price: row.target_price,
      stop_loss_price: row.stop_loss_price,
      note: row.note,
    });
  }, [editForm]);

  const saveEdit = async () => {
    const values = await editForm.validateFields();
    setSaving(true);
    try {
      await updatePortfolioPosition(editing.id, values);
      message.success("持仓已更新");
      setEditing(null);
      load();
    } catch (e: any) {
      message.error(e?.message || "更新失败");
    } finally {
      setSaving(false);
    }
  };

  const openClose = useCallback((row: any) => {
    setClosing(row);
    closeForm.setFieldsValue({
      quantity: row.quantity,
      close_price: row.current_price,
      note: "",
    });
  }, [closeForm]);

  const saveClose = async () => {
    const values = await closeForm.validateFields();
    setSaving(true);
    try {
      await closePortfolioPosition(closing.id, values);
      message.success(values.quantity >= closing.quantity ? "已平仓" : "已减仓");
      setClosing(null);
      load();
    } catch (e: any) {
      message.error(e?.message || "操作失败");
    } finally {
      setSaving(false);
    }
  };

  const summary = data.summary ?? {};

  const columns: ColumnsType<any> = useMemo(() => [
    {
      title: "标的",
      key: "stock",
      width: 150,
      render: (_: any, row: any) => (
        <a onClick={() => router.push(`/stock/${row.code}`)}>
          <Text strong>{row.name || row.code}</Text><br />
          <Text type="secondary">{row.code}</Text>
        </a>
      ),
    },
    {
      title: "持仓",
      key: "position",
      width: 150,
      render: (_: any, row: any) => (
        <Space orientation="vertical" size={2}>
          <Text>{row.quantity} 股</Text>
          <Text type="secondary">成本 {price(row.avg_cost)}</Text>
          <Text type="secondary">投入 {money(row.cost_amount)}</Text>
        </Space>
      ),
    },
    {
      title: "实时行情",
      key: "quote",
      width: 150,
      render: (_: any, row: any) => (
        <Space orientation="vertical" size={2}>
          <Text strong>{price(row.current_price)}</Text>
          <Text type={Number(row.change_pct ?? 0) >= 0 ? "danger" : "success"}>{pct(row.change_pct)}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {row.is_realtime ? "实时" : "入库"} · {shortTime(row.quote_time)}
          </Text>
        </Space>
      ),
    },
    {
      title: "收益",
      key: "profit",
      width: 170,
      sorter: (a: any, b: any) => (a.unrealized_profit ?? -Infinity) - (b.unrealized_profit ?? -Infinity),
      render: (_: any, row: any) => {
        const positive = Number(row.unrealized_profit ?? 0) >= 0;
        return (
          <Space orientation="vertical" size={2}>
            <Text strong type={positive ? "danger" : "success"}>{money(row.unrealized_profit)}</Text>
            <Text type={positive ? "danger" : "success"}>{pct(row.unrealized_return_pct)}</Text>
            <Text type="secondary">市值 {money(row.market_value)}</Text>
          </Space>
        );
      },
    },
    {
      title: "阈值",
      key: "threshold",
      width: 180,
      render: (_: any, row: any) => (
        <Space orientation="vertical" size={4}>
          {thresholdTag(row.threshold_status)}
          <Text type="secondary">止盈 {price(row.target_price)} / 止损 {price(row.stop_loss_price)}</Text>
        </Space>
      ),
    },
    {
      title: "操作建议",
      dataIndex: "action_advice",
      key: "action_advice",
      width: 320,
      render: (value: string) => <Paragraph style={{ margin: 0 }} ellipsis={{ rows: 2 }}>{value}</Paragraph>,
    },
    {
      title: "操作",
      key: "action",
      width: 150,
      fixed: "right" as const,
      render: (_: any, row: any) => row.status === "active" ? (
        <Space size={6}>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>修改</Button>
          <Button size="small" danger onClick={() => openClose(row)}>卖出</Button>
        </Space>
      ) : <Tag>已平仓</Tag>,
    },
  ], [openClose, openEdit, router]);

  const historyColumns: ColumnsType<any> = [
    { title: "时间", dataIndex: "created_at", key: "created_at", width: 150, render: shortTime },
    {
      title: "标的",
      key: "stock",
      width: 120,
      render: (_: any, row: any) => <a onClick={() => router.push(`/stock/${row.code}`)}>{row.code}</a>,
    },
    { title: "动作", dataIndex: "action", key: "action", width: 90, render: (v: string) => <Tag>{actionLabel(v)}</Tag> },
    { title: "股数", dataIndex: "quantity", key: "quantity", width: 90, render: (v: number) => v ?? "-" },
    { title: "价格", dataIndex: "price", key: "price", width: 90, render: price },
    { title: "金额", dataIndex: "amount", key: "amount", width: 110, render: money },
    {
      title: "已实现盈亏",
      dataIndex: "realized_profit",
      key: "realized_profit",
      width: 120,
      render: (v: number) => <Text type={Number(v ?? 0) >= 0 ? "danger" : "success"}>{money(v)}</Text>,
    },
    { title: "备注", dataIndex: "note", key: "note", render: (v: string) => v || "-" },
  ];

  if (loading) return <Spin size="large" style={{ display: "block", margin: "100px auto" }} />;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16 }}>
        <div>
          <Title level={3} style={{ marginBottom: 4 }}>持仓管理</Title>
          <Text type="secondary">当前 {summary.active_count ?? 0} 只持仓</Text>
        </div>
        <Space wrap>
          <Input
            style={{ width: 150 }}
            value={quickCode}
            maxLength={12}
            placeholder="股票代码"
            onChange={(event) => setQuickCode(event.target.value)}
          />
          <AddHoldingButton code={quickCode} label="加入" type="primary" size="middle" source="portfolio_page" onAdded={load} />
          <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
        </Space>
      </div>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={12} lg={4}><Card size="small"><Statistic title="持仓数" value={summary.active_count ?? 0} /></Card></Col>
        <Col xs={12} lg={4}><Card size="small"><Statistic title="投入成本" value={money(summary.total_cost)} /></Card></Col>
        <Col xs={12} lg={4}><Card size="small"><Statistic title="当前市值" value={money(summary.market_value)} /></Card></Col>
        <Col xs={12} lg={4}>
          <Card size="small">
            <Statistic
              title="浮动盈亏"
              value={money(summary.unrealized_profit)}
              styles={{ content: { color: Number(summary.unrealized_profit ?? 0) >= 0 ? "#cf1322" : "#3f8600" } }}
            />
          </Card>
        </Col>
        <Col xs={12} lg={4}><Card size="small"><Statistic title="收益率" value={pct(summary.unrealized_return_pct)} /></Card></Col>
        <Col xs={12} lg={4}><Card size="small"><Statistic title="阈值触发" value={summary.threshold_hit_count ?? 0} suffix="只" /></Card></Col>
      </Row>

      <Card
        title="持仓明细"
        style={{ marginTop: 16 }}
        extra={
          <Space>
            <Button size="small" type={includeClosed ? "primary" : "default"} onClick={() => setIncludeClosed((v) => !v)}>
              {includeClosed ? "隐藏已平仓" : "显示已平仓"}
            </Button>
          </Space>
        }
      >
        <Table
          rowKey="id"
          dataSource={data.items ?? []}
          columns={columns}
          size="small"
          pagination={{ pageSize: 12 }}
          locale={{ emptyText: <Empty description="暂无持仓" /> }}
          scroll={{ x: 1260 }}
        />
      </Card>

      <Card title="操作历史" style={{ marginTop: 16 }}>
        <Table
          rowKey="id"
          dataSource={history}
          columns={historyColumns}
          size="small"
          pagination={{ pageSize: 10 }}
          locale={{ emptyText: <Empty description="暂无操作历史" /> }}
          scroll={{ x: 900 }}
        />
      </Card>

      <Modal
        title={editing ? `修改持仓 · ${editing.name || editing.code}` : "修改持仓"}
        open={Boolean(editing)}
        onOk={saveEdit}
        confirmLoading={saving}
        onCancel={() => setEditing(null)}
        destroyOnHidden
      >
        <Form form={editForm} layout="vertical">
          <Space size={12} style={{ width: "100%" }}>
            <Form.Item name="quantity" label="股数" rules={[{ required: true }]} style={{ flex: 1 }}>
              <InputNumber min={1} step={100} style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item name="avg_cost" label="成本价" rules={[{ required: true }]} style={{ flex: 1 }}>
              <InputNumber min={0.01} step={0.01} precision={2} style={{ width: "100%" }} />
            </Form.Item>
          </Space>
          <Space size={12} style={{ width: "100%" }}>
            <Form.Item name="target_price" label="止盈价" style={{ flex: 1 }}>
              <InputNumber min={0.01} step={0.01} precision={2} style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item name="stop_loss_price" label="止损价" style={{ flex: 1 }}>
              <InputNumber min={0.01} step={0.01} precision={2} style={{ width: "100%" }} />
            </Form.Item>
          </Space>
          <Form.Item name="note" label="备注">
            <Input.TextArea rows={2} maxLength={200} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={closing ? `卖出 · ${closing.name || closing.code}` : "卖出"}
        open={Boolean(closing)}
        onOk={saveClose}
        confirmLoading={saving}
        okText="确认"
        onCancel={() => setClosing(null)}
        destroyOnHidden
      >
        <Form form={closeForm} layout="vertical">
          <Space size={12} style={{ width: "100%" }}>
            <Form.Item name="quantity" label="股数" rules={[{ required: true }]} style={{ flex: 1 }}>
              <InputNumber min={1} max={closing?.quantity} step={100} style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item name="close_price" label="卖出价" rules={[{ required: true }]} style={{ flex: 1 }}>
              <InputNumber min={0.01} step={0.01} precision={2} style={{ width: "100%" }} />
            </Form.Item>
          </Space>
          <Form.Item name="note" label="备注">
            <Input.TextArea rows={2} maxLength={200} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
