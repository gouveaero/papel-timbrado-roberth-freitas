#!/usr/bin/env python3
"""
Gera o manual de marca do escritório (PDF A4 paisagem) a partir do brand.json.

    python3 gerar_manual.py <brand.json> <saida.pdf> [--html arquivo.html]

Páginas (as opcionais só entram se o bloco existir em brand.json → "manual"):
    capa · nota de reconstrução da logo (manual.nota) · o escritório (manual.sobre)
    · a marca · versões · proteção e tamanho mínimo · cores · tipografia
    · aplicações (manual.aplicacoes) · usos incorretos
    · presença digital (manual.presenca) · arquivos entregues (manual.arquivos)
    · contracapa

Campos de manual.* estão documentados em references/brand-json.md.
Requer: Pillow, Playwright + Chromium, pdftoppm (para aplicações vindas de PDF).
"""
import argparse
import base64
import html
import io
import os
import string
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gerar_docx import carregar_brand, caminho  # noqa: E402
from gerar_pdf import data_uri, fontes_css, imprimir  # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(AQUI, "..", "assets", "manual.html")
esc = html.escape


def png_uri(im):
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def jpg_uri(im, q=88):
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=q)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def logo(brand, chave, fallback=None):
    rel = brand["logo"].get(chave) or (brand["logo"].get(fallback) if fallback else None)
    return data_uri(caminho(brand, rel)) if rel else ""


def rgb_cmyk(h):
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    k = 1 - max(r, g, b) / 255
    if k >= 1:
        return (r, g, b), (0, 0, 0, 100)
    c, m, y = ((1 - v / 255 - k) / (1 - k) for v in (r, g, b))
    return (r, g, b), tuple(round(x * 100) for x in (c, m, y, k))


def rodape(brand, secao):
    return f'<div class="rodape"><span>{esc(brand["nome"])} · {esc(secao)}</span><span class="n"></span></div>'


def topo(olho, brand, escura=False):
    return (f'<div class="topo"><div class="olho">{esc(olho)}</div>'
            f'<div class="marca-topo">Manual de Marca</div></div>')


# ---------------------------------------------------------------- páginas


def pg_capa(brand, man):
    simb = logo(brand, "simbolo_escuro", "simbolo")
    return (f'<section class="pg escura capa">'
            + (f'<img class="simb" src="{simb}" alt="">' if simb else "")
            + f'<img class="logo" src="{logo(brand, "escuro")}" alt="{esc(brand["nome"])}">'
            + '<div class="titulo"><div class="olho">Identidade visual</div>'
            + '<h1>Manual de Marca</h1>'
            + f'<div class="ver">Versão {esc(man.get("versao", "1.0"))} · {esc(man.get("data", ""))}</div></div>'
            + '<div class="fio"></div></section>')


def recortes_antes_depois(brand, nota):
    from PIL import Image
    orig = Image.open(caminho(brand, nota["antes"])).convert("RGBA")
    novo_rel = brand["logo"].get("escuro_png") or brand["logo"]["escuro"].replace(".svg", ".png")
    novo = Image.open(caminho(brand, novo_rel)).convert("RGBA")
    def recorte(im, filtro):
        w, h = im.size
        c = im.crop((0, 0, int(w * nota.get("recorte", 0.30)), h))
        alvo_h = 1100
        c = c.resize((round(c.width * alvo_h / c.height), alvo_h), filtro)
        fundo = Image.new("RGBA", c.size, brand["cores"]["escuro"])
        fundo.alpha_composite(c)
        return fundo
    return jpg_uri(recorte(orig, Image.BICUBIC)), jpg_uri(recorte(novo, Image.LANCZOS))


def pg_nota(brand, man):
    nota = man["nota"]
    antes, depois = recortes_antes_depois(brand, nota)
    texto = "".join(f"<p>{esc(p)}</p>" for p in nota["paragrafos"])
    return (f'<section class="pg">{topo("Antes de começar", brand)}'
            f'<div class="cols c-58"><div><h2>{esc(nota["titulo"])}</h2>{texto}</div>'
            f'<div style="padding-top:2mm"><div class="cols c2" style="gap:5mm">'
            f'<div class="zoom"><img src="{antes}" alt=""><div class="leg">{esc(nota.get("legenda_antes", "Antes"))}</div></div>'
            f'<div class="zoom depois"><img src="{depois}" alt=""><div class="leg">{esc(nota.get("legenda_depois", "Depois"))}</div></div>'
            f'</div>'
            f'<div class="palco preto" style="height:46mm;margin-top:5mm"><img src="{logo(brand, "escuro")}" style="width:72%" alt=""></div>'
            f'</div></div>{rodape(brand, "Nota sobre a logo")}</section>')


def pg_sobre(brand, man):
    s = man["sobre"]
    par = "".join(f"<p>{esc(p)}</p>" for p in s.get("paragrafos", []))
    cit = s.get("citacao")
    cit_html = f'<div class="citacao">{esc(cit["texto"])}<span>{esc(cit["autor"])}</span></div>' if cit else ""
    valores = "".join(f'<div><b>{esc(v["nome"])}</b><span>{esc(v["texto"])}</span></div>' for v in s.get("valores", []))
    areas = "".join(f"<span>{esc(a)}</span>" for a in s.get("areas", []))
    voz = "".join(f"<li>{esc(v)}</li>" for v in s.get("voz", []))
    col_dir = ""
    if s.get("missao"):
        col_dir += f'<div class="caixa" style="margin-bottom:4mm"><div class="rot">Missão</div><p>{esc(s["missao"])}</p></div>'
    if s.get("visao"):
        col_dir += f'<div class="caixa"><div class="rot">Visão</div><p>{esc(s["visao"])}</p></div>'
    if valores:
        col_dir += f'<div style="margin-top:5mm"><div class="rot">Valores</div><div class="valores">{valores}</div></div>'
    if voz:
        col_dir += f'<div style="margin-top:5mm"><div class="rot">Como a marca fala</div><ul class="voz">{voz}</ul></div>'
    col_esq = (f'<h2>{esc(s.get("titulo", "O escritório"))}</h2>'
               + (f'<div class="lead">{esc(s["abertura"])}</div>' if s.get("abertura") else "")
               + par + cit_html
               + (f'<div class="rot" style="margin-top:4mm">Áreas de atuação</div><div class="tags">{areas}</div>' if areas else ""))
    fonte = f'<p class="pequeno" style="position:absolute;left:20mm;bottom:15mm">{esc(s["fonte"])}</p>' if s.get("fonte") else ""
    return (f'<section class="pg">{topo("Quem somos", brand)}'
            f'<div class="cols c2" style="gap:14mm"><div>{col_esq}</div><div style="padding-top:2mm">{col_dir}</div></div>'
            f'{fonte}{rodape(brand, "O escritório")}</section>')


def pg_marca(brand, man):
    linhas = [("Símbolo", "Monograma que identifica o escritório sozinho, em avatar, selo e marca d'água."),
              ("Nome", "Composto em letras romanas maiúsculas, com o peso de uma inscrição."),
              ("Descritor", "Identifica a natureza do escritório e completa a assinatura.")]
    rot = "".join(f"<div><b>{esc(a)}</b><span>{esc(b)}</span></div>" for a, b in man.get("anatomia", linhas))
    return (f'<section class="pg">{topo("A marca", brand)}'
            f'<h2>Assinatura principal</h2>'
            f'<div class="palco branco" style="height:92mm"><img src="{logo(brand, "papel")}" style="width:58%" alt=""></div>'
            f'<div class="anatomia"><div class="rotulos">{rot}</div></div>'
            f'{rodape(brand, "A marca")}</section>')


def pg_versoes(brand, man):
    t = []
    cands = [("papel", "branco", "Dourada · fundos claros", "var(--cinza)"),
             ("escuro", "preto", "Dourada clara · fundos escuros", "rgba(255,255,255,.55)"),
             ("preto", "branco", "Preta · impressão em uma cor", "var(--cinza)"),
             ("branco", "preto", "Branca · sobre fotos e fundos escuros", "rgba(255,255,255,.55)")]
    for chave, fundo, leg, cor in cands:
        if brand["logo"].get(chave):
            t.append(f'<div class="tile palco {fundo}"><img src="{logo(brand, chave)}" style="width:66%" alt="">'
                     f'<div class="leg" style="color:{cor}">{esc(leg)}</div></div>')
    simb = []
    for chave, fundo in (("simbolo", "branco"), ("simbolo_escuro", "preto"), ("simbolo_preto", "branco"), ("simbolo_branco", "preto")):
        if brand["logo"].get(chave):
            simb.append(f'<div class="tile palco {fundo}" style="height:30mm"><img src="{logo(brand, chave)}" style="height:62%" alt=""></div>')
    return (f'<section class="pg">{topo("A marca", brand)}<h2>Versões</h2>'
            f'<div class="cols c2" style="gap:5mm">{"".join(t)}</div>'
            + (f'<div class="rot" style="margin-top:6mm">Símbolo isolado</div><div class="cols c4" style="gap:5mm">{"".join(simb)}</div>' if simb else "")
            + f'{rodape(brand, "Versões")}</section>')


def pg_protecao(brand, man):
    p = man.get("protecao", {"x_frac": 0.12, "x_desc": "altura do descritor", "multiplo": 2})
    mn = man.get("minimos", {})
    import re
    src = open(caminho(brand, brand["logo"]["papel"]), encoding="utf-8").read()
    w, h = [float(v) for v in re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', src).groups()]
    # cabe na coluna: até 34 mm de altura ou 140 mm de largura, o que vier primeiro
    alt_mm = min(34, 140 * h / w)
    larg_mm = alt_mm * w / h
    x = alt_mm * p["x_frac"]
    pad = x * p["multiplo"]
    quad = (f'<div class="x" style="left:0;top:0;width:{pad:.2f}mm;height:{pad:.2f}mm">{p["multiplo"]}x</div>'
            f'<div class="x" style="right:0;bottom:0;width:{pad:.2f}mm;height:{pad:.2f}mm">{p["multiplo"]}x</div>')
    caixa = (f'<div class="protecao" style="padding:{pad:.2f}mm">{quad}'
             f'<img src="{logo(brand, "papel")}" style="display:block;width:{larg_mm:.2f}mm;height:{alt_mm}mm" alt=""></div>')
    mins = ""
    if mn:
        a_mm, a_px = mn.get("assinatura_mm"), mn.get("assinatura_px")
        s_mm, s_px = mn.get("simbolo_mm"), mn.get("simbolo_px")
        mins = (f'<div class="minimos"><div class="rot">Tamanho mínimo</div>'
                f'<div class="item"><img src="{logo(brand, "papel")}" style="width:{a_mm}mm" alt="">'
                f'<div class="num">{a_mm}<small>mm</small> · {a_px}<small>px</small></div></div>'
                f'<div class="item"><img src="{logo(brand, "simbolo")}" style="width:{s_mm}mm" alt="">'
                f'<div class="num">{s_mm}<small>mm</small> · {s_px}<small>px</small></div></div>'
                f'<p class="pequeno">Abaixo desses tamanhos o desenho perde leitura. Em espaços menores, use só o símbolo.</p></div>')
    return (f'<section class="pg">{topo("A marca", brand)}<h2>Área de proteção e tamanho mínimo</h2>'
            f'<div class="cols c-85" style="align-items:center">'
            f'<div><div class="palco areia" style="height:110mm">{caixa}</div>'
            f'<p class="pequeno" style="margin-top:3mm">x = {esc(p["x_desc"])}. Mantenha pelo menos {p["multiplo"]}x livres em volta da assinatura: nenhum texto, imagem ou borda dentro dessa área.</p></div>'
            f'<div>{mins}</div></div>{rodape(brand, "Proteção e tamanho mínimo")}</section>')


def pg_cores(brand, man):
    cores = man.get("cores") or [{"nome": k, "hex": v, "uso": ""} for k, v in brand["cores"].items()]
    cards = []
    for c in cores:
        (r, g, b), (cc, mm, yy, kk) = rgb_cmyk(c["hex"])
        cards.append(f'<div class="cor"><div class="amostra" style="background:{c["hex"]}"></div><div class="dados">'
                     f'<b>{esc(c["nome"])}</b><code>HEX {c["hex"].upper()}</code><code>RGB {r} {g} {b}</code>'
                     f'<code>CMYK {cc} {mm} {yy} {kk}</code><div class="uso">{esc(c.get("uso", ""))}</div></div></div>')
    grads = "".join(f'<div><div class="grad" style="background:linear-gradient(110deg,{",".join(g["stops"])})"></div>'
                    f'<div class="pequeno" style="margin-top:1.6mm">{esc(g["nome"])} · {" → ".join(g["stops"])}</div></div>'
                    for g in man.get("gradientes", []))
    n = min(len(cores), 6)
    return (f'<section class="pg">{topo("Identidade", brand)}<h2>Cores</h2>'
            f'<div class="cols" style="grid-template-columns:repeat({n},1fr);gap:4mm">{"".join(cards)}</div>'
            + (f'<div class="rot" style="margin-top:6mm">Gradientes da logo</div><div class="cols c2" style="gap:6mm">{grads}</div>' if grads else "")
            + '<p class="pequeno" style="margin-top:4mm">CMYK aproximado, convertido do RGB. Para impressão em gráfica, peça prova de cor; o dourado metálico pode ser reproduzido com tinta especial ou hot stamping.</p>'
            + f'{rodape(brand, "Cores")}</section>')


def pg_tipografia(brand, man):
    ft, fx = brand["fontes"]["titulo"]["familia"], brand["fontes"]["texto"]["familia"]
    alfa = "ABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvwxyz 0123456789 áéíóúãõç"
    def bloco(fam, css_fam, uso, extra=""):
        return (f'<div class="tipo"><div class="rot">{esc(fam)}</div>'
                f'<div class="aa" style="font-family:{css_fam}{extra}">Aa</div>'
                f'<div class="alfa" style="font-family:{css_fam}{extra}">{alfa}</div>'
                f'<div class="uso">{esc(uso)}</div></div>')
    fl = man.get("fonte_logo")
    blocos = [bloco(ft, "var(--f-titulo)", "Títulos, subtítulos em itálico, números de página.", ";font-weight:700"),
              bloco(fx, "var(--f-texto)", "Texto corrido, rótulos em caixa alta espaçada, tabelas e rodapés.")]
    if fl:
        blocos.append(bloco(fl["familia"], "var(--f-logo)", fl.get("uso", "Exclusiva da logo."), ";font-weight:700"))
    hier = ('<div class="hier"><div class="rot">Hierarquia</div><div class="h-r">Parecer</div>'
            '<div class="h-t">Título do documento</div><div class="h-s">Subtítulo em itálico, na cor da marca</div>'
            '<div class="h-p">Texto corrido em corpo 10, com entrelinha generosa e alinhamento justificado nos documentos.</div></div>')
    return (f'<section class="pg">{topo("Identidade", brand)}<h2>Tipografia</h2>'
            f'<div class="cols" style="grid-template-columns:repeat({len(blocos)},1fr) 1.1fr;gap:9mm">{"".join(blocos)}<div class="tipo">{hier}</div></div>'
            '<p class="pequeno" style="margin-top:5mm">Todas as fontes são gratuitas (licença SIL Open Font License) e estão na pasta Fontes deste pacote.</p>'
            f'{rodape(brand, "Tipografia")}</section>')


def imagem_aplicacao(brand, item, td):
    from PIL import Image
    if item.get("pdf"):
        base = os.path.join(td, f"apl{abs(hash(item['pdf'] + str(item.get('pagina', 1))))}")
        p = item.get("pagina", 1)
        subprocess.run(["pdftoppm", "-r", "90", "-png", "-f", str(p), "-l", str(p), "-singlefile",
                        caminho(brand, item["pdf"]), base], check=True)
        im = Image.open(base + ".png")
    else:
        im = Image.open(caminho(brand, item["imagem"]))
    if im.width > 1100:
        im = im.resize((1100, round(im.height * 1100 / im.width)), Image.LANCZOS)
    return jpg_uri(im, 90)


def pg_aplicacoes(brand, man):
    itens = man["aplicacoes"]
    with tempfile.TemporaryDirectory() as td:
        figs = "".join(f'<figure><img src="{imagem_aplicacao(brand, it, td)}" alt=""><figcaption>{esc(it.get("legenda", ""))}</figcaption></figure>'
                       for it in itens)
    return (f'<section class="pg areia-fundo" style="background:var(--fundo-suave)">{topo("Aplicações", brand)}'
            f'<h2>Documentos do escritório</h2>'
            f'<div class="apl" style="grid-template-columns:repeat({len(itens)},1fr);padding:0 6mm">{figs}</div>'
            f'{rodape(brand, "Aplicações")}</section>')


def pg_incorretos(brand, man):
    from PIL import Image
    papel = logo(brand, "papel")
    antigo = ""
    if man.get("nota", {}).get("antes"):
        im = Image.open(caminho(brand, man["nota"]["antes"])).convert("RGBA")
        antigo = png_uri(im.resize((im.width // 3, im.height // 3), Image.NEAREST))
    casos = [
        ("Distorcer as proporções", f'<img src="{papel}" style="width:70%;transform:scaleX(1.45) scaleY(.8)">', "branco"),
        ("Trocar as cores", f'<img src="{papel}" style="width:66%;filter:hue-rotate(185deg) saturate(1.6)">', "branco"),
        ("Aplicar sombra, brilho ou relevo", f'<img src="{papel}" style="width:66%;filter:drop-shadow(1.2mm 1.2mm 0 rgba(0,0,0,.55)) drop-shadow(0 0 2mm rgba(255,200,0,.9))">', "branco"),
        ("Girar ou inclinar", f'<img src="{papel}" style="width:62%;transform:rotate(-14deg)">', "branco"),
        ("Usar sobre fundo sem contraste", f'<img src="{papel}" style="width:66%">', "dourado"),
    ]
    if antigo:
        casos.append(("Usar o arquivo antigo, de baixa resolução", f'<img src="{antigo}" style="width:72%;image-rendering:pixelated">', "preto"))
    tiles = []
    for leg, img, fundo in casos:
        estilo = ' style="background:#C9A24A"' if fundo == "dourado" else ""
        cls = "preto" if fundo == "preto" else ("branco" if fundo == "branco" else "")
        tiles.append(f'<div class="errado"><div class="tile palco {cls}"{estilo}>{img}</div><div class="leg">{esc(leg)}</div></div>')
    return (f'<section class="pg">{topo("Cuidados", brand)}<h2>Usos incorretos</h2>'
            f'<div class="cols c3" style="gap:6mm 7mm">{"".join(tiles)}</div>{rodape(brand, "Usos incorretos")}</section>')


def pg_presenca(brand, man):
    pr = man["presenca"]
    linhas = "".join(f'<tr><td>{esc(i["canal"])}</td><td>{esc(i["situacao"])}</td><td>{esc(i["recomendacao"])}</td></tr>'
                     for i in pr["itens"])
    return (f'<section class="pg">{topo("Presença digital", brand)}<h2>{esc(pr.get("titulo", "Presença digital"))}</h2>'
            + (f'<p style="max-width:200mm;margin-bottom:5mm">{esc(pr["intro"])}</p>' if pr.get("intro") else "")
            + f'<table class="pontos"><thead><tr><th>Onde</th><th>O que encontramos</th><th>Sugestão</th></tr></thead><tbody>{linhas}</tbody></table>'
            + f'{rodape(brand, "Presença digital")}</section>')


def pg_arquivos(brand, man):
    linhas = "".join(f"<div><b>{esc(a)}</b><span>{esc(b)}</span></div>" for a, b in man["arquivos"])
    return (f'<section class="pg">{topo("Pacote", brand)}<h2>Arquivos entregues</h2>'
            f'<div class="arquivos">{linhas}</div>'
            '<p class="pequeno" style="margin-top:5mm">SVG para gráfica, sinalização e site; PNG para redes, apresentações e e-mail. '
            'Para documentos, instale as fontes da pasta Fontes e use o modelo Word.</p>'
            f'{rodape(brand, "Arquivos")}</section>')


def pg_contra(brand):
    c = brand.get("contatos", {})
    linhas = [v for v in [c.get("endereco"), " · ".join(v for v in [c.get("telefone"), c.get("email")] if v), brand.get("site")] if v]
    return (f'<section class="pg escura contra"><img src="{logo(brand, "simbolo_escuro", "simbolo")}" alt="">'
            f'<div class="contatos">{"<br>".join(esc(l) for l in linhas)}</div></section>')


def montar(brand):
    man = brand.get("manual", {})
    pgs = [pg_capa(brand, man)]
    if man.get("nota"):
        pgs.append(pg_nota(brand, man))
    if man.get("sobre"):
        pgs.append(pg_sobre(brand, man))
    pgs += [pg_marca(brand, man), pg_versoes(brand, man), pg_protecao(brand, man), pg_cores(brand, man), pg_tipografia(brand, man)]
    if man.get("aplicacoes"):
        pgs.append(pg_aplicacoes(brand, man))
    pgs.append(pg_incorretos(brand, man))
    if man.get("presenca"):
        pgs.append(pg_presenca(brand, man))
    if man.get("arquivos"):
        pgs.append(pg_arquivos(brand, man))
    pgs.append(pg_contra(brand))

    css_logo = ""
    fl = man.get("fonte_logo")
    if fl and fl.get("arquivo"):
        css_logo = (f'@font-face {{ font-family: "{fl["familia"]}"; font-weight: 700; '
                    f'src: url("{data_uri(caminho(brand, fl["arquivo"]))}") format("truetype"); }}')
    c = brand["cores"]
    vals = {
        "titulo_doc": esc(f"Manual de Marca · {brand['nome']}"),
        "fontes": fontes_css(brand) + "\n" + css_logo,
        "c_tinta": c["tinta"], "c_escuro": c["escuro"], "c_primaria": c["primaria"],
        "c_primaria_escura": c["primaria_escura"], "c_primaria_clara": c["primaria_clara"],
        "c_cinza": c["cinza"], "c_linha": c["linha"], "c_fundo_suave": c["fundo_suave"],
        "f_titulo": brand["fontes"]["titulo"]["familia"], "f_texto": brand["fontes"]["texto"]["familia"],
        "f_logo": (fl or {}).get("familia", brand["fontes"]["titulo"]["familia"]),
        "paginas": "\n".join(pgs),
    }
    return string.Template(open(TEMPLATE, encoding="utf-8").read()).safe_substitute(vals)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("brand")
    ap.add_argument("saida")
    ap.add_argument("--html")
    a = ap.parse_args()
    brand = carregar_brand(a.brand)
    doc = montar(brand)
    if a.html:
        open(a.html, "w", encoding="utf-8").write(doc)
    saida = os.path.abspath(a.saida)
    os.makedirs(os.path.dirname(saida), exist_ok=True)
    imprimir(doc, saida)
    print(saida)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
