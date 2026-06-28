"""
Script de coleta de dados — Dashboard Mercado Commodities - Vila Vitória
==========================================================================
Arquitetura de acumulação:
  - A cada execução, coleta o preço do dia de cada commodity
  - Mescla com o histórico existente no JSON (mantém últimos 30 dias)
  - Isso garante histórico real sem depender de scraping de múltiplos dias

Fontes:
  1. NoticiasAgricolas — cotações diárias (scraping HTML)
  2. Agrolink — fallback para commodities sem dado no NoticiasAg
  3. IBRAFE — feijão preto (fonte de referência)
  4. AwesomeAPI — dólar (API gratuita)
  5. IBGE SIDRA + RSS — safra
  6. RSS feeds por commodity — notícias

CEPEA API (FUTURO):
  Quando contratada, definir CEPEA_API_KEY no ambiente.
  O script detecta automaticamente e usa a API em vez do scraping.
  Confirmar endpoint/autenticação com o CEPEA ao contratar.
"""

import json
import os
import re
import time
import traceback
from datetime import datetime, timedelta, date, timezone

import feedparser
import requests
from bs4 import BeautifulSoup

BRT  = timezone(timedelta(hours=-3))
HOJE = datetime.now(BRT)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
JSON_PATH  = os.path.join(SCRIPT_DIR, "dados_commodities.json")

CEPEA_API_KEY = os.environ.get("CEPEA_API_KEY", "")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)

HISTORICO_MAX_DIAS = 30  # mantém até 30 dias no JSON


# ═══════════════════════════════════════════════════════════════════════════
# UTILITÁRIOS
# ═══════════════════════════════════════════════════════════════════════════

def parse_float_br(text: str):
    if not text:
        return None
    text = re.sub(r"[^\d,.\-]", "", text.strip().replace("\xa0", "").replace(" ", ""))
    text = text.replace(".", "").replace(",", ".")
    try:
        v = float(text)
        return v if v > 0 else None
    except ValueError:
        return None


def parse_date_br(text: str):
    text = (text or "").strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def variacao_pct(novo, antigo):
    if novo is None or antigo is None or antigo == 0:
        return None
    return round((novo - antigo) / antigo * 100, 2)


def safe_get(url: str, timeout: int = 20, **kwargs):
    try:
        r = SESSION.get(url, timeout=timeout, **kwargs)
        r.raise_for_status()
        return r
    except Exception as exc:
        print(f"    GET {url[:70]} → {exc}")
        return None


# ═══════════════════════════════════════════════════════════════════════════
# FAIXAS DE PREÇO (validação anti-lixo)
# ═══════════════════════════════════════════════════════════════════════════

FAIXAS = {
    "arroz":          (30,   250),
    "feijao_carioca": (80,   700),
    "feijao_preto":   (80,   700),
    "acucar":         (60,   400),
    "soja":           (60,   350),
    "trigo":          (40,   250),
    "cafe":           (400, 4000),
    "leite":          (1.0,   15),
}


def preco_valido(chave: str, valor) -> bool:
    if valor is None:
        return False
    faixa = FAIXAS.get(chave)
    return (faixa[0] <= valor <= faixa[1]) if faixa else valor > 0


# ═══════════════════════════════════════════════════════════════════════════
# ACUMULAÇÃO DE HISTÓRICO
# ═══════════════════════════════════════════════════════════════════════════

def carregar_historico_existente() -> dict:
    """Lê o JSON atual e retorna historico_30d (ou historico_5d) por commodity."""
    try:
        with open(JSON_PATH, "r", encoding="utf-8") as f:
            dados = json.load(f)
        return {
            chave: c.get("historico_30d") or c.get("historico_5d", [])
            for chave, c in dados.get("commodities", {}).items()
        }
    except Exception:
        return {}


def _extrair_historico_completo(html: str, chave: str) -> list:
    """
    Extrai TODOS os preços datados disponíveis na página (tipicamente ~10 dias).
    Usa as mesmas Estratégias 1 e 2 de _extrair_preco_pagina, mas coleta todos.
    Retorna lista [{data, valor}] ordenada do mais recente ao mais antigo.
    """
    soup = BeautifulSoup(html, "html5lib")
    faixa_raw = FAIXAS_RAW.get(chave)
    conversao = CONVERSAO_FATOR.get(chave, 1.0)

    def valido_raw(v):
        if faixa_raw:
            return faixa_raw[0] <= v <= faixa_raw[1]
        return preco_valido(chave, v)

    por_data = {}  # data → valor (primeiro válido por data vence)

    for tabela in soup.find_all("table"):
        for linha in tabela.find_all("tr")[1:]:
            cells = [c.get_text(strip=True) for c in linha.find_all(["td", "th"])]
            if len(cells) < 2:
                continue

            # Estratégia 1: data na col[0]
            data = parse_date_br(cells[0])
            if data:
                if data not in por_data:
                    for c in cells[1:6]:
                        v = parse_float_br(c)
                        if v and valido_raw(v):
                            vf = round(v * conversao, 4)
                            if preco_valido(chave, vf):
                                por_data[data] = vf
                            break
                continue

            # Estratégia 2: data em outra coluna
            idx_data = -1
            data_encontrada = None
            for i, c in enumerate(cells):
                d = parse_date_br(c)
                if d:
                    data_encontrada = d
                    idx_data = i
                    break

            if data_encontrada and data_encontrada not in por_data:
                for j, c in enumerate(cells):
                    if j == idx_data:
                        continue
                    v = parse_float_br(c)
                    if v and valido_raw(v):
                        vf = round(v * conversao, 4)
                        if preco_valido(chave, vf):
                            por_data[data_encontrada] = vf
                        break

    resultado = sorted(
        [{"data": d, "valor": v} for d, v in por_data.items()],
        key=lambda x: x["data"],
        reverse=True,
    )
    return resultado


def _extrair_historico_feijao(html: str, chave: str) -> list:
    """
    Extrai histórico de páginas de feijão do NoticiasAgricolas.
    Estrutura: <div class="cotacao"> com <div class="fechamento">DATA</div>
               e tabela interna com colunas Região | Valor | Var./Dia.
    Pega o primeiro preço válido por bloco (primeira região com cotação).
    """
    soup = BeautifulSoup(html, "html5lib")
    por_data = {}

    for bloco in soup.find_all("div", class_="cotacao"):
        # Data no div.fechamento: "Fechamento: 26/06/2026"
        fechamento = bloco.find("div", class_="fechamento")
        if not fechamento:
            continue
        texto_data = fechamento.get_text(strip=True)
        m = re.search(r"(\d{2}/\d{2}/\d{4})", texto_data)
        if not m:
            continue
        data = parse_date_br(m.group(1))
        if not data or data in por_data:
            continue

        # Primeiro preço válido na tabela interna (primeira região com cotação real)
        tabela = bloco.find("table")
        if not tabela:
            continue
        for linha in tabela.find_all("tr")[1:]:
            cells = [c.get_text(strip=True) for c in linha.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            for c in cells[1:]:
                v = parse_float_br(c)
                if v and preco_valido(chave, v):
                    por_data[data] = v
                    break
            if data in por_data:
                break

    resultado = sorted(
        [{"data": d, "valor": v} for d, v in por_data.items()],
        key=lambda x: x["data"],
        reverse=True,
    )
    return resultado


def coletar_historico_completo(chave: str) -> list:
    """
    Busca a página de cotações e extrai todos os dias disponíveis (~10 dias úteis).
    Feijão: usa _extrair_historico_feijao (div.cotacao + div.fechamento).
    Demais: usa _extrair_historico_completo (tabelas com data em coluna).
    """
    url = NA_COTACOES.get(chave)
    if not url:
        return []
    r = safe_get(url, timeout=25)
    if not r:
        return []

    if chave in ("feijao_carioca", "feijao_preto"):
        hist = _extrair_historico_feijao(r.text, chave)
    else:
        hist = _extrair_historico_completo(r.text, chave)

    if hist:
        print(f"    [{chave}] histórico página: {len(hist)} dias ({hist[-1]['data']} a {hist[0]['data']})")
    return hist


def eh_dia_util(data_str: str) -> bool:
    """Retorna False para sábados e domingos — mercados não operam."""
    try:
        from datetime import datetime
        return datetime.strptime(data_str, "%Y-%m-%d").weekday() < 5
    except Exception:
        return True


def mesclar_multiplos(existente: list, novos: list, max_dias: int = HISTORICO_MAX_DIAS) -> list:
    """
    Mescla lista de novos registros com histórico existente.
    Deduplica por data (novo sobrescreve existente), filtra fins de semana,
    recalcula variação, limita a max_dias.
    """
    por_data = {r["data"]: r["valor"] for r in existente if r.get("data") and r.get("valor") is not None}
    for r in novos:
        if r.get("data") and r.get("valor") is not None:
            por_data[r["data"]] = r["valor"]

    historico = sorted(
        [{"data": d, "valor": v} for d, v in por_data.items() if eh_dia_util(d)],
        key=lambda x: x["data"],
        reverse=True,
    )[:max_dias]

    resultado = []
    for i, rec in enumerate(historico):
        ant = historico[i + 1]["valor"] if i + 1 < len(historico) else None
        resultado.append({
            "data":         rec["data"],
            "valor":        rec["valor"],
            "variacao_pct": variacao_pct(rec["valor"], ant),
        })
    return resultado


def mesclar_historico(existente: list, novo_registro: dict, max_dias: int = HISTORICO_MAX_DIAS) -> list:
    """
    Adiciona novo_registro ao histórico existente.
    - Remove registros com a mesma data (atualiza)
    - Mantém ordenado do mais recente para o mais antigo
    - Limita ao max_dias mais recentes
    """
    if not novo_registro or not novo_registro.get("data"):
        return existente

    # Remove entrada da mesma data, se existir
    historico = [r for r in existente if r.get("data") != novo_registro["data"]]
    historico.append({"data": novo_registro["data"], "valor": novo_registro["valor"]})
    historico.sort(key=lambda x: x["data"], reverse=True)
    historico = historico[:max_dias]

    # Recalcula variacao_pct dia-a-dia
    resultado = []
    for i, rec in enumerate(historico):
        ant = historico[i + 1]["valor"] if i + 1 < len(historico) else None
        resultado.append({
            "data":         rec["data"],
            "valor":        rec["valor"],
            "variacao_pct": variacao_pct(rec["valor"], ant),
        })
    return resultado


def variacao_mes(historico: list):
    mes_atual = HOJE.strftime("%Y-%m")
    do_mes = [r for r in historico if r.get("data", "").startswith(mes_atual)]
    if len(do_mes) >= 2:
        return variacao_pct(do_mes[0]["valor"], do_mes[-1]["valor"])
    return None


# ═══════════════════════════════════════════════════════════════════════════
# MÓDULO 1 — DÓLAR
# ═══════════════════════════════════════════════════════════════════════════

def coletar_dolar() -> dict:
    print("  [Dólar] AwesomeAPI...")
    r = safe_get("https://economia.awesomeapi.com.br/json/last/USD-BRL")
    if r:
        try:
            d   = r.json()["USDBRL"]
            bid = round(float(d["bid"]), 4)
            pct = round(float(d.get("pctChange", 0)), 2)
            print(f"  [Dólar] R$ {bid:,.4f} ({pct:+.2f}%)")
            return {"valor": bid, "variacao_pct": pct, "bid": bid, "ask": round(float(d["ask"]), 4)}
        except Exception as exc:
            print(f"  [Dólar] Erro: {exc}")
    return {"valor": None, "variacao_pct": None, "bid": None, "ask": None}


# ═══════════════════════════════════════════════════════════════════════════
# MÓDULO 2 — COTAÇÕES DO DIA
# ═══════════════════════════════════════════════════════════════════════════

# NoticiasAgricolas — URLs exatas conforme documento de fontes
NA_COTACOES = {
    "arroz":          "https://www.noticiasagricolas.com.br/cotacoes/arroz/arroz-em-casca-esalq-bbm",
    "feijao_carioca": "https://www.noticiasagricolas.com.br/cotacoes/feijao/precos-do-feijao-carioca-nota-8-a-8-5-cepea-cna",
    "feijao_preto":   "https://www.noticiasagricolas.com.br/cotacoes/feijao/precos-do-feijao-preto-tipo-1-cepea-cna",
    "acucar":         "https://www.noticiasagricolas.com.br/cotacoes/sucroenergetico/acucar-cristal-cepea",
    "soja":           "https://www.noticiasagricolas.com.br/cotacoes/soja/soja-indicador-cepea-esalq-porto-paranagua",
    "trigo":          "https://www.noticiasagricolas.com.br/cotacoes/trigo/preco-medio-do-trigo-cepea-esalq",
    "cafe":           "https://www.noticiasagricolas.com.br/cotacoes/cafe/indicador-cepea-esalq-cafe-arabica",
    "leite":          "https://www.noticiasagricolas.com.br/cotacoes/leite",
}

# Agrolink — fallback
AGROLINK_COTACOES = {
    "arroz":          "https://www.agrolink.com.br/cotacoes/graos/arroz",
    "feijao_carioca": "https://www.agrolink.com.br/cotacoes/graos/feijao-carioca",
    "acucar":         "https://www.agrolink.com.br/cotacoes/acucar-e-alcool/acucar-cristal",
    "soja":           "https://www.agrolink.com.br/cotacoes/graos/soja-em-grao",
    "trigo":          "https://www.agrolink.com.br/cotacoes/graos/trigo",
    "cafe":           "https://www.agrolink.com.br/cotacoes/cafe/cafe-arabica",
    # leite não está no Agrolink — tratado via fontes especializadas
}


# Fator de conversão de unidade por commodity (para páginas que retornam unidade diferente)
# trigo: NoticiasAg retorna R$/t — convertemos para R$/sc 60kg (×0,06)
CONVERSAO_FATOR = {
    "trigo": 0.06,
}
# Faixa de validação da unidade bruta (antes da conversão)
FAIXAS_RAW = {
    "trigo": (800, 3000),  # R$/t
}


def _extrair_preco_pagina(html: str, chave: str):
    """
    Extrai o preço mais recente de uma página de cotações.
    Estratégias (em ordem de prioridade):
      1. Data na col[0] + preço em col[1..4]  (formato padrão)
      2. Data em qualquer coluna + preço válido em qualquer outra coluna
         (para tabelas onde col[0] é nome do produto, ex: NoticiasAg feijão)
      3. Sem data na linha — usa hoje (FALLBACK, só usado se nenhum S1/S2 encontrado)
    Candidatos com data explícita (S1/S2) têm prioridade absoluta sobre S3.
    """
    soup = BeautifulSoup(html, "html5lib")
    # Faixa para validação raw (antes de conversão)
    faixa_raw   = FAIXAS_RAW.get(chave)
    conversao   = CONVERSAO_FATOR.get(chave, 1.0)
    data_hoje   = HOJE.strftime("%Y-%m-%d")

    def valido_raw(v):
        """Valida o valor antes de aplicar conversão."""
        if faixa_raw:
            return faixa_raw[0] <= v <= faixa_raw[1]
        return preco_valido(chave, v)

    candidatos_datados   = []  # S1 + S2: têm data explícita
    candidatos_sem_data  = []  # S3: data inferida como hoje (baixa confiança)

    for tabela in soup.find_all("table"):
        linhas = tabela.find_all("tr")
        for linha in linhas[1:]:
            cells = [c.get_text(strip=True) for c in linha.find_all(["td", "th"])]
            if len(cells) < 2:
                continue

            # Estratégia 1: data na coluna 0
            data = parse_date_br(cells[0])
            if data:
                for c in cells[1:6]:
                    v = parse_float_br(c)
                    if v and valido_raw(v):
                        candidatos_datados.append({"data": data, "valor": round(v * conversao, 4)})
                        break
                continue

            # Estratégia 2: procura data em qualquer coluna
            data_encontrada = None
            idx_data = -1
            for i, c in enumerate(cells):
                d = parse_date_br(c)
                if d:
                    data_encontrada = d
                    idx_data = i
                    break

            if not data_encontrada:
                # Estratégia 3 (baixa confiança): sem data → usa hoje
                for c in cells:
                    v = parse_float_br(c)
                    if v and valido_raw(v):
                        candidatos_sem_data.append({"data": data_hoje, "valor": round(v * conversao, 4)})
                        break
                continue

            # S2: Encontrou data em idx_data — pega preço em qualquer outra coluna
            for i, c in enumerate(cells):
                if i == idx_data:
                    continue
                v = parse_float_br(c)
                if v and valido_raw(v):
                    candidatos_datados.append({"data": data_encontrada, "valor": round(v * conversao, 4)})
                    break

    # Prioriza candidatos com data explícita; só usa S3 se nada mais encontrado
    candidatos = candidatos_datados if candidatos_datados else candidatos_sem_data
    if not candidatos:
        return None

    # Filtra os com data convertida: deve passar na faixa final da commodity
    candidatos = [c for c in candidatos if preco_valido(chave, c["valor"])]
    if not candidatos:
        return None

    candidatos.sort(key=lambda x: x["data"], reverse=True)
    return candidatos[0]


def coletar_cotacao_hoje(chave: str) -> dict | None:
    """Tenta NoticiasAgricolas → Agrolink. Retorna {data, valor} ou None."""

    # ── CEPEA API (quando disponível) ──
    if CEPEA_API_KEY:
        # TODO: implementar quando contratado. Ver docstring no topo.
        pass

    # ── NoticiasAgricolas ──
    url = NA_COTACOES.get(chave)
    if url:
        r = safe_get(url, timeout=20)
        if r:
            preco = _extrair_preco_pagina(r.text, chave)
            if preco:
                print(f"    [{chave}] NoticiasAg: R${preco['valor']} em {preco['data']}")
                return preco
        time.sleep(1)

    # ── Agrolink (fallback) ──
    url = AGROLINK_COTACOES.get(chave)
    if url:
        r = safe_get(url, timeout=20)
        if r:
            preco = _extrair_preco_pagina(r.text, chave)
            if preco:
                print(f"    [{chave}] Agrolink: R${preco['valor']} em {preco['data']}")
                return preco
        time.sleep(1)

    # ── Fontes especializadas para leite ──
    if chave == "leite":
        for fonte, url in [
            ("Scot Consultoria", "https://www.scotconsultoria.com.br/cotacoes/leite/"),
            ("Scot Consultoria", "https://www.scotconsultoria.com.br/noticias/artigos/?tipo=leite"),
            ("MilkPoint",        "https://www.milkpoint.com.br/preco-do-leite/"),
            ("CILeite Embrapa",  "https://cileite.com.br/preco-do-leite"),
            ("NoticiasAg Leite", "https://www.noticiasagricolas.com.br/cotacoes/leite/"),
        ]:
            r = safe_get(url, timeout=20)
            if r:
                preco = _extrair_preco_pagina(r.text, "leite")
                if preco:
                    print(f"    [leite] {fonte}: R${preco['valor']} em {preco['data']}")
                    return preco
            time.sleep(1)

    print(f"    [{chave}] Sem cotação disponível hoje.")
    return None


# ═══════════════════════════════════════════════════════════════════════════
# MÓDULO 3 — FEIJÃO PRETO (IBRAFE)
# ═══════════════════════════════════════════════════════════════════════════

def coletar_feijao_preto_hoje() -> dict | None:
    # Primário: NoticiasAgricolas — URL específica do documento de fontes
    url = NA_COTACOES.get("feijao_preto")
    if url:
        r = safe_get(url, timeout=20)
        if r:
            preco = _extrair_preco_pagina(r.text, "feijao_preto")
            if preco:
                print(f"    [feijao_preto] NoticiasAg: R${preco['valor']} em {preco['data']}")
                return preco
        time.sleep(1)

    # Fallback: IBRAFE
    print("  [IBRAFE] Feijão Preto (fallback)...")
    for url in ["https://www.ibrafe.org", "https://www.ibrafe.org/cotacoes"]:
        r = safe_get(url, timeout=20)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "html5lib")
        for tabela in soup.find_all("table"):
            texto = tabela.get_text().lower()
            if any(k in texto for k in ["preto", "cotaç", "preço"]):
                for linha in tabela.find_all("tr")[1:]:
                    cells = [c.get_text(strip=True) for c in linha.find_all(["td", "th"])]
                    data  = parse_date_br(cells[0]) if cells else None
                    valor = None
                    for c in cells[1:5]:
                        v = parse_float_br(c)
                        if v and preco_valido("feijao_preto", v):
                            valor = v
                            break
                    if data and valor:
                        print(f"    [feijao_preto] IBRAFE: R${valor} em {data}")
                        return {"data": data, "valor": valor}

    print("    [feijao_preto] Sem cotação disponível hoje.")
    return None


# ═══════════════════════════════════════════════════════════════════════════
# MÓDULO 4 — SAFRA
# ═══════════════════════════════════════════════════════════════════════════

def coletar_safra() -> list:
    noticias   = []
    limite_14d = date.today() - timedelta(days=14)

    # IBGE SIDRA
    print("  [IBGE SIDRA] Produção agrícola...")
    r = safe_get(
        "https://servicodados.ibge.gov.br/api/v3/agregados/5457/periodos/-1/"
        "variaveis/214|216?localidades=N1[all]",
        timeout=25,
    )
    if r:
        try:
            for item in r.json()[:4]:
                nome_var = item.get("variavel", "Produção")
                for res in item.get("resultados", [])[:1]:
                    for serie in res.get("series", [])[:1]:
                        local = serie.get("localidade", {}).get("nome", "Brasil")
                        vals  = serie.get("serie", {})
                        if vals:
                            periodo, valor = list(vals.items())[-1]
                            if valor and valor not in ("...", "-", ""):
                                noticias.append({
                                    "titulo": f"IBGE — {nome_var} ({local}): {valor} t em {periodo}",
                                    "fonte":  "IBGE SIDRA",
                                    "data":   HOJE.strftime("%Y-%m-%d"),
                                    "url":    "https://sidra.ibge.gov.br/tabela/5457",
                                })
        except Exception as exc:
            print(f"  [IBGE SIDRA] {exc}")

    # RSS safra
    feeds_safra = [
        ("CONAB",             "https://www.conab.gov.br/noticias?format=feed&type=rss"),
        ("CONAB",             "https://www.conab.gov.br/ultimas-noticias?format=feed&type=rss"),
        ("Notícias Agrícolas","https://www.noticiasagricolas.com.br/noticias/safra.rss"),
        ("Agrolink",          "https://www.agrolink.com.br/rss/safra.aspx"),
    ]
    safra_kw = ["safra", "colheita", "plantio", "produ", "estoque", "conab", "previs"]

    print("  [Safra RSS]...")
    for fonte, url in feeds_safra:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                titulo = entry.get("title", "").strip()
                if not any(k in titulo.lower() for k in safra_kw):
                    continue
                pub = entry.get("published_parsed") or entry.get("updated_parsed")
                ds  = date(*pub[:3]).isoformat() if pub else HOJE.strftime("%Y-%m-%d")
                if pub and date(*pub[:3]) < limite_14d:
                    continue
                noticias.append({
                    "titulo": titulo,
                    "tema":   classificar_tema(titulo),
                    "fonte":  fonte,
                    "data":   ds,
                    "url":    entry.get("link", ""),
                })
        except Exception as exc:
            print(f"    [{fonte}] {exc}")

    vistos, unicos = set(), []
    for n in sorted(noticias, key=lambda x: x["data"], reverse=True):
        if n["titulo"] not in vistos:
            vistos.add(n["titulo"])
            unicos.append(n)
    print(f"  [Safra] {len(unicos)} notícias")
    return unicos[:10]


# ═══════════════════════════════════════════════════════════════════════════
# MÓDULO 5 — NOTÍCIAS RSS
# ═══════════════════════════════════════════════════════════════════════════

RSS_POR_COMMODITY = {
    "arroz":          [("Notícias Agrícolas","https://www.noticiasagricolas.com.br/noticias/graos.rss"),
                       ("Notícias Agrícolas","https://www.noticiasagricolas.com.br/noticias/arroz.rss"),
                       ("Canal Rural",       "https://www.canalrural.com.br/rss/noticias/")],
    "feijao_carioca": [("Notícias Agrícolas","https://www.noticiasagricolas.com.br/noticias/feijao.rss"),
                       ("IBRAFE",            "https://www.ibrafe.org/feed/"),
                       ("Agrolink",          "https://www.agrolink.com.br/rss/feijao.aspx")],
    "feijao_preto":   [("Notícias Agrícolas","https://www.noticiasagricolas.com.br/noticias/feijao.rss"),
                       ("IBRAFE",            "https://www.ibrafe.org/feed/"),
                       ("Agrolink",          "https://www.agrolink.com.br/rss/feijao.aspx")],
    "acucar":         [("Notícias Agrícolas","https://www.noticiasagricolas.com.br/noticias/sucroenergetico.rss"),
                       ("Agrolink",          "https://www.agrolink.com.br/rss/acucar.aspx"),
                       ("UNICA",             "https://unica.com.br/feed/")],
    "soja":           [("Notícias Agrícolas","https://www.noticiasagricolas.com.br/noticias/soja.rss"),
                       ("Agrolink",          "https://www.agrolink.com.br/rss/soja.aspx"),
                       ("Canal Rural",       "https://www.canalrural.com.br/rss/noticias/")],
    "trigo":          [("Notícias Agrícolas","https://www.noticiasagricolas.com.br/noticias/trigo.rss"),
                       ("Agrolink",          "https://www.agrolink.com.br/rss/trigo.aspx")],
    "cafe":           [("Notícias Agrícolas","https://www.noticiasagricolas.com.br/noticias/cafe.rss"),
                       ("Cecafé",            "https://www.cecafe.com.br/feed/"),
                       ("Agrolink",          "https://www.agrolink.com.br/rss/cafe.aspx")],
    "leite":          [("MilkPoint",         "https://www.milkpoint.com.br/rss/"),
                       ("Scot Consultoria",  "https://www.scotconsultoria.com.br/rss/"),
                       ("Notícias Agrícolas","https://www.noticiasagricolas.com.br/noticias/leite.rss")],
}

RSS_GERAIS = [
    ("Notícias Agrícolas","https://www.noticiasagricolas.com.br/rss/noticias"),
    ("Agrolink",          "https://www.agrolink.com.br/rss/noticias.aspx"),
    ("Canal Rural",       "https://www.canalrural.com.br/rss/noticias/"),
    ("Globo Rural",       "https://revistagloborural.globo.com/rss2.xml"),
    ("CONAB",             "https://www.conab.gov.br/noticias?format=feed&type=rss"),
]

KEYWORDS = {
    "arroz":          ["arroz"],
    "feijao_carioca": ["feijão carioca","feijao carioca","carioca"],
    "feijao_preto":   ["feijão preto","feijao preto"],
    "acucar":         ["açúcar","acucar","sucro","icumsa","cana"],
    "soja":           ["soja"],
    "trigo":          ["trigo"],
    "cafe":           ["café","cafe","arábica","arabica","conilon"],
    "leite":          ["leite","lácteo","lacteo"],
}

# Palavras-chave que indicam impacto no preço — filtra notícias irrelevantes
PRECO_RELEVANTES_KW = [
    "preço", "preco", "cotação", "cotacao", "mercado", "alta", "queda",
    "valoriz", "desvaloriza", "safra", "estoque", "oferta", "demanda",
    "câmbio", "cambio", "dólar", "dolar", "exportação", "exportacao",
    "importação", "importacao", "clima", "seca", "chuva", "geada",
    "conab", "produção", "producao", "colheita", "plantio", "sanção",
    "embargo", "guerra", "conflito", "custo", "inflação", "inflacao",
    "supersafra", "déficit", "excedente", "consumo", "abastecimento",
]

# Classificação de tema por palavras-chave no título
TEMA_KEYWORDS = {
    "Clima":            ["chuva", "seca", "geada", "clima", "tempo", "temperatura",
                         "estiagem", "precipitação", "el niño", "la niña", "umidade",
                         "granizo", "déficit hídrico", "enchente", "inundação", "vendaval"],
    "Geopolítica":      ["guerra", "conflito", "sanção", "embargo", "acordo", "tratado",
                         "rússia", "ucrânia", "china", "eua", "estados unidos",
                         "governo federal", "política", "eleição", "tarifas", "trump"],
    "Safra":            ["safra", "colheita", "plantio", "área plantada", "produção",
                         "produtividade", "estimativa", "conab", "previsão", "supersafra",
                         "segundo cultivo", "safrinha"],
    "Câmbio":           ["dólar", "câmbio", "real", "moeda", "brl", "usd", "taxa de câmbio",
                         "banco central", "juros", "selic", "desvalorização do real"],
    "Oferta & Demanda": ["oferta", "demanda", "estoque", "consumo", "abastecimento",
                         "excedente", "deficit", "déficit", "exportação", "importação",
                         "frete", "porto", "logística", "processamento"],
}


def classificar_tema(titulo: str) -> str:
    tl = titulo.lower()
    for tema, palavras in TEMA_KEYWORDS.items():
        if any(p in tl for p in palavras):
            return tema
    return "Mercado"


def is_relevante(titulo: str) -> bool:
    tl = titulo.lower()
    return any(k in tl for k in PRECO_RELEVANTES_KW)


# Keywords de safra por commodity para filtrar notícias de safra dentro do card
SAFRA_KEYWORDS_COMMODITY = {
    "arroz":          ["arroz"],
    "feijao_carioca": ["feijão", "feijao", "carioca", "bean"],
    "feijao_preto":   ["feijão", "feijao", "preto", "bean"],
    "acucar":         ["açúcar", "acucar", "cana", "sucro"],
    "soja":           ["soja"],
    "trigo":          ["trigo"],
    "cafe":           ["café", "cafe", "arábica", "arabica", "conilon"],
    "leite":          ["leite", "lácteo", "lacteo", "bovino", "pecuária"],
}

LIMITE_NOTICIAS_DIAS = 7
MAX_POR_COMMODITY    = 5

# ─── Red Flags — fatores externos ───────────────────────────────────────────
COMMODITIES_DOLARIZADAS = {"soja", "cafe", "acucar", "trigo"}
DOLAR_THRESHOLD_PCT     = 1.5   # variação % do dólar que aciona alerta cambial

KEYWORDS_RISCO_EXTERNO = [
    "geada", "seca", "estiagem", "enchente", "inundação", "ciclone", "tornado",
    "granizo", "vendaval", "déficit hídrico", "crise hídrica",
    "guerra", "conflito", "embargo", "sanção", "bloqueio",
    "desabastecimento", "colapso", "crise de abastecimento",
]


def calcular_red_flags(chave: str, historico: list, dolar_var, noticias: list) -> list:
    """
    Gera lista de alertas (Red Flags) para a commodity.
    Item 1: variação > 3% em 1 dia ou > 5% em 3 dias úteis
    Item 2: dólar acima do threshold (commodities dolarizadas) + keywords de risco nas notícias
    """
    flags = []

    # ── Item 1a: variação > 3% em 1 dia ──────────────────────────────────────
    if historico and historico[0].get("variacao_pct") is not None:
        v1 = historico[0]["variacao_pct"]
        if abs(v1) >= 3.0:
            dir_ = "alta" if v1 > 0 else "queda"
            flags.append({
                "tipo":               "variacao_dia",
                "mensagem":           f"Variação de {v1:+.1f}% em 1 dia — movimento atípico de {dir_}",
                "severidade":         "alta",
                "impacto_tendencia":  dir_,
            })

    # ── Item 1b: variação > 5% em 3 dias úteis ───────────────────────────────
    if len(historico) >= 3:
        v3 = variacao_pct(historico[0]["valor"], historico[2]["valor"])
        if v3 is not None and abs(v3) >= 5.0:
            dir_ = "alta" if v3 > 0 else "queda"
            flags.append({
                "tipo":               "variacao_3d",
                "mensagem":           f"Variação acumulada de {v3:+.1f}% em 3 dias — tendência forte de {dir_}",
                "severidade":         "alta",
                "impacto_tendencia":  dir_,
            })

    # ── Item 2a: dólar com variação significativa ─────────────────────────────
    if chave in COMMODITIES_DOLARIZADAS and dolar_var is not None and abs(dolar_var) >= DOLAR_THRESHOLD_PCT:
        dir_ = "alta" if dolar_var > 0 else "queda"
        flags.append({
            "tipo":               "dolar",
            "mensagem":           f"Dólar {dolar_var:+.2f}% no dia — pressão cambial sobre preços desta commodity",
            "severidade":         "media",
            "impacto_tendencia":  dir_,
        })

    # ── Item 2b: palavras-chave de risco nas notícias ─────────────────────────
    vistos = set()
    for n in noticias:
        tl = (n.get("titulo") or "").lower()
        for kw in KEYWORDS_RISCO_EXTERNO:
            if kw in tl and kw not in vistos:
                vistos.add(kw)
                flags.append({
                    "tipo":               "evento_externo",
                    "mensagem":           f"Evento externo detectado: {n['titulo'][:120]}",
                    "severidade":         "media",
                    "impacto_tendencia":  "alta",
                    "fonte":              n.get("fonte", ""),
                    "url":                n.get("url", ""),
                })
                break

    return flags


def calcular_suporte_resistencia(historico: list) -> dict:
    """Calcula suporte (mínima) e resistência (máxima) do histórico disponível."""
    valores = [r["valor"] for r in historico if r.get("valor") is not None]
    if len(valores) < 3:
        return {"suporte": None, "resistencia": None}
    return {
        "suporte":    round(min(valores), 4),
        "resistencia": round(max(valores), 4),
    }


def insight_sr(preco_atual, suporte, resistencia) -> str:
    """Texto de insight sobre posição relativa ao suporte/resistência."""
    if suporte is None or resistencia is None or preco_atual is None:
        return ""
    if suporte == resistencia:
        return ""
    amp = resistencia - suporte
    pos = (preco_atual - suporte) / amp * 100
    if pos >= 85:
        return (f" Preço próximo à resistência histórica (R$ {resistencia:.2f})"
                " — zona de pressão vendedora; possível correção à frente.")
    if pos <= 15:
        return (f" Preço próximo ao suporte histórico (R$ {suporte:.2f})"
                " — zona de atenção; risco de queda adicional.")
    return (f" Preço em zona neutra entre suporte (R$ {suporte:.2f})"
            f" e resistência (R$ {resistencia:.2f}).")


def _processar_entry(entry, fonte: str) -> dict | None:
    """Converte um entry de feedparser em dict de notícia com tema classificado."""
    titulo = entry.get("title", "").strip()
    if not titulo:
        return None
    if not is_relevante(titulo):
        return None
    pub = entry.get("published_parsed") or entry.get("updated_parsed")
    if pub:
        dt   = date(*pub[:3])
        diff = (date.today() - dt).days
        ds   = dt.isoformat()
    else:
        diff = 0
        ds   = HOJE.strftime("%Y-%m-%d")
    if diff > LIMITE_NOTICIAS_DIAS:
        return None
    return {
        "titulo": titulo,
        "tema":   classificar_tema(titulo),
        "fonte":  entry.get("source", {}).get("title", "") or fonte,
        "data":   ds,
        "url":    entry.get("link", ""),
    }


def coletar_noticias_rss() -> dict:
    por_commodity = {k: [] for k in KEYWORDS}
    print("  [RSS] Feeds por commodity...")

    for chave, feeds in RSS_POR_COMMODITY.items():
        for fonte, url in feeds:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries:
                    n = _processar_entry(entry, fonte)
                    if n:
                        por_commodity[chave].append(n)
            except Exception as exc:
                print(f"    [{chave}/{fonte}] {exc}")

    print("  [RSS] Feeds gerais...")
    for fonte, url in RSS_GERAIS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                n = _processar_entry(entry, fonte)
                if not n:
                    continue
                tl = n["titulo"].lower()
                for chave, palavras in KEYWORDS.items():
                    if any(p in tl for p in palavras):
                        por_commodity[chave].append(n)
        except Exception as exc:
            print(f"    [{fonte}] {exc}")

    for chave in por_commodity:
        vistos, unicos = set(), []
        for n in sorted(por_commodity[chave], key=lambda x: x["data"], reverse=True):
            if n["titulo"] not in vistos:
                vistos.add(n["titulo"])
                unicos.append(n)
        por_commodity[chave] = unicos[:MAX_POR_COMMODITY]
        print(f"  [RSS] {chave}: {len(por_commodity[chave])} notícias")

    return por_commodity


# ═══════════════════════════════════════════════════════════════════════════
# MÓDULO 6 — TENDÊNCIA E INSIGHTS
# ═══════════════════════════════════════════════════════════════════════════

TEXTOS_CURTO = {
    "alta":      "Preço em trajetória de alta de {var:.1f}% no período. Nos próximos 30 a 90 dias, tendência de pressão para cima. Recomenda-se antecipar compras ou garantir volume contratado.",
    "queda":     "Preço em trajetória de queda de {var:.1f}% no período. Nos próximos 30 a 90 dias, perspectiva de preços mais favoráveis. Avalie aguardar para comprar.",
    "estavel":   "Preço estável ({var:.1f}% no período). Nos próximos 30 a 90 dias, sem sinal forte de mudança. Compras conforme demanda operacional.",
    "indefinida":"Dados insuficientes para análise de curto prazo (30-90 dias). Monitore as atualizações diárias.",
}
TEXTOS_MEDIO = {
    "alta":      "Perspectiva de pressão no médio prazo (90-360 dias). Considere contratos mais longos ou estoque estratégico.",
    "queda":     "Tendência de queda no médio prazo (90-360 dias). Negocie contratos e evite fixar preços altos por longos períodos.",
    "estavel":   "Mercado equilibrado no médio prazo (90-360 dias). Contratos padrão adequados.",
    "indefinida":"Histórico insuficiente para médio prazo. Acompanhe CONAB e CEPEA.",
}
RECOMENDACAO_MAP = {("alta","alta"): "comprar", ("alta","estavel"): "comprar", ("queda","queda"): "segurar"}


def calcular_tendencia(historico: list, var_mes) -> dict:
    # ── Curto prazo: variação dos últimos 7 pregões (momentum recente) ───────
    if len(historico) >= 2:
        n_curto = min(7, len(historico))
        ref_curto = variacao_pct(historico[0]["valor"], historico[n_curto - 1]["valor"])
    else:
        ref_curto = None

    if ref_curto is None:
        tc = "indefinida"; ref_curto = 0.0
    elif ref_curto >= 1.5:
        tc = "alta"
    elif ref_curto <= -1.5:
        tc = "queda"
    else:
        tc = "estavel"

    # ── Médio prazo: variação acumulada do período (todos os dados do mês) ───
    ref_medio = var_mes
    if ref_medio is None and len(historico) >= 2:
        ref_medio = variacao_pct(historico[0]["valor"], historico[-1]["valor"])

    if ref_medio is None:
        tm = "indefinida"; ref_medio = 0.0
    elif ref_medio >= 1.5:
        tm = "alta"
    elif ref_medio <= -1.5:
        tm = "queda"
    else:
        tm = "estavel"

    return {
        "tendencia_curta":     tc,
        "tendencia_media":     tm,
        "insight_curto_prazo": TEXTOS_CURTO[tc].format(var=abs(ref_curto)),
        "insight_medio_prazo": TEXTOS_MEDIO[tm],
        "recomendacao":        RECOMENDACAO_MAP.get((tc, tm), "aguardar"),
    }


# ═══════════════════════════════════════════════════════════════════════════
# METADADOS
# ═══════════════════════════════════════════════════════════════════════════

COMMODITIES_META = {
    "arroz":          {"nome": "Arroz em Casca",                  "unidade": "R$/sc 50kg",  "fonte_primaria": "CEPEA/IRGA-RS via NoticiasAgricolas"},
    "feijao_carioca": {"nome": "Feijão Carioca",                  "unidade": "R$/sc 60kg",  "fonte_primaria": "CEPEA/CNA via NoticiasAgricolas"},
    "feijao_preto":   {"nome": "Feijão Preto",                    "unidade": "R$/sc 60kg",  "fonte_primaria": "CEPEA/CNA via NoticiasAgricolas"},
    "acucar":         {"nome": "Açúcar Cristal (ICUMSA 130-180)", "unidade": "R$/sc 50kg",  "fonte_primaria": "CEPEA/ESALQ via NoticiasAgricolas"},
    "soja":           {"nome": "Soja",                            "unidade": "R$/sc 60kg",  "fonte_primaria": "CEPEA/Paranaguá via NoticiasAgricolas"},
    "trigo":          {"nome": "Trigo",                           "unidade": "R$/sc 60kg",  "fonte_primaria": "CEPEA/ESALQ via NoticiasAgricolas"},
    "cafe":           {"nome": "Café Arábica (Tipo 6)",           "unidade": "R$/sc 60kg",  "fonte_primaria": "CEPEA/ESALQ via NoticiasAgricolas"},
    "leite":          {"nome": "Leite ao Produtor",               "unidade": "R$/litro",    "fonte_primaria": "CEPEA/CNA via NoticiasAgricolas"},
}


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 65)
    print(f"Dashboard Commodities — {HOJE.strftime('%Y-%m-%d %H:%M:%S')} BRT")
    print(f"CEPEA API: {'✓ ativa' if CEPEA_API_KEY else 'não configurada (scraping)'}")
    print("=" * 65)

    print("\n[1/5] Dólar...")
    dolar = coletar_dolar()

    print("\n[2/5] Carregando histórico existente...")
    historico_existente = carregar_historico_existente()

    print("\n[3/5] Cotações (histórico completo da página + NoticiasAgricolas)...")
    commodities_out = {}

    for chave, meta in COMMODITIES_META.items():
        print(f"  [{chave}]")

        # Coleta todos os dias disponíveis na página (~10 dias úteis)
        hist_pagina = coletar_historico_completo(chave)

        # Feijão preto: fallback IBRAFE se NoticiasAgricolas falhar
        if not hist_pagina and chave == "feijao_preto":
            preco_hoje = coletar_feijao_preto_hoje()
            hist_pagina = [preco_hoje] if preco_hoje else []
        elif not hist_pagina:
            # Para leite: tenta fontes especializadas como ponto único
            if chave == "leite":
                preco_hoje = coletar_cotacao_hoje(chave)
                hist_pagina = [preco_hoje] if preco_hoje else []

        time.sleep(1.5)

        # Mescla histórico da página com histórico acumulado existente
        hist_ant = historico_existente.get(chave, [])
        hist_raw = [{"data": r["data"], "valor": r["valor"]} for r in hist_ant]
        historico = mesclar_multiplos(hist_raw, hist_pagina)

        preco_hoje = hist_pagina[0] if hist_pagina else None
        status = "ok" if preco_hoje else ("fallback" if historico else "sem_dados")
        vm     = variacao_mes(historico)
        tend   = calcular_tendencia(historico, vm)

        commodities_out[chave] = {
            **meta,
            "status":           status,
            "historico_5d":     historico[:5],   # exibe 5 dias no dashboard
            "historico_30d":    historico,        # mantém 30 dias internamente
            "variacao_mes_pct": vm,
            **tend,
            "noticias": [],  # preenchido no passo 4
        }

    print("\n[4/5] Safra e notícias RSS...")
    safra    = coletar_safra()
    noticias = coletar_noticias_rss()
    dolar_var = dolar.get("variacao_pct")

    for chave in commodities_out:
        noticias_commodity = noticias.get(chave, [])
        commodities_out[chave]["noticias"] = noticias_commodity

        # Safra filtrada por commodity
        kws = SAFRA_KEYWORDS_COMMODITY.get(chave, [])
        safra_commodity = [
            n for n in safra
            if any(k in n["titulo"].lower() for k in kws)
        ][:3]
        commodities_out[chave]["safra_noticias"] = safra_commodity

        # Suporte e resistência (usa historico_30d para mais pontos)
        hist30 = commodities_out[chave].get("historico_30d", [])
        sr = calcular_suporte_resistencia(hist30)
        commodities_out[chave].update(sr)

        # Red Flags (variação atípica + dólar + eventos externos)
        hist5 = commodities_out[chave].get("historico_5d", [])
        todas_noticias = noticias_commodity + safra_commodity
        flags = calcular_red_flags(chave, hist5, dolar_var, todas_noticias)
        commodities_out[chave]["red_flags"] = flags

        # Override de tendência se red flag de variação atípica confirmada
        for flag in flags:
            if flag.get("impacto_tendencia") in ("alta", "queda") and \
               flag["tipo"] in ("variacao_dia", "variacao_3d"):
                nova_tc = flag["impacto_tendencia"]
                commodities_out[chave]["tendencia_curta"] = nova_tc
                commodities_out[chave]["recomendacao"] = RECOMENDACAO_MAP.get(
                    (nova_tc, commodities_out[chave]["tendencia_media"]), "aguardar"
                )
                break  # a variação mais severa já tomou conta

        # Complementa insight com posição suporte/resistência
        preco_atual = hist5[0]["valor"] if hist5 else None
        txt_sr = insight_sr(preco_atual, sr["suporte"], sr["resistencia"])
        if txt_sr:
            commodities_out[chave]["insight_curto_prazo"] += txt_sr

    # Status geral
    com_dado = sum(1 for c in commodities_out.values() if c["historico_5d"])
    total    = len(commodities_out)
    ok_count = sum(1 for c in commodities_out.values() if c["status"] == "ok")
    status_geral = "ok" if ok_count == total else ("parcial" if com_dado > 0 else "erro")

    dados = {
        "ultima_atualizacao": HOJE.strftime("%Y-%m-%dT%H:%M:%S"),
        "status_coleta":      status_geral,
        "dolar":              dolar,
        "safra":              {"ultima_atualizacao": HOJE.strftime("%Y-%m-%dT%H:%M:%S"), "noticias": safra},
        "commodities":        commodities_out,
    }

    print("\n[5/5] Salvando JSON...")
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)

    print(f"\nStatus: {status_geral.upper()} | Com dados: {com_dado}/{total}")
    for k, c in commodities_out.items():
        preco = f"R${c['historico_5d'][0]['valor']}" if c["historico_5d"] else "—"
        dias  = len(c["historico_5d"])
        print(f"  {k:<20} [{c['status']:<9}] {preco:<15} ({dias} dias histórico)")
    print("=" * 65)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
