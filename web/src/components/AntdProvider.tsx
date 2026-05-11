"use client";

import { ConfigProvider, App, Layout, Menu } from "antd";
import {
  HomeOutlined,
  ThunderboltOutlined,
  FileTextOutlined,
  LineChartOutlined,
  ApartmentOutlined,
  AuditOutlined,
  SettingOutlined,
  DatabaseOutlined,
  RadarChartOutlined,
  StockOutlined,
} from "@ant-design/icons";
import { usePathname, useRouter } from "next/navigation";
import zhCN from "antd/locale/zh_CN";
import type { ReactNode } from "react";

const { Header, Content } = Layout;

const NAV_ITEMS = [
  { key: "/advisor", label: "投研", icon: <RadarChartOutlined /> },
  { key: "/graph", label: "图谱", icon: <ApartmentOutlined /> },
  { key: "/signals", label: "信号中心", icon: <ThunderboltOutlined /> },
  { key: "/eod-screener", label: "尾盘选股", icon: <StockOutlined /> },
  { key: "/reports", label: "研报库", icon: <FileTextOutlined /> },
  { key: "/backtest", label: "回测", icon: <LineChartOutlined /> },
  { key: "/settings", label: "设置", icon: <SettingOutlined /> },
  {
    key: "management",
    label: "管理",
    icon: <DatabaseOutlined />,
    children: [
      { key: "/", label: "总览", icon: <HomeOutlined /> },
      { key: "/data", label: "数据", icon: <DatabaseOutlined /> },
      { key: "/audit", label: "审计", icon: <AuditOutlined /> },
    ],
  },
];

export default function AntdProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();

  const selectedKey = pathname.startsWith("/chain/")
    ? "/graph"
    : pathname.startsWith("/stock/")
      ? "/advisor"
      : pathname === "/"
        ? "/"
        : NAV_ITEMS.flatMap((n) => n.children ? n.children : [n]).find((n) => n.key !== "/" && pathname.startsWith(n.key))?.key ?? "/";

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: { colorPrimary: "#1677ff", borderRadius: 6 },
        components: { Layout: { headerBg: "#fff", bodyBg: "#f5f5f5" } },
      }}
    >
      <App>
        <Layout style={{ minHeight: "100vh" }}>
          <Header
            style={{
              display: "flex",
              alignItems: "center",
              borderBottom: "1px solid #f0f0f0",
              padding: "0 24px",
              position: "sticky",
              top: 0,
              zIndex: 100,
            }}
          >
            <div
              style={{ fontWeight: 700, fontSize: 18, marginRight: 40, cursor: "pointer", whiteSpace: "nowrap" }}
              onClick={() => router.push("/")}
            >
              Stock Hawk
            </div>
            <Menu
              mode="horizontal"
              selectedKeys={[selectedKey]}
              items={NAV_ITEMS}
              onClick={({ key }) => router.push(key)}
              style={{ flex: 1, border: "none" }}
            />
          </Header>
          <Content
            style={{
              padding: pathname.startsWith("/advisor") ? "12px 16px" : 24,
              maxWidth: pathname.startsWith("/advisor") ? 1760 : 1200,
              margin: "0 auto",
              width: "100%",
            }}
          >
            {children}
          </Content>
        </Layout>
      </App>
    </ConfigProvider>
  );
}
