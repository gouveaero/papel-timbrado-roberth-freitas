#!/usr/bin/env python3
"""
Trava de white label: confere se um .docx, .pdf, .html ou .svg não carrega o
nome de quem executou o trabalho, em lugar nenhum (texto, metadados, XML
interno, nomes de arquivo embutidos, caminhos absolutos).

    python3 checar_white_label.py <arquivo> [<arquivo> ...] --proibir "termo1,termo2"

Os termos também podem vir de PAPEL_TIMBRADO_PROIBIDOS (separados por vírgula)
ou de um proibidos.local.json ao lado do script ({"termos": [...]}). Busca sem
diferenciar maiúsculas nem acentos. Sai com código 1 se achar qualquer coisa.

Requer: pdftotext e pdfinfo (poppler) para PDF.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import unicodedata
import zipfile

SEMPRE = [r"/Users/", r"C:\\Users\\", r"/home/[a-z]"]


def norm(t):
    t = unicodedata.normalize("NFKD", t)
    return "".join(ch for ch in t if not unicodedata.combining(ch)).lower()


def textos(path):
    """Gera (origem, texto) para cada parte inspecionável do arquivo."""
    ext = path.lower().rsplit(".", 1)[-1]
    if ext == "docx":
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                yield f"nome de parte: {n}", n
                if n.endswith((".xml", ".rels")):
                    yield n, z.read(n).decode("utf-8", "replace")
    elif ext == "pdf":
        yield "texto do PDF", subprocess.run(["pdftotext", "-q", path, "-"], capture_output=True, text=True).stdout
        yield "metadados do PDF", subprocess.run(["pdfinfo", path], capture_output=True, text=True).stdout
        bruto = open(path, "rb").read().decode("latin-1")
        yield "bytes do PDF", bruto
    else:
        yield "arquivo", open(path, encoding="utf-8", errors="replace").read()
    yield "nome do arquivo", os.path.basename(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("arquivos", nargs="+")
    ap.add_argument("--proibir", default="")
    a = ap.parse_args()

    termos = [t.strip() for t in a.proibir.split(",") if t.strip()]
    termos += [t.strip() for t in os.environ.get("PAPEL_TIMBRADO_PROIBIDOS", "").split(",") if t.strip()]
    local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "proibidos.local.json")
    if os.path.exists(local):
        termos += json.load(open(local, encoding="utf-8")).get("termos", [])
    if not termos:
        print("aviso: nenhum termo proibido informado; checando só caminhos absolutos", file=sys.stderr)

    padroes = [(t, re.compile(re.escape(norm(t)))) for t in termos] + [(p, re.compile(p, re.I)) for p in SEMPRE]
    achados = 0
    for arq in a.arquivos:
        ok = True
        for origem, txt in textos(arq):
            alvo = norm(txt)
            for termo, rx in padroes:
                m = rx.search(alvo) if termo not in SEMPRE else rx.search(txt)
                if m:
                    ok = False
                    achados += 1
                    trecho = alvo[max(0, m.start() - 40):m.end() + 40].replace("\n", " ")
                    print(f"✗ {os.path.basename(arq)} · {origem} · '{termo}' · …{trecho}…")
        if ok:
            print(f"✓ {os.path.basename(arq)}")
    return 1 if achados else 0


if __name__ == "__main__":
    raise SystemExit(main())
