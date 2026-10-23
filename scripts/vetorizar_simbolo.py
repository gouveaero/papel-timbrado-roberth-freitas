#!/usr/bin/env python3
"""
Vetoriza um símbolo a partir de uma máscara preto-no-branco com acabamento de
desenho vetorial: contorno subpixel, cantos detectados e preservados, trechos
retos endireitados, curvas suavizadas e ajustadas em Bézier cúbicas com erro
controlado. Fios finos (separação entre letras sobrepostas) entram como traço
vetorial exato, subtraído por operação booleana, em vez de virem do bitmap.

    python3 vetorizar_simbolo.py <mascara.png> <saida.svg> [--fios fios.json]
        [--suavizar 0.008] [--canto 50] [--janela 0.010] [--reta 0.0018] [--reta-min 0.065]
        [--erro 0.0006] [--min-area 0.0004]

--suavizar  desvio do desfoque ao longo do contorno (tira serrilhado de textura)
--canto     ângulo mínimo, em graus, para um ponto virar canto vivo
--janela    distância usada para medir o ângulo do canto
--reta      desvio máximo para um trecho ser endireitado
--reta-min  comprimento mínimo do trecho reto (curvas abertas não viram reta)
--erro      erro máximo do ajuste das Bézier

Medidas relativas ao maior lado da máscara (0.004 = 0,4%).

fios.json (coordenadas em pixels da máscara):
    {"largura": 30, "tracos": [
        {"tipo": "curva", "pontos": [[x, y], ...]},     # Catmull-Rom suave pelos pontos
        {"tipo": "linha", "pontos": [[x1, y1], [x2, y2]]}
    ]}

Requer: numpy, scipy, scikit-image, skia-pathops, Pillow, fontTools.
"""
import argparse
import json
import math

import numpy as np
import pathops
from fontTools.pens.svgPathPen import SVGPathPen
from PIL import Image
from scipy import ndimage as ndi
from skimage import measure


# ---------------------------------------------------------------- contorno


def contornos(mascara, min_area):
    tinta = (np.asarray(Image.open(mascara).convert("L"), dtype=float) < 128).astype(float)
    tinta = ndi.gaussian_filter(tinta, 1.2)
    H, W = tinta.shape
    saida = []
    for c in measure.find_contours(np.pad(tinta, 2), 0.5):
        xy = np.c_[c[:, 1] - 2, c[:, 0] - 2]
        area = 0.5 * abs(np.dot(xy[:-1, 0], xy[1:, 1]) - np.dot(xy[1:, 0], xy[:-1, 1]))
        if area >= min_area * H * W:
            saida.append(xy[:-1] if np.allclose(xy[0], xy[-1]) else xy)
    return saida, max(H, W)


def reamostrar(xy, passo):
    fechado = np.vstack([xy, xy[:1]])
    d = np.r_[0, np.cumsum(np.hypot(*np.diff(fechado, axis=0).T))]
    n = max(int(d[-1] / passo), 12)
    t = np.linspace(0, d[-1], n, endpoint=False)
    return np.c_[np.interp(t, d, fechado[:, 0]), np.interp(t, d, fechado[:, 1])]


def cantos(p, k, limiar_graus):
    n = len(p)
    v1 = p - np.roll(p, k, axis=0)
    v2 = np.roll(p, -k, axis=0) - p
    ang = np.degrees(np.abs(np.arctan2(v1[:, 0] * v2[:, 1] - v1[:, 1] * v2[:, 0], (v1 * v2).sum(1))))
    idx = []
    for i in np.argsort(-ang):
        if ang[i] < limiar_graus:
            break
        if all(min(abs(i - j), n - abs(i - j)) > k for j in idx):
            idx.append(int(i))
    return sorted(idx)


def suavizar_trecho(seg, sigma):
    if len(seg) < 5:
        return seg
    s = np.c_[ndi.gaussian_filter1d(seg[:, 0], sigma, mode="nearest"),
              ndi.gaussian_filter1d(seg[:, 1], sigma, mode="nearest")]
    t = np.linspace(0, 1, len(seg))[:, None]
    return s + (seg[0] - s[0]) * (1 - t) + (seg[-1] - s[-1]) * t


def endireitar(seg, tol, comprimento_min):
    """Projeta na reta os trechos que já são retos dentro da tolerância."""
    if len(seg) < 4:
        return seg
    vert = measure.approximate_polygon(seg, tolerance=tol)
    out = seg.copy()
    # índices dos vértices do RDP no trecho original
    pos = [int(np.argmin(np.hypot(*(seg - v).T))) for v in vert]
    for a, b in zip(pos[:-1], pos[1:]):
        if b - a < 3:
            continue
        A, B = seg[a], seg[b]
        L = np.hypot(*(B - A))
        if L < comprimento_min:
            continue
        u = (B - A) / L
        rel = seg[a:b + 1] - A
        sd = rel[:, 0] * u[1] - rel[:, 1] * u[0]
        if np.abs(sd).max() > tol:
            continue
        # arco suave fica todo de um lado da corda: não é reta, é curva aberta
        interno = sd[len(sd) // 10: len(sd) - len(sd) // 10] if len(sd) > 20 else sd
        lado = np.mean(interno > 0)
        if (lado > 0.85 or lado < 0.15) and np.abs(sd).max() > 0.35 * tol:
            continue
        out[a:b + 1] = A + np.outer((rel * u).sum(1), u)
    return out


# ---------------------------------------------------------------- Bézier (Schneider, Graphics Gems I)


def _bez(c, t):
    t = np.asarray(t)[:, None]
    mt = 1 - t
    return mt ** 3 * c[0] + 3 * mt ** 2 * t * c[1] + 3 * mt * t ** 2 * c[2] + t ** 3 * c[3]


def _bez_d(c, t):
    t = np.asarray(t)[:, None]
    mt = 1 - t
    return 3 * mt ** 2 * (c[1] - c[0]) + 6 * mt * t * (c[2] - c[1]) + 3 * t ** 2 * (c[3] - c[2])


def _bez_dd(c, t):
    t = np.asarray(t)[:, None]
    return 6 * (1 - t) * (c[2] - 2 * c[1] + c[0]) + 6 * t * (c[3] - 2 * c[2] + c[1])


def _gerar(p, u, t1, t2):
    A1 = np.outer(3 * (1 - u) ** 2 * u, t1)
    A2 = np.outer(3 * (1 - u) * u ** 2, t2)
    C = np.array([[np.sum(A1 * A1), np.sum(A1 * A2)], [np.sum(A1 * A2), np.sum(A2 * A2)]])
    base = _bez(np.array([p[0], p[0], p[-1], p[-1]]), u)
    tmp = p - base
    X = np.array([np.sum(A1 * tmp), np.sum(A2 * tmp)])
    det = C[0, 0] * C[1, 1] - C[0, 1] * C[1, 0]
    seg = np.hypot(*(p[-1] - p[0]))
    if abs(det) > 1e-12:
        a1 = (X[0] * C[1, 1] - X[1] * C[0, 1]) / det
        a2 = (C[0, 0] * X[1] - C[1, 0] * X[0]) / det
    else:
        a1 = a2 = seg / 3
    if a1 < 1e-6 * seg or a2 < 1e-6 * seg:
        a1 = a2 = seg / 3
    return np.array([p[0], p[0] + t1 * a1, p[-1] + t2 * a2, p[-1]])


def _param(p):
    d = np.r_[0, np.cumsum(np.hypot(*np.diff(p, axis=0).T))]
    return d / d[-1] if d[-1] > 0 else np.linspace(0, 1, len(p))


def _reparam(c, p, u):
    d = _bez(c, u) - p
    d1, d2 = _bez_d(c, u), _bez_dd(c, u)
    num = (d * d1).sum(1)
    den = (d1 * d1).sum(1) + (d * d2).sum(1)
    with np.errstate(divide="ignore", invalid="ignore"):
        nu = np.where(np.abs(den) > 1e-12, u - num / den, u)
    return np.clip(nu, 0, 1)


def _unit(v):
    n = np.hypot(*v)
    return v / n if n > 1e-12 else v


def ajustar(p, t1, t2, erro, profundidade=0):
    if len(p) == 2:
        L = np.hypot(*(p[1] - p[0])) / 3
        return [np.array([p[0], p[0] + t1 * L, p[1] + t2 * L, p[1]])]
    u = _param(p)
    c = _gerar(p, u, t1, t2)
    dist = np.hypot(*(_bez(c, u) - p).T)
    imax = int(np.argmax(dist))
    if dist[imax] < erro:
        return [c]
    if dist[imax] < erro * 4:
        for _ in range(20):
            u = _reparam(c, p, u)
            c = _gerar(p, u, t1, t2)
            dist = np.hypot(*(_bez(c, u) - p).T)
            imax = int(np.argmax(dist))
            if dist[imax] < erro:
                return [c]
    imax = min(max(imax, 1), len(p) - 2)
    if profundidade > 40:
        return [c]
    tc = _unit(p[imax - 1] - p[imax + 1])
    return ajustar(p[:imax + 1], t1, tc, erro, profundidade + 1) + ajustar(p[imax:], -tc, t2, erro, profundidade + 1)


def tangente(p, inicio, k=6):
    k = min(k, len(p) - 1)
    return _unit(p[k] - p[0]) if inicio else _unit(p[-1 - k] - p[-1])


# ---------------------------------------------------------------- contorno → path


def contorno_para_path(xy, escala, args, path):
    passo = max(escala * 0.0004, 1.0)
    p = reamostrar(xy, passo)
    k = max(int(escala * args.janela / passo), 4)
    cs = cantos(p, k, args.canto)
    sigma = max(escala * args.suavizar / passo, 1.0)
    tol = escala * args.reta
    erro = escala * args.erro
    if not cs:
        # laço sem canto: suaviza periodicamente e ajusta a partir do ponto 0
        s = np.c_[ndi.gaussian_filter1d(p[:, 0], sigma, mode="wrap"), ndi.gaussian_filter1d(p[:, 1], sigma, mode="wrap")]
        segs = [np.vstack([s, s[:1]])]
    else:
        segs = []
        for a, b in zip(cs, cs[1:] + [cs[0] + len(p)]):
            idx = np.arange(a, b + 1) % len(p)
            seg = suavizar_trecho(p[idx], sigma)
            segs.append(endireitar(seg, tol, escala * args.reta_min))
    pen = path.getPen()
    pen.moveTo(tuple(segs[0][0]))
    for seg in segs:
        if len(seg) < 2:
            continue
        for c in ajustar(seg, tangente(seg, True), tangente(seg, False), erro):
            pen.curveTo(tuple(c[1]), tuple(c[2]), tuple(c[3]))
    pen.closePath()


def catmull_rom(pontos):
    p = np.asarray(pontos, dtype=float)
    p = np.vstack([p[0] * 2 - p[1], p, p[-1] * 2 - p[-2]])
    out = []
    for i in range(1, len(p) - 2):
        p0, p1, p2, p3 = p[i - 1], p[i], p[i + 1], p[i + 2]
        out.append((p1 + (p2 - p0) / 6, p2 - (p3 - p1) / 6, p2))
    return out


def fios_path(fios):
    total = pathops.Path()
    for t in fios.get("tracos", []):
        linha = pathops.Path()
        pen = linha.getPen()
        pts = t["pontos"]
        pen.moveTo(tuple(pts[0]))
        if t.get("tipo") == "curva" and len(pts) > 2:
            for c1, c2, p2 in catmull_rom(pts):
                pen.curveTo(tuple(c1), tuple(c2), tuple(p2))
        else:
            for q in pts[1:]:
                pen.lineTo(tuple(q))
        pen.endPath()
        largura = t.get("largura", fios.get("largura", 10))
        linha.stroke(largura, pathops.LineCap.ROUND_CAP, pathops.LineJoin.ROUND_JOIN, 4)
        linha.convertConicsToQuads()
        total = pathops.op(total, linha, pathops.PathOp.UNION)
    return total


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mascara")
    ap.add_argument("saida")
    ap.add_argument("--fios")
    ap.add_argument("--suavizar", type=float, default=0.008)
    ap.add_argument("--canto", type=float, default=50)
    ap.add_argument("--janela", type=float, default=0.010)
    ap.add_argument("--reta", type=float, default=0.0018)
    ap.add_argument("--reta-min", type=float, default=0.065)
    ap.add_argument("--erro", type=float, default=0.0006)
    ap.add_argument("--min-area", type=float, default=0.0004)
    args = ap.parse_args()

    xys, escala = contornos(args.mascara, args.min_area)
    bruto = pathops.Path(fillType=pathops.FillType.EVEN_ODD)
    for xy in xys:
        contorno_para_path(xy, escala, args, bruto)
    forma = pathops.simplify(bruto, fix_winding=True)
    if args.fios:
        forma = pathops.op(forma, fios_path(json.load(open(args.fios))), pathops.PathOp.DIFFERENCE)

    x0, y0, x1, y1 = forma.bounds
    m = escala * 0.01
    pen = SVGPathPen(None, ntos=lambda v: f"{v:.2f}".rstrip("0").rstrip("."))
    forma.draw(pen)
    d = pen.getCommands()
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0 - m:.2f} {y0 - m:.2f} {x1 - x0 + 2 * m:.2f} {y1 - y0 + 2 * m:.2f}">'
           f'<path fill="#000" d="{d}"/></svg>\n')
    open(args.saida, "w").write(svg)
    # o SVGPathPen omite comandos repetidos (L/C implícitos): conta pares de coordenadas
    import re as _re
    nos = len(_re.findall(r"-?\d+(?:\.\d+)?", d)) // 2
    print(f"{args.saida} · {len(xys)} contorno(s) · {nos} pontos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
