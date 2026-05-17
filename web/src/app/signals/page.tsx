"use client";

import { useCallback, useState, useEffect, useRef, Suspense } from "react";
import { Table, Tag, Radio, Typography, Spin, Empty, Button, App, Space, Progress, Alert } from "antd";
import { useRouter, useSearchParams } from "next/navigation";
import { getSignals, getSignalTypes, triggerSignalScan, getScanStatus } from "@/lib/api";
import { formatScanProgress, formatSignalType } from "@/lib/labels";
import { ThunderboltOutlined, ReloadOutlined } from "@ant-design/icons";
import AddHoldingButton from "@/components/AddHoldingButton";

const { Title, Text } = Typography;

function signalStocks(row: any) {
  const codes = row?.target_codes;
  if (Array.isArray(codes)) return codes.map((code) => ({ code: String(code), name: "" })).filter((item) => item.code);
  if (codes && typeof codes === "object") {
    return Object.values(codes).flatMap((value: any) => Array.isArray(value) ? value : [value])
      .map((code: any) => ({ code: String(code), name: "" }))
      .filter((item: any) => item.code);
  }
  if (row?.source_entity && /^\d{6}$/.test(String(row.source_entity))) {
    return [{ code: String(row.source_entity), name: "" }];
  }
  return [];
}

function SignalsContent() {
  const { message } = App.useApp();
  const searchParams = useSearchParams();
  const router = useRouter();
  const currentType = searchParams.get("type") || "";
  const currentChain = searchParams.get("chain_id") || "";
  const currentPage = parseInt(searchParams.get("page") || "1");
  const pageSize = 30;

  const [data, setData] = useState<{ total: number; items: any[] }>({ total: 0, items: [] });
  const [types, setTypes] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [scanStatus, setScanStatus] = useState<any>(null);
  const pollRef = useRef<NodeJS.Timeout | null>(null);

  const loadData = useCallback(() => {
    setLoading(true);
    Promise.all([
      getSignals({
        chain_id: currentChain || undefined,
        signal_type: currentType || undefined,
        limit: pageSize,
        offset: (currentPage - 1) * pageSize,
      }).catch(() => ({ total: 0, items: [] })),
      getSignalTypes().catch(() => []),
    ]).then(([d, t]) => {
      setData(d);
      setTypes(t);
      setLoading(false);
    });
  }, [currentChain, currentPage, currentType]);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startPolling = useCallback(() => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const s = await getScanStatus();
        setScanStatus(s);
        if (!s.running) {
          stopPolling();
          setScanning(false);
          loadData(); // 扫描完成后刷新数据
          if (s.error) {
            message.error(`扫描出错: ${s.error}`);
          } else {
            message.success(`扫描完成！发现 ${s.signals_found} 个信号`);
          }
        }
      } catch {
        // ignore
      }
    }, 2000);
  }, [loadData, message, stopPolling]);

  useEffect(() => { loadData(); }, [loadData]);

  // 页面加载时检查是否有正在进行的扫描
  useEffect(() => {
    getScanStatus().then((s) => {
      if (s.running) {
        setScanStatus(s);
        setScanning(true);
        startPolling();
      }
    }).catch(() => {});
    return () => stopPolling();
  }, [startPolling, stopPolling]);

  const handleScan = async () => {
    setScanning(true);
    try {
      const res = await triggerSignalScan(currentChain || undefined);
      if (res.status === "already_running") {
        message.warning(res.message);
      } else {
        message.info("信号扫描已启动");
      }
      // 开始轮询状态
      setTimeout(() => startPolling(), 500);
    } catch (e: any) {
      message.error(`触发失败: ${e.message}`);
      setScanning(false);
    }
  };

  const pushSignalParams = (next: { type?: string; page?: number; chainId?: string }) => {
    const params = new URLSearchParams();
    const chainId = next.chainId ?? currentChain;
    const type = next.type ?? currentType;
    if (chainId) params.set("chain_id", chainId);
    if (type) params.set("type", type);
    if (next.page && next.page > 1) params.set("page", String(next.page));
    const query = params.toString();
    router.push(query ? `/signals?${query}` : "/signals");
  };

  const columns = [
    {
      title: "类型",
      dataIndex: "signal_type",
      key: "signal_type",
      width: 140,
      render: (v: string) => <Tag color="blue">{formatSignalType(v)}</Tag>,
    },
    {
      title: "产业链",
      dataIndex: "chain_id",
      key: "chain_id",
      width: 160,
      render: (v: string) => v ? <a onClick={() => router.push(`/chain/${encodeURIComponent(v)}`)}>{v}</a> : "-",
    },
    {
      title: "描述",
      dataIndex: "detail",
      key: "detail",
      render: (v: string, row: any) => {
        const stocks = signalStocks(row);
        return (
          <Space direction="vertical" size={6} style={{ width: "100%" }}>
            <span style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{v || "-"}</span>
            {stocks.length > 0 && (
              <Space wrap size={[4, 4]}>
                {stocks.map((stock: any) => (
                  <Space key={`${row.id}-${stock.code}`} size={2}>
                    <Tag color="geekblue" style={{ marginInlineEnd: 0 }}>{stock.code}</Tag>
                    <AddHoldingButton code={stock.code} source="signal_center" compact type="text" />
                  </Space>
                ))}
              </Space>
            )}
          </Space>
        );
      },
    },
    {
      title: "强度",
      dataIndex: "strength",
      key: "strength",
      width: 80,
      render: (v: number) => Number(v ?? 0).toFixed(2),
    },
    {
      title: "触发日期",
      dataIndex: "trigger_date",
      key: "trigger_date",
      width: 120,
      render: (v: string) => v?.slice(0, 10) || "-",
    },
  ];

  const scanPercent = scanStatus?.total_chains
    ? Math.round((scanStatus.scanned_chains / scanStatus.total_chains) * 100)
    : 0;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <Title level={3} style={{ marginBottom: 4 }}>信号中心</Title>
          <Text type="secondary">{currentChain ? `${currentChain} · ` : ""}共 {data.total} 条信号</Text>
        </div>
        <Space>
          {currentChain && (
            <>
              <Button onClick={() => router.push(`/advisor?chain=${encodeURIComponent(currentChain)}`)}>进入投研</Button>
              <Button onClick={() => router.push("/signals")}>清除产业链</Button>
            </>
          )}
          <Button icon={<ReloadOutlined />} onClick={loadData} disabled={loading}>
            刷新
          </Button>
          <Button
            type="primary"
            icon={<ThunderboltOutlined />}
            loading={scanning}
            onClick={handleScan}
          >
            {scanning ? "扫描中..." : currentChain ? "扫描本链" : "触发信号扫描"}
          </Button>
        </Space>
      </div>

      {/* 扫描进度条 */}
      {scanning && scanStatus && (
        <Alert
          type="info"
          showIcon
          style={{ marginTop: 16 }}
          title={
            <div>
              <div style={{ marginBottom: 8 }}>
                <Text strong>{formatScanProgress(scanStatus.progress)}</Text>
                {scanStatus.signals_found > 0 && (
                  <Text type="secondary" style={{ marginLeft: 12 }}>
                    已发现 {scanStatus.signals_found} 个信号
                  </Text>
                )}
              </div>
              {scanStatus.total_chains > 0 && (
                <Progress
                  percent={scanPercent}
                  size="small"
                  format={() => `${scanStatus.scanned_chains}/${scanStatus.total_chains}`}
                />
              )}
            </div>
          }
        />
      )}

      {/* 扫描完成提示 */}
      {!scanning && scanStatus?.finished_at && !scanStatus?.error && (
        <Alert
          type="success"
          showIcon
          closable
          style={{ marginTop: 16 }}
          title={`上次扫描完成: ${scanStatus.scanned_chains} 条产业链，发现 ${scanStatus.signals_found} 个信号`}
        />
      )}

      {types.length > 0 && (
        <div style={{ margin: "16px 0" }}>
          <Radio.Group
            value={currentType}
            onChange={(e) => {
              const v = e.target.value;
              pushSignalParams({ type: v, page: 1 });
            }}
            optionType="button"
            buttonStyle="solid"
            size="small"
          >
            <Radio.Button value="">全部</Radio.Button>
            {types.map((t: any) => (
              <Radio.Button key={t.signal_type} value={t.signal_type}>
                {formatSignalType(t.signal_type)} ({t.count})
              </Radio.Button>
            ))}
          </Radio.Group>
        </div>
      )}

      <Table
        dataSource={data.items}
        columns={columns}
        rowKey="id"
        loading={loading}
        locale={{ emptyText: <Empty description="暂无信号数据" /> }}
        pagination={{
          current: currentPage,
          pageSize,
          total: data.total,
          showSizeChanger: false,
          onChange: (page) => {
            pushSignalParams({ page });
          },
        }}
      />
    </div>
  );
}

export default function SignalsPage() {
  return (
    <Suspense fallback={<Spin size="large" style={{ display: "block", margin: "100px auto" }} />}>
      <SignalsContent />
    </Suspense>
  );
}
