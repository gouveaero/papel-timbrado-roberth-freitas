# brand.json e logo-spec.json

Caminhos relativos são resolvidos a partir da pasta do próprio JSON.

## brand.json

```json
{
  "nome": "Nome Completo Advogados",          // metadados do .docx e do PDF
  "nome_curto": "Nome Completo",
  "tagline": null,                             // só se for do próprio escritório
  "site": "dominio.com.br",
  "contatos": {"endereco": "Rua X, 100, Bairro · Cidade/UF", "telefone": "(00) 00000-0000", "email": "contato@dominio.com.br"},
  "oab": null,                                 // "OAB/UF 0.000" entra no rodapé quando preenchido
  "cores": {
    "tinta": "#1A1A1A",            // texto corrido
    "escuro": "#121212",           // títulos e fundo da capa
    "primaria": "#B4850E",         // fios, números de página, marcadores
    "primaria_escura": "#8E6B1C",  // subtítulos e rótulos sobre branco
    "primaria_clara": "#E0AE2E",   // rótulos e subtítulo sobre a capa escura
    "destaque": "#F8E472",
    "cinza": "#5E5E5E",            // rodapé e metadados
    "linha": "#D9C9A3",            // fios finos
    "fundo_suave": "#FAF6EC",      // fundo da ementa
    "papel": "#FFFFFF"
  },
  "fontes": {
    "titulo": {"familia": "Playfair Display", "regular": "fonts/...ttf", "bold": "...", "italic": "...", "semibold": "..."},
    "texto":  {"familia": "Montserrat", "regular": "...", "bold": "...", "italic": "...", "medium": "...", "semibold": "..."}
  },
  "logo": {
    "papel": "logo/logo-assinatura-<cor>.svg",       // cabeçalho do PDF
    "papel_png": "logo/logo-assinatura-<cor>.png",   // cabeçalho do .docx
    "escuro": "logo/logo-assinatura-<clara>.svg",    // capa
    "simbolo": "logo/logo-simbolo-<cor>.svg",        // marca d'água do miolo
    "simbolo_png": "logo/logo-simbolo-<cor>.png",
    "simbolo_escuro": "logo/logo-simbolo-<clara>.svg" // símbolo gigante da capa
  },
  "documento": {
    "autor": "Nome Completo Advogados",  // dc:creator / Company; nunca quem executa
    "local": "Cidade/UF",
    "logo_mm": 50,                       // largura da logo no cabeçalho do Word
    "marca_dagua_pdf": true,
    "marca_dagua_docx": false
  }
}
```

Campos que começam com `_` são anotações e são ignorados.

## logo-spec.json

```json
{
  "simbolo": {"svg": "simbolo.svg", "ignorar_fill": ["rgb(255,255,255)"]},
  "altura_simbolo": 1000,
  "coluna_texto": {"recuo": 106},
  "linhas": [
    {"texto": "NOME", "fonte": "fonts/Cinzel-Bold.ttf", "topo": 106, "altura_caixa": 323, "largura": 2218},
    {"texto": "ADVOGADOS", "fonte": "fonts/Cinzel-Black.ttf", "topo": 842, "altura_caixa": 109, "tracking": 40}
  ],
  "margem": 20,
  "cores": {
    "dourado": {"gradiente": ["#8E6B1C", "#B4850E", "#D9AE45", "#E8C86A", "#C9962A", "#8E6B1C"], "angulo": 30},
    "preto": {"solido": "#121212"}
  },
  "png_largura": 3000
}
```

- `topo` e `altura_caixa` em unidades da escala em que o símbolo mede `altura_simbolo`.
- `largura` (alvo, medido na original) calcula o tracking sozinho; `tracking` (unidades da fonte) é a alternativa manual.
- Sem `linhas`, sai só o símbolo.
