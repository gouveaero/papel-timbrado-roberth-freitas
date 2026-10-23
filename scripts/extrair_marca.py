#!/usr/bin/env python3
"""
Levanta a marca de um escritório a partir do site e grava um brand.json de
rascunho, com tudo o que precisa de confirmação marcado em "_confirmar".

    python3 extrair_marca.py <url do site> <pasta_marca>

O que busca (no HTML e nos bundles JS/CSS que ele carrega, inclusive SPA
como Lovable/Vite):
  - candidatos a logo (arquivos com logo/brand/marca no nome, favicon, og:image),
    baixados para <pasta_marca>/_site/
  - variáveis de cor do CSS (hex, rgb, hsl "h s% l%", oklch) convertidas para hex
  - famílias do Google Fonts
  - e-mails, telefones, links de WhatsApp, endereço e números de OAB citados

Nada é decidido sozinho: o rascunho lista as opções e você escolhe.
Requer: Python 3.9+ (só biblioteca padrão).
"""
import colorsys
import json
import math
import os
import re
import sys
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"


def baixar(url, binario=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        dados = r.read()
    return dados if binario else dados.decode("utf-8", "replace")


def oklch_hex(L, C, h_deg):
    h = math.radians(h_deg)
    a, b = C * math.cos(h), C * math.sin(h)
    l_, m_, s_ = L + 0.3963377774 * a + 0.2158037573 * b, L - 0.1055613458 * a - 0.0638541728 * b, L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    rgb = (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
           -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
           -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)
    enc = lambda x: round(max(0.0, min(1.0, 12.92 * x if x <= 0.0031308 else 1.055 * max(x, 0) ** (1 / 2.4) - 0.055)) * 255)
    return "#%02X%02X%02X" % tuple(enc(v) for v in rgb)


def cor_hex(val):
    v = val.strip().rstrip(";").strip()
    m = re.match(r"oklch\(\s*([\d.]+%?)\s+([\d.]+)\s+([\d.]+)", v, re.I)
    if m:
        L = float(m.group(1).rstrip("%")) / (100 if m.group(1).endswith("%") else 1)
        return oklch_hex(L, float(m.group(2)), float(m.group(3)))
    m = re.match(r"#([0-9a-f]{3}|[0-9a-f]{6})\b", v, re.I)
    if m:
        g = m.group(1)
        return "#" + ("".join(c * 2 for c in g) if len(g) == 3 else g).upper()
    m = re.match(r"rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)", v, re.I)
    if m:
        return "#%02X%02X%02X" % tuple(int(x) for x in m.groups())
    # shadcn/tailwind: "43 74% 53%" (hsl sem a função)
    m = re.match(r"(?:hsla?\()?\s*([\d.]+)(?:deg)?[\s,]+([\d.]+)%[\s,]+([\d.]+)%", v, re.I)
    if m:
        h, s, l = float(m.group(1)), float(m.group(2)), float(m.group(3))
        r, g, b = colorsys.hls_to_rgb(h / 360, l / 100, s / 100)
        return "#%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255))
    return None


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    url, pasta = sys.argv[1].rstrip("/") + "/", os.path.abspath(sys.argv[2])
    os.makedirs(os.path.join(pasta, "_site"), exist_ok=True)
    html = baixar(url)
    recursos = re.findall(r'(?:src|href)="([^"]+\.(?:js|css)[^"]*)"', html)
    textos = [html]
    for r in recursos:
        try:
            textos.append(baixar(urllib.parse.urljoin(url, r)))
        except Exception as e:  # noqa: BLE001
            print(f"aviso: não baixei {r}: {e}", file=sys.stderr)
    tudo = "\n".join(textos)
    # SPA (React/JSX): junta textos quebrados por <br> compilado ("...,",c.jsx("br",{}),"...")
    tudo_txt = re.sub(r'"\s*,\s*\w+\.jsxs?\("br",\{\}\)\s*,\s*"', " ", tudo)

    # cores: variáveis CSS
    cores = {}
    for nome, val in re.findall(r"(--[a-zA-Z0-9-]+)\s*:\s*([^;}{]+)", tudo):
        if any(x in nome for x in ("tw-", "radius", "shadow", "ring-offset-width", "font")):
            continue
        h = cor_hex(val)
        if h and nome not in cores:
            cores[nome] = h

    # cores com nome de marca primeiro (primary, accent, brand, gold...)
    marca = re.compile(r"primary|accent|brand|gold|dourad|secondary|dark|foreground|background", re.I)
    cores = dict(sorted(cores.items(), key=lambda kv: (not marca.search(kv[0]), kv[0])))

    fontes = sorted({f.replace("+", " ") for f in re.findall(r"family=([A-Za-z+]+)", tudo)})
    emails = sorted({e for e in re.findall(r"[\w.+-]+@[\w-]+\.[a-z.]{2,}", tudo, re.I)
                     if not re.search(r"seu@|example|exemplo|sentry|@\d|\.(png|jpg|svg|webp)$", e, re.I)})
    fones = sorted({t for t in re.findall(r"\(\d{2}\)\s?9?\s?\d{4}[-\s]?\d{4}", tudo) if "9999-9999" not in t and "99999-9999" not in t})
    whats = sorted(set(re.findall(r"wa\.me/\d+|api\.whatsapp\.com/send\?phone=\d+", tudo)))
    oabs = sorted(set(re.findall(r"OAB\s?/\s?[A-Z]{2}\s?(?:n[ºo°.]\s?)?[\d.]+", tudo)))
    enderecos = sorted({re.sub(r"\s+", " ", re.sub(r'[",]*c\.jsx\("br",\{\}\)[,"]*', " ", e)).strip(' ",')
                        for e in re.findall(r"(?:Av\.|Avenida|Rua|Alameda|Travessa|Rodovia)\s[^<>{}\[\]\"]{5,90}?(?:-\s?[A-Z]{2}\b|/[A-Z]{2}\b|CEP[\s\d.-]+)", tudo_txt)})

    logos, vistos = [], set()
    for u in re.findall(r"""["'(]((?:https?://|/)[^"'()\s]+\.(?:svg|png|webp|jpe?g|ico))""", tudo):
        if u in vistos or u.startswith("/src/"):
            continue
        vistos.add(u)
        if re.search(r"logo|brand|marca|favicon|icon|og|social", u, re.I):
            logos.append(urllib.parse.urljoin(url, u))
    baixados = []
    for u in logos[:12]:
        nome = re.sub(r"[^\w.-]", "_", os.path.basename(urllib.parse.urlparse(u).path))[:80]
        try:
            open(os.path.join(pasta, "_site", nome), "wb").write(baixar(u, binario=True))
            baixados.append(f"_site/{nome}")
        except Exception as e:  # noqa: BLE001
            print(f"aviso: não baixei {u}: {e}", file=sys.stderr)

    titulo = re.search(r"<title>(.*?)</title>", html, re.S)
    nome = (titulo.group(1).split("|")[0].strip() if titulo else "")
    rascunho = {
        "_origem": f"Rascunho gerado de {url}. Revise tudo em _confirmar antes de usar.",
        "_confirmar": {
            "logo_candidatos": baixados,
            "cores_do_site": cores,
            "fontes_do_site": fontes,
            "emails": emails, "telefones": fones, "whatsapp": whats,
            "enderecos": enderecos, "oab_citadas": oabs,
        },
        "nome": nome,
        "nome_curto": nome,
        "tagline": None,
        "site": urllib.parse.urlparse(url).netloc.replace("www.", ""),
        "contatos": {"endereco": enderecos[0] if enderecos else "", "telefone": fones[0] if fones else "",
                     "email": emails[0] if emails else ""},
        "oab": None,
        "cores": {"tinta": "#1A1A1A", "escuro": "#121212", "primaria": "", "primaria_escura": "",
                  "primaria_clara": "", "destaque": "", "cinza": "#5E5E5E", "linha": "#D9D9D9",
                  "fundo_suave": "#F7F7F5", "papel": "#FFFFFF"},
        "fontes": {"titulo": {"familia": fontes[0] if fontes else "", "regular": "", "bold": "", "italic": ""},
                   "texto": {"familia": fontes[1] if len(fontes) > 1 else "", "regular": "", "bold": "", "italic": ""}},
        "logo": {"papel": "", "papel_png": "", "escuro": "", "simbolo": "", "simbolo_png": "", "simbolo_escuro": ""},
        "documento": {"autor": nome, "local": "", "logo_mm": 50, "marca_dagua_pdf": True, "marca_dagua_docx": False},
    }
    saida = os.path.join(pasta, "brand.rascunho.json")
    json.dump(rascunho, open(saida, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"{saida}\n  {len(cores)} cores · fontes {fontes} · {len(baixados)} logo(s) baixada(s)")
    for k in ("emails", "telefones", "enderecos", "oab_citadas"):
        print(f"  {k}: {rascunho['_confirmar'][k]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
