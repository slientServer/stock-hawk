"use client";

import { useState } from "react";
import { Alert, App, Button, Descriptions, Form, Input, InputNumber, Modal, Space, Tag } from "antd";
import { PlusCircleOutlined } from "@ant-design/icons";
import { createPortfolioPosition, getPortfolioQuote } from "@/lib/api";

type Props = {
  code?: string | null;
  name?: string | null;
  source?: string;
  label?: string;
  size?: "small" | "middle" | "large";
  type?: "link" | "text" | "default" | "primary" | "dashed";
  compact?: boolean;
  stopPropagation?: boolean;
  onAdded?: (position: any) => void;
};

function roundPrice(value?: number | null) {
  return typeof value === "number" && Number.isFinite(value) ? Number(value.toFixed(2)) : undefined;
}

export default function AddHoldingButton({
  code,
  name,
  source = "manual",
  label,
  size = "small",
  type = "default",
  compact = false,
  stopPropagation = true,
  onAdded,
}: Props) {
  const { message } = App.useApp();
  const [open, setOpen] = useState(false);
  const [loadingQuote, setLoadingQuote] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [quote, setQuote] = useState<any>(null);
  const [form] = Form.useForm();

  if (!code) return null;

  const loadQuote = async () => {
    setOpen(true);
    setLoadingQuote(true);
    setQuote(null);
    form.setFieldsValue({ quantity: 100, note: "" });
    try {
      const data = await getPortfolioQuote(code);
      setQuote(data);
      const price = roundPrice(data?.price);
      form.setFieldsValue({
        quantity: 100,
        buy_price: price,
        target_price: price ? roundPrice(price * 1.05) : undefined,
        stop_loss_price: price ? roundPrice(price * 0.97) : undefined,
      });
    } catch (e: any) {
      message.error(e?.message || "获取实时股价失败");
    } finally {
      setLoadingQuote(false);
    }
  };

  const submit = async () => {
    const values = await form.validateFields();
    setSubmitting(true);
    try {
      const position = await createPortfolioPosition({
        code,
        name: name ?? quote?.name,
        quantity: values.quantity,
        buy_price: values.buy_price,
        target_price: values.target_price,
        stop_loss_price: values.stop_loss_price,
        note: values.note,
        source,
      });
      message.success(`${name || code} 已加入持仓`);
      setOpen(false);
      onAdded?.(position);
    } catch (e: any) {
      message.error(e?.message || "加入持仓失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <Button
        type={type}
        size={size}
        icon={<PlusCircleOutlined />}
        onClick={(event) => {
          if (stopPropagation) event.stopPropagation();
          loadQuote();
        }}
      >
        {compact ? undefined : label ?? "加入持仓"}
      </Button>
      <Modal
        title={`加入持仓 · ${name || quote?.name || code}`}
        open={open}
        onOk={submit}
        confirmLoading={submitting}
        okText="加入"
        onCancel={() => setOpen(false)}
        destroyOnHidden
      >
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Descriptions size="small" column={2}>
            <Descriptions.Item label="代码">{code}</Descriptions.Item>
            <Descriptions.Item label="实时价">
              {quote?.price != null ? Number(quote.price).toFixed(2) : "-"}
            </Descriptions.Item>
            <Descriptions.Item label="涨跌幅">
              {quote?.change_pct != null ? `${Number(quote.change_pct).toFixed(2)}%` : "-"}
            </Descriptions.Item>
            <Descriptions.Item label="来源">
              {quote ? <Tag color={quote.is_realtime ? "blue" : "default"}>{quote.quote_source || "-"}</Tag> : "-"}
            </Descriptions.Item>
          </Descriptions>
          {(quote?.data_gaps ?? []).length > 0 && (
            <Alert type="warning" showIcon description={quote.data_gaps.join("；")} />
          )}
          <Form form={form} layout="vertical" disabled={loadingQuote}>
            <Space size={12} style={{ width: "100%" }}>
              <Form.Item
                name="quantity"
                label="股数"
                rules={[{ required: true, message: "请输入股数" }]}
                style={{ flex: 1 }}
              >
                <InputNumber min={1} step={100} style={{ width: "100%" }} />
              </Form.Item>
              <Form.Item
                name="buy_price"
                label="买入价"
                rules={[{ required: true, message: "请输入买入价" }]}
                style={{ flex: 1 }}
              >
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
        </Space>
      </Modal>
    </>
  );
}
