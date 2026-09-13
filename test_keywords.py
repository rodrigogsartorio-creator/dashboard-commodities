"""Check mínimo do matching de KEYWORDS. Rodar: python test_keywords.py"""

from coletar_dados import KEYWORDS, _casa_keyword


def test_feijao_preto_exige_contexto_de_feijao():
    kp = KEYWORDS["feijao_preto"]
    # boletins CEPEA: "preto" solto, mas o título cita feijão
    assert _casa_keyword("feijão/cepea: qualidade sustenta o preto", kp)
    assert _casa_keyword("feijao/cepea: cotacoes do preto seguem firmes", kp)
    assert _casa_keyword("feijão preto tem alta de 3% na semana", kp)
    # "preto" fora de contexto de feijão não pode casar (feeds gerais)
    assert not _casa_keyword("café preto: consumo cresce no brasil", kp)
    assert not _casa_keyword("arroz preto ganha espaço no mercado gourmet", kp)


def test_outras_commodities_seguem_por_substring():
    assert _casa_keyword("feijão/cepea: carioca recua com oferta", KEYWORDS["feijao_carioca"])
    assert _casa_keyword("soja sobe forte nos eua com foco no clima", KEYWORDS["soja"])
    assert not _casa_keyword("mercado de soja opera em alta", KEYWORDS["trigo"])


if __name__ == "__main__":
    test_feijao_preto_exige_contexto_de_feijao()
    test_outras_commodities_seguem_por_substring()
    print("ok")
