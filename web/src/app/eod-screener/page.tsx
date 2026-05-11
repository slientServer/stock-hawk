"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Table,
  Typography,
  Button,
  App,
  Card,
  DatePicker,
  Space,
  Tag,
  Statistic,
  Row,
  Col,
  Modal,
  Form,
  InputNumber,
  Switch,
  Tabs,
  Empty,
  Descriptions,
  Alert,
} from "antd";
import {
  ReloadOutlined,
  SettingOutlined,
  ExperimentOutlined,
  RiseOutlined,
  FallOutlined,
} from "@ant-design/icons";
import dayjs from "dayjs";
import type { Dayjs } from "dayjs";
import type { ColumnsType } from "antd/es/table";
import {
  runEodScreener,
  getEodScreenerResults,
  getEodScreenerConfig,
  updateEodScreenerConfig,
  runEodBacktest,
  getEodBacktestResults,
  collectEodFullMarket,
} from "@/lib/api";

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;

const formatPct = (value?: number | null, digits = 2) =>
  typeof value === "number" ? `${value.toFixed(digits)}%` : "-";

const formatWinRate = (value?: number | null) =>
  typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "-";

const formatQuoteTime = (value?: string | null) =>
  value ? dayjs(value).format("MM-DD HH:mm") : "-";

export default function EodScreenerPage() {
  const { message } = App.useApp();

  // --- State ---
  const [results, setResults] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [screening, setScreening] = useState(false);
  const [collecting, setCollecting] = useState(false);
  const [selectedDate, setSelectedDate] = useState<Dayjs | null>(null);
  const [configVisible, setConfigVisible] = useState(false);
  const [config, setConfig] = useState<any>({});
  const [backtestVisible, setBacktestVisible] = useState(false);
  const [backtesting, setBacktesting] = useState(false);
  const [backtestResults, setBacktestResults] = useState<any[]>([]);
  const [latestBacktest, setLatestBacktest] = useState<any>(null);
  const [runInfo, setRunInfo] = useState<any>(null);

  // --- Load data ---
  const loadResults = useCallback(
    (tradeDate?: string) => {
      setLoading(true);
      getEodScreenerResults({ trade_date: tradeDate, limit: 100 })
        .then(setResults)
        .catch(() => message.error("加载选股结果失败"))
        .finally(() => setLoading(false));
    },
    [message],
  );

  const loadBacktestHistory = useCallback(() => {
    getEodBacktestResults({ limit: 5 })
      .then((data) => {
        setBacktestResults(data);
        if (data.length > 0) setLatestBacktest(data[0]);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    loadResults();
    loadBacktestHistory();
  }, [loadResults, loadBacktestHistory]);

  // --- Handlers ---
  const handleRunScreen = async () => {
    setScreening(true);
    try {
      const tradeDate = selectedDate?.format("YYYY-MM-DD");
      const mode = !tradeDate || tradeDate === dayjs().format("YYYY-MM-DD") ? "intraday" : "stored";
      const res = await runEodScreener(tradeDate, true, mode);
      setRunInfo(res);
      if (res.trade_date) setSelectedDate(dayjs(res.trade_date));
      if (res.status === "blocked") {
        message.warning("行情覆盖不足，请先采集全市场行情");
      } else {
        message.success(`选股完成，${res.trade_date ?? "无交易日"} 选出 ${res.count} 只股票`);
      }
      loadResults(res.trade_date ?? selectedDate?.format("YYYY-MM-DD"));
    } catch {
      message.error("选股执行失败");
    } finally {
      setScreening(false);
    }
  };

  const handleCollectFullMarket = async () => {
    setCollecting(true);
    try {
      const collectRes = await collectEodFullMarket({
        trade_date: selectedDate?.format("YYYY-MM-DD"),
        lookback_days: 30,
        mode: "intraday",
        run_after: true,
      });
      if (collectRes.trade_date) setSelectedDate(dayjs(collectRes.trade_date));
      const coverage = collectRes.market_coverage;
      if (!coverage?.is_full_market) {
        setRunInfo({
          status: "blocked",
          trade_date: collectRes.trade_date,
          count: 0,
          results: [],
          diagnostics: {
            candidate_count: 0,
            passed_count: 0,
            filter_reasons: {},
            market_coverage: coverage,
            data_gaps: [collectRes.message || "全市场行情采集完成但覆盖率不足"],
            sample_failures: [],
            action_required: "collect_full_market",
          },
        });
        message.warning(`采集完成但覆盖率不足：${coverage?.coverage_pct ?? 0}%`);
        return;
      }
      message.success(`全市场行情采集完成：${coverage.kline_stock_count}/${coverage.total_stock_count} 只`);
      const screenRes = collectRes.screen_result ?? (await runEodScreener(collectRes.trade_date, true, "stored"));
      setRunInfo(screenRes);
      loadResults(screenRes.trade_date ?? collectRes.trade_date);
    } catch {
      message.error("全市场行情采集失败");
    } finally {
      setCollecting(false);
    }
  };

  const handleDateChange = (date: Dayjs | null) => {
    setSelectedDate(date);
    setRunInfo(null);
    if (date) {
      loadResults(date.format("YYYY-MM-DD"));
    } else {
      loadResults();
    }
  };

  const handleOpenConfig = async () => {
    try {
      const cfg = await getEodScreenerConfig();
      setConfig(cfg);
      setConfigVisible(true);
    } catch {
      message.error("获取配置失败");
    }
  };

  const handleSaveConfig = async () => {
    try {
      await updateEodScreenerConfig(config);
      message.success("配置已保存");
      setConfigVisible(false);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "保存配置失败");
    }
  };

  const handleRunBacktest = async (values: any) => {
    setBacktesting(true);
    try {
      const res = await runEodBacktest({
        start_date: values.range[0].format("YYYY-MM-DD"),
        end_date: values.range[1].format("YYYY-MM-DD"),
      });
      message.success(`回测完成: ${res.total_trades} 笔交易`);
      setLatestBacktest(res);
      setBacktestVisible(false);
      loadBacktestHistory();
    } catch {
      message.error("回测失败");
    } finally {
      setBacktesting(false);
    }
  };

  // --- Table columns ---
  const columns: ColumnsType<any> = [
    {
      title: "排名",
      dataIndex: "rank",
      key: "rank",
      width: 60,
      render: (v: number) => (
        <Tag color={v <= 3 ? "red" : v <= 10 ? "orange" : "default"}>{v}</Tag>
      ),
    },
    { title: "代码", dataIndex: "code", key: "code", width: 80 },
    { title: "名称", dataIndex: "name", key: "name", width: 90 },
    {
      title: "行情",
      key: "quote",
      width: 120,
      render: (_: any, r: any) => (
        <Space direction="vertical" size={0}>
          <Tag color={r.data_mode === "intraday" ? "blue" : "default"}>
            {r.data_mode === "intraday" ? "盘中" : r.data_mode || "存量"}
          </Tag>
          <Text type="secondary">{formatQuoteTime(r.quote_time)}</Text>
        </Space>
      ),
    },
    {
      title: "收盘价",
      dataIndex: "close_price",
      key: "close_price",
      width: 80,
      render: (v: number) => v?.toFixed(2),
    },
    {
      title: "涨幅%",
      dataIndex: "change_pct",
      key: "change_pct",
      width: 80,
      render: (v: number) => (
        <Text type={v > 0 ? "danger" : "success"}>
          {v > 0 ? "+" : ""}
          {v?.toFixed(2)}%
        </Text>
      ),
    },
    {
      title: "量比",
      dataIndex: "volume_ratio",
      key: "volume_ratio",
      width: 70,
      render: (v: number) => v?.toFixed(2),
    },
    {
      title: "换手率%",
      dataIndex: "turnover_rate",
      key: "turnover_rate",
      width: 80,
      render: (v: number) => v?.toFixed(2),
    },
    {
      title: "尾盘强度",
      dataIndex: "late_strength",
      key: "late_strength",
      width: 80,
      render: (v: number) => v?.toFixed(2),
    },
    {
      title: "评分",
      dataIndex: "score",
      key: "score",
      width: 70,
      sorter: (a: any, b: any) => a.score - b.score,
      render: (v: number) => <Text strong>{v?.toFixed(1)}</Text>,
    },
    {
      title: "近月回测",
      key: "backtest",
      width: 140,
      sorter: (a: any, b: any) => (a.backtest_score ?? 0) - (b.backtest_score ?? 0),
      render: (_: any, r: any) => {
        const trades = r.backtest_total_trades ?? 0;
        if (!trades) return <Text type="secondary">无样本</Text>;
        return (
          <Space direction="vertical" size={0}>
            <Text strong type={r.backtest_avg_return > 0 ? "danger" : "success"}>
              {r.backtest_avg_return > 0 ? "+" : ""}
              {formatPct(r.backtest_avg_return)}
            </Text>
            <Text type="secondary">
              胜率 {formatWinRate(r.backtest_win_rate)} / {trades}笔
            </Text>
          </Space>
        );
      },
    },
    {
      title: "回测分",
      dataIndex: "backtest_score",
      key: "backtest_score",
      width: 80,
      sorter: (a: any, b: any) => (a.backtest_score ?? 0) - (b.backtest_score ?? 0),
      render: (v: number) => (typeof v === "number" && v > 0 ? <Text strong>{v.toFixed(1)}</Text> : "-"),
    },
    {
      title: "信号",
      dataIndex: "signal_strength",
      key: "signal_strength",
      width: 60,
      render: (v: string) => (
        <Tag color={v === "强" ? "red" : v === "中" ? "orange" : "default"}>{v}</Tag>
      ),
    },
    {
      title: "目标价",
      dataIndex: "target_price",
      key: "target_price",
      width: 80,
      render: (v: number) => <Text type="danger">{v?.toFixed(2)}</Text>,
    },
    {
      title: "止损价",
      dataIndex: "stop_loss_price",
      key: "stop_loss_price",
      width: 80,
      render: (v: number) => <Text type="success">{v?.toFixed(2)}</Text>,
    },
  ];

  // --- Stats from latest results ---
  const strongCount = results.filter((r) => r.signal_strength === "强").length;
  const mediumCount = results.filter((r) => r.signal_strength === "中").length;
  const reasonLabels: Record<string, string> = {
    change_pct: "涨幅区间",
    volume_ratio: "量比",
    moving_average: "均线",
    late_strength: "尾盘强度",
    turnover_rate: "换手率",
  };
  const diagnostics = runInfo?.diagnostics;
  const marketCoverage = diagnostics?.market_coverage;
  const reasonSummary = diagnostics?.filter_reasons
    ? Object.entries(diagnostics.filter_reasons)
        .sort((a: any, b: any) => Number(b[1]) - Number(a[1]))
        .map(([key, value]) => `${reasonLabels[key] ?? key} ${value}`)
        .join("，")
    : "";

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <Title level={3} style={{ margin: 0 }}>
          尾盘选股
        </Title>
        <Space>
          <DatePicker
            value={selectedDate}
            onChange={handleDateChange}
            placeholder="选择日期"
            allowClear
          />
          <Button
            icon={<ReloadOutlined />}
            loading={collecting}
            disabled={screening}
            onClick={handleCollectFullMarket}
          >
            采集全市场行情
          </Button>
          <Button
            type="primary"
            icon={<ReloadOutlined />}
            loading={screening}
            disabled={collecting}
            onClick={handleRunScreen}
          >
            执行选股
          </Button>
          <Button icon={<ExperimentOutlined />} onClick={() => setBacktestVisible(true)}>
            回测
          </Button>
          <Button icon={<SettingOutlined />} onClick={handleOpenConfig}>
            配置
          </Button>
        </Space>
      </div>

      {/* 统计卡片 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={4}>
          <Card size="small">
            <Statistic title="选出股票" value={results.length} suffix="只" />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic title="强信号" value={strongCount} valueStyle={{ color: "#cf1322" }} />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic title="中信号" value={mediumCount} valueStyle={{ color: "#d46b08" }} />
          </Card>
        </Col>
        {latestBacktest && (
          <>
            <Col span={4}>
              <Card size="small">
                <Statistic
                  title="历史胜率"
                  value={(latestBacktest.win_rate * 100).toFixed(1)}
                  suffix="%"
                  valueStyle={{ color: latestBacktest.win_rate > 0.5 ? "#3f8600" : "#cf1322" }}
                />
              </Card>
            </Col>
            <Col span={4}>
              <Card size="small">
                <Statistic
                  title="平均收益"
                  value={latestBacktest.avg_return?.toFixed(2)}
                  suffix="%"
                  prefix={latestBacktest.avg_return > 0 ? <RiseOutlined /> : <FallOutlined />}
                  valueStyle={{ color: latestBacktest.avg_return > 0 ? "#3f8600" : "#cf1322" }}
                />
              </Card>
            </Col>
            <Col span={4}>
              <Card size="small">
                <Statistic
                  title="盈亏比"
                  value={latestBacktest.profit_loss_ratio?.toFixed(2)}
                />
              </Card>
            </Col>
          </>
        )}
      </Row>

      {diagnostics && (
        <Alert
          style={{ marginBottom: 16 }}
          type={runInfo.count > 0 ? "info" : "warning"}
          showIcon
          message={`实际执行交易日 ${runInfo.trade_date ?? "-"}，基础候选 ${diagnostics.candidate_count ?? 0} 只，通过 ${diagnostics.passed_count ?? 0} 只`}
          description={
            <Space direction="vertical" size={4}>
              {marketCoverage && (
                <Text>
                  行情覆盖：{marketCoverage.kline_stock_count}/{marketCoverage.total_stock_count} 只
                  （{marketCoverage.coverage_pct}%）
                </Text>
              )}
              {marketCoverage?.field_coverage && (
                <Text type="secondary">
                  字段覆盖：成交量 {marketCoverage.field_coverage.volume_count}
                  （{marketCoverage.field_coverage.volume_pct ?? "-"}%），成交额{" "}
                  {marketCoverage.field_coverage.amount_count}
                  （{marketCoverage.field_coverage.amount_pct ?? "-"}%），换手率{" "}
                  {marketCoverage.field_coverage.turnover_rate_count}
                  （{marketCoverage.field_coverage.turnover_rate_pct ?? "-"}%）
                </Text>
              )}
              {marketCoverage?.stock_field_coverage && (
                <Text type="secondary">
                  基础字段：市值 {marketCoverage.stock_field_coverage.market_cap_count}，上市日期{" "}
                  {marketCoverage.stock_field_coverage.listed_date_count}
                </Text>
              )}
              {reasonSummary && <Text>过滤原因统计：{reasonSummary}</Text>}
              {(diagnostics.data_gaps ?? []).map((item: string) => (
                <Text key={item} type="secondary">{item}</Text>
              ))}
              {diagnostics.action_required === "collect_full_market" && (
                <Button size="small" loading={collecting} onClick={handleCollectFullMarket}>
                  采集全市场行情后重跑
                </Button>
              )}
            </Space>
          }
        />
      )}

      {/* 选股结果表格 */}
      <Card>
        <Table
          dataSource={results}
          columns={columns}
          rowKey={(r) => `${r.code}-${r.trade_date}`}
          loading={loading}
          size="small"
          pagination={{ pageSize: 20, showSizeChanger: true }}
          locale={{ emptyText: <Empty description="暂无选股结果，点击「执行选股」开始" /> }}
          expandable={{
            expandedRowRender: (record) => (
              <Descriptions size="small" column={1} style={{ marginLeft: 48 }}>
                <Descriptions.Item label="操作建议">
                  <Text>{record.suggestion}</Text>
                </Descriptions.Item>
                <Descriptions.Item label="近月回测">
                  <Text>
                    {record.backtest_start_date ?? "-"} ~ {record.backtest_end_date ?? "-"}，
                    样本 {record.backtest_total_trades ?? 0} 笔，胜率{" "}
                    {formatWinRate(record.backtest_win_rate)}，平均收益{" "}
                    {formatPct(record.backtest_avg_return)}，最大回撤{" "}
                    {formatPct(record.backtest_max_drawdown)}，盈亏比{" "}
                    {typeof record.backtest_profit_loss_ratio === "number"
                      ? record.backtest_profit_loss_ratio.toFixed(2)
                      : "-"}
                  </Text>
                </Descriptions.Item>
                <Descriptions.Item label="行情快照">
                  <Text>
                    {record.data_mode === "intraday" ? "盘中实时" : record.data_mode || "存量数据"}，
                    来源 {record.quote_source ?? "-"}，时间 {formatQuoteTime(record.quote_time)}
                  </Text>
                </Descriptions.Item>
              </Descriptions>
            ),
          }}
        />
      </Card>

      {/* 配置弹窗 */}
      <Modal
        title="尾盘选股参数配置"
        open={configVisible}
        onOk={handleSaveConfig}
        onCancel={() => setConfigVisible(false)}
        width={640}
      >
        <Tabs
          items={[
            {
              key: "screen",
              label: "选股条件",
              children: (
                <Row gutter={[16, 12]}>
                  <Col span={12}>
                    <Text type="secondary">最低涨幅%</Text>
                    <InputNumber
                      style={{ width: "100%" }}
                      value={config.min_change_pct}
                      onChange={(v) => setConfig({ ...config, min_change_pct: v })}
                    />
                  </Col>
                  <Col span={12}>
                    <Text type="secondary">最高涨幅%</Text>
                    <InputNumber
                      style={{ width: "100%" }}
                      value={config.max_change_pct}
                      onChange={(v) => setConfig({ ...config, max_change_pct: v })}
                    />
                  </Col>
                  <Col span={12}>
                    <Text type="secondary">最低量比</Text>
                    <InputNumber
                      style={{ width: "100%" }}
                      step={0.1}
                      value={config.volume_ratio_min}
                      onChange={(v) => setConfig({ ...config, volume_ratio_min: v })}
                    />
                  </Col>
                  <Col span={12}>
                    <Text type="secondary">均量天数</Text>
                    <InputNumber
                      style={{ width: "100%" }}
                      value={config.volume_avg_days}
                      onChange={(v) => setConfig({ ...config, volume_avg_days: v })}
                    />
                  </Col>
                  <Col span={12}>
                    <Text type="secondary">最低换手率%</Text>
                    <InputNumber
                      style={{ width: "100%" }}
                      value={config.min_turnover_rate}
                      onChange={(v) => setConfig({ ...config, min_turnover_rate: v })}
                    />
                  </Col>
                  <Col span={12}>
                    <Text type="secondary">最高换手率%</Text>
                    <InputNumber
                      style={{ width: "100%" }}
                      value={config.max_turnover_rate}
                      onChange={(v) => setConfig({ ...config, max_turnover_rate: v })}
                    />
                  </Col>
                  <Col span={12}>
                    <Text type="secondary">尾盘强度阈值</Text>
                    <InputNumber
                      style={{ width: "100%" }}
                      step={0.05}
                      value={config.late_strength_min}
                      onChange={(v) => setConfig({ ...config, late_strength_min: v })}
                    />
                  </Col>
                  <Col span={12}>
                    <Text type="secondary">最低市值(亿)</Text>
                    <InputNumber
                      style={{ width: "100%" }}
                      value={config.min_market_cap}
                      onChange={(v) => setConfig({ ...config, min_market_cap: v })}
                    />
                  </Col>
                  <Col span={12}>
                    <Text type="secondary">最低上市天数</Text>
                    <InputNumber
                      style={{ width: "100%" }}
                      min={0}
                      value={config.min_listed_days}
                      onChange={(v) => setConfig({ ...config, min_listed_days: v })}
                    />
                  </Col>
                  <Col span={12}>
                    <Text type="secondary">短期均线</Text>
                    <InputNumber
                      style={{ width: "100%" }}
                      min={1}
                      value={config.ma_short}
                      disabled={!config.price_above_ma}
                      onChange={(v) => setConfig({ ...config, ma_short: v })}
                    />
                  </Col>
                  <Col span={12}>
                    <Text type="secondary">长期均线</Text>
                    <InputNumber
                      style={{ width: "100%" }}
                      min={1}
                      value={config.ma_long}
                      disabled={!config.price_above_ma}
                      onChange={(v) => setConfig({ ...config, ma_long: v })}
                    />
                  </Col>
                  <Col span={12}>
                    <Space>
                      <Text type="secondary">排除ST</Text>
                      <Switch
                        checked={config.exclude_st}
                        onChange={(v) => setConfig({ ...config, exclude_st: v })}
                      />
                    </Space>
                  </Col>
                  <Col span={12}>
                    <Space>
                      <Text type="secondary">价格需在均线上方</Text>
                      <Switch
                        checked={config.price_above_ma}
                        onChange={(v) => setConfig({ ...config, price_above_ma: v })}
                      />
                    </Space>
                  </Col>
                </Row>
              ),
            },
            {
              key: "trade",
              label: "交易参数",
              children: (
                <Row gutter={[16, 12]}>
                  <Col span={8}>
                    <Text type="secondary">止盈%</Text>
                    <InputNumber
                      style={{ width: "100%" }}
                      step={0.5}
                      value={config.take_profit_pct}
                      onChange={(v) => setConfig({ ...config, take_profit_pct: v })}
                    />
                  </Col>
                  <Col span={8}>
                    <Text type="secondary">止损%</Text>
                    <InputNumber
                      style={{ width: "100%" }}
                      step={0.5}
                      value={config.stop_loss_pct}
                      onChange={(v) => setConfig({ ...config, stop_loss_pct: v })}
                    />
                  </Col>
                  <Col span={8}>
                    <Text type="secondary">最大持有天数</Text>
                    <InputNumber
                      style={{ width: "100%" }}
                      min={1}
                      max={10}
                      value={config.max_hold_days}
                      onChange={(v) => setConfig({ ...config, max_hold_days: v })}
                    />
                  </Col>
                  <Col span={8}>
                    <Text type="secondary">排序回测天数</Text>
                    <InputNumber
                      style={{ width: "100%" }}
                      min={5}
                      max={120}
                      value={config.backtest_lookback_days}
                      onChange={(v) => setConfig({ ...config, backtest_lookback_days: v })}
                    />
                  </Col>
                </Row>
              ),
            },
            {
              key: "score",
              label: "评分权重",
              children: (
                <Row gutter={[16, 12]}>
                  <Col span={8}>
                    <Text type="secondary">涨幅权重</Text>
                    <InputNumber
                      style={{ width: "100%" }}
                      min={0}
                      step={0.05}
                      value={config.weight_change_pct}
                      onChange={(v) => setConfig({ ...config, weight_change_pct: v })}
                    />
                  </Col>
                  <Col span={8}>
                    <Text type="secondary">量比权重</Text>
                    <InputNumber
                      style={{ width: "100%" }}
                      min={0}
                      step={0.05}
                      value={config.weight_volume_ratio}
                      onChange={(v) => setConfig({ ...config, weight_volume_ratio: v })}
                    />
                  </Col>
                  <Col span={8}>
                    <Text type="secondary">尾盘强度权重</Text>
                    <InputNumber
                      style={{ width: "100%" }}
                      min={0}
                      step={0.05}
                      value={config.weight_late_strength}
                      onChange={(v) => setConfig({ ...config, weight_late_strength: v })}
                    />
                  </Col>
                  <Col span={8}>
                    <Text type="secondary">换手率权重</Text>
                    <InputNumber
                      style={{ width: "100%" }}
                      min={0}
                      step={0.05}
                      value={config.weight_turnover}
                      onChange={(v) => setConfig({ ...config, weight_turnover: v })}
                    />
                  </Col>
                  <Col span={8}>
                    <Text type="secondary">主力资金权重</Text>
                    <InputNumber
                      style={{ width: "100%" }}
                      min={0}
                      step={0.05}
                      value={config.weight_main_flow}
                      onChange={(v) => setConfig({ ...config, weight_main_flow: v })}
                    />
                  </Col>
                </Row>
              ),
            },
          ]}
        />
      </Modal>

      {/* 回测弹窗 */}
      <Modal
        title="尾盘选股策略回测"
        open={backtestVisible}
        onCancel={() => setBacktestVisible(false)}
        footer={null}
        width={600}
      >
        <Form layout="vertical" onFinish={handleRunBacktest}>
          <Form.Item
            name="range"
            label="回测区间"
            rules={[{ required: true, message: "请选择回测区间" }]}
          >
            <RangePicker style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={backtesting} block>
              开始回测
            </Button>
          </Form.Item>
        </Form>

        {backtestResults.length > 0 && (
          <div style={{ marginTop: 16 }}>
            <Title level={5}>历史回测记录</Title>
            <Table
              dataSource={backtestResults}
              rowKey="task_id"
              size="small"
              pagination={false}
              columns={[
                {
                  title: "区间",
                  render: (_: any, r: any) => `${r.start_date} ~ ${r.end_date}`,
                },
                {
                  title: "交易数",
                  dataIndex: "total_trades",
                },
                {
                  title: "胜率",
                  dataIndex: "win_rate",
                  render: (v: number) => `${(v * 100).toFixed(1)}%`,
                },
                {
                  title: "平均收益",
                  dataIndex: "avg_return",
                  render: (v: number) => `${v?.toFixed(2)}%`,
                },
                {
                  title: "盈亏比",
                  dataIndex: "profit_loss_ratio",
                  render: (v: number) => v?.toFixed(2),
                },
              ]}
            />
          </div>
        )}
      </Modal>
    </div>
  );
}
