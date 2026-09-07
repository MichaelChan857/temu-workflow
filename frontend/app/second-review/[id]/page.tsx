"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import useSWR from "swr";
import Link from "next/link";
import { fetchWithAuth, getUser, hasPermission } from "@/lib/auth";

interface SecondReviewData {
  listing: {
    id: string;
    title: string | null;
    bullet_points: string[];
    description: string | null;
    category_id: string | null;
    attributes: Record<string, any>;
    image_urls: string[];
    status: string;
    version: number;
    is_ai_generated: boolean;
    has_snapshot: boolean;
  };
  first_review: {
    reviewer: string | null;
    reason_code: string | null;
    decided_at: string | null;
  } | null;
  checks: {
    can_pass: boolean;
    errors: string[];
    warnings: string[];
  };
}

const fetcher = (url: string) => fetchWithAuth(url).then(r => r.json());

export default function SecondReviewPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [user, setUser] = useState<ReturnType<typeof getUser>>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [confirmWarnings, setConfirmWarnings] = useState(false);

  useEffect(() => {
    const u = getUser();
    if (!u) { router.push("/login"); return; }
    setUser(u);
  }, [router]);

  const { data, error, mutate } = useSWR<SecondReviewData>(
    user ? `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/v1/listings/${id}/second-review` : null,
    fetcher,
  );

  const submit = async (decision: string) => {
    setBusy(decision);
    setMsg(null);
    let reason_code: string | undefined;
    if (decision !== "approve") {
      reason_code = prompt(`${decision === "return" ? "退回" : "驳回"}原因：`);
      if (!reason_code) { setBusy(null); return; }
    }

    try {
      const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const resp = await fetchWithAuth(`${API}/api/v1/listings/${id}/second-review`, {
        method: "POST",
        body: JSON.stringify({
          decision, reason_code,
          comment: reason_code,
          confirm_warnings: confirmWarnings,
        }),
      });
      if (!resp.ok) {
        const body = await resp.json();
        throw new Error(body.detail);
      }
      const result = await resp.json();
      setMsg(`✅ ${decision} 成功，listing 状态：${result.listing_status || result.status}`);

      if (decision === "approve" && result.listing_status === "ready_to_publish") {
        setTimeout(() => router.push(`/publish/${id}`), 1500);
      } else {
        mutate();
      }
    } catch (e: any) {
      setMsg(`❌ 失败：${e.message}`);
    } finally {
      setBusy(null);
    }
  };

  if (!user) return <div>跳转登录…</div>;
  if (error) return <div style={{ padding: 24, color: "red" }}>加载失败</div>;
  if (!data) return <div style={{ padding: 24 }}>加载中…</div>;

  const l = data.listing;
  const canReview = hasPermission("reviews.second") && !l.has_snapshot;
  const blocked = data.checks.errors.length > 0;
  const hasWarnings = data.checks.warnings.length > 0;

  return (
    <main style={{ maxWidth: 1000, margin: "0 auto", padding: 24 }}>
      <Link href="/listings" style={{ color: "#1f3a68", textDecoration: "none", fontSize: 13 }}>
        ← 返回资料列表
      </Link>

      <div style={{
        background: "#fff", borderRadius: 8, padding: 24, marginTop: 16,
        boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
      }}>
        <div style={{
          display: "flex", justifyContent: "space-between", alignItems: "start", marginBottom: 16,
        }}>
          <div>
            <h1 style={{ margin: "0 0 8px", fontSize: 22 }}>二审 · 上架决策</h1>
            <div style={{ fontSize: 12, color: "#666" }}>
              v{l.version} · {l.is_ai_generated ? "🤖 AI 生成" : "✋ 人工"} · 当前状态：{l.status}
            </div>
          </div>
          {l.has_snapshot && (
            <span style={{
              padding: "4px 12px", background: "#fbbf24", color: "#fff",
              borderRadius: 4, fontSize: 12, fontWeight: 600,
            }}>🔒 已冻结</span>
          )}
        </div>

        {/* 校验结果 */}
        <Section title="校验结果">
          {data.checks.errors.length === 0 && data.checks.warnings.length === 0 && (
            <div style={{ color: "#10b981", fontSize: 13 }}>✓ 全部通过</div>
          )}
          {data.checks.errors.map((e, i) => (
            <div key={i} style={{
              padding: 6, marginBottom: 4, background: "#fee2e2", color: "#991b1b",
              borderRadius: 4, fontSize: 12,
            }}>✗ {e}</div>
          ))}
          {data.checks.warnings.map((w, i) => (
            <div key={i} style={{
              padding: 6, marginBottom: 4, background: "#fef3c7", color: "#92400e",
              borderRadius: 4, fontSize: 12,
            }}>⚠ {w}</div>
          ))}
        </Section>

        {/* 一审信息 */}
        {data.first_review && (
          <Section title="一审记录">
            <div style={{ fontSize: 12, color: "#666" }}>
              {data.first_review.decided_at} · 原因：{data.first_review.reason_code || "—"}
            </div>
          </Section>
        )}

        {/* Listing 内容 */}
        <Section title="终稿预览">
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <div>
              <Label>标题</Label>
              <Value>{l.title || <span style={{ color: "#dc2626" }}>(缺失)</span>}</Value>

              <Label>描述</Label>
              <Value multiline>{l.description || <span style={{ color: "#dc2626" }}>(缺失)</span>}</Value>

              <Label>卖点</Label>
              <ul style={{ margin: 0, paddingLeft: 20, fontSize: 13 }}>
                {l.bullet_points.map((bp, i) => <li key={i}>{bp}</li>)}
                {l.bullet_points.length === 0 && <li style={{ color: "#dc2626" }}>(缺失)</li>}
              </ul>

              <Label>类目</Label>
              <Value>{l.category_id || <span style={{ color: "#dc2626" }}>(缺失)</span>}</Value>
            </div>

            <div>
              <Label>图片</Label>
              {l.image_urls.length === 0 ? (
                <Value><span style={{ color: "#dc2626" }}>(缺失)</span></Value>
              ) : (
                <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 4 }}>
                  {l.image_urls.map((url, i) => (
                    <img key={i} src={url} alt="" style={{
                      width: "100%", height: 80, objectFit: "cover",
                      borderRadius: 4, background: "#f3f4f6",
                    }} />
                  ))}
                </div>
              )}

              <Label>属性</Label>
              <pre style={{
                background: "#f9fafb", padding: 8, borderRadius: 4,
                fontSize: 11, fontFamily: "monospace", margin: 0,
              }}>
                {JSON.stringify(l.attributes, null, 2)}
              </pre>
            </div>
          </div>
        </Section>

        {/* 操作 */}
        {canReview ? (
          <>
            {hasWarnings && (
              <div style={{ marginTop: 16, padding: 8, background: "#fef3c7", borderRadius: 4 }}>
                <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>
                  <input
                    type="checkbox"
                    checked={confirmWarnings}
                    onChange={e => setConfirmWarnings(e.target.checked)}
                  />
                  我已知晓警告项（{data.checks.warnings.join("; ")}），仍确认通过
                </label>
              </div>
            )}

            {msg && (
              <div style={{
                marginTop: 12, padding: 8, background: "#f0f9ff",
                color: "#1e40af", borderRadius: 4, fontSize: 12,
              }}>{msg}</div>
            )}

            <div style={{
              display: "flex", gap: 12, marginTop: 16,
              paddingTop: 16, borderTop: "1px solid #e5e7eb",
            }}>
              <button
                onClick={() => submit("approve")}
                disabled={busy === "approve" || blocked || (hasWarnings && !confirmWarnings)}
                style={{
                  flex: 1, padding: "10px 20px",
                  background: (blocked || (hasWarnings && !confirmWarnings)) ? "#9ca3af" : "#10b981",
                  color: "#fff", border: "none", borderRadius: 4,
                  fontSize: 14, fontWeight: 600,
                  cursor: (blocked || (hasWarnings && !confirmWarnings)) ? "not-allowed" : "pointer",
                }}
              >
                {blocked ? "✗ 校验未通过" : "✓ 通过 → 进入发布"}
              </button>
              <button onClick={() => submit("return")} disabled={busy === "return"} style={{
                flex: 1, padding: "10px 20px", background: "#f59e0b",
                color: "#fff", border: "none", borderRadius: 4,
                fontSize: 14, fontWeight: 600, cursor: "pointer",
              }}>↩ 退回修改</button>
              <button onClick={() => submit("reject")} disabled={busy === "reject"} style={{
                flex: 1, padding: "10px 20px", background: "#ef4444",
                color: "#fff", border: "none", borderRadius: 4,
                fontSize: 14, fontWeight: 600, cursor: "pointer",
              }}>✗ 驳回</button>
            </div>
          </>
        ) : (
          <div style={{
            marginTop: 16, padding: 12, background: "#fef3c7",
            color: "#92400e", borderRadius: 4, fontSize: 13,
          }}>
            {l.has_snapshot ? "此 listing 已冻结（二审已通过），不可再次审核。" : "您的角色无「二审」权限。"}
          </div>
        )}
      </div>
    </main>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <h3 style={{ margin: "0 0 8px", fontSize: 13, color: "#1f3a68", fontWeight: 600 }}>{title}</h3>
      {children}
    </div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return <div style={{ fontSize: 11, color: "#6b7280", marginTop: 8, marginBottom: 2 }}>{children}</div>;
}

function Value({ children, multiline }: { children: React.ReactNode; multiline?: boolean }) {
  return (
    <div style={{
      padding: 8, background: "#f9fafb", borderRadius: 4, fontSize: 13,
      whiteSpace: multiline ? "pre-wrap" : "normal",
    }}>{children}</div>
  );
}