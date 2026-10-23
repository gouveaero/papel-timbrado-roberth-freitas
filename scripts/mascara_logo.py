#!/usr/bin/env python3
"""
Transforma uma logo raster com textura, brilho ou bevel (dourado metálico,
relevo, sombra) numa máscara limpa preto-no-branco, pronta para vetorizar
(Magnific images_to_svg ou outro traçador).

    python3 mascara_logo.py <imagem> <saida.png> [--alpha-de original.png] [--limiar 60]
                            [--fundo escuro|claro] [--buracos 4000] [--suavizar 3] [--escala 2]

--alpha-de    PNG original com transparência: restringe a máscara à área da
              logo (útil quando o upscale achatou o fundo transparente em preto)
--limiar      corte de luminância (0-255) entre logo e fundo
--fundo       "escuro": logo clara sobre fundo escuro (padrão); "claro": o inverso
--buracos     preenche furos internos menores que N px (textura, reflexo);
              0 desliga. Detalhes finos de desenho (fios de separação entre
              letras) somem junto: redesenhe-os depois, se existirem
--suavizar    raio do desfoque antes do recorte final (alisa serrilhado)
--escala      amplia antes de suavizar (traço mais fino no vetorizador)

Requer: Pillow, numpy e scipy.
"""
import argparse

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage as ndi


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("imagem")
    ap.add_argument("saida")
    ap.add_argument("--alpha-de")
    ap.add_argument("--limiar", type=int, default=60)
    ap.add_argument("--fundo", choices=["escuro", "claro"], default="escuro")
    ap.add_argument("--buracos", type=int, default=4000)
    ap.add_argument("--suavizar", type=float, default=3)
    ap.add_argument("--escala", type=int, default=2)
    a = ap.parse_args()

    im = Image.open(a.imagem).convert("RGBA")
    W, H = im.size
    fundo = Image.new("RGBA", im.size, (0, 0, 0, 255) if a.fundo == "escuro" else (255, 255, 255, 255))
    fundo.alpha_composite(im)
    lum = np.array(fundo.convert("L"))
    tinta = lum > a.limiar if a.fundo == "escuro" else lum < a.limiar
    if a.alpha_de:
        alpha = Image.open(a.alpha_de).convert("RGBA").getchannel("A").resize((W, H), Image.LANCZOS)
        tinta &= np.array(alpha) > 100
    tinta = ndi.median_filter(tinta.astype(np.uint8), size=5).astype(bool)
    if a.buracos:
        furos = ndi.binary_fill_holes(tinta) & ~tinta
        lab, n = ndi.label(furos)
        if n:
            areas = ndi.sum(furos, lab, np.arange(1, n + 1))
            pequenos = np.isin(lab, np.nonzero(areas < a.buracos)[0] + 1)
            tinta |= pequenos
    out = Image.fromarray(np.where(tinta, 0, 255).astype(np.uint8))
    if a.escala > 1:
        out = out.resize((W * a.escala, H * a.escala), Image.LANCZOS)
    if a.suavizar:
        out = out.filter(ImageFilter.GaussianBlur(a.suavizar))
    out = out.point(lambda v: 255 if v > 127 else 0)
    out.save(a.saida)
    print(a.saida, out.size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
