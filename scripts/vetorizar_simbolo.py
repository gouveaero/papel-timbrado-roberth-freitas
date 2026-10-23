#!/usr/bin/env python3
"""
Vetoriza um símbolo a partir de uma máscara preto-no-branco com acabamento de
desenho vetorial: contorno subpixel, cantos detectados e preservados, trechos
retos endireitados, curvas suavizadas e ajustadas em Bézier cúbicas com erro
controlado. Fios finos (separação entre letras sobrepostas) entram como traço
vetorial exato, subtraído por operação booleana, em vez de virem do bitmap.

    python3 vetorizar_simbolo.py <mascara.png> <saida.svg> [--fios fios.json]
        [--suavizar 0.008] [--canto 50] [--janela 0.010] [--reta 0.0018] [--reta-min 0.08] [--eixo 2.5]
        [--erro 0.0006] [--min-area 0.0004]

--suavizar  desvio do desfoque ao longo do contorno (tira serrilhado de textura)
--canto     ângulo mínimo, em graus, para um ponto virar canto vivo
--janela    distância usada para medir o ângulo do canto
--reta      desvio máximo para um trecho ser endireitado
--reta-min  comprimento mínimo do trecho reto (curvas abertas não viram reta)
--eixo      retas a menos desse ângulo (graus) do eixo viram exatamente horizontais/verticais
--alinhar  retas de eixo mais próximas que isso passam a ter a mesma coordenada
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


def _reta(pts):
    c = pts.mean(0)
    _, _, vt = np.linalg.svd(pts - c)
    return c, vt[0]


def _desvio(pts, c, u):
    rel = pts - c
    return rel[:, 0] * u[1] - rel[:, 1] * u[0]


def _curva_de_um_lado(sd, tol):
    interno = sd[len(sd) // 10: len(sd) - len(sd) // 10] if len(sd) > 20 else sd
    lado = np.mean(interno > 0)
    return (lado > 0.8 or lado < 0.2) and np.abs(sd).max() > 0.25 * tol


def _encaixe_eixo(pts, c, u, graus, tol):
    """Reta a menos de `graus` do eixo vira exatamente horizontal ou vertical."""
    ang = math.degrees(math.atan2(u[1], u[0])) % 180
    for alvo, eixo in ((0, (1.0, 0.0)), (180, (1.0, 0.0)), (90, (0.0, 1.0))):
        if abs(ang - alvo) <= graus:
            ue = np.array(eixo)
            if np.abs(_desvio(pts, c, ue)).max() <= tol * 1.4:
                return c, ue
    return c, u


def retas(seg, tol, comprimento_min, graus_eixo, encosta=0):
    """Trechos retos do segmento: [(a, b, centro, direção)], já fundidos e encaixados no eixo.
    Reta que termina a menos de `encosta` amostras do canto é estendida até ele."""
    if len(seg) < 6:
        return []
    vert = measure.approximate_polygon(seg, tolerance=tol * 0.8)
    idx, j = [], 0
    for v in vert:                                  # o RDP devolve pontos do próprio trecho, em ordem
        while j < len(seg) - 1 and not np.allclose(seg[j], v):
            j += 1
        idx.append(j)
    cand = []
    for a, b in zip(idx[:-1], idx[1:]):
        if b - a < 3:
            continue
        pts = seg[a:b + 1]
        c, u = _reta(pts)
        sd = _desvio(pts, c, u)
        if np.abs(sd).max() <= tol and not _curva_de_um_lado(sd, tol):
            cand.append([a, b])
    # funde vizinhos colineares (o RDP às vezes parte uma reta em duas com ângulos quase iguais)
    fundidos = []
    for a, b in cand:
        if fundidos and a - fundidos[-1][1] <= 2:
            a0 = fundidos[-1][0]
            c, u = _reta(seg[a0:b + 1])
            if np.abs(_desvio(seg[a0:b + 1], c, u)).max() <= tol:
                fundidos[-1][1] = b
                continue
        fundidos.append([a, b])
    out = []
    for a, b in fundidos:
        pts = seg[a:b + 1]
        if np.hypot(*(pts[-1] - pts[0])) < comprimento_min:
            continue
        c, u = _encaixe_eixo(pts, *_reta(pts), graus_eixo, tol)
        if np.dot(pts[-1] - pts[0], u) < 0:
            u = -u
        if a <= encosta:
            a = 0
        if b >= len(seg) - 1 - encosta:
            b = len(seg) - 1
        out.append((a, b, c, u))
    return out


def _proj(p, c, u):
    return c + np.dot(p - c, u) * u


def _cruza(c1, u1, c2, u2):
    A = np.array([u1, -u2]).T
    if abs(np.linalg.det(A)) < 1e-6:
        return None
    t = np.linalg.solve(A, c2 - c1)[0]
    return c1 + t * u1


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
    pen = path.getPen()
    if not cs:
        # laço sem canto: suaviza periodicamente e ajusta a partir do ponto 0
        s = np.c_[ndi.gaussian_filter1d(p[:, 0], sigma, mode="wrap"), ndi.gaussian_filter1d(p[:, 1], sigma, mode="wrap")]
        s = np.vstack([s, s[:1]])
        pen.moveTo(tuple(s[0]))
        for c in ajustar(s, tangente(s, True), tangente(s, False), erro):
            pen.curveTo(tuple(c[1]), tuple(c[2]), tuple(c[3]))
        pen.closePath()
        return

    # segmentos entre cantos, suavizados, com as retas detectadas
    segs, rets = [], []
    for a, b in zip(cs, cs[1:] + [cs[0] + len(p)]):
        idx = np.arange(a, b + 1) % len(p)
        seg = suavizar_trecho(p[idx], sigma)
        segs.append(seg)
        rets.append(retas(seg, tol, escala * args.reta_min, args.eixo, encosta=k))

    # alinha retas de eixo quase coincidentes (ex.: a borda da haste acima e abaixo de um braço)
    lim = escala * args.alinhar
    for eixo, comp in (("x", 0), ("y", 1)):
        itens = [(rs[j][2][comp], i, j) for i, rs in enumerate(rets) for j in range(len(rs))
                 if abs(rets[i][j][3][comp]) < 1e-9]              # vertical: u=(0,±1) → alinha x
        itens.sort()
        grupos, atual_g = [], []
        for item in itens:
            if atual_g and item[0] - atual_g[-1][0] > lim:
                grupos.append(atual_g); atual_g = []
            atual_g.append(item)
        if atual_g:
            grupos.append(atual_g)
        for g in grupos:
            if len(g) < 2:
                continue
            media = float(np.mean([v for v, _, _ in g]))
            for _, i, j in g:
                a, b, c, u = rets[i][j]
                c = c.copy(); c[comp] = media
                rets[i][j] = (a, b, c, u)

    # cantos: interseção de duas retas que chegam nele; senão, projeção na reta que chega
    n = len(segs)
    canto = []
    for i in range(n):
        anterior, seguinte = rets[i - 1], rets[i]
        ponto = segs[i][0]
        ra = anterior[-1] if anterior and anterior[-1][1] == len(segs[i - 1]) - 1 else None
        rb = seguinte[0] if seguinte and seguinte[0][0] == 0 else None
        if ra and rb:
            x = _cruza(ra[2], ra[3], rb[2], rb[3])
            if x is not None and np.hypot(*(x - ponto)) < escala * 0.02:
                ponto = x
            else:
                ponto = _proj(ponto, rb[2], rb[3])
        elif ra:
            ponto = _proj(ponto, ra[2], ra[3])
        elif rb:
            ponto = _proj(ponto, rb[2], rb[3])
        canto.append(np.asarray(ponto, float))

    pen.moveTo(tuple(canto[0]))
    for i, (seg, rs) in enumerate(zip(segs, rets)):
        fim_seg = canto[(i + 1) % n]
        pecas, cur = [], 0
        for a, b, c, u in rs:
            if a > cur:
                pecas.append(("C", cur, a, None))
            pecas.append(("L", a, b, (c, u)))
            cur = b
        if cur < len(seg) - 1:
            pecas.append(("C", cur, len(seg) - 1, None))
        atual = canto[i]
        for j, (tipo, a, b, reta) in enumerate(pecas):
            ultimo = j == len(pecas) - 1
            if tipo == "L":
                c, u = reta
                if ultimo:
                    fim_p = fim_seg
                elif pecas[j + 1][0] == "L":
                    # duas retas seguidas: o encontro é a interseção, não a projeção numa delas
                    x = _cruza(c, u, *pecas[j + 1][3])
                    fim_p = x if x is not None and np.hypot(*(x - seg[b])) < escala * 0.02 else _proj(seg[b], c, u)
                else:
                    fim_p = _proj(seg[b], c, u)
                pen.lineTo(tuple(fim_p))
                atual = fim_p
            else:
                prox = pecas[j + 1] if not ultimo else None
                fim_p = fim_seg if ultimo else _proj(seg[b], *prox[3])
                # a curva acompanha o deslocamento das retas vizinhas (encaixe no eixo, alinhamento,
                # interseção): sem isso sobra um "gancho" na junção
                pts = seg[a:b + 1].copy()
                t = np.linspace(0, 1, len(pts))[:, None]
                pts = pts + (atual - seg[a]) * (1 - t) + (fim_p - seg[b]) * t
                ant = pecas[j - 1] if j > 0 else None
                t1 = ant[3][1] if ant and ant[0] == "L" else tangente(pts, True)
                t2 = -prox[3][1] if prox and prox[0] == "L" else tangente(pts, False)
                if len(pts) < 3 or np.hypot(*(fim_p - atual)) < 1e-6:
                    pen.lineTo(tuple(fim_p))
                else:
                    for cb in ajustar(pts, _unit(t1), _unit(t2), erro):
                        pen.curveTo(tuple(cb[1]), tuple(cb[2]), tuple(cb[3]))
                atual = fim_p
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
    ap.add_argument("--reta-min", type=float, default=0.08)
    ap.add_argument("--eixo", type=float, default=2.5)
    ap.add_argument("--alinhar", type=float, default=0.002)
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
