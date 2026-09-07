"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { setAuth, getUser } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin123");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (typeof window !== "undefined" && getUser()) {
    router.push("/");
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const resp = await fetch(`${API}/api/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (!resp.ok) {
        const body = await resp.json();
        throw new Error(body.detail || "登录失败");
      }
      const data = await resp.json();
      setAuth(data.access_token, data.user);
      router.push("/");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <main style={{
      minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center",
      background: "#f5f7fa",
    }}>
      <form onSubmit={submit} style={{
        background: "#fff", padding: 32, borderRadius: 8, width: 360,
        boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
      }}>
        <h1 style={{ margin: "0 0 24px", fontSize: 20, color: "#1f3a68" }}>
          Temu 工作流 · 登录
        </h1>

        <label style={{ display: "block", marginBottom: 12 }}>
          <div style={{ fontSize: 13, color: "#666", marginBottom: 4 }}>用户名</div>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            style={{
              width: "100%", padding: 8, fontSize: 14,
              border: "1px solid #d1d5db", borderRadius: 4, boxSizing: "border-box",
            }}
          />
        </label>

        <label style={{ display: "block", marginBottom: 16 }}>
          <div style={{ fontSize: 13, color: "#666", marginBottom: 4 }}>密码</div>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            style={{
              width: "100%", padding: 8, fontSize: 14,
              border: "1px solid #d1d5db", borderRadius: 4, boxSizing: "border-box",
            }}
          />
        </label>

        {error && (
          <div style={{
            marginBottom: 12, padding: 8, background: "#fef2f2",
            color: "#dc2626", fontSize: 12, borderRadius: 4,
          }}>
            {error}
          </div>
        )}

        <button type="submit" disabled={loading} style={{
          width: "100%", padding: 10, fontSize: 14, fontWeight: 600,
          background: loading ? "#9ca3af" : "#1f3a68",
          color: "#fff", border: "none", borderRadius: 4,
          cursor: loading ? "not-allowed" : "pointer",
        }}>
          {loading ? "登录中…" : "登录"}
        </button>

        <div style={{
          marginTop: 16, padding: 12, background: "#f9fafb",
          borderRadius: 4, fontSize: 12, color: "#666",
        }}>
          <strong>测试账号</strong>（默认密码均为 <code>admin123</code>）：
          <ul style={{ margin: "8px 0 0", paddingLeft: 20 }}>
            <li>admin — 系统管理员</li>
            <li>operator — 选品运营</li>
            <li>reviewer — 上品审核员</li>
            <li>publisher — 发布操作员</li>
          </ul>
        </div>
      </form>
    </main>
  );
}