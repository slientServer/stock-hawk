import type { Metadata } from "next";
import "./globals.css";
import AntdProvider from "@/components/AntdProvider";

export const metadata: Metadata = {
  title: "Stock Hawk",
  description: "ETF 分析、持续上涨筛选与财经资讯中心",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <AntdProvider>{children}</AntdProvider>
      </body>
    </html>
  );
}
