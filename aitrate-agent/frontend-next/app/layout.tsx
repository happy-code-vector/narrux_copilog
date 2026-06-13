import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'aiTrate Co-Pilot',
  description: 'Domain-specialised AI agent for trading strategies',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="flex h-screen overflow-hidden bg-[#fafaf7]">
        {children}
      </body>
    </html>
  );
}
