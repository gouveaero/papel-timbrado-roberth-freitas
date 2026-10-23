---
name: papel-timbrado
description: Use quando precisar criar o papel timbrado ou a identidade de documentos de um escritório (advocacia, contabilidade, consultoria) e entregar documentos já na marca dele, inclusive em white label. Triggers - "cria o papel timbrado do escritório X", "faz o timbre do parceiro", "manda esse parecer na identidade visual dele", "documento timbrado", "white label com a marca do escritório", "refaz a logo em vetor para o timbre", "passa esse .md/.docx para o PDF timbrado". Levanta a marca pelo site, refaz a logo em vetor (símbolo vetorizado + texto em curvas), gera o .docx timbrado (cabeçalho, rodapé, estilos, fontes embutidas), o PDF de apresentação (capa + miolo timbrado) e trava o white label. NÃO use para carrossel ou post (content-machine-pro), deck de slides (slidev-presentation) nem manual de marca completo (brand-guidelines).
---

# Papel timbrado

Transforma a marca de um escritório em três coisas que ele usa no dia a dia:

1. **Logo em vetor** (SVG + PNG transparente, em dourado/cor da marca, claro, preto e branco).
2. **Timbrado Word** (`.docx`): cabeçalho com logo, rodapé com contatos e paginação, estilos nomeados (Title, Heading, Ementa, Assinatura, Pendente...) e fontes embutidas. É onde o advogado escreve.
3. **PDF de apresentação**: capa escura sangrada + miolo com cabeçalho, rodapé, paginação e marca d'água. É o que vai para o cliente final.
4. **Manual de marca** (PDF A4 paisagem) e **pacote de entrega** (pasta + zip com manual, logos, timbrado, modelo e fontes).

Tudo sai de um `brand.json` por escritório. Os scripts estão em `scripts/`; o modelo do PDF em `assets/documento.html`.

## Antes de começar

- **Pasta do cliente fora da skill.** Crie `<projeto>/<parceiro>/marca/` (logo, fontes, brand.json), `timbrado/` e `documentos/<data>_<slug>/`. Nada de cliente entra no repositório da skill.
- **Python com as dependências:** `fonttools`, `python-docx`, `pillow`, `numpy`, `scipy`, `scikit-image`, `skia-pathops`, `playwright` (+ `python -m playwright install chromium`). Ferramentas: `pandoc`, `hb-shape` (HarfBuzz), `pdftotext`/`pdfinfo`/`pdftoppm` (poppler).
- **White label é regra, não opção.** O documento não pode carregar, em lugar nenhum, o nome de quem executa o trabalho. Vale para o texto, os metadados, os nomes de arquivo e os comentários.

## Fluxo

### 1. Levantar a marca

```bash
python3 scripts/extrair_marca.py https://site-do-escritorio.com.br <cliente>/marca
```

Gera `brand.rascunho.json`, com cores (hex/rgb/hsl/oklch → hex), fontes do Google Fonts, e-mails, telefones, endereços e OABs citadas, e baixa os candidatos a logo em `_site/`. **Tudo vai para `_confirmar`**: sites feitos em Lovable/templates costumam ter dados de exemplo esquecidos (endereço "Av. FAB, 1234", telefone "(96) 99999-9999"). Escolha à mão e confirme com o escritório o que for duvidoso (qual e-mail, se entra nº de OAB).

Instagram: o perfil público (bio, nome) dá o posicionamento; para baixar imagens use a skill `instagram-download`.

### 2. Refazer a logo em vetor

Logo de site costuma ser PNG pequeno, muitas vezes com textura metálica, bevel e sombra. **Não vetorize a imagem crua**: o traço sai "escorrendo". Separe símbolo e texto (procedimento completo em `references/logo-vetor.md`):

- **Símbolo:** comece pelo **canal alfa** do favicon ou do PNG do site, que é o contorno limpo, sem textura. Se não houver, use o upscale de precisão do Magnific + `scripts/mascara_logo.py`. Feche furos e canais quebrados, reconstrua as junções com geometria (cantos por interseção de retas) e vetorize com `scripts/vetorizar_simbolo.py`. Ele detecta cantos, suaviza, endireita retas, ajusta em Bézier e subtrai os fios de separação como traço vetorial (`fios.json`). Confira a coincidência com o alfa (>95%) e dê zoom nas junções.
- **Texto:** identifique a fonte (ex.: Trajan → Cinzel) e recomponha com o texto convertido em curvas.
- **Montagem:** `scripts/logo_svg.py <logo-spec.json> <cliente>/marca/logo`. O spec traz o SVG do símbolo, as linhas de texto (fonte, topo, altura de caixa, largura alvo) e as cores. Gera `logo-assinatura-*` e `logo-simbolo-*` em SVG e PNG.
- **Compare lado a lado com a original** antes de seguir. Ajuste peso da fonte e largura até bater.

Fontes: `scripts/baixar_fontes.py <cliente>/marca/fonts "Playfair Display:400,600,700,400i" "Montserrat:400,500,600,700,400i"` gera TTFs estáticos com nomes que o Word reconhece.

### 3. Timbrado Word

```bash
python3 scripts/gerar_docx.py <cliente>/marca/brand.json "<cliente>/timbrado/Timbrado - <Escritório>.docx"
python3 scripts/gerar_docx.py <cliente>/marca/brand.json "<doc>.docx" --conteudo conteudo.md   # documento já no timbre
```

- A4, margens 36/22/28/24 mm. Logo no cabeçalho (`documento.logo_mm`, padrão 50 mm) com fio na cor primária; rodapé com endereço · telefone / e-mail · site e o número da página.
- **Fontes embutidas** (subset latino, ofuscado conforme ECMA-376): o documento não vira Calibri na máquina de quem não tem a fonte.
- **Marca d'água desligada no Word** (`marca_dagua_docx: false`): imagem flutuante atrás do texto em cabeçalho muda de lugar entre Word, Google Docs e WPS. O PDF leva a marca d'água.
- O `.md` usa `##` para seções (vira Heading 1 no Word), `###` para subtítulos, `>` para ementa, `[[a redigir]]{custom-style="Pendente"}` para pendências e divs `::: {custom-style="Assinatura"}` / `"Cargo"` / `"Local e data"`. Exemplo completo em `exemplos/escritorio-ficticio/conteudo.md`.
- Prévia sem Word: `scripts/previa_docx.py <arquivo.docx> <pasta>`, que renderiza com docx-preview no Chromium. Ela não pagina e é uma aproximação. **O teste final é abrir no Word.**

### 4. PDF de apresentação

```bash
python3 scripts/gerar_pdf.py <cliente>/marca/brand.json conteudo.md saida.pdf
python3 scripts/gerar_pdf.py <cliente>/marca/brand.json escrito-no-word.docx saida.pdf --cliente "Empresa X" --data "23 de outubro de 2026"
```

- Capa (`@page capa`, sangrada, fundo `cores.escuro`, logo clara, símbolo gigante a 8% de opacidade) e miolo com timbre por `@page`: logo no canto, título curto à direita, contatos e página `02, 03...` no rodapé, fios e marca d'água no fundo da página.
- Entrada `.docx` (o advogado escreveu no timbrado): título e subtítulo saem dos estilos Title/Subtitle; destinatário, data e referência vêm das opções.
- **Capa preenchida:** o rótulo leva tipo e referência; os dados trazem destinatário, preparado por (`responsavel` do brand.json, com OAB) e local e data; embaixo, um bloco de contato com telefone, e-mail, site e endereço. Sem destinatário, a coluna some, e nada vira placeholder.
- `--sem-capa` para carta/ofício curto; `--html arquivo.html` guarda o HTML para ajuste fino.

### 5. Travar o white label

```bash
python3 scripts/checar_white_label.py <arquivos...> --proibir "nome da executora,sobrenome,dominio.com.br"
```

Varre texto, XML interno do .docx, metadados e bytes do PDF, sem diferenciar acentos e maiúsculas, e barra caminhos absolutos (`/Users/...`). Os termos também podem vir de `PAPEL_TIMBRADO_PROIBIDOS` ou de `scripts/proibidos.local.json` (ignorado pelo git). **Rode antes de qualquer envio.** Se sair código 1, não envie.

### 6. Manual de marca e pacote

```bash
python3 scripts/gerar_manual.py <cliente>/marca/brand.json "<entrega>/01 Manual de Marca.pdf"
```

Páginas: capa, nota sobre a reconstrução da logo (com antes e depois ampliados), o escritório (história, missão, visão, valores, áreas, tom de voz), a logo (assinatura completa + logomarca lado a lado), tipografia da logo (cada fonte com a amostra composta e as regras de construção), versões, área de proteção e tamanho mínimo, cores (HEX, RGB, CMYK aproximado), tipografia, aplicações, usos incorretos, presença digital, arquivos entregues e contracapa. Tudo vem do bloco `manual` do brand.json. As páginas opcionais (`nota`, `sobre`, `presenca`, `aplicacoes`, `arquivos`) só entram se existirem.

- **Pesquise antes de escrever "o escritório":** site (textos institucionais, equipe, áreas), Instagram (bio), whois do registro.br (data e titular do domínio) e DNS (`dig MX`), para saber se os e-mails publicados existem. Guarde a pesquisa completa num arquivo interno; no manual entra só o que é público e útil ao cliente.
- **Resumo de busca na web não é fonte.** Número, prêmio ou estatística só entra se aparecer no site ou em documento do próprio escritório.
- **A nota sobre a logo é diplomática:** explica a limitação técnica do arquivo antigo, sem criticar o desenho, e deixa claro que a marca é a mesma.
- **Número de OAB:** busque no Diário Eletrônico da OAB (deoab.oab.org.br, PDFs indexados pela busca), que é fonte oficial. O CNA bloqueia consulta automatizada. Confirme com o escritório quando o nome completo não bater exatamente.
- **Pacote:** `01 Manual de Marca.pdf`, `02 Logo/SVG` e `02 Logo/PNG` (nomes legíveis, sem acento), `03 Papel Timbrado` (timbrado, modelo .docx e .pdf), `04 Fontes` (TTF + licença OFL). Zip com `zip -qr -X`, sem `.DS_Store`. Rode o `checar_white_label.py` no pacote inteiro antes de zipar.

### 7. Aprovação

Mostre ao usuário as páginas do PDF em PNG (`pdftoppm -r 70 -png`), a prévia do .docx e o comparativo da logo. Nada vai para o escritório parceiro sem o OK de quem pediu.

## Conteúdo jurídico

- **Fato jurídico só com fonte primária** (portal do STF/STJ, Diário Oficial, lei no Planalto). Notícia de portal ajuda a achar, mas não é a fonte. Cite a fonte em nota.
- O que não foi confirmado fica marcado `[[conferir ...]]{custom-style="Pendente"}`; o que cabe ao advogado redigir fica `[[a redigir]]`. Os dois aparecem em destaque no Word e no PDF, e o advogado apaga ao preencher.
- Publicidade da advocacia: o documento é informativo; nada de promessa de resultado ou de valor a recuperar.
- Esta skill monta forma e estrutura. Não redige parecer no lugar do advogado.

## O que tem aqui

| Arquivo | Função |
|---|---|
| `scripts/extrair_marca.py` | site → `brand.rascunho.json` + logos candidatas |
| `scripts/mascara_logo.py` | logo texturizada → máscara limpa para vetorizar |
| `scripts/vetorizar_simbolo.py` | máscara → símbolo em vetor de acabamento profissional (cantos, retas, Bézier, fios booleanos) |
| `scripts/logo_svg.py` | símbolo SVG + texto em curvas (HarfBuzz) → logo em variantes de cor, SVG + PNG |
| `scripts/baixar_fontes.py` | Google Fonts → TTFs estáticos com nomes de Word |
| `scripts/gerar_docx.py` | brand.json → timbrado .docx; com `--conteudo`, documento pronto |
| `scripts/gerar_pdf.py` | brand.json + .md/.docx → PDF com capa e timbre |
| `scripts/gerar_manual.py` | brand.json → manual de marca em PDF (A4 paisagem) |
| `scripts/previa_docx.py` | .docx → PNG sem Word |
| `scripts/checar_white_label.py` | trava de termos proibidos e caminhos |
| `assets/documento.html` | modelo do PDF (CSS de página, capa, tipografia) |
| `assets/manual.html` | modelo do manual de marca |
| `references/logo-vetor.md` | passo a passo da logo + fontes livres equivalentes |
| `references/brand-json.md` | campos do brand.json e do logo-spec.json |
| `exemplos/escritorio-ficticio/` | marca inventada para testar tudo de ponta a ponta |
