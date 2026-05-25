"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  App,
  Button,
  Card,
  Divider,
  Empty,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Spin,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import { PlusOutlined, ReloadOutlined, ReadOutlined, SyncOutlined } from "@ant-design/icons";
import type { TableProps } from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  addFinanceNewsSource,
  collectFinanceNews,
  disableFinanceNewsSource,
  getFinanceNewsSources,
  getFinanceNewsSummaries,
  getNewsCenterToday,
  summarizeFinanceNews,
  updateFinanceNewsSource,
} from "@/lib/api";

const { Title, Text, Paragraph } = Typography;

function shortTime(value?: string | null) {
  if (!value) return "-";
  return value.slice(0, 16).replace("T", " ");
}

export default function NewsCenterPage() {
  const { message } = App.useApp();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [summarizing, setSummarizing] = useState(false);
  const [today, setToday] = useState<any>({ articles: [] });
  const [sources, setSources] = useState<any[]>([]);
  const [history, setHistory] = useState<any[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [sourceFilter, setSourceFilter] = useState<string>("all");
  const [form] = Form.useForm();

  const loadData = async () => {
    setLoading(true);
    try {
      const [todayData, sourceData, summaryData] = await Promise.all([
        getNewsCenterToday().catch(() => ({ articles: [] })),
        getFinanceNewsSources().catch(() => ({ items: [] })),
        getFinanceNewsSummaries(30).catch(() => ({ items: [] })),
      ]);
      setToday(todayData);
      setSources(sourceData.items ?? []);
      setHistory(summaryData.items ?? []);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadData(); }, []);

  const handleCollect = async () => {
    setRefreshing(true);
    try {
      const result = await collectFinanceNews({ use_llm: true, limit_per_source: 40 });
      message.success(`拉取完成：新增 ${result.inserted_count ?? 0} 条，更新 ${result.updated_count ?? 0} 条`);
      await loadData();
    } catch (e: any) {
      message.error(e.message || "资讯拉取失败");
    } finally {
      setRefreshing(false);
    }
  };

  const handleSummarize = async () => {
    setSummarizing(true);
    try {
      await summarizeFinanceNews({ use_llm: true });
      message.success("今日财经小结已生成");
      await loadData();
    } catch (e: any) {
      message.error(e.message || "生成小结失败");
    } finally {
      setSummarizing(false);
    }
  };

  const handleAddSource = async (values: any) => {
    try {
      await addFinanceNewsSource(values);
      message.success("财经源已添加");
      form.resetFields();
      setModalOpen(false);
      await loadData();
    } catch (e: any) {
      message.error(e.message || "添加失败");
    }
  };

  const handleToggleSource = async (record: any, enabled: boolean) => {
    await updateFinanceNewsSource(record.id, { enabled });
    await loadData();
  };

  const summary = today?.summary;
  const articles: any[] = useMemo(() => today?.articles ?? [], [today]);

  // 来源选项（用于过滤下拉）
  const sourceOptions = useMemo(() => {
    const names = Array.from(new Set(articles.map((a) => a.source_name).filter(Boolean)));
    return [{ value: "all", label: "全部来源" }, ...names.map((n) => ({ value: n, label: n }))];
  }, [articles]);

  const filteredArticles = useMemo(
    () => (sourceFilter === "all" ? articles : articles.filter((a) => a.source_name === sourceFilter)),
    [articles, sourceFilter]
  );

  const articleColumns: ColumnsType<any> = [
    { title: "时间", dataIndex: "published_at", key: "published_at", width: 150, render: shortTime },
    { title: "来源", dataIndex: "source_name", key: "source_name", width: 140, render: (v) => <Tag>{v || "-"}</Tag> },
    {
      title: "标题",
      dataIndex: "title",
      key: "title",
      render: (value: string, row: any) =>
        row.url ? (
          <a href={row.url} target="_blank" rel="noreferrer">{value}</a>
        ) : (
          <Text>{value}</Text>
        ),
    },
  ];

  const sourceColumns: ColumnsType<any> = [
    { title: "启用", dataIndex: "enabled", key: "enabled", width: 80, render: (v, row) => <Switch checked={v} onChange={(checked) => handleToggleSource(row, checked)} /> },
    { title: "名称", dataIndex: "name", key: "name", width: 170 },
    { title: "分类", dataIndex: "category", key: "category", width: 100, render: (v) => v || "-" },
    { title: "类型", dataIndex: "source_type", key: "source_type", width: 120, render: (v) => <Tag>{v}</Tag> },
    { title: "地址", dataIndex: "url", key: "url", ellipsis: true },
    {
      title: "操作",
      key: "action",
      width: 90,
      render: (_: any, row: any) => (
        <Button size="small" danger disabled={!row.enabled} onClick={async () => { await disableFinanceNewsSource(row.id); await loadData(); }}>
          停用
        </Button>
      ),
    },
  ];

  const historyColumns: ColumnsType<any> = [
    { title: "日期", dataIndex: "summary_date", key: "summary_date", width: 120 },
    { title: "生成时间", dataIndex: "generated_at", key: "generated_at", width: 160, render: shortTime },
    { title: "资讯", dataIndex: "article_count", key: "article_count", width: 80, render: (v) => `${v ?? 0} 条` },
    { title: "来源", dataIndex: "source_count", key: "source_count", width: 80, render: (v) => `${v ?? 0} 个` },
    {
      title: "模式",
      dataIndex: "llm_used",
      key: "llm_used",
      width: 100,
      render: (v) => <Tag color={v ? "blue" : "default"}>{v ? "LLM 汇总" : "规则化"}</Tag>,
    },
    { title: "小结摘要", dataIndex: "content", key: "content", render: (v) => <Text type="secondary" style={{ fontSize: 12 }}>{(v || "-").slice(0, 80)}{v?.length > 80 ? "…" : ""}</Text> },
  ];

  const historyExpandable: NonNullable<TableProps<any>["expandable"]> = {
    expandedRowRender: (row) => (
      <div style={{ padding: "8px 16px" }}>
        <Paragraph style={{ whiteSpace: "pre-line", marginBottom: 8 }}>{row.content || "-"}</Paragraph>
        {(row.key_points ?? []).length > 0 && (
          <>
            <Divider style={{ margin: "8px 0" }} />
            <Space direction="vertical" size={6} style={{ width: "100%" }}>
              {(row.key_points ?? []).map((item: any, idx: number) => (
                <div key={idx}>
                  <Text strong style={{ fontSize: 13 }}>{item.topic || `要点 ${idx + 1}`}</Text>
                  {(item.sources ?? []).map((s: string) => (
                    <Tag key={s} style={{ marginLeft: 6, fontSize: 11 }}>{s}</Tag>
                  ))}
                  <div style={{ color: "#555", fontSize: 12, marginTop: 2 }}>{item.summary}</div>
                </div>
              ))}
            </Space>
          </>
        )}
        {(row.watch_items ?? []).length > 0 && (
          <>
            <Divider style={{ margin: "8px 0" }} />
            <Text type="secondary" style={{ fontSize: 12 }}>后续关注：</Text>
            <Space wrap style={{ marginTop: 4 }}>
              {(row.watch_items ?? []).map((item: string, idx: number) => (
                <Tag key={idx} color="orange" style={{ fontSize: 11 }}>{item}</Tag>
              ))}
            </Space>
          </>
        )}
      </div>
    ),
    rowExpandable: (row) => !!(row.content || (row.key_points ?? []).length > 0),
  };

  if (loading) return <Spin size="large" style={{ display: "block", margin: "100px auto" }} />;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, marginBottom: 16 }}>
        <div>
          <Title level={3} style={{ marginBottom: 4 }}>
            <ReadOutlined style={{ marginRight: 8 }} />
            资讯中心
          </Title>
          <Text type="secondary">每小时拉取重要财经频道，LLM 去重汇总为今日财经小结并保留历史</Text>
        </div>
        <Space wrap>
          <Button icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>添加财经源</Button>
          <Button icon={<SyncOutlined />} loading={summarizing} onClick={handleSummarize}>生成小结</Button>
          <Button type="primary" icon={<ReloadOutlined />} loading={refreshing} onClick={handleCollect}>拉取最新资讯</Button>
        </Space>
      </div>

      {summary?.data_gaps?.length > 0 && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="小结存在数据缺口"
          description={summary.data_gaps.join("；")}
        />
      )}

      <Card title="今日财经小结" style={{ marginBottom: 16 }}>
        {summary ? (
          <Space direction="vertical" size={12} style={{ width: "100%" }}>
            <Space wrap>
              <Tag color={summary.llm_used ? "blue" : "default"}>{summary.llm_used ? "LLM 汇总去重" : "规则化小结"}</Tag>
              <Text type="secondary">{shortTime(summary.generated_at)}</Text>
              <Text type="secondary">{summary.article_count} 条资讯 / {summary.source_count} 个来源</Text>
            </Space>

            <Paragraph style={{ whiteSpace: "pre-line", marginBottom: 0 }}>{summary.content}</Paragraph>

            {(summary.key_points ?? []).length > 0 && (
              <>
                <Divider style={{ margin: "4px 0" }} />
                <Space direction="vertical" size={8} style={{ width: "100%" }}>
                  {(summary.key_points ?? []).map((item: any, index: number) => (
                    <div key={`${item.topic}-${index}`} style={{ borderLeft: "3px solid #1677ff", paddingLeft: 10 }}>
                      <Space wrap>
                        <Text strong>{item.topic || `要点 ${index + 1}`}</Text>
                        {(item.sources ?? []).map((s: string) => (
                          <Tag key={s} style={{ fontSize: 11 }}>{s}</Tag>
                        ))}
                      </Space>
                      <Paragraph style={{ margin: "4px 0 0", color: "#444" }}>{item.summary || "-"}</Paragraph>
                    </div>
                  ))}
                </Space>
              </>
            )}

            {(summary.watch_items ?? []).length > 0 && (
              <>
                <Divider style={{ margin: "4px 0" }} />
                <div>
                  <Text type="secondary" style={{ marginRight: 8 }}>后续关注变量：</Text>
                  <Space wrap>
                    {(summary.watch_items ?? []).map((item: string, idx: number) => (
                      <Tag key={idx} color="orange">{item}</Tag>
                    ))}
                  </Space>
                </div>
              </>
            )}
          </Space>
        ) : (
          <Empty description="今日暂无小结，点击「拉取最新资讯」后自动生成" />
        )}
      </Card>

      <Tabs
        items={[
          {
            key: "articles",
            label: `今日资讯${articles.length ? `（${articles.length}）` : ""}`,
            children: (
              <>
                <div style={{ marginBottom: 8 }}>
                  <Select
                    value={sourceFilter}
                    onChange={setSourceFilter}
                    options={sourceOptions}
                    style={{ width: 200 }}
                    size="small"
                  />
                </div>
                <Table
                  rowKey="id"
                  dataSource={filteredArticles}
                  columns={articleColumns}
                  size="small"
                  pagination={{ pageSize: 20, showSizeChanger: true }}
                  locale={{ emptyText: <Empty description="今日暂无资讯" /> }}
                />
              </>
            ),
          },
          {
            key: "history",
            label: "历史小结",
            children: (
              <Table
                rowKey="id"
                dataSource={history}
                columns={historyColumns}
                expandable={historyExpandable}
                size="small"
                pagination={{ pageSize: 10 }}
                locale={{ emptyText: <Empty description="暂无历史小结" /> }}
              />
            ),
          },
          {
            key: "sources",
            label: "财经源",
            children: (
              <Table
                rowKey="id"
                dataSource={sources}
                columns={sourceColumns}
                size="small"
                pagination={false}
                scroll={{ x: 900 }}
              />
            ),
          },
        ]}
      />

      <Modal
        title="添加财经源"
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => form.submit()}
        okText="添加"
        destroyOnHidden
      >
        <Form form={form} layout="vertical" onFinish={handleAddSource} initialValues={{ source_type: "rss", enabled: true }}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: "请输入名称" }]}>
            <Input placeholder="例如：交易所公告 RSS" />
          </Form.Item>
          <Form.Item name="url" label="RSS/Atom URL" rules={[{ required: true, message: "请输入 RSS/Atom 地址" }]}>
            <Input placeholder="https://example.com/rss" />
          </Form.Item>
          <Form.Item name="category" label="分类">
            <Input placeholder="例如：宏观 / A股 / 全球市场" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
