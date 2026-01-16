import type { ReactNode } from "react";
import "./globals.css";

export const metadata = {
  title: "Skills Coach",
  description: "Mental health skills coach demo"
};

export default function RootLayout({
  children
}: {
  children: ReactNode;
}) {
  return (
    <html lang="en">
      <body className="antialiased">
        {children}
      </body>
    </html>
  );
}
