"use client";

import { useState, useEffect, useCallback } from "react";
import { Row, Col, Card, Statistic, Table, Tag, Tabs, Typography, Spin, Empty, Alert, Space, Button, App, Progress } from "antd";
import {
  getAuditStats,
  getAgentLogs,
  getAutomationJobs,
  getAutomationRuns,
  getCollectLogs,
  getDataQuality,
  triggerAutomation,
} from "@/lib/api";

const { Title, Text } = Typography;

const stepLabels: Record<string, string> = {
  collect_focus_data: "采集重点股票",
  collect_fund_flow: "采集资金流",
  daily_scan: "每日信号扫描",
  chain_discovery: "产业链发现",
  weekly_analysis: "周度分析",
  risk_check: "风险检查",
};

const stepLabel = (name?: string) => (name ? stepLabels[name] || name : "-");

const statusTag = (status: string) => {
  const map: Record<string, string> = {
    completed: "success",
    success: "success",
    running: "processing",
    degraded: "warning",
    failed: "error",
    error: "error",
  };
  return <Tag color={map[status] || "default"}>{status}</Tag>;
};

const formatHeartbeat = (run: any) => {
  const value = run.heartbeat_at || run.updated_at;
  if (!value) return "-";
  const age = typeof run.heartbeat_age_seconds === "number" ? ` · ${run.heartbeat_age_seconds}s 前` : "";
  return `${String(value).slice(0, 19)}${age}`;
};

const runMessage = (run: any) => {
  if (run.status === "running" && run.current_step && run.current_step_index && run.total_steps) {
    return `正在执行 ${stepLabel(run.current_step)}（${run.current_step_index}/${run.total_steps}）`;
  }
  if (run.status === "running" && run.completed_steps && run.total_steps) {
    return `已完成 ${run.completed_steps}/${run.total_steps} 步，等待下一步`;
  }
  if (run.status === "completed") return "任务完成";
  if (run.status === "failed") return run.error_message || run.message || "任务失败";
  return run.message || (run.current_step ? `当前步骤: ${stepLabel(run.current_step)}` : "-");
};

export default function AuditPage() {
  const { message } = App.useApp();
  const [stats, setStats] = useState<any>({});
  const [dataQuality, setDataQuality] = useState<any>({});
  const [agentLogs, setAgentLogs] = useState<any[]>([]);
  const [collectLogs, setCollectLogs] = useState<any[]>([]);
  const [automationJobs, setAutomationJobs] = useState<any>({ jobs: [], workflows: [], running: [] });
  const [automationRuns, setAutomationRuns] = useState<any[]>([]);
  const [triggering, setTriggering] = useState<string>("");
  const [loading, setLoading] = useState(true);

  const loadData = useCallback((showLoading = false) => {
    if (showLoading) setLoading(true);
    Promise.all([
      getAuditStats().catch(() => ({})),
      getDataQuality().catch(() => ({})),
      getAgentLogs({ limit: 50 }).catch(() => []),
      getCollectLogs(50).catch(() => []),
      getAutomationJobs().catch(() => ({ jobs: [], workflows: [], running: [] })),
      getAutomationRuns({ limit: 50 }).catch(() => []),
    ]).then(([s, q, a, c, jobs, runs]) => {
      setStats(s);
      setDataQuality(q);
      setAgentLogs(a);
      setCollectLogs(c);
      setAutomationJobs(jobs);
      setAutomationRuns(runs);
      setLoading(false);
    });
  }, []);

  useEffect(() => {
    loadData(true);
  }, [loadData]);

  const runningRuns = automationRuns.filter((run) => run.status === "running");
  const runningDetails = runningRuns.length ? runningRuns : automationJobs.running_details || [];
  const hasRunningAutomation = runningRuns.length > 0 || (automationJobs.running || []).length > 0;

  useEffect(() => {
    if (!hasRunningAutomation) return;
    const timer = window.setInterval(() => loadData(false), 3000);
    return () => window.clearInterval(timer);
  }, [hasRunningAutomation, loadData]);

  const onTriggerAutomation = async (workflowType: string) => {
    setTriggering(workflowType);
    try {
      const result = await triggerAutomation({ workflow_type: workflowType });
      if (result.status === "already_running") {
        message.warning("该自动任务正在执行中");
      } else {
        message.success(`已启动任务: ${result.task_id}`);
      }
      loadData(false);
    } catch (e: any) {
      message.error(`启动失败: ${e.message}`);
    } finally {
      setTriggering("");
    }
  };

  if (loading) return <Spin size="large" style={{ display: "block", margin: "100px auto" }} />;

  const agentColumns = [
    { title: "状态", dataIndex: "status", key: "status", width: 100, render: statusTag },
    { title: "Agent", dataIndex: "agent_id", key: "agent_id", width: 160 },
    { title: "工作流", dataIndex: "workflow_type", key: "workflow_type", width: 140 },
    { title: "耗时(ms)", dataIndex: "duration_ms", key: "duration_ms", width: 100 },
    { title: "时间", dataIndex: "created_at", key: "created_at", width: 170, render: (v: string) => v?.slice(0, 19) || "-" },
  ];

  const collectColumns = [
    { title: "状态", dataIndex: "status", key: "status", width: 100, render: statusTag },
    { title: "数据源", dataIndex: "source", key: "source", width: 120 },
    { title: "任务类型", dataIndex: "task_type", key: "task_type", width: 140 },
    { title: "记录数", dataIndex: "records_count", key: "records_count", width: 80 },
    { title: "时间", dataIndex: "started_at", key: "started_at", width: 170, render: (v: string) => v?.slice(0, 19) || "-" },
  ];

  const jobColumns = [
    { title: "任务ID", dataIndex: "id", key: "id", width: 150 },
    { title: "任务名", dataIndex: "name", key: "name", width: 190 },
    { title: "下次执行", dataIndex: "next_run", key: "next_run", render: (v: string) => v || "-" },
  ];

  const runColumns = [
    { title: "状态", dataIndex: "status", key: "status", width: 100, render: statusTag },
    { title: "任务", dataIndex: "workflow_type", key: "workflow_type", width: 160 },
    { title: "触发", dataIndex: "trigger", key: "trigger", width: 90, render: (v: string) => v || "-" },
    {
      title: "进度",
      key: "progress",
      width: 260,
      render: (_: any, run: any) => {
        const percent = Number(run.progress_percent ?? (run.status === "completed" ? 100 : 0));
        const progressStatus = run.status === "failed" ? "exception" : run.status === "completed" ? "success" : "active";
        return (
          <Space direction="vertical" size={2} style={{ width: "100%" }}>
            <Progress percent={percent} size="small" status={progressStatus} />
            <Text type={run.stale ? "danger" : "secondary"} style={{ fontSize: 12 }}>
              {runMessage(run)}
            </Text>
          </Space>
        );
      },
    },
    {
      title: "步骤",
      dataIndex: "steps",
      key: "steps",
      render: (steps: any[]) => (
        <Space wrap size={4}>
          {(steps || []).map((step) => (
            <Tag key={step.name} color={step.status === "failed" ? "error" : step.status === "running" ? "processing" : "success"}>
              {stepLabel(step.name)}
            </Tag>
          ))}
        </Space>
      ),
    },
    { title: "耗时(ms)", dataIndex: "duration_ms", key: "duration_ms", width: 100, render: (v: number) => v ?? "-" },
    {
      title: "心跳",
      key: "heartbeat",
      width: 190,
      render: (_: any, run: any) => (
        <Text type={run.stale ? "danger" : "secondary"}>
          {run.status === "running" ? formatHeartbeat(run) : run.updated_at?.slice(0, 19) || "-"}
        </Text>
      ),
    },
    { title: "开始时间", dataIndex: "started_at", key: "started_at", width: 170, render: (v: string) => v?.slice(0, 19) || "-" },
    { title: "错误", dataIndex: "error_message", key: "error_message", width: 220, render: (v: string) => v || "-" },
  ];

  return (
    <div>
      <Title level={3}>审计中心</Title>
      <Text type="secondary">Agent 执行记录与数据采集日志</Text>

      <Row gutter={16} style={{ marginTop: 24 }}>
        <Col span={8}>
          <Card><Statistic title="Agent 总执行" value={stats.agent_executions ?? 0} /></Card>
        </Col>
        <Col span={8}>
          <Card><Statistic title="Agent 失败" value={stats.agent_failures ?? 0} styles={{ content: { color: "#cf1322" } }} /></Card>
        </Col>
        <Col span={8}>
          <Card><Statistic title="数据采集次数" value={stats.collect_runs ?? 0} /></Card>
        </Col>
      </Row>

      <Card title="数据质量" style={{ marginTop: 16 }}>
        {dataQuality.status === "blocked" ? (
          <Alert
            type="error"
            showIcon
            title="关键数据缺失"
            description={
              <Space orientation="vertical" size={4}>
                {(dataQuality.blocking_issues ?? []).map((item: string) => (
                  <Text key={item}>{item}</Text>
                ))}
              </Space>
            }
          />
        ) : (
          <Alert type="success" showIcon title="关键数据检查通过" />
        )}
        {(dataQuality.warnings ?? []).length > 0 && (
          <Alert
            type="warning"
            showIcon
            title="数据覆盖提醒"
            description={(dataQuality.warnings ?? []).join("；")}
            style={{ marginTop: 12 }}
          />
        )}
      </Card>

      <Tabs
        style={{ marginTop: 24 }}
        items={[
          {
            key: "automation",
            label: `自动任务 (${automationRuns.length})`,
            children: (
              <Space orientation="vertical" size={16} style={{ width: "100%" }}>
                <Card size="small" title="手动触发">
                  <Space wrap>
                    {(automationJobs.workflows || []).map((workflow: any) => (
                      <Button
                        key={workflow.workflow_type}
                        onClick={() => onTriggerAutomation(workflow.workflow_type)}
                        loading={triggering === workflow.workflow_type}
                      >
                        {workflow.name}
                      </Button>
                    ))}
                  </Space>
                  {hasRunningAutomation && (
                    <Alert
                      type="info"
                      showIcon
                      style={{ marginTop: 12 }}
                      title={`运行中: ${
                        (automationJobs.running || []).length
                          ? automationJobs.running.join(", ")
                          : runningRuns.map((run) => run.workflow_type).join(", ")
                      }`}
                      description={
                        <Space direction="vertical" size={4}>
                          {runningDetails.length ? (
                            runningDetails.map((run: any) => (
                              <Text key={run.task_id || run.workflow_type}>
                                {runMessage(run)}
                                {typeof run.progress_percent === "number" ? ` · ${run.progress_percent}%` : ""}
                                {run.stale ? " · 心跳超过 180 秒未更新" : ""}
                              </Text>
                            ))
                          ) : (
                            <Text>等待任务写入进度...</Text>
                          )}
                        </Space>
                      }
                    />
                  )}
                </Card>
                <Card size="small" title="定时计划">
                  <Table
                    dataSource={automationJobs.jobs || []}
                    columns={jobColumns}
                    rowKey="id"
                    pagination={false}
                    locale={{ emptyText: <Empty description="暂无定时任务" /> }}
                    scroll={{ x: 700 }}
                  />
                </Card>
                <Table
                  dataSource={automationRuns}
                  columns={runColumns}
                  rowKey="id"
                  pagination={{ pageSize: 10 }}
                  locale={{ emptyText: <Empty description="暂无自动任务执行记录" /> }}
                  scroll={{ x: 1300 }}
                />
              </Space>
            ),
          },
          {
            key: "agent",
            label: `Agent 日志 (${agentLogs.length})`,
            children: (
              <Table
                dataSource={agentLogs}
                columns={agentColumns}
                rowKey="id"
                pagination={{ pageSize: 15 }}
                locale={{ emptyText: <Empty description="暂无 Agent 执行记录" /> }}
                scroll={{ x: 700 }}
              />
            ),
          },
          {
            key: "collect",
            label: `采集日志 (${collectLogs.length})`,
            children: (
              <Table
                dataSource={collectLogs}
                columns={collectColumns}
                rowKey="id"
                pagination={{ pageSize: 15 }}
                locale={{ emptyText: <Empty description="暂无采集记录" /> }}
                scroll={{ x: 700 }}
              />
            ),
          },
        ]}
      />
    </div>
  );
}
