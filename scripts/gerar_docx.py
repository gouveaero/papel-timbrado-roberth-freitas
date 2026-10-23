#!/usr/bin/env python3
"""
Gera o papel timbrado em Word (.docx) a partir de um brand.json.

    python3 gerar_docx.py <brand.json> <saida.docx>
        Timbrado em branco: cabeçalho com logo, rodapé com contatos e paginação,
        marca d'água do símbolo, estilos nomeados e fontes embutidas.

    python3 gerar_docx.py <brand.json> <saida.docx> --conteudo texto.md
        Documento pronto no timbre: o Markdown vira .docx pelo pandoc, usando o
        timbrado como reference-doc. O front matter do .md (tipo, title,
        subtitle, cliente, date, local) vira o bloco de título da primeira página.

Requer: python-docx, Pillow, fontTools e (para --conteudo) pandoc no PATH.
"""
import argparse
import copy
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
import zipfile

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING, WD_TAB_ALIGNMENT, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor, Emu

# ---------------------------------------------------------------- utilidades


def carregar_brand(path):
    brand = json.load(open(path, encoding="utf-8"))
    brand["_base"] = os.path.dirname(os.path.abspath(path))
    return brand


def caminho(brand, rel):
    return rel if os.path.isabs(rel) else os.path.join(brand["_base"], rel)


def hexcor(h):
    return RGBColor.from_string(h.lstrip("#").upper())


def _el(obj):
    """Elemento XML de um estilo, parágrafo ou run do python-docx."""
    for att in ("_r", "_p"):
        if hasattr(obj, att):
            return getattr(obj, att)
    return obj.element


def limpar_tema(rpr_parent):
    """Remove referências a fontes/cores do tema, que sobrescrevem o que definimos."""
    for el in rpr_parent.iter():
        for att in list(el.attrib):
            if att.endswith("}asciiTheme") or att.endswith("}hAnsiTheme") or att.endswith("}eastAsiaTheme") \
                    or att.endswith("}cstheme") or att.endswith("}themeColor") or att.endswith("}themeShade") \
                    or att.endswith("}themeTint"):
                del el.attrib[att]


def set_fonte(style_or_run, familia):
    f = style_or_run.font
    f.name = familia
    rpr = _el(style_or_run).get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    for k in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(k), familia)
    limpar_tema(rpr)


def espacamento_letras(run_or_style, pts):
    rpr = _el(run_or_style).get_or_add_rPr()
    sp = rpr.find(qn("w:spacing"))
    if sp is None:
        sp = OxmlElement("w:spacing")
        rpr.append(sp)
    sp.set(qn("w:val"), str(int(pts * 20)))


def borda_paragrafo(pf_owner, lado, cor, tamanho_oitavos=6, espaco=4):
    ppr = _el(pf_owner).get_or_add_pPr()
    bdr = ppr.find(qn("w:pBdr"))
    if bdr is None:
        bdr = OxmlElement("w:pBdr")
        ppr.append(bdr)
    el = OxmlElement(f"w:{lado}")
    el.set(qn("w:val"), "single")
    el.set(qn("w:sz"), str(tamanho_oitavos))
    el.set(qn("w:space"), str(espaco))
    el.set(qn("w:color"), cor.lstrip("#").upper())
    bdr.append(el)


def sombreamento(pf_owner, cor):
    ppr = _el(pf_owner).get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), cor.lstrip("#").upper())
    ppr.append(shd)


def campo(paragrafo, instr, fonte=None, tamanho=None, cor=None, negrito=False):
    """Insere um campo (PAGE, NUMPAGES) com valor provisório."""
    def run_xml(tag_children):
        r = paragrafo.add_run()
        if fonte:
            set_fonte(r, fonte)
        if tamanho:
            r.font.size = Pt(tamanho)
        if cor:
            r.font.color.rgb = hexcor(cor)
        r.font.bold = negrito
        for ch in tag_children:
            r._r.append(ch)
        return r
    b = OxmlElement("w:fldChar"); b.set(qn("w:fldCharType"), "begin")
    t = OxmlElement("w:instrText"); t.set(qn("xml:space"), "preserve"); t.text = f" {instr} "
    s = OxmlElement("w:fldChar"); s.set(qn("w:fldCharType"), "separate")
    v = OxmlElement("w:t"); v.text = "1"
    e = OxmlElement("w:fldChar"); e.set(qn("w:fldCharType"), "end")
    run_xml([b]); run_xml([t]); run_xml([s]); run_xml([v]); run_xml([e])


# ---------------------------------------------------------------- estilos


def configurar_estilos(doc, brand):
    c = brand["cores"]
    ft = brand["fontes"]["titulo"]["familia"]
    fx = brand["fontes"]["texto"]["familia"]
    st = doc.styles

    # padrões do documento (docDefaults) sem fontes de tema
    rpr_def = doc.styles.element.find(qn("w:docDefaults")).find(qn("w:rPrDefault")).find(qn("w:rPr"))
    rf = rpr_def.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts"); rpr_def.insert(0, rf)
    for k in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rf.set(qn(k), fx)
    limpar_tema(rpr_def)
    lang = rpr_def.find(qn("w:lang"))
    if lang is None:
        lang = OxmlElement("w:lang"); rpr_def.append(lang)
    lang.set(qn("w:val"), "pt-BR"); lang.set(qn("w:eastAsia"), "pt-BR"); lang.set(qn("w:bidi"), "ar-SA")

    def estilo(nome, tipo=WD_STYLE_TYPE.PARAGRAPH, base=None):
        try:
            s = st[nome]
        except KeyError:
            s = st.add_style(nome, tipo)
        if base is not None:
            s.base_style = st[base]
        limpar_tema(s.element)
        return s

    normal = estilo("Normal")
    set_fonte(normal, fx)
    normal.font.size = Pt(10)
    normal.font.color.rgb = hexcor(c["tinta"])
    pf = normal.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(7)
    pf.line_spacing = 1.38
    pf.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    for nome in ("Body Text", "First Paragraph"):
        s = estilo(nome, base="Normal")
        s.font.size = Pt(10)
        s.paragraph_format.space_after = Pt(7)
    compacto = estilo("Compact", base="Normal")
    compacto.paragraph_format.space_after = Pt(2)

    rotulo = estilo("Rótulo", base="Normal")
    set_fonte(rotulo, fx)
    rotulo.font.size = Pt(8)
    rotulo.font.bold = True
    rotulo.font.all_caps = True
    rotulo.font.color.rgb = hexcor(c["primaria"])
    rotulo.paragraph_format.space_after = Pt(4)
    rotulo.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    espacamento_letras(rotulo, 2)

    titulo = estilo("Title", base="Normal")
    set_fonte(titulo, ft)
    titulo.font.size = Pt(25)
    titulo.font.bold = True
    titulo.font.color.rgb = hexcor(c["escuro"])
    titulo.paragraph_format.space_after = Pt(6)
    titulo.paragraph_format.line_spacing = 1.08
    titulo.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    # remove a borda azul do Title do modelo padrão
    for b in titulo.element.findall(".//" + qn("w:pBdr")):
        b.getparent().remove(b)

    sub = estilo("Subtitle", base="Normal")
    set_fonte(sub, ft)
    sub.font.size = Pt(13)
    sub.font.italic = True
    sub.font.color.rgb = hexcor(c["primaria_escura"])
    sub.paragraph_format.space_after = Pt(10)
    sub.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT

    meta = estilo("Meta", base="Normal")
    meta.font.size = Pt(8.5)
    meta.font.color.rgb = hexcor(c["cinza"])
    meta.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    meta.paragraph_format.space_after = Pt(18)
    borda_paragrafo(meta, "bottom", c["linha"], 4, 10)

    for nivel, (tam, fam, cor, antes, depois) in {
        1: (15, ft, c["escuro"], 18, 6),
        2: (11, fx, c["primaria_escura"], 12, 4),
        3: (10, fx, c["tinta"], 10, 3),
    }.items():
        h = estilo(f"Heading {nivel}", base="Normal")
        set_fonte(h, fam)
        h.font.size = Pt(tam)
        h.font.bold = True
        h.font.italic = False
        h.font.color.rgb = hexcor(cor)
        h.paragraph_format.space_before = Pt(antes)
        h.paragraph_format.space_after = Pt(depois)
        h.paragraph_format.keep_with_next = True
        h.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
        h.paragraph_format.line_spacing = 1.15
        if nivel == 2:
            h.font.all_caps = True
            espacamento_letras(h, 0.6)
            h.font.size = Pt(9)

    bloco = estilo("Block Text", base="Normal")
    bloco.font.size = Pt(9.5)
    bloco.font.italic = True
    bloco.font.color.rgb = hexcor(c["tinta"])
    bloco.paragraph_format.left_indent = Mm(5)
    bloco.paragraph_format.right_indent = Mm(3)
    bloco.paragraph_format.space_before = Pt(4)
    bloco.paragraph_format.space_after = Pt(10)
    borda_paragrafo(bloco, "left", c["primaria"], 18, 10)
    sombreamento(bloco, c["fundo_suave"])
    # "Ementa" é o mesmo bloco, com nome jurídico, para quem escreve direto no Word
    ementa = estilo("Ementa", base="Block Text")

    for nome in ("List Bullet", "List Number", "List Paragraph"):
        s = estilo(nome, base="Normal")
        s.paragraph_format.space_after = Pt(3)

    assin = estilo("Assinatura", base="Normal")
    set_fonte(assin, ft)
    assin.font.size = Pt(12)
    assin.font.bold = True
    assin.font.color.rgb = hexcor(c["escuro"])
    assin.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    assin.paragraph_format.space_before = Pt(28)
    assin.paragraph_format.space_after = Pt(0)
    borda_paragrafo(assin, "top", c["primaria"], 6, 8)

    cargo = estilo("Cargo", base="Normal")
    cargo.font.size = Pt(8.5)
    cargo.font.color.rgb = hexcor(c["cinza"])
    cargo.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT

    for nome, tam in (("Footnote Text", 8), ("Caption", 8)):
        s = estilo(nome, base="Normal")
        s.font.size = Pt(tam)
        s.font.color.rgb = hexcor(c["cinza"])

    local = estilo("Local e data", base="Normal")
    local.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    local.paragraph_format.space_before = Pt(18)

    # marca trechos ainda por escrever ([a redigir], [conferir]); some quando o texto entra
    pend = estilo("Pendente", tipo=WD_STYLE_TYPE.CHARACTER)
    pend.font.bold = True
    pend.font.color.rgb = hexcor(c["primaria_escura"])
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), "F6E7B8")
    pend.element.get_or_add_rPr().append(shd)

    link = estilo("Hyperlink", tipo=WD_STYLE_TYPE.CHARACTER)
    link.font.color.rgb = hexcor(c["primaria_escura"])
    link.font.underline = True

    # Estilos de caractere vinculados ("Heading 2 Char", "Title Char"...) do modelo
    # padrão guardam fonte e cor do tema. O Word ignora, mas Google Docs e outros
    # leitores aplicam por cima do parágrafo. Remove o vínculo e os estilos órfãos.
    raiz = doc.styles.element
    vinculados = set()
    for s in raiz.findall(qn("w:style")):
        link = s.find(qn("w:link"))
        if link is not None:
            if s.get(qn("w:type")) == "paragraph":
                vinculados.add(link.get(qn("w:val")))
            s.remove(link)
    for s in raiz.findall(qn("w:style")):
        if s.get(qn("w:type")) == "character" and s.get(qn("w:styleId")) in vinculados:
            raiz.remove(s)
    return doc


# ---------------------------------------------------------------- cabeçalho, rodapé, marca d'água


ANCHOR_XML = (
    '<wp:anchor xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'distT="0" distB="0" distL="0" distR="0" simplePos="0" relativeHeight="251658240" behindDoc="1" '
    'locked="1" layoutInCell="1" allowOverlap="1">'
    '<wp:simplePos x="0" y="0"/>'
    '<wp:positionH relativeFrom="page"><wp:posOffset>{x}</wp:posOffset></wp:positionH>'
    '<wp:positionV relativeFrom="page"><wp:posOffset>{y}</wp:posOffset></wp:positionV>'
    '<wp:extent cx="{cx}" cy="{cy}"/><wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapNone/>'
    '</wp:anchor>')


def imagem_atras(run, png_bytes, largura_mm, x_mm, y_mm):
    """Imagem flutuante atrás do texto, posicionada em relação à página."""
    from lxml import etree
    run.add_picture(io.BytesIO(png_bytes), width=Mm(largura_mm))
    inline = run._r.find(".//" + qn("wp:inline"))
    cx, cy = inline.find(qn("wp:extent")).get("cx"), inline.find(qn("wp:extent")).get("cy")
    anchor = etree.fromstring(ANCHOR_XML.format(x=int(Mm(x_mm)), y=int(Mm(y_mm)), cx=cx, cy=cy))
    for tag in ("wp:docPr", "wp:cNvGraphicFramePr", "a:graphic"):
        el = inline.find(qn(tag))
        if el is not None:
            anchor.append(el)
    inline.getparent().replace(inline, anchor)


def png_reduzido(path, largura_mm, dpi=600):
    """PNG na resolução de impressão da largura final (evita docx pesado)."""
    from PIL import Image
    im = Image.open(path)
    alvo = round(largura_mm / 25.4 * dpi)
    if im.width > alvo:
        im = im.resize((alvo, round(im.height * alvo / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def marca_dagua_png(brand, opacidade=0.06):
    from PIL import Image
    src = caminho(brand, brand["logo"]["simbolo_png"])
    im = Image.open(src).convert("RGBA")
    a = im.getchannel("A").point(lambda v: int(v * opacidade))
    im.putalpha(a)
    w = 1400
    im = im.resize((w, round(im.height * w / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue(), im.width / im.height


def montar_cabecalho_rodape(doc, brand, sec):
    c = brand["cores"]
    fx = brand["fontes"]["texto"]["familia"]
    ft = brand["fontes"]["titulo"]["familia"]
    largura_texto_mm = (sec.page_width - sec.left_margin - sec.right_margin) / Mm(1)

    sec.different_first_page_header_footer = False
    hdr = sec.header
    hdr.is_linked_to_previous = False
    p = hdr.paragraphs[0]
    p.style = doc.styles["Normal"]
    p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.0
    logo_mm = brand.get("documento", {}).get("logo_mm", 50)
    p.add_run().add_picture(io.BytesIO(png_reduzido(caminho(brand, brand["logo"]["papel_png"]), logo_mm)), width=Mm(logo_mm))
    borda_paragrafo(p, "bottom", c["primaria"], 6, 8)

    # desligada por padrão no Word: imagem flutuante atrás do texto em cabeçalho
    # varia entre Word, Google Docs e WPS. O PDF de apresentação leva a marca d'água.
    if brand.get("documento", {}).get("marca_dagua_docx", False):
        png, ratio = marca_dagua_png(brand)
        larg = 120
        alt = larg / ratio
        pw, ph = sec.page_width / Mm(1), sec.page_height / Mm(1)
        imagem_atras(p.add_run(), png, larg, pw - larg * 0.78, ph - alt * 0.88)

    ftr = sec.footer
    ftr.is_linked_to_previous = False
    contatos = brand.get("contatos", {})
    linha1 = " · ".join(v for v in [contatos.get("endereco"), contatos.get("telefone")] if v)
    linha2 = " · ".join(v for v in [contatos.get("email"), brand.get("site")] if v)
    if brand.get("oab"):
        linha2 = f"{linha2} · {brand['oab']}" if linha2 else brand["oab"]

    f1 = ftr.paragraphs[0]
    f1.style = doc.styles["Normal"]
    f1.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    f1.paragraph_format.space_after = Pt(0)
    f1.paragraph_format.line_spacing = 1.25
    f1.paragraph_format.tab_stops.add_tab_stop(Mm(largura_texto_mm), WD_TAB_ALIGNMENT.RIGHT)
    borda_paragrafo(f1, "top", c["primaria"], 4, 8)
    r = f1.add_run(linha1)
    r.font.size = Pt(7.5); r.font.color.rgb = hexcor(c["cinza"])
    espacamento_letras(r, 0.2)
    f1.add_run("\t")
    campo(f1, "PAGE", fonte=ft, tamanho=11, cor=c["primaria"], negrito=True)

    f2 = ftr.add_paragraph()
    f2.style = doc.styles["Normal"]
    f2.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    f2.paragraph_format.space_after = Pt(0)
    f2.paragraph_format.line_spacing = 1.25
    r = f2.add_run(linha2)
    r.font.size = Pt(7.5); r.font.color.rgb = hexcor(c["cinza"])
    espacamento_letras(r, 0.2)


def configurar_pagina(sec):
    sec.page_width, sec.page_height = Mm(210), Mm(297)
    sec.top_margin, sec.bottom_margin = Mm(36), Mm(28)
    sec.left_margin, sec.right_margin = Mm(24), Mm(22)
    sec.header_distance, sec.footer_distance = Mm(11), Mm(10)


# ---------------------------------------------------------------- fontes embutidas e limpeza do pacote

LATIM = ("U+0020-007E,U+00A0-017F,U+0192,U+02C6-02DC,U+2010-2027,U+2030-203A,"
         "U+2044,U+20AC,U+20BD,U+2116,U+2122,U+2190-2193,U+2212,U+25CF,U+FB01-FB02")


def subset_fonte(path):
    from fontTools import subset
    opts = subset.Options()
    opts.layout_features = ["kern", "liga", "lnum", "onum", "pnum", "tnum", "case", "calt", "ccmp", "locl", "mark", "mkmk"]
    opts.name_IDs = ["*"]
    opts.name_languages = ["*"]
    opts.notdef_outline = True
    opts.glyph_names = False
    font = subset.load_font(path, opts)
    sub = subset.Subsetter(opts)
    sub.populate(unicodes=subset.parse_unicodes(LATIM))
    sub.subset(font)
    buf = io.BytesIO()
    font.save(buf)
    return buf.getvalue()


def ofuscar(dados, guid):
    """ECMA-376: XOR dos 32 primeiros bytes com a chave do GUID (bytes em ordem inversa)."""
    chave = bytes.fromhex(guid.replace("-", ""))[::-1]
    b = bytearray(dados)
    for i in range(32):
        b[i] ^= chave[i % 16]
    return bytes(b)


def pos_processar(docx_path, brand, titulo=None):
    """Embute fontes, limpa metadados e remove a miniatura genérica do modelo."""
    familias = []
    for papel in ("titulo", "texto"):
        f = brand["fontes"][papel]
        familias.append((f["familia"], {k: caminho(brand, f[k]) for k in ("regular", "bold", "italic") if f.get(k)}))

    zin = zipfile.ZipFile(docx_path)
    partes = {n: zin.read(n) for n in zin.namelist()}
    zin.close()

    # miniatura genérica do python-docx
    partes.pop("docProps/thumbnail.jpeg", None)
    partes["_rels/.rels"] = re.sub(rb'<Relationship [^>]*thumbnail[^>]*/>', b"", partes["_rels/.rels"])
    ct = partes["[Content_Types].xml"].decode()
    ct = re.sub(r'<Override PartName="/docProps/thumbnail.jpeg"[^>]*/>', "", ct)
    if 'Extension="odttf"' not in ct:
        ct = ct.replace("<Default ", '<Default Extension="odttf" ContentType="application/vnd.openxmlformats-officedocument.obfuscatedFont"/><Default ', 1)
    partes["[Content_Types].xml"] = ct.encode()

    # fontes embutidas
    ft = partes["word/fontTable.xml"].decode()
    rels = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
    n = 0
    for familia, arquivos in familias:
        embeds = []
        for estilo, path in arquivos.items():
            n += 1
            guid = str(uuid.uuid4()).upper()
            partes[f"word/fonts/font{n}.odttf"] = ofuscar(subset_fonte(path), guid)
            rels.append(f'<Relationship Id="rIdF{n}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/font" Target="fonts/font{n}.odttf"/>')
            tag = {"regular": "embedRegular", "bold": "embedBold", "italic": "embedItalic"}[estilo]
            embeds.append(f'<w:{tag} r:id="rIdF{n}" w:fontKey="{{{guid}}}"/>')
        ft = re.sub(rf'<w:font w:name="{re.escape(familia)}">.*?</w:font>', "", ft, flags=re.S)
        bloco = (f'<w:font w:name="{familia}"><w:charset w:val="00"/><w:family w:val="auto"/>'
                 f'<w:pitch w:val="variable"/>{"".join(embeds)}</w:font>')
        ft = ft.replace("</w:fonts>", bloco + "</w:fonts>")
    rels.append("</Relationships>")
    partes["word/fontTable.xml"] = ft.encode()
    partes["word/_rels/fontTable.xml.rels"] = "".join(rels).encode()

    st = partes["word/settings.xml"].decode()
    if "embedTrueTypeFonts" not in st:
        st = re.sub(r"(<w:settings[^>]*>)", r"\1<w:embedTrueTypeFonts/>", st, count=1)
    partes["word/settings.xml"] = st.encode()

    # metadados: só o escritório
    autor = brand.get("documento", {}).get("autor", brand["nome"])
    core = partes["docProps/core.xml"].decode()
    def tag(xml, nome, valor):
        valor = (valor or "").replace("&", "&amp;").replace("<", "&lt;")
        xml = re.sub(rf"<{nome}\s*/>", f"<{nome}>{valor}</{nome}>", xml)
        return re.sub(rf"<{nome}>.*?</{nome}>", f"<{nome}>{valor}</{nome}>", xml, flags=re.S)
    core = tag(core, "dc:creator", autor)
    core = tag(core, "cp:lastModifiedBy", autor)
    core = tag(core, "dc:description", "")
    core = tag(core, "dc:title", titulo or brand["nome"])
    partes["docProps/core.xml"] = core.encode()
    app = partes["docProps/app.xml"].decode()
    if "<Company>" in app:
        app = re.sub(r"<Company>.*?</Company>", f"<Company>{brand['nome']}</Company>", app)
    else:
        app = app.replace("</Properties>", f"<Company>{brand['nome']}</Company></Properties>")
    partes["docProps/app.xml"] = app.encode()

    tmp = docx_path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        ordem = ["[Content_Types].xml"] + [k for k in partes if k != "[Content_Types].xml"]
        for k in ordem:
            z.writestr(k, partes[k])
    os.replace(tmp, docx_path)


# ---------------------------------------------------------------- documento com conteúdo


def ler_front_matter(md):
    meta, corpo = {}, md
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", md, re.S)
    if m:
        corpo = md[m.end():]
        for linha in m.group(1).splitlines():
            if ":" in linha and not linha.lstrip().startswith("#"):
                k, v = linha.split(":", 1)
                meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, corpo


def bloco_titulo(doc, meta, brand):
    """Insere rótulo, título, subtítulo e linha de meta no início do corpo."""
    corpo = doc.element.body
    primeiro = corpo[0]
    def novo(texto, estilo):
        p = doc.add_paragraph(texto, style=estilo)
        corpo.remove(p._p)
        primeiro.addprevious(p._p)
        return p
    rotulo = " · ".join(v for v in [meta.get("tipo"), meta.get("referencia")] if v)
    if rotulo:
        novo(rotulo, "Rótulo")
    if meta.get("title"):
        novo(meta["title"], "Title")
    if meta.get("subtitle"):
        novo(meta["subtitle"], "Subtitle")
    partes = []
    if meta.get("cliente"):
        partes.append(f"Destinatário: {meta['cliente']}")
    resp = brand.get("responsavel") or {}
    if resp.get("nome"):
        partes.append(" · ".join(v for v in [resp.get("nome"), resp.get("oab")] if v))
    local_data = ", ".join(v for v in [meta.get("local") or brand.get("documento", {}).get("local"), meta.get("date")] if v)
    if local_data:
        partes.append(local_data)
    if partes:
        novo("   ·   ".join(partes), "Meta")


def documento_com_conteudo(brand, timbrado, md_path, saida):
    md = open(md_path, encoding="utf-8").read()
    meta, corpo = ler_front_matter(md)
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "corpo.md")
        open(src, "w", encoding="utf-8").write(corpo)
        bruto = os.path.join(td, "bruto.docx")
        # "#" é o título (vai para a capa/abertura); "##" são as seções → Heading 1 no Word
        subprocess.run(["pandoc", src, "-f", "markdown", "-t", "docx", "--shift-heading-level-by=-1",
                        "--reference-doc", timbrado, "-o", bruto], check=True)
        doc = Document(bruto)
        bloco_titulo(doc, meta, brand)
        # pandoc copia cabeçalho/rodapé, mas não as margens da seção
        for sec in doc.sections:
            configurar_pagina(sec)
        doc.save(saida)
    pos_processar(saida, brand, titulo=meta.get("title"))


# ---------------------------------------------------------------- principal


def timbrado_em_branco(brand, saida):
    doc = Document()
    configurar_estilos(doc, brand)
    sec = doc.sections[0]
    configurar_pagina(sec)
    montar_cabecalho_rodape(doc, brand, sec)
    p = doc.paragraphs[0] if doc.paragraphs else doc.add_paragraph()
    p.style = doc.styles["Normal"]
    doc.save(saida)
    pos_processar(saida, brand)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("brand")
    ap.add_argument("saida")
    ap.add_argument("--conteudo", help="Markdown com front matter; gera o documento já no timbre")
    a = ap.parse_args()
    brand = carregar_brand(a.brand)
    saida = os.path.abspath(a.saida)
    os.makedirs(os.path.dirname(saida), exist_ok=True)
    if a.conteudo:
        with tempfile.TemporaryDirectory() as td:
            ref = os.path.join(td, "referencia.docx")
            timbrado_em_branco(brand, ref)
            documento_com_conteudo(brand, ref, a.conteudo, saida)
    else:
        timbrado_em_branco(brand, saida)
    print(saida)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
