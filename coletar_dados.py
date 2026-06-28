"""
Script de coleta de dados para o Dashboard Mercado Commodities - Vila Vitória
Fontes primárias: CEPEA/ESALQ, IBRAFE, CONAB, AwesomeAPI
Fallback: NoticiasAgricolas.com.br
"""

import json
import re
import time
import traceback
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

import feedparser
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

BRT = ZoneInfo("America/Sao_Paulo")
HOJE = datetime.now(BRT)
SCRIPT_DIR = __file__.replace("\\", "/").rsplit("/", 1)[0]
JSON_PATH = f"{SCRIPT_DIR}/dados_commodities.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
}

CEPEA_INDICADORES = {
    "arroz":          "https://www.cepea.esalq.usp.br/br/indicador/arroz.aspx",
    "feijao_carioca": "https://www.cepea.esalq.usp.br/br/indicador/feijao.aspx",
    "acucar":         "https://www.cepea.esalq.usp.br/br/indicador/acucar.aspx",
    "soja":           "https://www.cepea.esalq.usp.br/br/indicador/soja.aspx",
    "trigo":          "https://www.cepea.esalq.usp.br/br/indicador/trigo.aspx",
    "cafe":           "https://www.cepea.esalq.usp.br/br/indicador/cafe.aspx",
    "leite":          "https://www.cepea.esalq.usp.br/br/indicador/leite.aspx",
}

NOTICIAS_AG_BASE = "https://www.noticiasagricolas.com.br"
NOTICIAS_AG_RSS  = "https://www.noticiasagricolas.com.br/rss"

KEYWORDS_COMMODITY = {
    "arroz":          ["arroz"],
    "feijao_carioca": ["feijão carioca", "feijao carioca", "carioca"],
    "feijao_preto":   ["feijão preto", "feijao preto", "feijão negro"],
    "acucar":         ["açúcar", "acucar", "sucrose", "icumsa"],
    "soja":           ["soja"],
    "trigo":          ["trigo"],
    "cafe":           ["café", "cafe", "arábica", "arabica"],
    "leite":          ["leite"],
}

SAFRA_KEYWORDS = ["safra", "colheita", "plantio", "produção", "produtividade", "conab", "estoques"]


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------

def parse_float_br(text: str):
    """Converte '1.234,56' → 1234.56, retorna None se inválido."""
    if not text:
        return None
    text = text.strip().replace("\xa0", "").replace(" ", "")
    text = re.sub(r"[^\d,.\-]", "", text)
    text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def parse_date_br(text: str):
    """Converte 'dd/mm/aaaa' → 'YYYY-MM-DD', retorna None se inválido."""
    text = text.strip() if text else ""
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def variacao_pct(novo, antigo):
    if novo is None or antigo is None or antigo == 0:
        return None
    return round((novo - antigo) / antigo * 100, 2)


def data_relativa(data_str: str) -> str:
    try:
        d = date.fromisoformat(data_str)
        delta = (date.today() - d).days
        if delta == 0:
            return "hoje"
        if delta == 1:
            return "ontem"
        return f"há {delta} dias"
    except Exception:
        return data_str


# ---------------------------------------------------------------------------
# Módulo 1: Dólar (AwesomeAPI)
# ---------------------------------------------------------------------------

def coletar_dolar() -> dict:
    print("  [Dólar] Coletando via AwesomeAPI...")
    try:
        r = requests.get(
            "https://economia.awesomeapi.com.br/json/last/USD-BRL",
            headers=HEADERS,
            timeout=15,
        )
        r.raise_for_status()
        d = r.json()["USDBRL"]
        bid = round(float(d["bid"]), 4)
        ask = round(float(d["ask"]), 4)
        pct = round(float(d.get("pctChange", 0)), 2)
        print(f"  [Dólar] R$ {bid:,.4f} ({pct:+.2f}%)")
        return {"valor": bid, "variacao_pct": pct, "bid": bid, "ask": ask}
    except Exception as exc:
        print(f"  [Dólar] ERRO: {exc}")
        return {"valor": None, "variacao_pct": None, "bid": None, "ask": None}


# ---------------------------------------------------------------------------
# Módulo 2: CEPEA via Playwright
# ---------------------------------------------------------------------------

def _extrair_tabela_cepea(html: str, chave: str) -> list[dict]:
    """Extrai os últimos 5 registros da tabela de indicadores do CEPEA."""
    soup = BeautifulSoup(html, "lxml")
    tabela = soup.find("table", {"id": re.compile(r"(ctn-tabela-grafico|tabela)", re.I)})
    if not tabela:
        tabela = soup.find("table")
    if not tabela:
        return []

    linhas = tabela.find_all("tr")
    registros = []
    for linha in linhas[1:]:  # pula cabeçalho
        cels = [c.get_text(strip=True) for c in linha.find_all(["td", "th"])]
        if len(cels) < 2:
            continue
        dt = parse_date_br(cels[0])
        if not dt:
            continue
        valor = parse_float_br(cels[1])
        if valor is None:
            continue

        # Açúcar: validar que a página é ICUMSA 130-180 (SP)
        if chave == "acucar":
            titulo = soup.get_text().lower()
            if "icumsa 130" not in titulo and "cristal" not in titulo:
                print("  [CEPEA/Açúcar] Aviso: verifique se a página é ICUMSA 130-180.")

        registros.append({"data": dt, "valor": valor})

    # Ordena por data e pega os 5 mais recentes
    registros.sort(key=lambda x: x["data"], reverse=True)
    return registros[:5]


def _calcular_variacao_serie(registros: list[dict]) -> list[dict]:
    resultado = []
    for i, rec in enumerate(registros):
        if i < len(registros) - 1:
            ant = registros[i + 1]["valor"]
            pct = variacao_pct(rec["valor"], ant)
        else:
            pct = None
        resultado.append({
            "data": rec["data"],
            "valor": rec["valor"],
            "variacao_pct": pct,
        })
    return resultado


def _variacao_mes_cepea(registros: list[dict]) -> float | None:
    """Compara o valor mais recente com o primeiro dia útil do mês atual."""
    if not registros:
        return None
    mais_recente = registros[0]["valor"]
    mes_atual = HOJE.strftime("%Y-%m")
    do_mes = [r for r in registros if r["data"].startswith(mes_atual)]
    if len(do_mes) >= 2:
        primeiro = do_mes[-1]["valor"]
        return variacao_pct(mais_recente, primeiro)
    return None


def coletar_cepea_playwright() -> dict:
    """Raspa todos os indicadores CEPEA com Playwright (headless Chromium)."""
    resultados = {}
    print("  [CEPEA] Iniciando Playwright...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                locale="pt-BR",
            )
            page = context.new_page()

            for chave, url in CEPEA_INDICADORES.items():
                try:
                    print(f"  [CEPEA] {chave}: {url}")
                    page.goto(url, wait_until="networkidle", timeout=40000)
                    # Aguarda a tabela aparecer
                    page.wait_for_selector("table", timeout=20000)
                    html = page.content()
                    registros_raw = _extrair_tabela_cepea(html, chave)
                    if registros_raw:
                        registros = _calcular_variacao_serie(registros_raw)
                        var_mes = _variacao_mes_cepea(registros_raw)
                        resultados[chave] = {
                            "historico_5d": registros,
                            "variacao_mes_pct": var_mes,
                            "status": "ok",
                        }
                        print(f"  [CEPEA] {chave}: {len(registros)} registros coletados.")
                    else:
                        print(f"  [CEPEA] {chave}: tabela não encontrada, tentando fallback.")
                        resultados[chave] = {"historico_5d": [], "variacao_mes_pct": None, "status": "sem_dados"}
                    time.sleep(2)
                except PlaywrightTimeout:
                    print(f"  [CEPEA] {chave}: timeout.")
                    resultados[chave] = {"historico_5d": [], "variacao_mes_pct": None, "status": "sem_dados"}
                except Exception as exc:
                    print(f"  [CEPEA] {chave}: erro — {exc}")
                    resultados[chave] = {"historico_5d": [], "variacao_mes_pct": None, "status": "sem_dados"}

            browser.close()
    except Exception as exc:
        print(f"  [CEPEA] Playwright falhou globalmente: {exc}")
        for chave in CEPEA_INDICADORES:
            resultados.setdefault(chave, {"historico_5d": [], "variacao_mes_pct": None, "status": "sem_dados"})
    return resultados


# ---------------------------------------------------------------------------
# Módulo 3: Fallback NoticiasAgricolas (scraping leve)
# ---------------------------------------------------------------------------

def _scrape_noticias_ag_cotacao(slug: str) -> list[dict]:
    """Tenta coletar cotação de noticiasagricolas.com.br/{slug}."""
    url = f"{NOTICIAS_AG_BASE}/cotacoes/{slug}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        tabela = soup.find("table")
        if not tabela:
            return []
        linhas = tabela.find_all("tr")[1:]
        registros = []
        for linha in linhas[:6]:
            cels = [c.get_text(strip=True) for c in linha.find_all(["td", "th"])]
            if len(cels) < 2:
                continue
            dt = parse_date_br(cels[0])
            valor = parse_float_br(cels[1])
            if dt and valor:
                registros.append({"data": dt, "valor": valor})
        registros.sort(key=lambda x: x["data"], reverse=True)
        return registros[:5]
    except Exception as exc:
        print(f"  [NoticiasAg] {slug}: {exc}")
        return []


FALLBACK_SLUGS = {
    "arroz":          "arroz",
    "feijao_carioca": "feijao",
    "acucar":         "acucar",
    "soja":           "soja",
    "trigo":          "trigo",
    "cafe":           "cafe",
    "leite":          "leite",
}


def aplicar_fallback_noticias_ag(resultados_cepea: dict) -> dict:
    """Para commodities sem dados do CEPEA, tenta NoticiasAgricolas."""
    for chave, slug in FALLBACK_SLUGS.items():
        if resultados_cepea.get(chave, {}).get("status") != "ok":
            print(f"  [Fallback] {chave}: buscando em NoticiasAgricolas/{slug}...")
            registros_raw = _scrape_noticias_ag_cotacao(slug)
            if registros_raw:
                registros = _calcular_variacao_serie(registros_raw)
                var_mes = _variacao_mes_cepea(registros_raw)
                resultados_cepea[chave] = {
                    "historico_5d": registros,
                    "variacao_mes_pct": var_mes,
                    "status": "fallback",
                }
                print(f"  [Fallback] {chave}: {len(registros)} registros via fallback.")
            else:
                resultados_cepea[chave] = {
                    "historico_5d": [],
                    "variacao_mes_pct": None,
                    "status": "sem_dados",
                }
    return resultados_cepea


# ---------------------------------------------------------------------------
# Módulo 4: Feijão Preto (IBRAFE)
# ---------------------------------------------------------------------------

def coletar_feijao_preto_ibrafe() -> dict:
    """Coleta cotação de feijão preto do IBRAFE."""
    print("  [IBRAFE] Coletando feijão preto...")
    url = "https://www.ibrafe.org"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")

        # Tenta encontrar tabela com "preto" no contexto
        registros = []
        for table in soup.find_all("table"):
            texto = table.get_text().lower()
            if "preto" in texto or "cotação" in texto:
                linhas = table.find_all("tr")[1:]
                for linha in linhas[:6]:
                    cels = [c.get_text(strip=True) for c in linha.find_all(["td", "th"])]
                    if len(cels) >= 2:
                        dt = parse_date_br(cels[0])
                        valor = parse_float_br(cels[1])
                        if dt and valor:
                            registros.append({"data": dt, "valor": valor})
                if registros:
                    break

        if registros:
            registros.sort(key=lambda x: x["data"], reverse=True)
            registros = registros[:5]
            serie = _calcular_variacao_serie(registros)
            var_mes = _variacao_mes_cepea(registros)
            print(f"  [IBRAFE] {len(serie)} registros coletados.")
            return {"historico_5d": serie, "variacao_mes_pct": var_mes, "status": "ok"}
        else:
            print("  [IBRAFE] Tabela não encontrada, usando fallback NoticiasAg.")
            registros_raw = _scrape_noticias_ag_cotacao("feijao")
            preto = [r for r in registros_raw]  # NoticiasAg agrupa carioca e preto; usa como referência
            if preto:
                serie = _calcular_variacao_serie(preto[:5])
                var_mes = _variacao_mes_cepea(preto[:5])
                return {"historico_5d": serie, "variacao_mes_pct": var_mes, "status": "fallback"}
            return {"historico_5d": [], "variacao_mes_pct": None, "status": "sem_dados"}
    except Exception as exc:
        print(f"  [IBRAFE] Erro: {exc}")
        return {"historico_5d": [], "variacao_mes_pct": None, "status": "sem_dados"}


# ---------------------------------------------------------------------------
# Módulo 5: Notícias via RSS
# ---------------------------------------------------------------------------

RSS_FEEDS = [
    ("Notícias Agrícolas", NOTICIAS_AG_RSS),
    ("Agrolink", "https://www.agrolink.com.br/rss/noticias.aspx"),
    ("MilkPoint", "https://www.milkpoint.com.br/rss/"),
    ("Scot Consultoria", "https://www.scotconsultoria.com.br/rss/"),
    ("Cecafé", "https://www.cecafe.com.br/feed/"),
]

LIMITE_DIAS_NOTICIAS = 3
LIMITE_DIAS_SAFRA = 7
MAX_NOTICIAS_POR_COMMODITY = 4
MAX_NOTICIAS_SAFRA = 8


def _entry_para_noticia(entry) -> dict:
    titulo = entry.get("title", "").strip()
    url = entry.get("link", "")
    fonte = entry.get("source", {}).get("title", "") or ""
    published = entry.get("published_parsed") or entry.get("updated_parsed")
    if published:
        dt = datetime(*published[:6]).strftime("%Y-%m-%d")
    else:
        dt = HOJE.strftime("%Y-%m-%d")
    return {"titulo": titulo, "fonte": fonte, "data": dt, "url": url}


def _dentro_do_limite(noticia: dict, dias: int) -> bool:
    try:
        d = date.fromisoformat(noticia["data"])
        return (date.today() - d).days <= dias
    except Exception:
        return True


def coletar_noticias_rss() -> tuple[dict, list]:
    """
    Retorna (noticias_por_commodity, noticias_safra).
    noticias_por_commodity: dict[chave] → list[dict]
    noticias_safra: list[dict]
    """
    por_commodity = {k: [] for k in KEYWORDS_COMMODITY}
    safra = []
    print("  [RSS] Coletando feeds de notícias...")

    for fonte_nome, feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                noticia = _entry_para_noticia(entry)
                if not noticia["fonte"]:
                    noticia["fonte"] = fonte_nome
                titulo_lower = noticia["titulo"].lower()

                # Classifica safra
                if any(k in titulo_lower for k in SAFRA_KEYWORDS):
                    if _dentro_do_limite(noticia, LIMITE_DIAS_SAFRA):
                        safra.append(noticia)

                # Classifica por commodity
                for chave, palavras in KEYWORDS_COMMODITY.items():
                    if any(p in titulo_lower for p in palavras):
                        if _dentro_do_limite(noticia, LIMITE_DIAS_NOTICIAS):
                            por_commodity[chave].append(noticia)
        except Exception as exc:
            print(f"  [RSS] Erro em {fonte_nome}: {exc}")

    # Deduplica e limita
    for chave in por_commodity:
        vistos = set()
        unicos = []
        for n in por_commodity[chave]:
            if n["titulo"] not in vistos:
                vistos.add(n["titulo"])
                unicos.append(n)
        por_commodity[chave] = sorted(unicos, key=lambda x: x["data"], reverse=True)[:MAX_NOTICIAS_POR_COMMODITY]

    safra_vistos = set()
    safra_unicos = []
    for n in safra:
        if n["titulo"] not in safra_vistos:
            safra_vistos.add(n["titulo"])
            safra_unicos.append(n)
    safra = sorted(safra_unicos, key=lambda x: x["data"], reverse=True)[:MAX_NOTICIAS_SAFRA]

    print(f"  [RSS] Notícias safra: {len(safra)}")
    for k, v in por_commodity.items():
        print(f"  [RSS] {k}: {len(v)} notícias")

    return por_commodity, safra


# ---------------------------------------------------------------------------
# Módulo 6: Tendência e Insights
# ---------------------------------------------------------------------------

LIMIAR_ALTA = 1.5
LIMIAR_QUEDA = -1.5

TEXTOS_CURTO = {
    "alta": (
        "Preço em trajetória de alta de {var:.1f}% no período recente. "
        "Nos próximos 30 a 90 dias, a tendência aponta pressão para cima. "
        "Recomenda-se antecipar compras ou garantir volume contratado."
    ),
    "queda": (
        "Preço em trajetória de queda de {var:.1f}% no período recente. "
        "Nos próximos 30 a 90 dias, há perspectiva de preços mais favoráveis. "
        "Avalie aguardar para comprar, monitorando pontos de suporte."
    ),
    "estavel": (
        "Preço estável, com variação de {var:.1f}% no período recente. "
        "Nos próximos 30 a 90 dias, não há sinal forte de mudança de direção. "
        "Compras podem ser realizadas conforme demanda operacional."
    ),
    "indefinida": (
        "Dados insuficientes para análise de curto prazo (30 a 90 dias). "
        "Monitore as atualizações diárias e as notícias das fontes primárias."
    ),
}

TEXTOS_MEDIO = {
    "alta": (
        "Perspectiva de pressão de preços no médio prazo (90 a 360 dias), "
        "possivelmente impulsionada por fundamentos de oferta/demanda. "
        "Considere contratos de fornecimento mais longos ou estoque estratégico."
    ),
    "queda": (
        "Tendência de queda no médio prazo (90 a 360 dias) sugere janela de "
        "oportunidade para negociações com fornecedores e revisão de contratos. "
        "Evite fixar preços altos por períodos longos."
    ),
    "estavel": (
        "Mercado relativamente equilibrado no médio prazo (90 a 360 dias). "
        "Contratos standard são adequados; priorize diversificação de fornecedores."
    ),
    "indefinida": (
        "Histórico insuficiente para projeção de médio prazo (90 a 360 dias). "
        "Acompanhe as publicações da CONAB e CEPEA para reavaliação."
    ),
}

RECOMENDACAO_MATRIX = {
    ("alta", "alta"):    "comprar",
    ("alta", "estavel"): "comprar",
    ("alta", "indefinida"): "aguardar",
    ("alta", "queda"):   "aguardar",
    ("queda", "queda"):  "segurar",
    ("queda", "estavel"): "aguardar",
    ("queda", "alta"):   "aguardar",
    ("queda", "indefinida"): "aguardar",
    ("estavel", "alta"): "aguardar",
    ("estavel", "estavel"): "aguardar",
    ("estavel", "queda"): "aguardar",
    ("estavel", "indefinida"): "aguardar",
    ("indefinida", "indefinida"): "aguardar",
    ("indefinida", "alta"): "aguardar",
    ("indefinida", "queda"): "aguardar",
    ("indefinida", "estavel"): "aguardar",
}


def calcular_tendencia(historico_5d: list, variacao_mes_pct: float | None) -> dict:
    """Determina tendências curta/média e gera textos de insight."""
    # Tendência curta: baseada na variação do mês (ou dos últimos 5 dias)
    if variacao_mes_pct is not None:
        if variacao_mes_pct >= LIMIAR_ALTA:
            tendencia_curta = "alta"
        elif variacao_mes_pct <= LIMIAR_QUEDA:
            tendencia_curta = "queda"
        else:
            tendencia_curta = "estavel"
        var_ref_curta = variacao_mes_pct
    elif len(historico_5d) >= 2:
        v_novo = historico_5d[0]["valor"]
        v_ant = historico_5d[-1]["valor"]
        var_5d = variacao_pct(v_novo, v_ant) or 0
        if var_5d >= LIMIAR_ALTA:
            tendencia_curta = "alta"
        elif var_5d <= LIMIAR_QUEDA:
            tendencia_curta = "queda"
        else:
            tendencia_curta = "estavel"
        var_ref_curta = var_5d
    else:
        tendencia_curta = "indefinida"
        var_ref_curta = 0.0

    # Tendência média: usamos mesma métrica por ora (histórico extendido viria de coleta adicional)
    # Lógica de inversão: se curta é alta mas variação forte, média tende a corrigir
    tendencia_media = tendencia_curta  # simplificado; pode ser refinado com histórico 90d

    insight_curto = TEXTOS_CURTO[tendencia_curta].format(var=abs(var_ref_curta))
    insight_medio = TEXTOS_MEDIO[tendencia_media]
    recomendacao = RECOMENDACAO_MATRIX.get((tendencia_curta, tendencia_media), "aguardar")

    return {
        "tendencia_curta": tendencia_curta,
        "tendencia_media": tendencia_media,
        "insight_curto_prazo": insight_curto,
        "insight_medio_prazo": insight_medio,
        "recomendacao": recomendacao,
    }


# ---------------------------------------------------------------------------
# Montagem final do JSON
# ---------------------------------------------------------------------------

COMMODITIES_META = {
    "arroz": {
        "nome": "Arroz em Casca",
        "unidade": "R$/sc 50kg",
        "fonte_primaria": "CEPEA/IRGA-RS",
    },
    "feijao_carioca": {
        "nome": "Feijão Carioca",
        "unidade": "R$/sc 60kg",
        "fonte_primaria": "CEPEA/CNA",
    },
    "feijao_preto": {
        "nome": "Feijão Preto",
        "unidade": "R$/sc 60kg",
        "fonte_primaria": "IBRAFE",
    },
    "acucar": {
        "nome": "Açúcar Cristal (ICUMSA 130-180)",
        "unidade": "R$/sc 50kg",
        "fonte_primaria": "CEPEA/ESALQ (SP)",
    },
    "soja": {
        "nome": "Soja",
        "unidade": "R$/sc 60kg",
        "fonte_primaria": "CEPEA/Paranaguá",
    },
    "trigo": {
        "nome": "Trigo",
        "unidade": "R$/sc 60kg",
        "fonte_primaria": "CEPEA/ESALQ",
    },
    "cafe": {
        "nome": "Café Arábica (Tipo 6)",
        "unidade": "R$/sc 60kg",
        "fonte_primaria": "CEPEA/ESALQ",
    },
    "leite": {
        "nome": "Leite ao Produtor",
        "unidade": "R$/litro",
        "fonte_primaria": "CEPEA/CNA",
    },
}


def montar_json(dolar, cotacoes, noticias_por_commodity, noticias_safra) -> dict:
    commodities = {}
    status_geral_ok = 0
    status_geral_total = len(COMMODITIES_META)

    for chave, meta in COMMODITIES_META.items():
        cot = cotacoes.get(chave, {"historico_5d": [], "variacao_mes_pct": None, "status": "sem_dados"})
        nots = noticias_por_commodity.get(chave, [])
        tendencia = calcular_tendencia(cot["historico_5d"], cot["variacao_mes_pct"])

        if cot["status"] == "ok":
            status_geral_ok += 1

        commodities[chave] = {
            **meta,
            "status": cot["status"],
            "historico_5d": cot["historico_5d"],
            "variacao_mes_pct": cot["variacao_mes_pct"],
            **tendencia,
            "noticias": nots,
        }

    # Status geral
    if status_geral_ok == status_geral_total:
        status_coleta = "ok"
    elif status_geral_ok > 0:
        status_coleta = "parcial"
    else:
        status_coleta = "erro"

    return {
        "ultima_atualizacao": HOJE.strftime("%Y-%m-%dT%H:%M:%S"),
        "status_coleta": status_coleta,
        "dolar": dolar,
        "safra": {
            "ultima_atualizacao": HOJE.strftime("%Y-%m-%dT%H:%M:%S"),
            "noticias": noticias_safra,
        },
        "commodities": commodities,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print(f"Dashboard Commodities — Coleta iniciada: {HOJE.strftime('%Y-%m-%d %H:%M:%S')} BRT")
    print("=" * 60)

    print("\n[1/5] Coletando Dólar...")
    dolar = coletar_dolar()

    print("\n[2/5] Coletando cotações CEPEA (Playwright)...")
    cotacoes = coletar_cepea_playwright()

    print("\n[3/5] Aplicando fallback para commodities sem dados...")
    cotacoes = aplicar_fallback_noticias_ag(cotacoes)

    print("\n[4/5] Coletando Feijão Preto (IBRAFE)...")
    cotacoes["feijao_preto"] = coletar_feijao_preto_ibrafe()

    print("\n[5/5] Coletando notícias via RSS...")
    noticias_por_commodity, noticias_safra = coletar_noticias_rss()

    print("\n[6/6] Montando e salvando dados_commodities.json...")
    dados = montar_json(dolar, cotacoes, noticias_por_commodity, noticias_safra)

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)

    print(f"\nJSON salvo em: {JSON_PATH}")
    print(f"Status geral: {dados['status_coleta'].upper()}")
    ok_count = sum(1 for c in dados["commodities"].values() if c["status"] == "ok")
    fb_count = sum(1 for c in dados["commodities"].values() if c["status"] == "fallback")
    nd_count = sum(1 for c in dados["commodities"].values() if c["status"] == "sem_dados")
    print(f"  OK: {ok_count} | Fallback: {fb_count} | Sem dados: {nd_count}")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
