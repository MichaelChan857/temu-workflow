"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import Link from "next/link";
import { fetchWithAuth, getUser, clearAuth, hasPermission } from "@/lib/auth";

const fetcher = (url: string) => fetchWithAuth(url).then(r => r.json());

interface Candidate {
  id: string;
  title: string;
  category: string | null;
  price: number | null;
  total_score: number | null;
  confidence: number | null;
  status: string;
  image_urls: string[];
  created_at: string;
}

export default function HomePage() {
  const router = useRouter();
  const [user, setUser] = useState<ReturnType<typeof getUser>>(null);

  useEffect(() => {
    const u = getUser();
    if (!u) {
      router.push("/login");
      return;
    }
    setUser(u);
  }, [router]);

  const { data, error, isLoading, mutate } = useSWR<Candidate[]>(
    user ? `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/v1/candidates?status=first_review&limit=50` : null,
    fetcher,
    { refreshInterval: 5000 }
  );

  const approve = async (id: string) => {
    const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    await fetchWithAuth(`${API}/api/v1/candidates/${id}/decision`, {
      method: "POST",
      body: JSON.stringify({ decision: "approve", comment: "通过" }),
    });
    mutate();
  };

  const reject = async (id: string) => {
    const reason = prompt("驳回原因：");
    if (!reason) return;
    const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    await fetchWithAuth(`${API}/api/v1/candidates/${id}/decision`, {
      method: "POST",
      body: JSON.stringify({ decision: "reject", reason_code: reason, comment: reason }),
    });
    mutate();
  };

  if (!user) return <div style={{ padding: 24 }}>跳转登录…</div>;

  const canReview = hasPermission("reviews.first");

  return (
    <main style={{ maxWidth: 1200, margin: "0 auto", padding: 24 }}>
      <header style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        marginBottom: 24,
      }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 24, color: "#1f3a68" }}>一审工作台</h1>
          <p style={{ margin: "8px 0 0", color: "#666", fontSize: 13 }}>
            Temu 自动选品与上品工作流 · MVP v0.2 · 仅显示「待一审」商品
          </p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <Link href="/alerts" style={{
            padding: "6px 12px", background: "#fef3c7", color: "#92400e",
            borderRadius: 4, textDecoration: "none", fontSize: 12,
          }}>告警中心</Link>
          <Link href="/scoring-config" style={{
            padding: "6px 12px", background: "#dbeafe", color: "#1e40af",
            borderRadius: 4, textDecoration: "none", fontSize: 12,
          }}>评分配置</Link>
          <Link href="/listings" style={{
            padding: "6px 12px", background: "#d1fae5", color: "#065f46",
            borderRadius: 4, textDecoration: "none", fontSize: 12,
          }}>资料编辑</Link>
          <span style={{
            padding: "4px 12px", background: "#1f3a68", color: "#fff",
            borderRadius: 16, fontSize: 12,
          }}>
            {user.display_name} · {ROLE_NAMES[user.role] || user.role}
          </span>
          <button onClick={() => {
            clearAuth();
            router.push("/login");
          }} style={{
            padding: "6px 12px", background: "#f3f4f6", color: "#374151",
            border: "1px solid #d1d5db", borderRadius: 4, fontSize: 12,
            cursor: "pointer",
          }}>登出</button>
        </div>
      </header>

      {!canReview && (
        <div style={{
          padding: 12, background: "#fef3c7", color: "#92400e",
          borderRadius: 4, marginBottom: 16, fontSize: 13,
        }}>
          您的角色（{user.role}）没有「一审」权限，以下商品仅供查看。
        </div>
      )}

      {isLoading && <div>加载中…</div>}
      {error && <div style={{ color: "red" }}>API 连接失败 — 请确认后端在 8000 端口运行</div>}
      {data && data.length === 0 && (
        <div style={{
          padding: 48, background: "#fff", borderRadius: 8,
          textAlign: "center", color: "#666",
        }}>
          暂无待审核商品。请先运行：
          <code style={{
            display: "block", marginTop: 12, padding: 12,
            background: "#1f2937", color: "#a7f3d0", borderRadius: 4,
          }}>
            docker compose exec backend python scripts/import_sample.py
          </code>
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 16 }}>
        {data?.map(c => (
          <article key={c.id} style={{
            background: "#fff", borderRadius: 8, padding: 16,
            boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
          }}>
            <div style={{
              width: "100%", height: 140, background: "#f3f4f6",
              borderRadius: 4, display: "flex", alignItems: "center",
              justifyContent: "center", color: "#999", marginBottom: 12,
              overflow: "hidden",
            }}>
              {c.image_urls[0] ? (
                <img src={c.image_urls[0]} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
              ) : "无图片"}
            </div>
            <h3 style={{
              margin: "0 0 8px", fontSize: 14, fontWeight: 600,
              overflow: "hidden", textOverflow: "ellipsis",
              display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
            }}>{c.title}</h3>
            <div style={{ fontSize: 12, color: "#666", marginBottom: 8 }}>
              {c.category && <span>{c.category} · </span>}
              {c.price != null && <span>${c.price}</span>}
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
              <span style={{
                padding: "2px 8px", background: "#1f3a68", color: "#fff",
                borderRadius: 4, fontSize: 12, fontWeight: 600,
              }}>
                {c.total_score?.toFixed(1) ?? "-"} 分
              </span>
              <span style={{ fontSize: 11, color: "#999" }}>
                置信度 {((c.confidence ?? 0) * 100).toFixed(0)}%
              </span>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <Link href={`/candidates/${c.id}`} style={{
                flex: 1, textAlign: "center", padding: "6px 12px",
                background: "#f3f4f6", color: "#1f3a68",
                borderRadius: 4, textDecoration: "none", fontSize: 13,
              }}>详情</Link>
              {canReview && (
                <>
                  <button onClick={() => approve(c.id)} style={{
                    flex: 1, padding: "6px 12px", background: "#10b981",
                    color: "#fff", border: "none", borderRadius: 4,
                    fontSize: 13, cursor: "pointer",
                  }}>通过</button>
                  <button onClick={() => reject(c.id)} style={{
                    flex: 1, padding: "6px 12px", background: "#ef4444",
                    color: "#fff", border: "none", borderRadius: 4,
                    fontSize: 13, cursor: "pointer",
                  }}>驳回</button>
                </>
              )}
            </div>
          </article>
        ))}
      </div>
    </main>
  );
}

const ROLE_NAMES: Record<string, string> = {
  admin: "系统管理员",
  operator: "选品运营",
  editor: "商品编辑",
  reviewer: "上品审核员",
  publisher: "发布操作员",
  readonly: "只读",
};