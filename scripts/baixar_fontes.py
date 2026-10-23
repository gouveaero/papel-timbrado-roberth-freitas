#!/usr/bin/env python3
"""
Baixa famílias do Google Fonts (repositório google/fonts, licença OFL/Apache)
e gera TTFs estáticos com nomes que o Word reconhece (família + Regular/Bold/
Italic), prontos para embutir no .docx e no PDF.

    python3 baixar_fontes.py <pasta_fontes> "Playfair Display:400,600,700,400i" "Montserrat:400,500,600,700,400i"

Pesos: 400 = Regular, 700 = Bold, "i" = itálico. Outros pesos viram família
própria no Word ("Montserrat SemiBold"), que é como o Word lida com eles.
Grava também o arquivo de licença de cada família.

Requer: fontTools.
"""
import io
import json
import os
import re
import sys
import urllib.request

from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

NOMES = {100: "Thin", 200: "ExtraLight", 300: "Light", 400: "Regular", 500: "Medium",
         600: "SemiBold", 700: "Bold", 800: "ExtraBold", 900: "Black"}
RIBBI = {"Regular", "Bold", "Italic", "Bold Italic"}


def get(url, binario=True):
    req = urllib.request.Request(url, headers={"User-Agent": "papel-timbrado"})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = r.read()
    return d if binario else d.decode()


def listar(familia):
    slug = re.sub(r"[^a-z0-9]", "", familia.lower())
    for lic in ("ofl", "apache", "ufl"):
        try:
            itens = json.loads(get(f"https://api.github.com/repos/google/fonts/contents/{lic}/{slug}", False))
            return lic, slug, {i["name"]: i["download_url"] for i in itens if i["type"] == "file"}
        except Exception:  # noqa: BLE001
            continue
    raise SystemExit(f"família não encontrada no google/fonts: {familia}")


def nomear(font, familia, estilo, peso, italico):
    name = font["name"]
    for nid in (1, 2, 3, 4, 6, 16, 17, 21, 22, 25):
        name.removeNames(nameID=nid)
    sub = "Italic" if italico and peso != 700 else ("Bold Italic" if italico else ("Bold" if peso == 700 else "Regular"))
    legado = familia if estilo in RIBBI else f"{familia} {NOMES[peso]}"
    ps = f"{familia.replace(' ', '')}-{estilo.replace(' ', '')}"
    for nid, val in [(1, legado), (2, sub), (3, f"{ps};static"), (4, f"{familia} {estilo}".replace(" Regular", "")),
                     (6, ps), (16, familia), (17, estilo)]:
        name.setName(val, nid, 3, 1, 0x409)
    os2 = font["OS/2"]
    os2.usWeightClass = peso
    fs = os2.fsSelection & ~0b1100001
    if italico:
        fs |= 1
    if peso == 700:
        fs |= 1 << 5
    if not italico and peso != 700:
        fs |= 1 << 6
    os2.fsSelection = fs
    os2.fsType = 0
    font["head"].macStyle = (1 if peso == 700 else 0) | (2 if italico else 0)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    pasta = os.path.abspath(sys.argv[1])
    os.makedirs(pasta, exist_ok=True)
    for spec in sys.argv[2:]:
        familia, pesos = spec.split(":")
        lic, slug, arquivos = listar(familia)
        base = familia.replace(" ", "")
        var_rom = next((u for n, u in arquivos.items() if n.endswith(".ttf") and "[" in n and "Italic" not in n), None)
        var_ita = next((u for n, u in arquivos.items() if n.endswith(".ttf") and "[" in n and "Italic" in n), None)
        for lic_nome in ("OFL.txt", "LICENSE.txt"):
            if lic_nome in arquivos:
                open(os.path.join(pasta, f"{lic_nome[:-4]}-{base}.txt"), "wb").write(get(arquivos[lic_nome]))
        for p in pesos.split(","):
            italico = p.endswith("i")
            peso = int(p.rstrip("i"))
            estilo = NOMES[peso] if not italico else ("Italic" if peso == 400 else f"{NOMES[peso]} Italic")
            if peso == 700 and italico:
                estilo = "Bold Italic"
            fonte_var = var_ita if italico else var_rom
            if fonte_var:
                f = TTFont(io.BytesIO(get(fonte_var)))
                # fixa todos os eixos: wght no peso pedido, os demais (opsz, wdth...) no padrão
                loc = {a.axisTag: a.defaultValue for a in f["fvar"].axes}
                if "wght" in loc:
                    ax = next(a for a in f["fvar"].axes if a.axisTag == "wght")
                    loc["wght"] = max(ax.minValue, min(ax.maxValue, peso))
                f = instantiateVariableFont(f, loc, updateFontNames=False)
                for t in ("STAT", "fvar", "gvar", "avar", "HVAR", "MVAR", "cvar"):
                    if t in f:
                        del f[t]
            else:
                alvo = f"{base}-{estilo.replace(' ', '')}.ttf"
                if alvo not in arquivos:
                    print(f"  sem arquivo para {familia} {estilo}", file=sys.stderr)
                    continue
                f = TTFont(io.BytesIO(get(arquivos[alvo])))
            nomear(f, familia, estilo, peso, italico)
            saida = os.path.join(pasta, f"{base}-{estilo.replace(' ', '')}.ttf")
            f.save(saida)
            print(f"  {os.path.basename(saida)} ({lic})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
