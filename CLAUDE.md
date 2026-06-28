# Dashboard Mercado Commodities — Vila Vitória

## Visão Geral

Sistema de monitoramento de commodities agrícolas para o Departamento de Compras.
Atualizado automaticamente às **07h00 BRT** em dias úteis via GitHub Actions.
Hospedado como **GitHub Pages** (site estático, zero custo).

## Commodities Monitoradas

| Commodity | Unidade | Fonte Primária | Fallback |
|---|---|---|---|
| Arroz em Casca | R$/sc 50kg | CEPEA/IRGA-RS | NoticiasAgricolas |
| Feijão Carioca | R$/sc 60kg | CEPEA/CNA | NoticiasAgricolas |
| Feijão Preto | R$/sc 60kg | IBRAFE | NoticiasAgricolas |
| Açúcar Cristal (ICUMSA 130-180) | R$/sc 50kg | CEPEA/ESALQ (SP) | UNICAdata |
| Soja | R$/sc 60kg | CEPEA/Paranaguá | FAEP |
| Trigo | R$/sc 60kg | CEPEA/ESALQ | NoticiasAgricolas |
| Café Arábica (Tipo 6) | R$/sc 60kg | CEPEA/ESALQ | cotacaodocafe.com |
| Leite ao Produtor | R$/litro | CEPEA/CNA | MilkPoint / Scot |
| Dólar USD/BRL | R$ | AwesomeAPI | — |

**Atenção açúcar:** o dashboard acompanha exclusivamente Açúcar Cristal ICUMSA 130-180 (São Paulo).
Não confundir com Açúcar Cristal Branco (ICUMSA ≤ 45) — preços diferentes.

## Estrutura de Arquivos

```
Dashboard Mercado Commodities/
├── index.html               # Dashboard (HTML/CSS/JS puro)
├── dados_commodities.json   # Dados gerados pelo script Python
├── coletar_dados.py         # Script de coleta (executado pelo Actions)
├── requirements.txt         # Dependências Python
├── CLAUDE.md                # Este arquivo
└── .github/
    └── workflows/
        └── atualizacao.yml  # GitHub Actions — cron diário 07h BRT
```

## Schema do dados_commodities.json

```json
{
  "ultima_atualizacao": "YYYY-MM-DDTHH:MM:SS",
  "status_coleta": "ok | parcial | erro",
  "dolar": {
    "valor": 5.82,
    "variacao_pct": 0.3,
    "bid": 5.82,
    "ask": 5.84
  },
  "safra": {
    "ultima_atualizacao": "...",
    "noticias": [
      { "titulo": "...", "fonte": "...", "data": "YYYY-MM-DD", "url": "..." }
    ]
  },
  "commodities": {
    "arroz": {
      "nome": "Arroz em Casca",
      "unidade": "R$/sc 50kg",
      "fonte_primaria": "CEPEA/IRGA-RS",
      "status": "ok | fallback | sem_dados",
      "historico_5d": [
        { "data": "YYYY-MM-DD", "valor": 78.50, "variacao_pct": -0.5 }
      ],
      "variacao_mes_pct": -2.3,
      "tendencia_curta": "alta | queda | estavel | indefinida",
      "tendencia_media": "alta | queda | estavel | indefinida",
      "insight_curto_prazo": "Texto gerado pelo script...",
      "insight_medio_prazo": "Texto gerado pelo script...",
      "recomendacao": "comprar | aguardar | segurar",
      "noticias": [
        { "titulo": "...", "fonte": "...", "data": "YYYY-MM-DD", "url": "..." }
      ]
    }
    // ... mesmo schema para todas as commodities
  }
}
```

**Regras de integridade:**
- `null` = dado não confirmado (nunca inventado)
- `status: "ok"` = fonte primária
- `status: "fallback"` = fonte secundária (dado válido, mas diferente do primário)
- `status: "sem_dados"` = coleta falhou; dashboard exibe "—"

## Instalação Local

```bash
# 1. Instalar dependências
pip install -r requirements.txt

# 2. Instalar o browser Playwright
playwright install chromium

# 3. Executar coleta (gera dados_commodities.json)
python coletar_dados.py

# 4. Servir o dashboard localmente
python -m http.server 8080
# Abrir: http://localhost:8080
```

## Como Adicionar Nova Commodity

1. **`coletar_dados.py`**:
   - Adicionar URL em `CEPEA_INDICADORES` (se disponível no CEPEA)
   - Adicionar slug em `FALLBACK_SLUGS`
   - Adicionar keywords em `KEYWORDS_COMMODITY`
   - Adicionar metadados em `COMMODITIES_META`

2. **`dados_commodities.json`**:
   - Adicionar bloco com o schema padrão na seção `commodities`

3. **`index.html`**:
   - Adicionar link na nav (`<a href="#sec-{chave}">Nome</a>`)
   - O card e a linha de tabela são gerados automaticamente por JavaScript

## Como Adicionar Nova Fonte de Notícias

Em `coletar_dados.py`, adicionar à lista `RSS_FEEDS`:
```python
RSS_FEEDS = [
    ...
    ("Nome da Fonte", "https://url-do-feed-rss.com/rss"),
]
```

## GitHub Pages — Configuração Inicial

1. Criar repositório no GitHub
2. Push do código: `git push -u origin main`
3. No repositório: **Settings → Pages → Source: Deploy from branch → main → / (root)**
4. URL pública: `https://{usuario}.github.io/{repositorio}/`

## Troubleshooting

| Problema | Causa provável | Solução |
|---|---|---|
| CEPEA retorna vazio | Site bloqueou o bot ou mudou estrutura HTML | Status muda para `fallback` automaticamente; verificar log do Actions |
| Playwright timeout | Rede lenta no GitHub Actions | Aumentar `timeout=` no `page.goto()` em `coletar_dados.py` |
| RSS sem notícias | Feed fora do ar ou URL mudou | Verificar URLs em `RSS_FEEDS` no script |
| Dashboard carrega "—" em tudo | JSON vazio ou não gerado | Rodar `python coletar_dados.py` localmente |
| Açúcar com preço errado | Página CEPEA mostrou ICUMSA diferente | Verificar log `[CEPEA/Açúcar] Aviso` e ajustar validação |

## Insights — Lógica de Geração

- **Curto prazo (30-90 dias):** baseado na variação % do mês corrente (CEPEA padrão)
- **Médio prazo (90-360 dias):** baseado na mesma tendência (expansível com histórico 90d+)
- Limiares: `>= +1.5%` → alta | `<= -1.5%` → queda | entre → estável
- Recomendação:
  - Alta + Alta → 🟢 COMPRAR
  - Queda + Queda → 🔴 SEGURAR
  - Demais combinações → 🟡 AGUARDAR

## Fontes de Referência Completas

- CEPEA/ESALQ: https://www.cepea.esalq.usp.br/br/indicador/
- IBRAFE: https://www.ibrafe.org
- CONAB: https://portaldeinformacoes.conab.gov.br
- AwesomeAPI (Dólar): https://docs.awesomeapi.com.br/api-de-moedas
- Notícias Agrícolas: https://www.noticiasagricolas.com.br
- Agrolink: https://www.agrolink.com.br
- MilkPoint: https://www.milkpoint.com.br
- Scot Consultoria: https://www.scotconsultoria.com.br
- Cecafé: https://www.cecafe.com.br
