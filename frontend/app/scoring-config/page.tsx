"use client";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { fetchWithAuth, getUser, hasPermission } from "@/lib/auth";

interface ConfigVersion {
  id: number;
  version: string;
  definition: { weights: Record<string, number>; thresholds: Record<string, number> };
  is_active: boolean;
  created_at: string;
  activated_at: string | null;
}

const DIM_NAMES: Record<string, string> = {
  heat: "市场热度",
  competition: "竞争程度",
  profit: "价格/利润",
  trend: "销量趋势",
  ratings: "评价质量",
  risk: "风险控制",
};

const fetcher = (url: string) => fetchWithAuth(url).then(r => r.json());

export default function ScoringConfigPage() {
  const [user, setUser] = useState<ReturnType<typeof getUser>>(null);
  const [draft, setDraft] = useState<Record<string, number>>({});
  const [draftThresholds, setDraftThresholds] = useState<Record<string, number>>({});
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    const u = getUser();
    if (!u) {
      window.location.href = "/login";
      return;
    }
    setUser(u);
  }, []);

  const { data: configs, mutate } = useSWR<ConfigVersion[]>(
    user ? `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/v1/scoring-config` : null,
    fetcher,
  );

  const { data: active } = useSWR<{ version: string; weights: Record<string, number>; thresholds: Record<string, number> }>(
    user ? `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/v1/scoring-config/active` : null,
    fetcher,
  );

  useEffect(() => {
    if (active) {
      setDraft(active.weights);
      setDraftThresholds(active.thresholds);
    }
  }, [active]);

  const sum = Object.values(draft).reduce((a, b) => a + b, 0);
  const valid = Math.abs(sum - 1.0) < 0.01;

  const save = async () => {
    if (!valid) {
      setMsg("权重总和必须 = 1.0");
      return;
    }
    setSaving(true);
    setMsg(null);
    try {
      const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const resp = await fetchWithAuth(`${API}/api/v1/scoring-config`, {
        method: "POST",
        body: JSON.stringify({
          weights: draft,
          thresholds: draftThresholds,
          name: `draft-${new Date().toISOString().slice(0, 16)}`,
        }),
      });
      if (!resp.ok) {
        const body = await resp.json();
        throw new Error(body.detail);
      }
      setMsg("已保存草稿，请点击右侧版本号的「激活」按钮");
      mutate();
    } catch (e: any) {
      setMsg(`保存失败：${e.message}`);
    } finally {
      setSaving(false);
    }
  };

  const activate = async (id: number) => {
    if (!confirm("激活后所有新评分将使用此配置。继续？")) return;
    const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    await fetchWithAuth(`${API}/api/v1/scoring-config/${id}/activate`, { method: "POST" });
    mutate();
  };

  if (!user) return <div>跳转登录…</div>;

  const canEdit = hasPermission("operator");

  return (
    <main style={{ maxWidth: 1200, margin: "0 auto", padding: 24 }}>
      <h1 style={{ margin: "0 0 8px", fontSize: 24, color: "#1f3a68" }}>评分模型配置</h1>
      <p style={{ margin: "0 0 24px", color: "#666", fontSize: 13 }}>
        PRD §8.3 默认权重；变更后所有新评分生效；版本可回滚
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 24 }}>
        <section style={{
          background: "#fff", borderRadius: 8, padding: 24,
          boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
        }}>
          <h2 style={{ margin: "0 0 16px", fontSize: 18 }}>编辑草稿</h2>

          <h3 style={{ margin: "16px 0 8px", fontSize: 14, color: "#1f3a68" }}>6 维权重（总和=1.0）</h3>
          {Object.keys(DIM_NAMES).map(dim => (
            <div key={dim} style={{ marginBottom: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 4 }}>
                <span>{DIM_NAMES[dim]}</span>
                <span style={{ fontWeight: 600 }}>
                  {((draft[dim] ?? 0) * 100).toFixed(0)}%
                </span>
              </div>
              <input
                type="range"
                min="0"
                max="0.5"
                step="0.01"
                disabled={!canEdit}
                value={draft[dim] ?? 0}
                onChange={e => setDraft({ ...draft, [dim]: parseFloat(e.target.value) })}
                style={{ width: "100%" }}
              />
            </div>
          ))}

          <div style={{
            marginTop: 8, padding: 8, borderRadius: 4,
            background: valid ? "#d1fae5" : "#fee2e2",
            color: valid ? "#065f46" : "#991b1b",
            fontSize: 12,
          }}>
            当前权重总和：<strong>{sum.toFixed(2)}</strong> {valid ? "✓ 合法" : "✗ 必须 = 1.00"}
          </div>

          <h3 style={{ margin: "16px 0 8px", fontSize: 14, color: "#1f3a68" }}>阈值</h3>
          {[
            { key: "min_recommend_score", label: "最低推荐分", min: 0, max: 100, step: 1 },
            { key: "category_quota_ratio", label: "类目占比上限", min: 0, max: 1, step: 0.05 },
            { key: "target_count", label: "每日推荐目标数", min: 1, max: 50, step: 1 },
          ].map(t => (
            <div key={t.key} style={{ marginBottom: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 4 }}>
                <span>{t.label}</span>
                <span style={{ fontWeight: 600 }}>{draftThresholds[t.key] ?? 0}</span>
              </div>
              <input
                type="range"
                min={t.min} max={t.max} step={t.step}
                disabled={!canEdit}
                value={draftThresholds[t.key] ?? 0}
                onChange={e => setDraftThresholds({ ...draftThresholds, [t.key]: parseFloat(e.target.value) })}
                style={{ width: "100%" }}
              />
            </div>
          ))}

          {msg && (
            <div style={{
              marginTop: 16, padding: 8, background: "#f3f4f6",
              borderRadius: 4, fontSize: 12,
            }}>
              {msg}
            </div>
          )}

          {canEdit && (
            <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
              <button onClick={save} disabled={saving || !valid} style={{
                padding: "10px 20px", background: valid ? "#1f3a68" : "#9ca3af",
                color: "#fff", border: "none", borderRadius: 4,
                fontSize: 14, fontWeight: 600,
                cursor: valid && !saving ? "pointer" : "not-allowed",
              }}>
                {saving ? "保存中…" : "保存为新版本（草稿）"}
              </button>
            </div>
          )}
        </section>

        <section>
          <h2 style={{ margin: "0 0 16px", fontSize: 18 }}>版本历史</h2>
          {!configs && <div>加载中…</div>}
          {configs?.map(v => (
            <article key={v.id} style={{
              background: "#fff", borderRadius: 8, padding: 12, marginBottom: 8,
              borderLeft: v.is_active ? "4px solid #10b981" : "4px solid #e5e7eb",
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <strong style={{ fontSize: 13 }}>{v.version}</strong>
                {v.is_active && (
                  <span style={{
                    padding: "2px 6px", background: "#d1fae5", color: "#065f46",
                    borderRadius: 4, fontSize: 10, fontWeight: 600,
                  }}>激活</span>
                )}
              </div>
              <div style={{ fontSize: 11, color: "#666", marginTop: 4 }}>
                {new Date(v.created_at).toLocaleString("zh-CN")}
              </div>
              {canEdit && !v.is_active && (
                <button onClick={() => activate(v.id)} style={{
                  marginTop: 8, padding: "4px 8px", fontSize: 11,
                  background: "#1f3a68", color: "#fff",
                  border: "none", borderRadius: 4, cursor: "pointer",
                }}>激活</button>
              )}
            </article>
          ))}
        </section>
      </div>
    </main>
  );
}