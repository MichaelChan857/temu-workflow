export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body style={{
        margin: 0,
        fontFamily: '-apple-system, "Segoe UI", "Microsoft YaHei", sans-serif',
        background: "#f5f7fa",
        color: "#1f2937",
      }}>{children}</body>
    </html>
  );
}