"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// Navegação com o link ativo destacado (o layout é server component; o estado de
// rota é client).
export default function Nav() {
  const rota = usePathname();
  const ativo = (href) =>
    href === "/" ? rota === "/" : rota.startsWith(href);
  return (
    <header className="navbar">
      <Link href="/" className="marca">◈ Smart Price Tracker</Link>
      <nav>
        <Link href="/" className={ativo("/") && !rota.startsWith("/cadastrar") && !rota.startsWith("/carteira") ? "ativo" : ""}>
          Produtos
        </Link>
        <Link href="/cadastrar" className={rota.startsWith("/cadastrar") ? "ativo" : ""}>
          Cadastrar
        </Link>
        <Link href="/carteira" className={rota.startsWith("/carteira") ? "ativo" : ""}>
          Carteira
        </Link>
      </nav>
    </header>
  );
}
