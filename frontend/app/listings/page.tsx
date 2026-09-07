"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { fetchWithAuth, getUser, hasPermission } from "@/lib/auth";

interface Listing {
  id: string;
  title: string | null;
  status: string;
  version: number;
  is_ai_generated: boolean;
  has_snapshot: boolean;
  updated_at: string;
}

const fetcher = (url: string) => fetchWithAuth(url).then(r => r.json());

const STATUS_NAMES: Record<string, string> = {
  imported: "已导入", normalized: "已标准化", filtered_out: "已淘汰",
  scored: "已评分", first_review: "待一审", content_generating: "资料生成中",
  editing: "编辑中", second_review: "待二审", ready_to_publish: "待发布",
  publishing: "发布中", published: "已发布", publish_failed: "发布失败",
  rejected_1: "一审驳回", rejected_2: "二审驳回",
};

export default function ListingsIndex() {
  const [user, setUser] = useState<ReturnType<typeof getUser>>(null);

  useEffect(() => {
    const u = getUser();
    if (!u) { window.location.href = "/login"; return; }
    setUser(u);
  }, []);

  const { data: listings } = useSWR<Listing[]>(
    user ? `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/v1/listings?limit=50` : null,
    fetcher,
    { refreshInterval: 5000 }
  );

  if (!user) return <div>跳转登录…</div>;

  return (
    <main style={{ maxWidth: 1100, margin: "0 auto", padding: 24 }}>
      <h1 style={{ margin: "0 0 16px", fontSize: 22, color: "#1f3a68" }}>上品资料</h1>

      {!listings && <div>加载中…</div>}
      {listings && listings.length === 0 && (
        <div style={{ padding: 48, background: "#fff", borderRadius: 8, textAlign: "center", color: "#666" }}>
          暂无资料。先在一审工作台通过一个候选。
        </div>
      )}

      <div style={{ display: "grid", gap: 8 }}>
        {listings?.map(l => {
          const canEnterSecondReview = ["editing", "second_review"].includes(l.status) && !l.has_snapshot;
          const canPublish = l.status === "ready_to_publish" && l.has_snapshot;

          return (
            <div key={l.id} style={{
              background: "#fff", borderRadius: 6, padding: 16,
              boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
              display: "flex", justifyContent: "space-between", alignItems: "center",
            }}>
              <Link href={`/listings/${l.id}`} style={{
                flex: 1, textDecoration: "none", color: "inherit",
              }}>
                <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>
                  {l.title || "(无标题)"}
                </div>
                <div style={{ fontSize: 11, color: "#666" }}>
                  v{l.version} · {l.is_ai_generated ? "🤖 AI" : "✋ 人工"} · {STATUS_NAMES[l.status] || l.status}
                  {l.has_snapshot && <span style={{ color: "#f59e0b", marginLeft: 8 }}>🔒 已冻结</span>}
                </div>
                <div style={{ fontSize: 10, color: "#9ca3af", marginTop: 2 }}>
                  {new Date(l.updated_at).toLocaleString("zh-CN")}
                </div>
              </Link>

              <div style={{ display: "flex", gap: 8, marginLeft: 16 }}>
                {canEnterSecondReview && hasPermission("reviews.second") && (
                  <Link href={`/second-review/${l.id}`} style={{
                    padding: "6px 12px", background: "#1f3a68", color: "#fff",
                    borderRadius: 4, textDecoration: "none", fontSize: 12,
                  }}>进入二审 →</Link>
                )}
                {canPublish && hasPermission("publish.execute") && (
                  <Link href={`/publish/${l.id}`} style={{
                    padding: "6px 12px", background: "#10b981", color: "#fff",
                    borderRadius: 4, textDecoration: "none", fontSize: 12,
                  }}>发起发布 →</Link>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </main>
  );
}