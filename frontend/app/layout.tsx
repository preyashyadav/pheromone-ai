import "./globals.css";
import { Providers } from "./providers";

export const metadata = {
  title: "Pheromone",
  description: "Agentic AI recall operating system"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-slate-950 text-slate-50 antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
