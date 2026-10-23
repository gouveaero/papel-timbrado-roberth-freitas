#!/usr/bin/env python3
"""
Prévia de um .docx sem Word: renderiza no Chromium com a biblioteca docx-preview
(cabeçalho, rodapé, imagens e fontes embutidas) e salva um PNG por página.

    python3 previa_docx.py <arquivo.docx> <pasta_saida>

É uma aproximação do Word, boa para pegar erro de layout e de fonte. A palavra
final continua sendo abrir no Word.

Requer: Playwright + Chromium e acesso à CDN jsDelivr.
"""
import base64
import os
import sys

LIBS = [
    "https://cdn.jsdelivr.net/npm/jszip@3.10.1/dist/jszip.min.js",
    "https://cdn.jsdelivr.net/npm/docx-preview@0.4.0/dist/docx-preview.min.js",
]


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    src, out = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    os.makedirs(out, exist_ok=True)
    b64 = base64.b64encode(open(src, "rb").read()).decode()
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 900, "height": 1200}, device_scale_factor=2)
        page.set_content('<html><body style="margin:0;background:#888"><div id="c"></div></body></html>')
        for u in LIBS:
            page.add_script_tag(url=u)
        n = page.evaluate("""async (b64) => {
            const bin = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
            await docx.renderAsync(bin, document.getElementById('c'), null, {
                inWrapper: true, ignoreWidth: false, ignoreHeight: false, breakPages: true,
                renderHeaders: true, renderFooters: true, renderFootnotes: true,
                useBase64URL: true, experimental: true });
            await document.fonts.ready;
            return document.querySelectorAll('section.docx').length;
        }""", b64)
        page.wait_for_timeout(800)
        paginas = page.locator("section.docx")
        for i in range(n):
            paginas.nth(i).screenshot(path=os.path.join(out, f"pagina-{i + 1:02d}.png"))
        b.close()
    print(f"{n} página(s) em {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
