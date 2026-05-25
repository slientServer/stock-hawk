"use client";

import { ConfigProvider, App, Layout, Menu } from "antd";
import {
  HomeOutlined,
  SettingOutlined,
  FundOutlined,
  RadarChartOutlined,
  RiseOutlined,
  ReadOutlined,
} from "@ant-design/icons";
import { usePathname, useRouter } from "next/navigation";
import zhCN from "antd/locale/zh_CN";
import type { ReactNode } from "react";

const { Header, Content } = Layout;

const NAV_ITEMS = [
  { key: "/", label: "工作台", icon: <HomeOutlined /> },
  { key: "/etf-analysis", label: "ETF分析", icon: <FundOutlined /> },
  { key: "/ten-bagger", label: "持续上涨", icon: <RiseOutlined /> },
  { key: "/pre-market", label: "盘前选股", icon: <RadarChartOutlined /> },
  { key: "/news-center", label: "资讯中心", icon: <ReadOutlined /> },
  { key: "/settings", label: "设置", icon: <SettingOutlined /> },
];

export default function AntdProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();

  const selectedKey = pathname === "/"
    ? "/"
    : NAV_ITEMS.find((n) => n.key !== "/" && pathname.startsWith(n.key))?.key ?? "/";
  const wideContent = pathname.startsWith("/etf-analysis") || pathname.startsWith("/news-center") || pathname.startsWith("/pre-market");

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
              padding: wideContent ? "12px 16px" : 24,
              maxWidth: wideContent ? 1760 : 1200,
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
