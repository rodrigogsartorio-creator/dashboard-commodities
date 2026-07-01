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
from datetime import date, timedelta
from pathlib import Path

import anthropic
import requests
from bs4 import BeautifulSoup

# ═══════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════

JSON_PATH           = Path(__file__).parent / "dados_commodities.json"
MODEL               = "claude-haiku-4-5-20251001"
MAX_TOKENS          = 1200
ARTICLE_CHARS       = 2000   # máx. de caracteres por artigo enviados ao Claude
MAX_ARTIGOS         = 4      # artigos lidos por commodity
TIMEOUT_HTTP        = 12
JANELA_DECISAO_DIAS = 5      # janela principal para notícias de curto prazo
JANELA_CEPEA_DIAS   = 10     # busca diária CEPEA em janela estendida (marcada como contexto)

# Preços Mínimos do Governo Federal (PGPM/CONAB — safra 2025/26)
# Quando preço de mercado < preço mínimo: risco de queda é limitado (piso governamental)
PRECOS_MINIMOS = {
    "arroz":          ("R$ 63,74/sc 50kg", "CONAB/MAPA 2025/26"),
    "feijao_carioca": ("R$ 165,00/sc 60kg", "CONAB/MAPA 2025/26"),
    "feijao_preto":   ("R$ 155,00/sc 60kg", "CONAB/MAPA 2025/26"),
    "trigo":          ("R$ 31,00/sc 60kg",  "CONAB/MAPA 2025/26"),
    "milho":          ("R$ 26,00/sc 60kg",  "CONAB/MAPA 2025/26"),
}


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


def bullets_html(itens) -> str:
    """Monta lista HTML (<ul><li>) a partir de tópicos de texto (aceita string única como fallback)."""
    if isinstance(itens, str):
        itens = [itens]
    itens = [i for i in itens if i]
    if not itens:
        return "—"
    return "<ul class='insight-list'>" + "".join(f"<li>{i}</li>" for i in itens) + "</ul>"


def fmtBRL(valor):
    if valor is None:
        return "—"
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _is_diaria_cepea(titulo: str) -> bool:
    """Identifica se uma notícia é a diária qualitativa do CEPEA."""
    t = titulo.lower()
    return "cepea" in t and ("cotaç" in t or "preço" in t or "indicador" in t or "mercado" in t)


# ═══════════════════════════════════════════════════════════════════════════
# PROMPT
# ═══════════════════════════════════════════════════════════════════════════

PROMPT_TEMPLATE = """Você é um analista sênior de commodities agrícolas do Departamento de Compras da Vila Vitória (distribuidora de alimentos no Brasil).

Analise a commodity **{nome}** ({unidade}) e gere uma análise objetiva e acionável para o comprador decidir: comprar agora, aguardar ou segurar estoque.

## DADOS DE PREÇO (sinal primário — maior peso na decisão)
- Preço atual: {preco_atual}
- Histórico recente (mais novo primeiro): {hist_precos}
- Variação acumulada do período: {var_periodo}
- Tendência nos últimos pregões: {tendencia_curta}
- Preço Mínimo Governamental (PGPM): {preco_minimo}
- Red Flags ativos: {red_flags}

## NOTICIAS E DIARIAS DE MERCADO
{artigos_texto}

## REGRAS
1. Preço tem prioridade: se o preço subiu consistentemente, isso supera notícias antigas.
2. Preço Mínimo Governamental: se o preço atual está ABAIXO do PGPM, isso representa um piso estrutural — risco de queda adicional é limitado pois o governo pode intervir (PEPRO, AGF). Mencione isso na análise.
3. Priorize diárias CEPEA (quando disponíveis) para extrair postura do produtor e liquidez.
4. Notícias marcadas como [DIARIA CEPEA] têm maior peso qualitativo que notícias genéricas.
5. postura_produtor: como o produtor está se comportando (Retraído = segurando estoque, não quer vender; Ofertante = vendendo ativamente).
6. liquidez: volume de negócios no mercado (Baixa = poucos negócios; Alta = mercado ativo).
7. Seja específico: cite fatos reais das notícias, não generalizações.
8. Assimetria de risco: avalie o downside máximo realista vs. o upside máximo realista nos próximos 60 dias. Se o upside supera claramente o downside, recomende comprar mesmo com incerteza — a assimetria favorável justifica a decisão.
9. Eventos futuros datados: se as notícias mencionarem evento conhecido com data (relatório USDA, reunião de política agrícola, início/fim de safra, resultado climático), registre em gatilho_revisao e condicione a estrategia_volume a ele quando relevante.
10. Para ACUCAR: analise se etanol em alta está competindo pelo mix de cana nas usinas — etanol valorizado desvia cana do açúcar, reduz oferta e pressiona preço para cima. Mencione se houver evidência nas notícias.
11. Mercado externo: se as notícias citarem cotações de futuros (Chicago CBOT, NY Sugar #11, Londres), transmissão desses preços para o mercado físico brasileiro deve ser explicada em fator_externo.
12. insight_curto_prazo e insight_medio_prazo sao ARRAYS de topicos (strings), nao paragrafos. Cada item do array e uma frase completa, autonoma e especifica (com fatos reais das noticias) — nao divida uma unica ideia em duas frases artificialmente, e nao repita nos topicos os numeros percentuais ja visiveis no quadro.

## INSTRUCAO
Responda APENAS com JSON valido, sem texto antes ou depois, sem markdown. Siga exatamente esta estrutura:

{{
  "postura_produtor": "Retraido | Ofertante | Neutro",
  "postura_comprador": "Retraido | Ativo | Neutro",
  "liquidez": "Baixa | Normal | Alta",
  "fator_externo": "frase curta sobre fator externo relevante — inclua cotacao de futuros se citada nas noticias (ex: Chicago nov/26 US$11,56/bu); null se nao houver",
  "postura_mercado": "frase curta (max 8 palavras) descrevendo a dinamica atual do mercado",
  "insight_curto_prazo": ["topico 1: cenario de 7 a 30 dias com base no preco como sinal primario", "topico 2: assimetria de risco (downside vs. upside realistas) e/ou postura produtor/comprador", "topico 3 (opcional): mercado externo ou fator qualitativo relevante das noticias"],
  "insight_medio_prazo": ["topico 1: tendencia estrutural de 30 a 90 dias (safra, clima ou regulatorio)", "topico 2 (opcional): fator complementar de medio prazo"],
  "recomendacao": "comprar | aguardar | segurar",
  "estrategia_volume": "volume_total | parcial | aguardar — com breve explicacao: ex: volume_total significa comprar necessidade dos proximos 60 dias agora; parcial significa comprar parte agora e aguardar evento especifico para o restante",
  "gatilho_revisao": "evento ou data especifica para reavaliar — ex: Relatorio USDA 30/jun, Inicio safra RS ago/26, Dolar abaixo de R$5,00; ou revisao em 30 dias se nao houver evento especifico",
  "decisao_texto": "2 a 3 frases explicando a logica: por que esta recomendacao agora, qual o risco principal, e o gatilho para reavaliar."
}}"""


# ═══════════════════════════════════════════════════════════════════════════
# COLETA DE ARTIGOS
# ═══════════════════════════════════════════════════════════════════════════

def montar_artigos_texto(noticias_todas: list) -> str:
    """
    Seleciona e formata os artigos para o prompt:
    - Prioriza diárias CEPEA (mesmo que >5 dias, até 10 dias)
    - Complementa com notícias dos últimos 5 dias
    - Máximo MAX_ARTIGOS artigos
    """
    corte_5d  = (date.today() - timedelta(days=JANELA_DECISAO_DIAS)).isoformat()
    corte_10d = (date.today() - timedelta(days=JANELA_CEPEA_DIAS)).isoformat()

    # Separa diárias CEPEA (janela estendida) das demais
    diarias_cepea = [
        n for n in noticias_todas
        if n.get("data", "") >= corte_10d and _is_diaria_cepea(n.get("titulo", ""))
    ]
    noticias_5d = [
        n for n in noticias_todas
        if n.get("data", "") >= corte_5d and not _is_diaria_cepea(n.get("titulo", ""))
    ]

    # Ordena por data (mais recente primeiro)
    diarias_cepea.sort(key=lambda x: x.get("data", ""), reverse=True)
    noticias_5d.sort(key=lambda x: x.get("data", ""), reverse=True)

    # Monta lista de artigos: CEPEA primeiro, depois demais, até MAX_ARTIGOS
    selecionados = []
    for n in diarias_cepea[:2]:
        selecionados.append((n, "diaria"))
    for n in noticias_5d:
        if len(selecionados) >= MAX_ARTIGOS:
            break
        selecionados.append((n, "recente"))

    # Fallback: se nada foi selecionado, pega a mais recente disponível
    if not selecionados and noticias_todas:
        mais_recente = sorted(noticias_todas, key=lambda x: x.get("data", ""), reverse=True)[0]
        selecionados.append((mais_recente, "fallback"))

    print(f"    Diarias CEPEA (10d): {len(diarias_cepea)} | Noticias 5d: {len(noticias_5d)} | Selecionados: {len(selecionados)}")

    partes = []
    for n, tipo in selecionados:
        titulo = n.get("titulo", "Sem título")
        fonte  = n.get("fonte", "")
        data   = n.get("data", "")
        url    = n.get("url", "")

        dias_atrás = (date.today() - date.fromisoformat(data)).days if data else "?"

        if tipo == "diaria":
            label = f"[DIARIA CEPEA — {dias_atrás} dias atras]"
        elif tipo == "fallback":
            label = f"[NOTICIA MAIS RECENTE — {dias_atrás} dias atras, peso reduzido]"
        else:
            label = f"[{dias_atrás} dias atras]"

        texto = buscar_texto_artigo(url)
        parte = f"**{label} {titulo}** ({fonte}, {data})"
        if texto:
            parte += f"\n{texto}"
        partes.append(parte)
        time.sleep(0.5)

    if not partes:
        return "Nenhuma noticia disponivel."

    return "\n\n---\n\n".join(partes)


# ═══════════════════════════════════════════════════════════════════════════
# ANÁLISE
# ═══════════════════════════════════════════════════════════════════════════

def analisar_commodity(client: anthropic.Anthropic, chave: str, dados: dict) -> dict | None:
    """Chama o Claude para gerar análise qualitativa de uma commodity."""

    hist = dados.get("historico_5d", [])
    preco_atual = fmtBRL(hist[0]["valor"]) if hist else "—"
    tendencia   = dados.get("tendencia_curta", "indefinida")
    var_periodo = (
        f"{dados['variacao_mes_pct']:+.1f}%" if dados.get("variacao_mes_pct") is not None
        else "nao disponivel"
    )

    flags = dados.get("red_flags", [])
    red_flags_txt = (
        "; ".join(f["mensagem"] for f in flags) if flags
        else "nenhum"
    )

    hist_fmt = " → ".join(
        f"{h['data']}: {fmtBRL(h['valor'])}" + (f" ({h['variacao_pct']:+.2f}%)" if h.get("variacao_pct") is not None else "")
        for h in hist
    ) or "nao disponivel"

    noticias_todas = dados.get("noticias", [])
    artigos_texto  = montar_artigos_texto(noticias_todas)

    # Preço mínimo governamental (PGPM)
    pm = PRECOS_MINIMOS.get(chave)
    preco_minimo_txt = f"{pm[0]} ({pm[1]})" if pm else "não se aplica"

    prompt = PROMPT_TEMPLATE.format(
        nome=dados.get("nome", chave),
        unidade=dados.get("unidade", ""),
        preco_atual=preco_atual,
        tendencia_curta=tendencia,
        hist_precos=hist_fmt,
        var_periodo=var_periodo,
        preco_minimo=preco_minimo_txt,
        red_flags=red_flags_txt,
        artigos_texto=artigos_texto,
    )

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        texto = response.content[0].text.strip()
        texto = re.sub(r"^```(?:json)?\s*", "", texto)
        texto = re.sub(r"\s*```$", "", texto)

        resultado = json.loads(texto)

        campos_obrigatorios = [
            "postura_produtor", "postura_comprador", "liquidez",
            "postura_mercado", "insight_curto_prazo", "insight_medio_prazo",
            "recomendacao", "estrategia_volume", "gatilho_revisao", "decisao_texto"
        ]
        for campo in campos_obrigatorios:
            if campo not in resultado:
                raise ValueError(f"Campo ausente: {campo}")

        rec = resultado["recomendacao"].lower().strip()
        if rec not in ("comprar", "aguardar", "segurar"):
            rec = "aguardar"
        resultado["recomendacao"] = rec

        # Normaliza campos categóricos
        pp = resultado.get("postura_produtor", "Neutro").strip().capitalize()
        if pp not in ("Retraido", "Ofertante", "Neutro", "Retraído"):
            pp = "Neutro"
        resultado["postura_produtor"] = pp

        pc = resultado.get("postura_comprador", "Neutro").strip().capitalize()
        if pc not in ("Retraido", "Ativo", "Neutro", "Retraído"):
            pc = "Neutro"
        resultado["postura_comprador"] = pc

        liq = resultado.get("liquidez", "Normal").strip().capitalize()
        if liq not in ("Baixa", "Normal", "Alta"):
            liq = "Normal"
        resultado["liquidez"] = liq

        resultado["insight_curto_prazo"] = bullets_html(resultado["insight_curto_prazo"])
        resultado["insight_medio_prazo"] = bullets_html(resultado["insight_medio_prazo"])

        return resultado

    except Exception as exc:
        print(f"    [{chave}] Erro na analise Claude: {exc}")
        return None


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ANTHROPIC_API_KEY nao configurada — abortando analise de insights.")
        sys.exit(0)

    if not JSON_PATH.exists():
        print(f"Arquivo nao encontrado: {JSON_PATH}")
        sys.exit(1)

    with open(JSON_PATH, "r", encoding="utf-8") as f:
        dados = json.load(f)

    commodities = dados.get("commodities", {})
    if not commodities:
        print("Nenhuma commodity encontrada no JSON.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    print("=" * 65)
    print("Analise de insights - Claude Haiku")
    print("=" * 65)

    total = len(commodities)
    atualizadas = 0

    for i, (chave, c) in enumerate(commodities.items(), 1):
        print(f"\n[{i}/{total}] {c.get('nome', chave)}...")

        if not c.get("historico_5d"):
            print("    Sem historico de preco — pulando.")
            continue

        resultado = analisar_commodity(client, chave, c)

        if resultado:
            c["postura_produtor"]    = resultado["postura_produtor"]
            c["postura_comprador"]   = resultado["postura_comprador"]
            c["liquidez"]            = resultado["liquidez"]
            c["fator_externo"]       = resultado.get("fator_externo")
            c["postura_mercado"]     = resultado["postura_mercado"]
            c["insight_curto_prazo"] = resultado["insight_curto_prazo"]
            c["insight_medio_prazo"] = resultado["insight_medio_prazo"]
            c["recomendacao"]        = resultado["recomendacao"]
            c["estrategia_volume"]   = resultado.get("estrategia_volume")
            c["gatilho_revisao"]     = resultado.get("gatilho_revisao")
            c["decisao_texto"]       = resultado["decisao_texto"]
            c["insight_gerado_por"]  = "claude-haiku"
            atualizadas += 1
            print(f"    OK {resultado['recomendacao'].upper()} | Produtor: {resultado['postura_produtor']} | Liquidez: {resultado['liquidez']} | Gatilho: {resultado.get('gatilho_revisao', '—')}")
        else:
            c["insight_gerado_por"] = "regras"
            print("    AVISO: Mantendo insight baseado em regras.")

        time.sleep(1)

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*65}")
    print(f"Insights atualizados: {atualizadas}/{total}")
    print(f"JSON salvo: {JSON_PATH}")


if __name__ == "__main__":
    main()
