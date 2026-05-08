import type { Metadata } from "next";
import "./globals.css";
import AntdProvider from "@/components/AntdProvider";

export const metadata: Metadata = {
  title: "Stock Hawk - 智能量化分析系统",
  description: "A股产业链多维度信号分析",
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
