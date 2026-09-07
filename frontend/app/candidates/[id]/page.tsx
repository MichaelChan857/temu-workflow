"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { fetchWithAuth, getUser, hasPermission } from "@/lib/auth";

interface Candidate {
  id: string;
  title: string;
  description: string | null;
  category: string | null;
  price: number | null;
  cost: number | null;
  currency: string;
  total_score: number | null;
  confidence: number | null;
  dimension_scores: Record<string, number> | null;
  reason: string | null;
  risks: string[];
  data_gaps: string[];
  filter_hits: Array<{ rule_code: string; action: string; evidence: any }>;
  image_urls: string[];
  rights_confirmed: boolean;
  version: number;
}

export default function CandidateDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [user, setUser] = useState<ReturnType<typeof getUser>>(null);
  const [data, setData] = useState<Candidate | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const u = getUser();
    if (!u) {
      router.push("/login");
      return;
    }
    setUser(u);
    load();
  }, [id]);

  const load = async () => {
    const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    try {
      const resp = await fetchWithAuth(`${API}/api/v1/candidates/${id}`);
      if (!resp.ok) throw new Error("加载失败");
      setData(await resp.json());
    } catch (e: any) {
      setError(e.message);
    }
  };

  const submit = async (decision: string, reason_code?: string) => {
    const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    const url = `${API}/api/v1/candidates/${id}/decision?expected_version=${data?.version ?? ""}`;
    const resp = await fetchWithAuth(url, {
      method: "POST",
      body: JSON.stringify({ decision, reason_code, comment: reason_code }),
    });
    if (resp.status === 409) {
      alert("版本冲突：其他审核员已修改本页。请刷新后重试。");
      load();
      return;
    }
    if (!resp.ok) {
      const body = await resp.json();
      alert(`提交失败：${body.detail}`);
      return;
    }
    router.push("/");
  };

  if (!user) return <div style={{ padding: 24 }}>跳转登录…</div>;
  if (error) return <div style={{ padding: 24, color: "red" }}>{error}</div>;
  if (!data) return <div style={{ padding: 24 }}>加载中…</div>;

  const canReview = hasPermission("reviews.first");

  return (
    <main style={{ maxWidth: 960, margin: "0 auto", padding: 24 }}>
      <a href="/" style={{ color: "#1f3a68", textDecoration: "none", fontSize: 13 }}>← 返回列表</a>

      <div style={{
        background: "#fff", borderRadius: 8, padding: 24, marginTop: 16,
        boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
          <h1 style={{ margin: "0 0 12px", fontSize: 22 }}>{data.title}</h1>
          <span style={{
            padding: "4px 8px", background: "#f3f4f6", color: "#666",
            borderRadius: 4, fontSize: 11,
          }}>
            v{data.version}
          </span>
        </div>
        <div style={{ color: "#666", marginBottom: 16 }}>
          {data.category} · ${data.price}（成本 ${data.cost}） · {data.currency}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
          <div>
            <h3 style={{ margin: "0 0 8px", fontSize: 14, color: "#1f3a68" }}>商品图片</h3>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8 }}>
              {data.image_urls.map((url, i) => (
                <img key={i} src={url} alt="" style={{
                  width: "100%", height: 100, objectFit: "cover",
                  borderRadius: 4, background: "#f3f4f6",
                }} />
              ))}
            </div>
            {data.description && (
              <>
                <h3 style={{ margin: "16px 0 8px", fontSize: 14, color: "#1f3a68" }}>描述</h3>
                <p style={{ fontSize: 13, lineHeight: 1.6, color: "#374151" }}>{data.description}</p>
              </>
            )}
          </div>

          <div>
            <h3 style={{ margin: "0 0 8px", fontSize: 14, color: "#1f3a68" }}>评分详情</h3>
            <div style={{
              padding: 16, background: "#f9fafb", borderRadius: 4, marginBottom: 16,
            }}>
              <div style={{ fontSize: 24, fontWeight: 600, color: "#1f3a68" }}>
                {data.total_score?.toFixed(1) ?? "-"} <span style={{ fontSize: 14, color: "#666" }}>/ 100</span>
              </div>
              <div style={{ fontSize: 12, color: "#666", marginTop: 4 }}>
                置信度 {((data.confidence ?? 0) * 100).toFixed(0)}%
              </div>
              <div style={{ marginTop: 8, fontSize: 13 }}>{data.reason}</div>
            </div>

            {data.dimension_scores && (
              <div style={{ marginBottom: 16 }}>
                {Object.entries(data.dimension_scores).map(([k, v]) => (
                  <div key={k} style={{ marginBottom: 6 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
                      <span>{DIM_NAMES[k] || k}</span>
                      <span style={{ fontWeight: 600 }}>{v?.toFixed(1)}</span>
                    </div>
                    <div style={{ height: 4, background: "#e5e7eb", borderRadius: 2, marginTop: 2 }}>
                      <div style={{
                        width: `${v}%`, height: "100%",
                        background: v >= 75 ? "#10b981" : v >= 60 ? "#f59e0b" : "#ef4444",
                        borderRadius: 2,
                      }} />
                    </div>
                  </div>
                ))}
              </div>
            )}

            {data.risks.length > 0 && (
              <div style={{ marginBottom: 12 }}>
                <h4 style={{ margin: "0 0 4px", fontSize: 12, color: "#dc2626" }}>风险</h4>
                {data.risks.map((r, i) => <div key={i} style={{ fontSize: 12, color: "#dc2626" }}>• {r}</div>)}
              </div>
            )}

            {data.data_gaps.length > 0 && (
              <div style={{ marginBottom: 12 }}>
                <h4 style={{ margin: "0 0 4px", fontSize: 12, color: "#f59e0b" }}>数据缺失</h4>
                {data.data_gaps.map((g, i) => <div key={i} style={{ fontSize: 12, color: "#f59e0b" }}>• {g}</div>)}
              </div>
            )}
          </div>
        </div>

        {canReview ? (
          <div style={{
            display: "flex", gap: 12, marginTop: 24,
            paddingTop: 16, borderTop: "1px solid #e5e7eb",
          }}>
            <button onClick={() => submit("approve")} style={{
              flex: 1, padding: "10px 20px", background: "#10b981",
              color: "#fff", border: "none", borderRadius: 4,
              fontSize: 14, fontWeight: 600, cursor: "pointer",
            }}>通过 → 进入资料生成</button>
            <button onClick={() => {
              const r = prompt("退回原因：");
              if (r) submit("return", r);
            }} style={{
              flex: 1, padding: "10px 20px", background: "#f59e0b",
              color: "#fff", border: "none", borderRadius: 4,
              fontSize: 14, fontWeight: 600, cursor: "pointer",
            }}>退回补充数据</button>
            <button onClick={() => {
              const r = prompt("驳回原因：");
              if (r) submit("reject", r);
            }} style={{
              flex: 1, padding: "10px 20px", background: "#ef4444",
              color: "#fff", border: "none", borderRadius: 4,
              fontSize: 14, fontWeight: 600, cursor: "pointer",
            }}>驳回</button>
          </div>
        ) : (
          <div style={{
            marginTop: 24, padding: 12, background: "#fef3c7",
            color: "#92400e", borderRadius: 4, fontSize: 13,
          }}>
            您的角色无「一审」权限，仅可查看。
          </div>
        )}
      </div>
    </main>
  );
}

const DIM_NAMES: Record<string, string> = {
  heat: "市场热度",
  competition: "竞争程度",
  profit: "价格/利润",
  trend: "销量趋势",
  ratings: "评价质量",
  risk: "风险控制",
};