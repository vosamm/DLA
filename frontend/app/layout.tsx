import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "DLA - 웹 크롤링 RAG 챗봇",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
