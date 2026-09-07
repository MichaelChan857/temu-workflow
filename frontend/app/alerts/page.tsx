"use client";
import { useEffect, useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import { fetchWithAuth, getUser, hasPermission } from "@/lib/auth";

interface Alert {
  id: number;
  level: string;
  title: string;
  message: string;
  created_at: string;
}

const fetcher = (url: string) => fetchWithAuth(url).then(r => r.json());

export default function AlertsPage() {
  const [user, setUser] = useState<ReturnType<typeof getUser>>(null);

  useEffect(() => {
    const u = getUser();
    if (!u) {
      window.location.href = "/login";
      return;
    }
    setUser(u);
  }, []);

  const { data: alerts, mutate } = useSWR<Alert[]>(
    user ? `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/v1/alerts` : null,
    fetcher,
    { refreshInterval: 10000 }
  );

  const sendTestAlert = async () => {
    const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    await fetchWithAuth(`${API}/api/v1/alerts/send`, {
      method: "POST",
      body: JSON.stringify({
        level: "info",
        title: "测试告警",
        message: `来自 ${user?.username} 的手动触发（${new Date().toLocaleTimeString()}）`,
      }),
    });
    setTimeout(() => mutate(), 500);
  };

  if (!user) return <div>跳转登录…</div>;

  const counts = {
    error: alerts?.filter(a => a.level === "error").length ?? 0,
    warning: alerts?.filter(a => a.level === "warning").length ?? 0,
    info: alerts?.filter(a => a.level === "info").length ?? 0,
  };

  return (
    <main style={{ maxWidth: 1000, margin: "0 auto", padding: 24 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 24, color: "#1f3a68" }}>告警中心</h1>
          <p style={{ margin: "8px 0 0", color: "#666", fontSize: 13 }}>
            n8n 工作流推送 + 人工测试告警（轮询 10s）
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Link href="/" style={{
            padding: "8px 16px", background: "#f3f4f6", color: "#1f3a68",
            borderRadius: 4, textDecoration: "none", fontSize: 13,
          }}>← 一审工作台</Link>
          {hasPermission("alerts") && (
            <button onClick={sendTestAlert} style={{
              padding: "8px 16px", background: "#1f3a68", color: "#fff",
              border: "none", borderRadius: 4, fontSize: 13, cursor: "pointer",
            }}>发送测试告警</button>
          )}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginBottom: 24 }}>
        <StatCard label="错误" value={counts.error} color="#dc2626" />
        <StatCard label="警告" value={counts.warning} color="#f59e0b" />
        <StatCard label="信息" value={counts.info} color="#3b82f6" />
      </div>

      {!alerts && <div>加载中…</div>}
      {alerts && alerts.length === 0 && (
        <div style={{
          padding: 48, background: "#fff", borderRadius: 8, textAlign: "center", color: "#666",
        }}>
          暂无告警。点击" "发送测试告警" 试试。
        </div>
      )}

      <div style={{ display: "grid", gap: 8 }}>
        {alerts?.map(a => (
          <article key={a.id} style={{
            background: "#fff", borderRadius: 8, padding: 16,
            borderLeft: `4px solid ${LEVEL_COLOR[a.level] ?? "#9ca3af"}`,
            boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                  <span style={{
                    padding: "2px 8px", borderRadius: 4, fontSize: 11,
                    fontWeight: 600, color: "#fff",
                    background: LEVEL_COLOR[a.level] ?? "#9ca3af",
                  }}>
                    {a.level.toUpperCase()}
                  </span>
                  <strong style={{ fontSize: 14 }}>{a.title}</strong>
                </div>
                <div style={{ fontSize: 13, color: "#374151" }}>{a.message}</div>
              </div>
              <span style={{ fontSize: 11, color: "#9ca3af" }}>
                {new Date(a.created_at).toLocaleString("zh-CN")}
              </span>
            </div>
          </article>
        ))}
      </div>
    </main>
  );
}

const LEVEL_COLOR: Record<string, string> = {
  error: "#dc2626",
  warning: "#f59e0b",
  info: "#3b82f6",
};

function StatCard({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div style={{
      background: "#fff", borderRadius: 8, padding: 20,
      boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
    }}>
      <div style={{ fontSize: 12, color: "#666", marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 28, fontWeight: 600, color }}>{value}</div>
    </div>
  );
}