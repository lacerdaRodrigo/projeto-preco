import "./globals.css";
import { Sora, Source_Sans_3 } from "next/font/google";
import Nav from "./nav";

// Tipografia do design Clean: Sora (títulos/números) + Source Sans 3 (corpo).
const sora = Sora({ subsets: ["latin"], variable: "--fonte-titulo" });
const sourceSans = Source_Sans_3({ subsets: ["latin"], variable: "--fonte-corpo" });

export const metadata = {
  title: "Smart Price Tracker",
  description: "Comparador pessoal de preços em lojas online BR.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="pt-br">
      <body className={`${sora.variable} ${sourceSans.variable}`}>
        <Nav />
        {children}
      </body>
    </html>
  );
}
