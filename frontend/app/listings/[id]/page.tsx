"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import useSWR from "swr";
import { fetchWithAuth, getUser, hasPermission } from "@/lib/auth";

interface Listing {
  id: string;
  candidate_id: string;
  shop_id: string;
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
}

interface Version {
  version: number;
  change_reason: string;
  change_note: string | null;
  created_by_name: string | null;
  created_at: string;
  is_frozen: boolean;
}

const fetcher = (url: string) => fetchWithAuth(url).then(r => r.json());

export default function ListingEditPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [user, setUser] = useState<ReturnType<typeof getUser>>(null);
  const [editForm, setEditForm] = useState<Partial<Listing>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    const u = getUser();
    if (!u) { router.push("/login"); return; }
    setUser(u);
  }, [router]);

  const { data: listing, mutate } = useSWR<Listing>(
    user ? `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/v1/listings/${id}` : null,
    fetcher,
  );

  const { data: versions } = useSWR<Version[]>(
    user ? `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/v1/listings/${id}/versions` : null,
    fetcher,
  );

  useEffect(() => {
    if (listing) setEditForm(listing);
  }, [listing]);

  const generate = async () => {
    if (!listing) return;
    setBusy("generate");
    setMsg(null);
    try {
      const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const resp = await fetchWithAuth(`${API}/api/v1/listings/generate`, {
        method: "POST",
        body: JSON.stringify({ candidate_id: listing.candidate_id }),
      });
      if (!resp.ok) {
        const body = await resp.json();
        throw new Error(body.detail);
      }
      const data = await resp.json();
      setMsg(`AI 生成成功 v${data.version}（消耗 ${data.tokens_in + data.tokens_out} tokens）`);
      mutate();
    } catch (e: any) {
      setMsg(`生成失败：${e.message}`);
    } finally {
      setBusy(null);
    }
  };

  const saveEdit = async () => {
    if (!listing) return;
    setBusy("edit");
    setMsg(null);
    try {
      const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const resp = await fetchWithAuth(`${API}/api/v1/listings/${id}`, {
        method: "PUT",
        body: JSON.stringify({
          title: editForm.title,
          bullet_points: editForm.bullet_points,
          description: editForm.description,
          category_id: editForm.category_id,
          attributes: editForm.attributes,
          change_note: "manual edit via UI",
        }),
      });
      if (!resp.ok) {
        const body = await resp.json();
        throw new Error(body.detail);
      }
      setMsg("已保存新版本");
      mutate();
    } catch (e: any) {
      setMsg(`保存失败：${e.message}`);
    } finally {
      setBusy(null);
    }
  };

  const rollback = async (targetVersion: number) => {
    if (!confirm(`回退到 v${targetVersion}？当前未保存的修改会丢失。`)) return;
    setBusy(`rollback-${targetVersion}`);
    try {
      const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const resp = await fetchWithAuth(`${API}/api/v1/listings/${id}/rollback/${targetVersion}`, {
        method: "POST",
      });
      if (!resp.ok) {
        const body = await resp.json();
        throw new Error(body.detail);
      }
      const data = await resp.json();
      setMsg(`已回退，新版本 v${data.new_version}`);
      mutate();
    } catch (e: any) {
      setMsg(`回退失败：${e.message}`);
    } finally {
      setBusy(null);
    }
  };

  if (!user) return <div>跳转登录…</div>;
  if (!listing) return <div>加载中…</div>;

  const canEdit = hasPermission("listings.edit") && !listing.has_snapshot;

  return (
    <main style={{ maxWidth: 1200, margin: "0 auto", padding: 24 }}>
      <a href="/" style={{ color: "#1f3a68", textDecoration: "none", fontSize: 13 }}>← 返回列表</a>

      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        marginTop: 16, marginBottom: 16,
      }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 22, color: "#1f3a68" }}>上品资料编辑</h1>
          <div style={{ marginTop: 4, fontSize: 12, color: "#666" }}>
            状态：<strong>{listing.status}</strong>
            {" · "}当前 v{listing.version}
            {" · "}{listing.is_ai_generated ? "🤖 AI 生成" : "✋ 人工编辑"}
            {listing.has_snapshot && (
              <span style={{ marginLeft: 8, padding: "2px 8px", background: "#fbbf24", color: "#fff", borderRadius: 4 }}>
                已冻结（二审后）
              </span>
            )}
          </div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          {hasPermission("listings.edit") && (
            <button onClick={generate} disabled={busy === "generate"} style={{
              padding: "8px 16px", background: "#1f3a68", color: "#fff",
              border: "none", borderRadius: 4, fontSize: 13, cursor: "pointer",
            }}>{busy === "generate" ? "生成中…" : "🤖 AI 生成"}</button>
          )}
          {canEdit && (
            <button onClick={saveEdit} disabled={busy === "edit"} style={{
              padding: "8px 16px", background: "#10b981", color: "#fff",
              border: "none", borderRadius: 4, fontSize: 13, cursor: "pointer",
            }}>{busy === "edit" ? "保存中…" : "💾 保存修改"}</button>
          )}
        </div>
      </div>

      {msg && (
        <div style={{
          marginBottom: 16, padding: 8, background: "#f0f9ff",
          color: "#1e40af", borderRadius: 4, fontSize: 12,
        }}>{msg}</div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 16 }}>
        <section style={{
          background: "#fff", borderRadius: 8, padding: 20,
          boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
        }}>
          <Field label="标题（≤200 字符）">
            <input
              type="text" disabled={!canEdit}
              value={editForm.title ?? ""}
              onChange={e => setEditForm({ ...editForm, title: e.target.value })}
              style={{ width: "100%", padding: 8, fontSize: 14, border: "1px solid #d1d5db", borderRadius: 4 }}
            />
          </Field>

          <Field label="卖点（每行一条，3-5 条）">
            <textarea
              disabled={!canEdit}
              value={(editForm.bullet_points ?? []).join("\n")}
              onChange={e => setEditForm({ ...editForm, bullet_points: e.target.value.split("\n").filter(Boolean) })}
              rows={4}
              style={{ width: "100%", padding: 8, fontSize: 13, border: "1px solid #d1d5db", borderRadius: 4, fontFamily: "inherit" }}
            />
          </Field>

          <Field label="描述">
            <textarea
              disabled={!canEdit}
              value={editForm.description ?? ""}
              onChange={e => setEditForm({ ...editForm, description: e.target.value })}
              rows={4}
              style={{ width: "100%", padding: 8, fontSize: 13, border: "1px solid #d1d5db", borderRadius: 4, fontFamily: "inherit" }}
            />
          </Field>

          <Field label="类目 ID">
            <input
              type="text" disabled={!canEdit}
              value={editForm.category_id ?? ""}
              onChange={e => setEditForm({ ...editForm, category_id: e.target.value })}
              style={{ width: "100%", padding: 8, fontSize: 13, border: "1px solid #d1d5db", borderRadius: 4 }}
            />
          </Field>

          <Field label="属性（JSON）">
            <textarea
              disabled={!canEdit}
              value={JSON.stringify(editForm.attributes ?? {}, null, 2)}
              onChange={e => {
                try {
                  setEditForm({ ...editForm, attributes: JSON.parse(e.target.value) });
                } catch {
                  /* 解析中，忽略 */
                }
              }}
              rows={4}
              style={{
                width: "100%", padding: 8, fontSize: 11, border: "1px solid #d1d5db",
                borderRadius: 4, fontFamily: "monospace",
              }}
            />
          </Field>
        </section>

        <aside>
          <h3 style={{ margin: "0 0 8px", fontSize: 14, color: "#1f3a68" }}>版本历史</h3>
          <div style={{ display: "grid", gap: 6 }}>
            {!versions && <div>加载中…</div>}
            {versions?.map(v => (
              <article key={v.version} style={{
                background: "#fff", borderRadius: 6, padding: 10,
                borderLeft: v.is_frozen ? "3px solid #f59e0b" : "3px solid #e5e7eb",
                boxShadow: "0 1px 2px rgba(0,0,0,0.05)",
              }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <strong style={{ fontSize: 12 }}>v{v.version}</strong>
                  <span style={{ fontSize: 10, color: "#666" }}>{REASONS[v.change_reason] || v.change_reason}</span>
                </div>
                <div style={{ fontSize: 10, color: "#666", marginTop: 2 }}>
                  {v.created_by_name} · {new Date(v.created_at).toLocaleString("zh-CN")}
                </div>
                {v.change_note && (
                  <div style={{ fontSize: 10, color: "#374151", marginTop: 2 }}>{v.change_note}</div>
                )}
                {canEdit && v.version !== listing.version && !v.is_frozen && (
                  <button
                    onClick={() => rollback(v.version)}
                    disabled={busy === `rollback-${v.version}`}
                    style={{
                      marginTop: 6, padding: "4px 8px", fontSize: 10,
                      background: "#fef3c7", color: "#92400e",
                      border: "none", borderRadius: 4, cursor: "pointer",
                    }}>
                    回退到此版本
                  </button>
                )}
              </article>
            ))}
          </div>
        </aside>
      </div>
    </main>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <label style={{
        display: "block", fontSize: 12, fontWeight: 600,
        color: "#374151", marginBottom: 4,
      }}>{label}</label>
      {children}
    </div>
  );
}

const REASONS: Record<string, string> = {
  ai_generated: "🤖 AI 生成",
  human_edit: "✋ 人工",
  rollback: "↩️ 回退",
};