import "./globals.css";

export const metadata = {
  title: "Pheromone",
  description: "Agentic AI recall operating system"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

