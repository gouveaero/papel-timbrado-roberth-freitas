# Logo em vetor a partir de raster ruim

O caso comum: o escritório só tem a logo do site, um PNG de ~500 px com dourado metálico, bevel e sombra. Ampliar não resolve (fica borrado na impressão) e vetorizar direto não serve (a textura vira dezenas de manchas e as bordas "escorrem"). O caminho que funciona é separar **símbolo** de **texto**.

## 1. Fontes de imagem

- Logo do site (`extrair_marca.py` baixa os candidatos em `marca/_site/`).
- **Favicon**: muitas vezes é o símbolo sozinho, em resolução maior que dentro da logo. Use para o símbolo.
- Instagram (foto de perfil, destaques) e posts com a logo aplicada.

## 2. Símbolo

1. **Upscale de precisão** no Magnific: `creations_upload_image` (URL pública) → `images_upscale` com `mode: ultra-sublime`, `scale: 4x`, `grain: 0`, `sharpness: ~10`. Custo típico: ~180 créditos por imagem. Avise antes e confira com `simulate_cost`.
   - O upscale achata o fundo transparente em preto e pode criar franja colorida na borda. Isso não atrapalha, porque só a silhueta interessa.
2. **Máscara**: `python3 scripts/mascara_logo.py upscale.jpg mascara.png --alpha-de original.png --limiar 45 --buracos 400`
   - `--alpha-de` recorta pela transparência do PNG original e elimina a sombra.
   - Comece com `--buracos` baixo (só pontinhos de textura). Furo grande pode ser desenho de verdade.
   - **Fios finos de separação** (uma letra passando na frente da outra) quase sempre saem quebrados. Redesenhe: preencha os furos na região, ajuste uma curva (`numpy.polyfit` de x em função de y) pelos fragmentos que sobraram e desenhe o fio como linha contínua (PIL `ImageDraw.line`, `joint="curve"`). Em trechos retos, uma linha entre dois pontos medidos no zoom basta. Confira sempre num recorte ampliado.
3. **Vetorizar**: envie a máscara (`creations_request_upload` → PUT do arquivo → `creations_finalize_upload`) e rode `images_to_svg` (~150 créditos). O retorno é um retângulo branco de fundo + um path preto composto. O `logo_svg.py` ignora o fundo (`ignorar_fill`).

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
