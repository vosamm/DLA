"use client";

import { useState } from "react";

interface CrawlResult {
  url: string;
  title: string;
  markdown: string;
}

export default function Home() {
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<CrawlResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setResult(null);
    setError(null);

    try {
      const res = await fetch("http://localhost:8000/api/crawl", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });

      const data = await res.json();

      if (!res.ok) {
        setError(data.detail ?? "알 수 없는 오류가 발생했습니다.");
        return;
      }

      setResult(data);
    } catch {
      setError("백엔드 서버에 연결할 수 없습니다.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main style={{ maxWidth: 800, margin: "0 auto", padding: "2rem" }}>
      <h1>URL 크롤링</h1>

      <form onSubmit={handleSubmit} style={{ display: "flex", gap: "0.5rem" }}>
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://example.com"
          required
          style={{ flex: 1, padding: "0.5rem" }}
        />
        <button type="submit" disabled={loading} style={{ padding: "0.5rem 1rem" }}>
          {loading ? "크롤링 중..." : "크롤링"}
        </button>
      </form>

      {error && (
        <p style={{ color: "red", marginTop: "1rem" }}>{error}</p>
      )}

      {result && (
        <div style={{ marginTop: "1.5rem" }}>
          <h2>{result.title || result.url}</h2>
          <pre
            style={{
              background: "#f4f4f4",
              padding: "1rem",
              overflowX: "auto",
              whiteSpace: "pre-wrap",
              maxHeight: "60vh",
            }}
          >
            {result.markdown}
          </pre>
        </div>
      )}
    </main>
  );
}
