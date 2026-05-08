import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  transpilePackages: ["antd", "@ant-design/icons"],
  turbopack: {
    root: process.cwd(),
  },
};

export default nextConfig;
