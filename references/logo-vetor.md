# Logo em vetor a partir de raster ruim

O caso comum: o escritório só tem a logo do site, um PNG de ~500 px com dourado metálico, bevel e sombra. Ampliar não resolve (fica borrado na impressão) e vetorizar direto não serve (a textura vira dezenas de manchas e as bordas "escorrem"). O caminho que funciona é separar **símbolo** de **texto**.

## 1. Fontes de imagem

- Logo do site (`extrair_marca.py` baixa os candidatos em `marca/_site/`).
- **Favicon**: muitas vezes é o símbolo sozinho, em resolução maior que dentro da logo. Use para o símbolo.
- Instagram (foto de perfil, destaques) e posts com a logo aplicada.

## 2. Símbolo

**Procure primeiro um canal alfa.** Favicon e logos PNG de site quase sempre têm transparência: o alfa é o contorno exato do desenho, sem a textura do dourado, do relevo e da sombra. Ampliado com bicúbica (16x de um favicon de ~370 px), vira uma silhueta lisa e fiel. Medir pelo brilho da imagem (limiar de luminância) perde as bordas escuras do relevo e deixa o traço fino demais.

Sem alfa útil, faça upscale de precisão no Magnific (`images_upscale`, `ultra-sublime`, 4x, `grain: 0`) e gere a máscara com `scripts/mascara_logo.py`.

1. **Silhueta sólida.** Preencha furos pequenos (textura) e feche os canais finos de separação que saíram quebrados. Eles voltam depois como vetor. Guarde os fragmentos dos fios para saber por onde passam.
2. **Junções exatas.** Onde letras se cruzam (um triângulo entre duas letras, o fim de uma haste sobre uma perna), ajuste retas nas arestas, calcule os cantos pela interseção e repinte a região com geometria. É o que deixa canto vivo onde o desenho pede.
3. **Fios de separação como traço.** Monte `fios.json` com curvas (pontos por Catmull-Rom; ajuste polinomial nos fragmentos, ancorado nos cantos) e retas (de canto a canto). A espessura é constante.
4. **Vetorizar:** `python3 scripts/vetorizar_simbolo.py silhueta.png simbolo.svg --fios fios.json`.
   - Contorno subpixel e cantos detectados por ângulo.
   - Cada trecho entre cantos é suavizado, com os cantos fixos.
   - Trecho longo e sem curvatura de um lado só vira **segmento de reta exato** (não Bézier quase reta: é isso que deixa a logo "tortinha").
   - Reta a menos de 2,5° do eixo encaixa exatamente na horizontal ou na vertical (`--eixo`).
   - Retas de eixo quase coincidentes ficam com a mesma coordenada (`--alinhar`), como a borda de uma haste acima e abaixo de um braço.
   - Duas retas seguidas, ou que chegam a um canto, se encontram na interseção exata.
   - As curvas vizinhas acompanham o deslocamento das retas, sem gancho na junção, e saem com a tangente da reta.
   - Curvas em Bézier cúbica com erro controlado (Schneider).
   - Os fios são subtraídos por operação booleana (skia-pathops).
   - Resultado típico: algumas centenas de pontos, retas de verdade nos trechos retos, sem buracos nem serrilhado.
   - Para auditar, liste os `lineTo` longos do path: as hastes devem sair `VERT` e os braços `HORIZ`, com coordenada idêntica nas duas pontas.
5. **Conferir** em três níveis:
   - **Coincidência com o alfa original:** acima de 95%. Os fios ficam de fora, porque o alfa não os tem.
   - **Vista geral:** lado a lado com a original.
   - **Zoom nas junções:** pontas, cantos e encontros dos fios. Um fio que termina antes do canto, um recorte na junção ou uma reta com ângulo diferente da aresta vizinha aparecem no zoom e passam na vista geral.

A vetorização automática do Magnific (`images_to_svg`) serve como rascunho rápido, mas segue o serrilhado da máscara. Para entrega, use o `vetorizar_simbolo.py`.

## 3. Texto

Traçar letras de 40 px de altura nunca fica bom. Identifique a fonte e recomponha:

| Na logo parece | Livre equivalente (Google Fonts) |
|---|---|
| Trajan | Cinzel |
| Optima, romana com serifa "flare" | Marcellus |
| Didot, Bodoni | Bodoni Moda, Playfair Display |
| Garamond | EB Garamond, Cormorant Garamond |
| Baskerville | Libre Baskerville |
| Gotham | Montserrat |
| Futura | Jost |

Meça a logo original (altura de caixa de cada linha, topo, largura, recuo em relação ao símbolo) numa escala em que o símbolo = 1000 e passe para o `logo-spec.json`. Com `largura` em cada linha, o script ajusta o espaçamento entre letras para bater a largura medida. Se o tracking calculado ficar muito negativo (letras quase encostando), a fonte está pesada demais: troque o peso (ex.: Cinzel 800 → 700).

## 4. Conferir

Monte um comparativo (original em cima, nova embaixo, mesma largura, fundo escuro e fundo branco) e olhe peso, proporção, espaçamento entre linhas e o desenho do símbolo. Só siga para o timbre quando estiver fiel.

## 5. Cores

- **Fundo branco (papel):** gradiente dourado mais fechado (bronze → dourado → dourado claro discreto → bronze). O dourado muito claro some no branco.
- **Fundo escuro (capa):** gradiente com brilho (dourado → amarelo-claro → dourado).
- Sempre gere preto e branco também (fax, carimbo, impressão econômica, aplicação em foto).
