"use client";

import { useState, useEffect } from "react";
import { Space, Tag, Typography, Spin, Empty, Card } from "antd";
import { useRouter } from "next/navigation";
import { getReports } from "@/lib/api";

const { Title, Text, Paragraph } = Typography;

export default function ReportsPage() {
  const router = useRouter();
  const [reports, setReports] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getReports(30)
      .then(setReports)
      .catch(() => setReports([]))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Spin size="large" style={{ display: "block", margin: "100px auto" }} />;

  return (
    <div>
      <Title level={3}>研报库</Title>
      <Text type="secondary">Agent 分析报告输出</Text>

      {reports.length === 0 ? (
        <Empty description="暂无研报数据" style={{ marginTop: 48 }} />
      ) : (
        <Space orientation="vertical" size={12} style={{ marginTop: 16, width: "100%" }}>
          {reports.map((r: any, index: number) => (
            <Card
              key={r.id ?? r.task_id ?? index}
              style={{ width: "100%" }}
              size="small"
              hoverable
              onClick={() => r.id && router.push(`/reports/${r.id}`)}
            >
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
                <span>
                  <Tag color="blue">{r.workflow_type}</Tag>
                  {r.agent_id && <Tag>{r.agent_id}</Tag>}
                </span>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {r.created_at?.slice(0, 19)} {r.duration_ms ? `· ${r.duration_ms}ms` : ""}
                </Text>
              </div>
              {r.output_text ? (
                <Paragraph
                  ellipsis={{ rows: 4, expandable: false }}
                  style={{ marginBottom: 0, whiteSpace: "pre-wrap", fontSize: 13 }}
                >
                  {r.output_text}
                </Paragraph>
              ) : (
                <Text type="secondary">无内容</Text>
              )}
            </Card>
          ))}
        </Space>
      )}
    </div>
  );
}
