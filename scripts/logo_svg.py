#!/usr/bin/env python3
"""
Monta a logo de um escritório em vetor: símbolo (SVG vetorizado) + linhas de
texto convertidas em curvas, com kerning real da fonte (HarfBuzz).

Saídas, para cada layout ("assinatura" = símbolo + texto, "simbolo" = só o
símbolo) e cada cor declarada no spec:
    logo-<layout>-<cor>.svg   vetor puro, sem fonte externa
    logo-<layout>-<cor>.png   raster transparente em alta (Chromium)

Uso:
    python3 logo_svg.py <logo-spec.json> <pasta_saida>

Spec (caminhos relativos ao próprio spec):
{
  "simbolo": {"svg": "simbolo.svg", "ignorar_fill": ["rgb(255,255,255)", "#fff"]},
  "altura_simbolo": 1000,
  "coluna_texto": {"recuo": 106},          # distância do símbolo até o texto
  "linhas": [
    {"texto": "NOME", "fonte": "fonts/X.ttf", "topo": 103, "altura_caixa": 331,
     "largura": 2233}                       # largura opcional: ajusta o tracking
  ],
  "margem": 20,
  "cores": {
    "dourado": {"gradiente": ["#B4850E", "#E0AE2E", "#F8E472", "#E0AE2E", "#A2802A"], "angulo": 35},
    "preto": {"solido": "#121212"}
  },
  "png_largura": 3000
}

Requer: fontTools, hb-shape (HarfBuzz) no PATH e Playwright + Chromium para os PNG.
"""
import base64
import json
import math
import os
import re
import subprocess
import sys

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.svgLib.path import parse_path
from fontTools.ttLib import TTFont


def _fmt(v):
    return f"{v:.2f}".rstrip("0").rstrip(".")


def ler_simbolo(svg_path, ignorar):
    """Devolve os atributos d dos paths do SVG, sem o retângulo de fundo."""
    src = open(svg_path, encoding="utf-8").read()
    ds = []
    for m in re.finditer(r"<path\b([^>]*)/?>", src):
        attrs = m.group(1)
        fill = re.search(r'fill="([^"]+)"', attrs)
        if fill and fill.group(1).replace(" ", "").lower() in ignorar:
            continue
        d = re.search(r'\sd="([^"]+)"', attrs)
        if d:
            ds.append(d.group(1))
    if not ds:
        raise SystemExit(f"nenhum path útil em {svg_path}")
    return ds


def desenhar_d(ds, pen):
    for d in ds:
        parse_path(d, pen)


def caixa_simbolo(ds):
    bp = BoundsPen(None)
    desenhar_d(ds, bp)
    return bp.bounds  # xmin, ymin, xmax, ymax (coordenadas do SVG, y para baixo)


def shape(font_path, texto):
    out = subprocess.run(
        ["hb-shape", "--output-format=json", "--no-glyph-names", font_path, texto],
        check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def linha_para_path(linha, base_dir, x0, topo):
    font_path = os.path.join(base_dir, linha["fonte"])
    font = TTFont(font_path)
    upm = font["head"].unitsPerEm
    cap = getattr(font["OS/2"], "sCapHeight", 0) or int(upm * 0.7)
    escala = linha["altura_caixa"] / cap
    glifos = shape(font_path, linha["texto"])
    ordem = font.getGlyphOrder()
    gs = font.getGlyphSet()
    natural = sum(g["ax"] for g in glifos) * escala
    # largura natural medida pela tinta, não pelo avanço (o último glifo tem folga à direita)
    tracking = linha.get("tracking", 0) * escala
    if linha.get("largura") and len(glifos) > 1:
        bp = BoundsPen(gs)
        x = 0
        for g in glifos:
            gs[ordem[g["g"]]].draw(TransformPen(bp, (1, 0, 0, 1, x + g["dx"], g["dy"])))
            x += g["ax"]
        tinta = (bp.bounds[2] - bp.bounds[0]) * escala
        tracking = (linha["largura"] - tinta) / (len(glifos) - 1)
    pen = SVGPathPen(gs, ntos=_fmt)
    baseline = topo + linha["altura_caixa"]
    x = x0
    primeiro_lsb = None
    for g in glifos:
        nome = ordem[g["g"]]
        if primeiro_lsb is None:
            bp = BoundsPen(gs)
            gs[nome].draw(bp)
            primeiro_lsb = (bp.bounds[0] if bp.bounds else 0) * escala
        gx = x - primeiro_lsb + g["dx"] * escala
        gs[nome].draw(TransformPen(pen, (escala, 0, 0, -escala, gx, baseline - g["dy"] * escala)))
        x += g["ax"] * escala + tracking
    return pen.getCommands(), {"natural": round(natural), "tracking": round(tracking, 2)}


def montar(spec_path):
    spec = json.load(open(spec_path, encoding="utf-8"))
    base = os.path.dirname(os.path.abspath(spec_path))
    sim = spec["simbolo"]
    ignorar = [c.replace(" ", "").lower() for c in sim.get("ignorar_fill", ["rgb(255,255,255)", "#fff", "#ffffff", "white"])]
    ds = ler_simbolo(os.path.join(base, sim["svg"]), ignorar)
    xmin, ymin, xmax, ymax = caixa_simbolo(ds)
    alt = spec.get("altura_simbolo", 1000)
    k = alt / (ymax - ymin)
    larg_sim = (xmax - xmin) * k
    margem = spec.get("margem", 20)

    # símbolo normalizado: canto superior esquerdo em (margem, margem)
    pen = SVGPathPen(None, ntos=_fmt)
    desenhar_d(ds, TransformPen(pen, (k, 0, 0, k, margem - xmin * k, margem - ymin * k)))
    simbolo_d = pen.getCommands()

    x_txt = margem + larg_sim + spec.get("coluna_texto", {}).get("recuo", 100)
    linhas_d, info = [], []
    largura_txt = 0
    for ln in spec.get("linhas", []):
        d, meta = linha_para_path(ln, base, x_txt, margem + ln["topo"])
        linhas_d.append(d)
        info.append({"texto": ln["texto"], **meta})
        bp = BoundsPen(None)
        parse_path(d, bp)
        largura_txt = max(largura_txt, bp.bounds[2])
    layouts = {
        "simbolo": {"w": larg_sim + 2 * margem, "h": alt + 2 * margem, "ds": [simbolo_d]},
    }
    if linhas_d:
        layouts["assinatura"] = {"w": largura_txt + margem, "h": alt + 2 * margem,
                                 "ds": [simbolo_d] + linhas_d}
    return spec, layouts, info


def svg_doc(layout, cor, nome):
    w, h = layout["w"], layout["h"]
    defs, fill = "", cor.get("solido", "#000")
    if "gradiente" in cor:
        ang = math.radians(cor.get("angulo", 35))
        x2, y2 = 0.5 + 0.5 * math.cos(ang), 0.5 + 0.5 * math.sin(ang)
        x1, y1 = 1 - x2, 1 - y2
        stops = cor["gradiente"]
        st = "".join(f'<stop offset="{i / (len(stops) - 1):.3f}" stop-color="{c}"/>' for i, c in enumerate(stops))
        defs = (f'<defs><linearGradient id="g-{nome}" gradientUnits="objectBoundingBox" '
                f'x1="{x1:.3f}" y1="{y1:.3f}" x2="{x2:.3f}" y2="{y2:.3f}">{st}</linearGradient></defs>')
        fill = f"url(#g-{nome})"
    corpo = "".join(f'<path d="{d}"/>' for d in layout["ds"])
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_fmt(w)} {_fmt(h)}" '
            f'width="{_fmt(w)}" height="{_fmt(h)}">{defs}<g fill="{fill}">{corpo}</g></svg>\n')


def exportar_png(svgs, largura):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(device_scale_factor=1)
        for svg_path in svgs:
            src = open(svg_path, encoding="utf-8").read()
            w, h = [float(v) for v in re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', src).groups()]
            alto = round(largura * h / w)
            page.set_viewport_size({"width": largura, "height": alto})
            # data URI: página about:blank não carrega file://
            uri = "data:image/svg+xml;base64," + base64.b64encode(src.encode()).decode()
            html = (f'<html><body style="margin:0;background:transparent">'
                    f'<img src="{uri}" style="display:block;width:{largura}px;height:{alto}px"></body></html>')
            page.set_content(html)
            page.wait_for_load_state("load")
            png = svg_path[:-4] + ".png"
            page.screenshot(path=png, omit_background=True, clip={"x": 0, "y": 0, "width": largura, "height": alto})
        b.close()


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    spec, layouts, info = montar(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    os.makedirs(out, exist_ok=True)
    feitos = []
    for lay_nome, lay in layouts.items():
        for cor_nome, cor in spec["cores"].items():
            p = os.path.join(out, f"logo-{lay_nome}-{cor_nome}.svg")
            open(p, "w", encoding="utf-8").write(svg_doc(lay, cor, f"{lay_nome}-{cor_nome}"))
            feitos.append(p)
    if spec.get("png_largura"):
        exportar_png(feitos, int(spec["png_largura"]))
    for i in info:
        print(f"  linha {i['texto']!r}: avanço natural {i['natural']}, tracking {i['tracking']}")
    print(f"{len(feitos)} SVG{' + PNG' if spec.get('png_largura') else ''} em {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
