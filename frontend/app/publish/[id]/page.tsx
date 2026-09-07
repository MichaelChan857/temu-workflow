"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import useSWR from "swr";
import Link from "next/link";
import { fetchWithAuth, getUser, hasPermission } from "@/lib/auth";

interface Job {
  job_id: string;
  status: string;
  idempotency_key: string;
  platform_status: string | null;
  platform_product_id: string | null;
  platform_task_id: string | null;
  last_error: string | null;
  last_error_class: string | null;
  attempt_count: number;
  attempts: any[];
  submitted_at: string | null;
  published_at: string | null;
}

const fetcher = (url: string) => fetchWithAuth(url).then(r => r.json());

export default function PublishPage() {
  const { id } = useParams<{ id: string }>();  // listing_id
  const router = useRouter();
  const [user, setUser] = useState<ReturnType<typeof getUser>>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [currentJob, setCurrentJob] = useState<Job | null>(null);

  useEffect(() => {
    const u = getUser();
    if (!u) { router.push("/login"); return; }
    setUser(u);
  }, [router]);

  const { data: listing } = useSWR(
    user ? `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/v1/listings/${id}` : null,
    fetcher,
  );

  const startPublish = async () => {
    setBusy("start");
    setMsg(null);
    try {
      const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const resp = await fetchWithAuth(`${API}/api/v1/publish/start`, {
        method: "POST",
        body: JSON.stringify({ listing_id: id, auto_execute: true }),
      });
      if (!resp.ok) {
        const body = await resp.json();
        throw new Error(body.detail);
      }
      const data = await resp.json();
      setCurrentJob({ job_id: data.job_id, status: data.status, idempotency_key: data.idempotency_key,
        platform_status: null, platform_product_id: null, platform_task_id: null,
        last_error: null, last_error_class: null, attempt_count: 0, attempts: [],
        submitted_at: null, published_at: null });
      setMsg(`✅ 已发起：${data.message || "后台执行中"}`);
      pollJob(data.job_id);
    } catch (e: any) {
      setMsg(`❌ 发起失败：${e.message}`);
    } finally {
      setBusy(null);
    }
  };

  const pollJob = async (jobId: string) => {
    const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    for (let i = 0; i < 15; i++) {
      await new Promise(r => setTimeout(r, 2000));
      try {
        const resp = await fetchWithAuth(`${API}/api/v1/publish/jobs/${jobId}`);
        if (resp.ok) {
          const data = await resp.json();
          setCurrentJob(data);
          if (["published", "failed"].includes(data.platform_status) ||
              data.status === "failed") break;
        }
      } catch {}
    }
  };

  const retryJob = async () => {
    if (!currentJob) return;
    setBusy("retry");
    try {
      const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      await fetchWithAuth(`${API}/api/v1/publish/jobs/${currentJob.job_id}/retry`, { method: "POST" });
      pollJob(currentJob.job_id);
    } finally { setBusy(null); }
  };

  if (!user) return <div>跳转登录…</div>;

  return (
    <main style={{ maxWidth: 900, margin: "0 auto", padding: 24 }}>
      <Link href="/listings" style={{ color: "#1f3a68", textDecoration: "none", fontSize: 13 }}>
        ← 返回资料列表
      </Link>

      <h1 style={{ marginTop: 16, fontSize: 22, color: "#1f3a68" }}>发布到 Temu</h1>

      {!listing && <div>加载中…</div>}
      {listing && (
        <div style={{ background: "#fff", borderRadius: 8, padding: 20, marginTop: 12, boxShadow: "0 1px 3px rgba(0,0,0,0.1)" }}>
          <div style={{ marginBottom: 12 }}>
            <strong>{listing.title}</strong>
            <span style={{ marginLeft: 8, fontSize: 11, color: "#666" }}>
              v{listing.version} · 状态：{listing.status}
              {listing.has_snapshot && <span style={{ color: "#f59e0b", marginLeft: 8 }}>🔒 已冻结</span>}
            </span>
          </div>

          {!listing.has_snapshot && (
            <div style={{ padding: 8, background: "#fee2e2", color: "#991b1b", borderRadius: 4, fontSize: 12 }}>
              ⚠ listing 尚未通过二审，无发布快照。请先完成二审。
            </div>
          )}

          {listing.has_snapshot && !currentJob && hasPermission("publish.execute") && (
            <button onClick={startPublish} disabled={busy === "start"} style={{
              padding: "10px 20px", background: "#10b981", color: "#fff",
              border: "none", borderRadius: 4, fontSize: 14, fontWeight: 600,
              cursor: "pointer",
            }}>
              {busy === "start" ? "发起中…" : "🚀 发起发布"}
            </button>
          )}

          {msg && (
            <div style={{
              marginTop: 12, padding: 8, background: "#f0f9ff",
              color: "#1e40af", borderRadius: 4, fontSize: 12,
            }}>{msg}</div>
          )}

          {currentJob && (
            <div style={{ marginTop: 16, padding: 16, background: "#f9fafb", borderRadius: 6 }}>
              <h3 style={{ margin: "0 0 8px", fontSize: 14 }}>任务状态</h3>
              <KV k="Job ID" v={currentJob.job_id} mono />
              <KV k="状态" v={currentJob.status} badge />
              <KV k="平台状态" v={currentJob.platform_status || "—"} />
              <KV k="平台商品 ID" v={currentJob.platform_product_id} mono />
              <KV k="尝试次数" v={currentJob.attempt_count} />
              {currentJob.last_error && (
                <KV k="错误" v={`${currentJob.last_error_class || "?"}: ${currentJob.last_error}`} danger />
              )}
              {currentJob.platform_status === "failed" && hasPermission("publish.retry") && (
                <button onClick={retryJob} disabled={busy === "retry"} style={{
                  marginTop: 8, padding: "6px 12px", background: "#f59e0b",
                  color: "#fff", border: "none", borderRadius: 4,
                  fontSize: 12, cursor: "pointer",
                }}>↻ 重试</button>
              )}
            </div>
          )}
        </div>
      )}
    </main>
  );
}

function KV({ k, v, mono, badge, danger }: { k: string; v: any; mono?: boolean; badge?: boolean; danger?: boolean }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4, fontSize: 12 }}>
      <span style={{ color: "#6b7280" }}>{k}</span>
      <span style={{
        fontFamily: mono ? "monospace" : "inherit",
        color: danger ? "#dc2626" : "inherit",
        padding: badge ? "2px 6px" : 0,
        background: badge ? "#dbeafe" : "transparent",
        borderRadius: 3,
      }}>{v}</span>
    </div>
  );
}