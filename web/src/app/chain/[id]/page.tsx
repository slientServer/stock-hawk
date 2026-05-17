"use client";

import { useState, useEffect } from "react";
import { Card, Descriptions, Table, Tag, Typography, Spin, Empty, Breadcrumb, Button, Space, App } from "antd";
import { RadarChartOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { useParams, useRouter } from "next/navigation";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getChainDetail, getChainScores, getChainTopology, triggerSignalScan } from "@/lib/api";
import { formatSignalType } from "@/lib/labels";
import AddHoldingButton from "@/components/AddHoldingButton";

const { Title, Text } = Typography;

export default function ChainDetailPage() {
  const { message } = App.useApp();
  const params = useParams();
  const router = useRouter();
  const chainId = decodeURIComponent(params.id as string);

  const [detail, setDetail] = useState<any>(null);
  const [scores, setScores] = useState<any[]>([]);
  const [topology, setTopology] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);

  useEffect(() => {
    Promise.all([
      getChainDetail(chainId).catch(() => null),
      getChainScores(chainId, 30).catch(() => []),
      getChainTopology(chainId).catch(() => null),
    ]).then(([d, s, t]) => {
      setDetail(d);
      setScores(s);
      setTopology(t);
      setLoading(false);
    });
  }, [chainId]);

  if (loading) return <Spin size="large" style={{ display: "block", margin: "100px auto" }} />;

  const latestScore = detail?.latest_score ?? {};
  const score = Number(latestScore?.score ?? detail?.score ?? 0);
  const signals = detail?.signals ?? detail?.recent_signals ?? [];
  const segments = topology?.segments ?? [];
  const activeSignalCount = detail?.active_signal_count ?? latestScore?.signal_count ?? signals.length;
  const scoreChartData = scores.map((item) => ({
    date: item.score_date,
    label: item.score_date ? item.score_date.slice(5, 10) : "-",
    score: Number(item.score ?? 0),
    signal_count: item.signal_count ?? 0,
  }));

  const scanCurrentChain = async () => {
    setScanning(true);
    try {
      await triggerSignalScan(chainId);
      message.success("本链信号扫描已启动");
      router.push(`/signals?chain_id=${encodeURIComponent(chainId)}`);
    } catch (e: any) {
      message.error(`启动失败: ${e?.message || "unknown error"}`);
    } finally {
      setScanning(false);
    }
  };

  const positionColor: Record<string, string> = { "上游": "orange", "中游": "blue", "下游": "green" };

  const segmentColumns = [
    {
      title: "位置",
      dataIndex: "position",
      key: "position",
      width: 90,
      render: (v: string) => <Tag color={positionColor[v] || "default"}>{v || "-"}</Tag>,
      sorter: (a: any, b: any) => {
        const order: Record<string, number> = { "上游": 0, "中游": 1, "下游": 2 };
        return (order[a.position] ?? 9) - (order[b.position] ?? 9);
      },
    },
    {
      title: "环节",
      dataIndex: "segment_name",
      key: "segment_name",
      width: 160,
      render: (_: string, row: any) => <Text strong>{row.segment_name ?? row.name ?? "-"}</Text>,
    },
    {
      title: "公司数",
      key: "company_count",
      width: 80,
      render: (_: any, row: any) => (row.companies ?? []).length,
      sorter: (a: any, b: any) => (a.companies ?? []).length - (b.companies ?? []).length,
    },
    {
      title: "公司",
      key: "companies",
      render: (_: any, row: any) => {
        const companies = row.companies ?? [];
        if (companies.length === 0) return <Text type="secondary">暂无公司</Text>;
        return (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, maxHeight: 72, overflow: "auto" }}>
            {companies.map((comp: any) => (
              <Space key={comp.code} size={2}>
                <Tag
                  style={{ cursor: "pointer", marginInlineEnd: 0 }}
                  onClick={() => router.push(`/stock/${comp.code}`)}
                >
                  {comp.name} ({comp.code})
                </Tag>
                <AddHoldingButton code={comp.code} name={comp.name} source="chain_segment" compact type="text" />
              </Space>
            ))}
          </div>
        );
      },
    },
  ];

  const renderSignalDetail = (row: any) => (
    <Space direction="vertical" size={4} style={{ width: "100%" }}>
      <span style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{row.detail || "-"}</span>
      {(row.target_stocks ?? []).length > 0 && (
        <Space wrap size={[4, 4]}>
          {(row.target_stocks ?? []).map((stock: any) => (
            <Space key={stock.code} size={2}>
              <Tag
                color={stock.name ? "geekblue" : "default"}
                style={{ cursor: "pointer", marginInlineEnd: 0 }}
                onClick={() => router.push(`/stock/${stock.code}`)}
              >
                {stock.name ? `${stock.name} (${stock.code})` : stock.code}
              </Tag>
              <AddHoldingButton code={stock.code} name={stock.name} source="chain_signal" compact type="text" />
            </Space>
          ))}
        </Space>
      )}
    </Space>
  );

  const signalColumns = [
    { title: "类型", dataIndex: "signal_type", key: "signal_type", render: (v: string) => <Tag color="blue">{formatSignalType(v)}</Tag> },
    {
      title: "描述",
      dataIndex: "detail",
      key: "detail",
      render: (_: string, row: any) => renderSignalDetail(row),
    },
    {
      title: "强度",
      dataIndex: "strength",
      key: "strength",
      width: 90,
      sorter: (a: any, b: any) => Number(a.strength ?? 0) - Number(b.strength ?? 0),
      render: (v: number) => Number(v ?? 0).toFixed(2),
    },
    {
      title: "触发日期",
      dataIndex: "trigger_date",
      key: "trigger_date",
      width: 120,
      defaultSortOrder: "descend" as const,
      sorter: (a: any, b: any) => Date.parse(a.trigger_date || "1970-01-01") - Date.parse(b.trigger_date || "1970-01-01"),
      render: (v: string) => v?.slice(0, 10) || "-",
    },
  ];

  return (
    <div>
      <Breadcrumb
        items={[
          { title: <a onClick={() => router.push("/")}>总览</a> },
          { title: chainId },
        ]}
        style={{ marginBottom: 16 }}
      />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16 }}>
        <div>
          <Title level={3} style={{ marginBottom: 4 }}>{chainId}</Title>
          {topology?.chain?.description && (
            <Text type="secondary">{topology.chain.description}</Text>
          )}
        </div>
        <Space wrap>
          <Button icon={<ThunderboltOutlined />} onClick={() => router.push(`/signals?chain_id=${encodeURIComponent(chainId)}`)}>
            查看信号
          </Button>
          <Button loading={scanning} onClick={scanCurrentChain}>扫描本链</Button>
          <Button type="primary" icon={<RadarChartOutlined />} onClick={() => router.push(`/advisor?chain=${encodeURIComponent(chainId)}`)}>
            进入投研
          </Button>
        </Space>
      </div>

      <Card size="small" style={{ marginTop: 16 }}>
        <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 5 }}>
          <Descriptions.Item label="当前评分">
            <Text strong style={{ color: score >= 80 ? "#f5222d" : score >= 60 ? "#fa8c16" : "#595959" }}>
              {score.toFixed(0)}
            </Text>
          </Descriptions.Item>
          <Descriptions.Item label="活跃信号">{activeSignalCount}</Descriptions.Item>
          <Descriptions.Item label="评分日期">{latestScore?.score_date || "-"}</Descriptions.Item>
          <Descriptions.Item label="环节">{segments.length}</Descriptions.Item>
          <Descriptions.Item label="公司">{topology?.companies?.length ?? detail?.company_count ?? "-"}</Descriptions.Item>
        </Descriptions>
      </Card>

      {/* 产业链结构 */}
      {segments.length > 0 && (
        <>
          <Card title="产业链结构" style={{ marginTop: 16 }}>
            <Table
              rowKey={(row: any) => row.uid || row.segment_id || row.segment_name}
              dataSource={segments}
              columns={segmentColumns}
              pagination={false}
              size="small"
              scroll={{ x: 760 }}
            />
          </Card>
        </>
      )}

      {/* 评分趋势 */}
      {scoreChartData.length > 0 && (
        <Card title="评分趋势（近30日）" style={{ marginTop: 16 }}>
          <div style={{ height: 260 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={scoreChartData} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="label" minTickGap={24} tick={{ fontSize: 12 }} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 12 }} width={40} />
                <Tooltip
                  labelFormatter={(_, items) => items?.[0]?.payload?.date ?? "-"}
                  formatter={(value: any, name: any) => [
                    name === "score" ? Number(value).toFixed(0) : value,
                    name === "score" ? "评分" : "信号数",
                  ]}
                />
                <Line type="monotone" dataKey="score" name="score" stroke="#1677ff" dot strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
      )}

      {/* 近期信号 */}
      <Title level={4} style={{ marginTop: 24 }}>近期信号</Title>
      <Table
        dataSource={signals}
        columns={signalColumns}
        rowKey="id"
        pagination={false}
        locale={{ emptyText: <Empty description="暂无信号" /> }}
        scroll={{ x: 760 }}
      />
    </div>
  );
}
