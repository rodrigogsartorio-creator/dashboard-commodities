"""
analisar_insights.py — Enriquecimento de insights via Claude API (Haiku)

Lê dados_commodities.json (já populado pelo coletar_dados.py),
busca o texto completo dos artigos de notícia e usa o Claude para gerar
análise qualitativa no nível de um analista de mercado.

Custo estimado: ~R$ 0,02 por execução completa (8 commodities).
"""

import json
import os
import re
import sys
import time
from pathlib import Path

import anthropic
import requests
from bs4 import BeautifulSoup

# ═══════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════

JSON_PATH     = Path(__file__).parent / "dados_commodities.json"
MODEL         = "claude-haiku-4-5-20251001"
MAX_TOKENS    = 700
ARTICLE_CHARS = 1200   # máx. de caracteres por artigo enviados ao Claude
MAX_ARTIGOS   = 3      # artigos lidos por commodity
TIMEOUT_HTTP  = 12


# ═══════════════════════════════════════════════════════════════════════════
# UTILITÁRIOS
# ═══════════════════════════════════════════════════════════════════════════

def buscar_texto_artigo(url: str) -> str:
    """Extrai o texto relevante de um artigo via scraping simples."""
    if not url or not url.startswith("http"):
        return ""
    try:
        r = requests.get(
            url, timeout=TIMEOUT_HTTP,
            headers={"User-Agent": "Mozilla/5.0 (compatible; DashboardBot/1.0)"},
        )
        soup = BeautifulSoup(r.text, "html5lib")
        for tag in soup(["script", "style", "nav", "header", "footer",
                         "aside", "form", "button"]):
            tag.decompose()
        texto = " ".join(soup.get_text(" ", strip=True).split())
        return texto[:ARTICLE_CHARS]
    except Exception:
        return ""


def fmtBRL(valor):
    if valor is None:
        return "—"
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ═══════════════════════════════════════════════════════════════════════════
# PROMPT E CHAMADA AO CLAUDE
# ═══════════════════════════════════════════════════════════════════════════

PROMPT_TEMPLATE = """Você é um analista sênior de commodities agrícolas do Departamento de Compras da Vila Vitória (distribuidora de alimentos no Brasil).

Analise a commodity **{nome}** ({unidade}) com base nos dados abaixo. Seu objetivo é gerar uma análise objetiva e acionável para o comprador decidir: comprar agora, aguardar ou segurar estoque.

## DADOS DE PREÇO
- Preço atual: {preco_atual}
- Tendência nos últimos 7 pregões: {tendencia_curta}
- Variação do período: {var_periodo}
- Suporte histórico (mínima 30d): {suporte}
- Resistência histórica (máxima 30d): {resistencia}
- Red Flags ativos: {red_flags}

## NOTÍCIAS E ARTIGOS (últimos 14 dias)
{artigos_texto}

## INSTRUÇÃO
Responda APENAS com um objeto JSON válido, sem texto antes ou depois. Use aspas duplas. Não use markdown.

{{
  "postura_mercado": "frase curta (máx 8 palavras) descrevendo a dinâmica atual — ex: 'Oferta restrita com produtor retraído'",
  "insight_curto_prazo": "2 a 3 frases qualitativas sobre o cenário de 30 a 90 dias. Seja específico: cite fatores reais das notícias, comportamento de oferta/demanda, clima, câmbio — o que for relevante. Não repita variações percentuais já visíveis no quadro.",
  "insight_medio_prazo": "1 a 2 frases sobre perspectiva de 90 a 360 dias com base em safra, tendência estrutural ou fatores de médio prazo identificados.",
  "recomendacao": "comprar | aguardar | segurar",
  "decisao_texto": "2 a 3 frases explicando a lógica da decisão: por que esta recomendação agora, qual o risco principal, e se há janela de oportunidade ou prazo sugerido para revisão."
}}"""


def analisar_commodity(client: anthropic.Anthropic, chave: str, dados: dict) -> dict | None:
    """Chama o Claude para gerar análise qualitativa de uma commodity."""

    # ── Dados de preço ──────────────────────────────────────────────────────
    hist = dados.get("historico_5d", [])
    preco_atual = fmtBRL(hist[0]["valor"]) if hist else "—"
    tendencia   = dados.get("tendencia_curta", "indefinida")
    var_periodo = (
        f"{dados['variacao_mes_pct']:+.1f}%" if dados.get("variacao_mes_pct") is not None
        else "não disponível"
    )
    suporte     = fmtBRL(dados.get("suporte"))
    resistencia = fmtBRL(dados.get("resistencia"))

    flags = dados.get("red_flags", [])
    red_flags_txt = (
        "; ".join(f["mensagem"] for f in flags) if flags
        else "nenhum"
    )

    # ── Artigos: título + texto completo ────────────────────────────────────
    noticias = dados.get("noticias", [])
    artigos_partes = []
    for n in noticias[:MAX_ARTIGOS]:
        titulo = n.get("titulo", "Sem título")
        fonte  = n.get("fonte", "")
        data   = n.get("data", "")
        url    = n.get("url", "")
        texto  = buscar_texto_artigo(url)
        parte  = f"**{titulo}** ({fonte}, {data})"
        if texto:
            parte += f"\n{texto}"
        artigos_partes.append(parte)
        time.sleep(0.5)

    artigos_texto = (
        "\n\n---\n\n".join(artigos_partes)
        if artigos_partes
        else "Nenhuma notícia disponível neste período."
    )

    # ── Prompt ──────────────────────────────────────────────────────────────
    prompt = PROMPT_TEMPLATE.format(
        nome=dados.get("nome", chave),
        unidade=dados.get("unidade", ""),
        preco_atual=preco_atual,
        tendencia_curta=tendencia,
        var_periodo=var_periodo,
        suporte=suporte,
        resistencia=resistencia,
        red_flags=red_flags_txt,
        artigos_texto=artigos_texto,
    )

    # ── Chamada à API ────────────────────────────────────────────────────────
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        texto = response.content[0].text.strip()

        # Remove possível markdown em torno do JSON
        texto = re.sub(r"^```(?:json)?\s*", "", texto)
        texto = re.sub(r"\s*```$", "", texto)

        resultado = json.loads(texto)

        # Valida campos obrigatórios
        campos = ["postura_mercado", "insight_curto_prazo", "insight_medio_prazo",
                  "recomendacao", "decisao_texto"]
        for campo in campos:
            if campo not in resultado:
                raise ValueError(f"Campo ausente: {campo}")

        # Normaliza recomendacao
        rec = resultado["recomendacao"].lower().strip()
        if rec not in ("comprar", "aguardar", "segurar"):
            rec = "aguardar"
        resultado["recomendacao"] = rec

        return resultado

    except Exception as exc:
        print(f"    [{chave}] Erro na análise Claude: {exc}")
        return None


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ANTHROPIC_API_KEY não configurada — abortando análise de insights.")
        sys.exit(0)   # exit 0 para não quebrar o workflow se a key não estiver configurada

    if not JSON_PATH.exists():
        print(f"Arquivo não encontrado: {JSON_PATH}")
        sys.exit(1)

    with open(JSON_PATH, "r", encoding="utf-8") as f:
        dados = json.load(f)

    commodities = dados.get("commodities", {})
    if not commodities:
        print("Nenhuma commodity encontrada no JSON.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    print("=" * 65)
    print("Análise de insights — Claude Haiku")
    print("=" * 65)

    total = len(commodities)
    atualizadas = 0

    for i, (chave, c) in enumerate(commodities.items(), 1):
        print(f"\n[{i}/{total}] {c.get('nome', chave)}...")

        # Pula commodities sem dados de preço
        if not c.get("historico_5d"):
            print("    Sem histórico de preço — pulando.")
            continue

        resultado = analisar_commodity(client, chave, c)

        if resultado:
            c["postura_mercado"]    = resultado["postura_mercado"]
            c["insight_curto_prazo"] = resultado["insight_curto_prazo"]
            c["insight_medio_prazo"] = resultado["insight_medio_prazo"]
            c["recomendacao"]        = resultado["recomendacao"]
            c["decisao_texto"]       = resultado["decisao_texto"]
            c["insight_gerado_por"]  = "claude-haiku"
            atualizadas += 1
            print(f"    ✓ {resultado['recomendacao'].upper()} — {resultado['postura_mercado']}")
        else:
            c["insight_gerado_por"] = "regras"
            print("    ⚠ Mantendo insight baseado em regras.")

        time.sleep(1)  # respeita rate limit

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*65}")
    print(f"Insights atualizados: {atualizadas}/{total}")
    print(f"JSON salvo: {JSON_PATH}")


if __name__ == "__main__":
    main()
