#!/usr/bin/env python3
"""
Gera o PDF de apresentação no timbre do escritório: capa escura sangrada e
miolo com cabeçalho, rodapé, paginação e marca d'água em todas as páginas.

    python3 gerar_pdf.py <brand.json> <conteudo.md|conteudo.docx> <saida.pdf> [opções]

Entrada .md: o front matter vira capa e abertura
    ---
    tipo: Parecer
    title: Título do documento
    subtitle: Linha de apoio
    cliente: Nome do destinatário
    date: 23 de outubro de 2026
    local: Cidade/UF
    referencia: Parecer nº 01/2026
    cabecalho: Texto curto do cabeçalho (opcional)
    ---

Entrada .docx (escrito no timbrado do Word): título e subtítulo saem dos
estilos Title/Subtitle; os demais campos vêm das opções abaixo.

Opções:
    --sem-capa          começa direto no miolo, com o bloco de abertura
    --html <arquivo>    guarda o HTML intermediário (para ajuste fino)
    --tipo/--cliente/--data/--local/--referencia   sobrescrevem o front matter

Requer: pandoc no PATH e Playwright + Chromium.
"""
import argparse
import base64
import html
import os
import re
import string
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gerar_docx import carregar_brand, caminho, ler_front_matter  # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(AQUI, "..", "assets", "documento.html")

# geometria do miolo (mm)
GEO = {"m_top": 36, "m_right": 22, "m_bottom": 28, "m_left": 24,
       "fio_topo": 31, "logo_mm": 40, "fio_base": 271.5}


def data_uri(path, mime=None):
    mime = mime or {"svg": "image/svg+xml", "png": "image/png", "ttf": "font/ttf"}[path.rsplit(".", 1)[1].lower()]
    return f"data:{mime};base64," + base64.b64encode(open(path, "rb").read()).decode()


def svg_dimensionado(path, largura_mm):
    """Mesmo SVG com width/height em mm (para margin boxes do @page)."""
    src = open(path, encoding="utf-8").read()
    w, h = [float(v) for v in re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', src).groups()]
    alt = largura_mm * h / w
    src = re.sub(r'\swidth="[^"]+"', "", src, count=1)
    src = re.sub(r'\sheight="[^"]+"', "", src, count=1)
    src = src.replace("<svg ", f'<svg width="{largura_mm}mm" height="{alt:.2f}mm" ', 1)
    return "data:image/svg+xml;base64," + base64.b64encode(src.encode()).decode(), alt


def papel_svg(brand, marca_dagua=True):
    """Fundo A4 do miolo: fio do cabeçalho, fio do rodapé e marca d'água."""
    c = brand["cores"]
    x0, x1 = GEO["m_left"], 210 - GEO["m_right"]
    partes = [
        f'<rect x="{x0}" y="{GEO["fio_topo"]}" width="{x1 - x0}" height="0.25" fill="{c["primaria"]}"/>',
        f'<rect x="{x0}" y="{GEO["fio_base"]}" width="{x1 - x0}" height="0.18" fill="{c["primaria"]}"/>',
    ]
    if marca_dagua and brand["logo"].get("simbolo"):
        src = open(caminho(brand, brand["logo"]["simbolo"]), encoding="utf-8").read()
        w, h = [float(v) for v in re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', src).groups()]
        alt = 150
        larg = alt * w / h
        uri = "data:image/svg+xml;base64," + base64.b64encode(src.encode()).decode()
        partes.insert(0, f'<image href="{uri}" x="{210 - larg * 0.70:.1f}" y="{297 - alt - 10:.1f}" '
                         f'width="{larg:.1f}" height="{alt}" opacity="0.045"/>')
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="210mm" height="297mm" viewBox="0 0 210 297">'
           + "".join(partes) + "</svg>")
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def fontes_css(brand):
    regras = []
    pesos = {"regular": ("400", "normal"), "medium": ("500", "normal"), "semibold": ("600", "normal"),
             "bold": ("700", "normal"), "italic": ("400", "italic")}
    for papel in ("titulo", "texto"):
        f = brand["fontes"][papel]
        for k, (peso, estilo) in pesos.items():
            if f.get(k):
                regras.append(f'@font-face {{ font-family: "{f["familia"]}"; font-weight: {peso}; '
                              f'font-style: {estilo}; src: url("{data_uri(caminho(brand, f[k]))}") format("truetype"); }}')
    return "\n".join(regras)


def css_str(txt):
    return txt.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\A ")


def pandoc_html(path, formato):
    """Converte para fragmento HTML e devolve (meta, corpo)."""
    with tempfile.TemporaryDirectory() as td:
        tpl = os.path.join(td, "t.html")
        open(tpl, "w").write("<!--title-->$title$<!--/title-->\n<!--subtitle-->$subtitle$<!--/subtitle-->\n"
                             "<!--date-->$date$<!--/date-->\n<!--body-->$body$<!--/body-->\n")
        out = subprocess.run(["pandoc", path, "-f", formato, "-t", "html5", "--standalone",
                              "--template", tpl, "--wrap=none"],
                             check=True, capture_output=True, text=True).stdout
    def pega(k):
        m = re.search(rf"<!--{k}-->(.*?)<!--/{k}-->", out, re.S)
        return (m.group(1).strip() if m else "")
    meta = {k: html.unescape(re.sub(r"<[^>]+>", "", pega(k))) for k in ("title", "subtitle", "date")}
    return meta, pega("body")


def montar_html(brand, meta, corpo, com_capa=True):
    c = brand["cores"]
    contatos = brand.get("contatos", {})
    l1 = " · ".join(v for v in [contatos.get("endereco"), contatos.get("telefone")] if v)
    l2 = " · ".join(v for v in [contatos.get("email"), brand.get("site"), brand.get("oab")] if v)
    logo_cab, alt_logo = svg_dimensionado(caminho(brand, brand["logo"]["papel"]), GEO["logo_mm"])
    titulo = meta.get("title") or brand["nome"]
    tipo = meta.get("tipo", "")
    cab_txt = meta.get("cabecalho") or " · ".join(v for v in [tipo, titulo] if v)
    if len(cab_txt) > 70:
        cab_txt = cab_txt[:67].rstrip() + "…"
    local_data = ", ".join(v for v in [meta.get("local") or brand.get("documento", {}).get("local"), meta.get("date")] if v)
    esc = html.escape

    capa = ""
    if com_capa:
        dados = [(k, v) for k, v in [("Destinatário", meta.get("cliente")), ("Local e data", local_data),
                                     ("Referência", meta.get("referencia"))] if v]
        dados_html = "".join(f'<div><div class="k">{esc(k)}</div><div class="v">{esc(v)}</div></div>' for k, v in dados)
        simb = brand["logo"].get("simbolo_escuro") or brand["logo"].get("simbolo")
        capa = (
            '<section class="capa">'
            + (f'<img class="simbolo" src="{data_uri(caminho(brand, simb))}" alt="">' if simb else "")
            + f'<img class="logo" src="{data_uri(caminho(brand, brand["logo"]["escuro"]))}" alt="{esc(brand["nome"])}">'
            + '<div class="miolo">'
            + (f'<div class="rotulo">{esc(tipo)}</div><div class="fio"></div>' if tipo else "")
            + f'<h1>{esc(titulo)}</h1>'
            + (f'<div class="sub">{esc(meta["subtitle"])}</div>' if meta.get("subtitle") else "")
            + "</div>"
            + (f'<div class="dados">{dados_html}</div>' if dados else "")
            + f'<div class="contatos">{esc(l1)}<br>{esc(l2)}</div>'
            + "</section>")
        abertura = ""
    else:
        linha = "   ·   ".join(v for v in [f"Destinatário: {meta['cliente']}" if meta.get("cliente") else "",
                                           local_data, meta.get("referencia", "")] if v)
        abertura = ('<header class="abertura">'
                    + (f'<div class="rotulo">{esc(tipo)}</div>' if tipo else "")
                    + f"<h1>{esc(titulo)}</h1>"
                    + (f'<div class="sub">{esc(meta["subtitle"])}</div>' if meta.get("subtitle") else "")
                    + (f'<div class="meta">{esc(linha)}</div>' if linha else "")
                    + "</header>")

    vals = {
        "titulo_doc": esc(" · ".join(v for v in [titulo, brand["nome"]] if v)),
        "fontes": fontes_css(brand),
        "c_tinta": c["tinta"], "c_escuro": c["escuro"], "c_primaria": c["primaria"],
        "c_primaria_escura": c["primaria_escura"], "c_primaria_clara": c["primaria_clara"],
        "c_destaque": c["destaque"], "c_cinza": c["cinza"], "c_linha": c["linha"], "c_fundo_suave": c["fundo_suave"],
        "f_titulo": brand["fontes"]["titulo"]["familia"], "f_texto": brand["fontes"]["texto"]["familia"],
        "papel_svg": papel_svg(brand, brand.get("documento", {}).get("marca_dagua_pdf", True)),
        "logo_cabecalho": logo_cab,
        "cabecalho_txt": css_str(cab_txt.upper()),
        "rodape_txt": css_str(f"{l1}\n{l2}"),
        "m_top": GEO["m_top"], "m_right": GEO["m_right"], "m_bottom": GEO["m_bottom"], "m_left": GEO["m_left"],
        # logo termina 2,6 mm acima do fio; textos do rodapé começam 3 mm abaixo do fio
        "pad_logo": round(GEO["m_top"] - GEO["fio_topo"] + 2.6, 2),
        "pad_cab_txt": round(GEO["m_top"] - GEO["fio_topo"] + 3.0, 2),
        "pad_rod": round(GEO["fio_base"] - (297 - GEO["m_bottom"]) + 3.0, 2),
        "pad_num": round(GEO["fio_base"] - (297 - GEO["m_bottom"]) + 2.2, 2),
        "capa": capa, "abertura": abertura, "corpo": corpo,
    }
    tpl = string.Template(open(TEMPLATE, encoding="utf-8").read())
    return tpl.safe_substitute(vals)


def imprimir(html_txt, saida):
    from playwright.sync_api import sync_playwright
    with tempfile.TemporaryDirectory() as td:
        f = os.path.join(td, "doc.html")
        open(f, "w", encoding="utf-8").write(html_txt)
        with sync_playwright() as p:
            b = p.chromium.launch()
            page = b.new_page()
            page.goto(f"file://{f}", wait_until="load")
            page.evaluate("() => document.fonts.ready")
            page.wait_for_timeout(400)
            page.pdf(path=saida, prefer_css_page_size=True, print_background=True)
            b.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("brand")
    ap.add_argument("conteudo")
    ap.add_argument("saida")
    ap.add_argument("--sem-capa", action="store_true")
    ap.add_argument("--html")
    for k in ("tipo", "cliente", "data", "local", "referencia", "cabecalho"):
        ap.add_argument(f"--{k}")
    a = ap.parse_args()

    brand = carregar_brand(a.brand)
    meta = {}
    if a.conteudo.lower().endswith(".docx"):
        meta, corpo = pandoc_html(a.conteudo, "docx+styles")
        # o bloco de título do timbrado (Rótulo/Meta) não entra no corpo
        corpo = re.sub(r'<div data-custom-style="(Rótulo|Meta)">.*?</div>', "", corpo, flags=re.S)
    else:
        fm, corpo_md = ler_front_matter(open(a.conteudo, encoding="utf-8").read())
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "c.md")
            open(src, "w", encoding="utf-8").write(corpo_md)
            _, corpo = pandoc_html(src, "markdown")
        meta.update(fm)
    for k_cli, k_meta in (("tipo", "tipo"), ("cliente", "cliente"), ("data", "date"), ("local", "local"),
                          ("referencia", "referencia"), ("cabecalho", "cabecalho")):
        if getattr(a, k_cli):
            meta[k_meta] = getattr(a, k_cli)

    html_txt = montar_html(brand, meta, corpo, com_capa=not a.sem_capa)
    if a.html:
        open(a.html, "w", encoding="utf-8").write(html_txt)
    saida = os.path.abspath(a.saida)
    os.makedirs(os.path.dirname(saida), exist_ok=True)
    imprimir(html_txt, saida)
    print(saida)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
