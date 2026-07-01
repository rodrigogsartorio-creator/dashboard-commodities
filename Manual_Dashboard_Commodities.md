# DASHBOARD MERCADO COMMODITIES
## Manual de Uso para o Departamento de Compras

**Vila Vitória Distribuidora de Alimentos**
Julho de 2026

---

## 1. Objetivo do Dashboard

O Dashboard Mercado Commodities é uma ferramenta de apoio à decisão de compra para o Departamento de Compras da Vila Vitória. Ele coleta, consolida e analisa automaticamente dados de preço e notícias de 8 commodities agrícolas essenciais para a operação da empresa, gerando uma recomendação diária fundamentada para cada produto.

O sistema responde a três perguntas práticas:

- É o momento certo para comprar agora, ou é melhor esperar?
- Quais são os riscos e as oportunidades de preço nos próximos 7 a 90 dias?
- Que evento ou data devo monitorar antes de revisar minha decisão?

O dashboard é atualizado automaticamente todos os dias úteis às **07h50 (horário de Brasília)**, permitindo que o comprador inicie o dia com informações de mercado atualizadas.

---

## 2. Commodities Monitoradas

| Commodity | Unidade | Fonte Principal |
| --- | --- | --- |
| Arroz em Casca | R$/sc 50kg | CEPEA/IRGA-RS |
| Feijão Carioca | R$/sc 60kg | CEPEA/CNA |
| Feijão Preto | R$/sc 60kg | IBRAFE |
| Açúcar Cristal ICUMSA 130 | R$/sc 50kg | CEPEA/ESALQ-SP |
| Soja | R$/sc 60kg | CEPEA/Paranaguá |
| Trigo | R$/sc 60kg | CEPEA/ESALQ |
| Café Arábica Tipo 6 | R$/sc 60kg | CEPEA/ESALQ |
| Leite ao Produtor | R$/litro | CEPEA/CNA |

> **Nota sobre açúcar:** o dashboard monitora exclusivamente Açúcar Cristal ICUMSA 130-180 (São Paulo), que é a referência para o mercado interno brasileiro. Não confundir com açúcar branco refinado (ICUMSA ≤ 45), cujos preços são diferentes.

---

## 3. Estrutura do Dashboard

### 3.1 Cabeçalho

Exibe a data e hora da última atualização automática, o status geral da coleta (OK / Parcial / Erro) e a cotação do dólar USD/BRL do dia, que impacta diretamente as commodities negociadas em mercados internacionais.

### 3.2 Painel de Cotações (tabela resumo)

Tabela com todas as commodities em uma linha cada, mostrando:

- Os últimos 4 dias de preço disponível
- Variação percentual do dia (último pregão vs. anterior)
- Variação percentual acumulada dos últimos ~21 pregões (aproximadamente 1 mês)
- Status da fonte: **OK** (fonte primária CEPEA) ou **Fallback** (fonte secundária, dado válido porém de origem alternativa)

### 3.3 Cards por Commodity

Para cada commodity, há um card detalhado com:

- Gráfico de linha com todo o histórico de preços acumulado desde o início da coleta (cresce um pregão por dia útil, até um limite de armazenamento de ~200 pregões / 9-10 meses; a meta é manter ao menos 6 meses visíveis)
- Métricas: último preço, variação do dia, variação do período, tendência 7-30 dias, tendência 30-90 dias
- Cards de mercado: Postura do Produtor, Postura do Comprador e Liquidez em etiquetas compactas numa única linha, com o Fator Externo em um quadro próprio abaixo (texto mais longo)
- Insights de curto prazo (7 a 30 dias) e médio prazo (30 a 90 dias) gerados por inteligência artificial, apresentados em tópicos (bullet points) para leitura rápida
- Decisão de compra com estratégia de volume e gatilho de revisão
- Notícias dos últimos 5 dias úteis relacionadas àquela commodity

### 3.4 Seção de Safra

Notícias gerais sobre safra nacional (CONAB e fontes especializadas), úteis para antecipar movimentos estruturais de oferta.

---

## 4. Significados Principais

### 4.1 Recomendação de Compra

O campo mais importante do dashboard. Cada commodity recebe uma das três recomendações:

| Recomendação | Significado | Ação sugerida |
| --- | --- | --- |
| **COMPRAR** | Assimetria favorável: upside supera downside. Momento de adquirir o volume necessário. | Fechar compra do volume dos próximos 30 a 60 dias. |
| **ATENÇÃO** | Cenário incerto ou evento próximo pode mudar o preço. Risco de comprar caro ou barato. | Esperar o gatilho de revisão indicado antes de decidir. |
| **SEGURAR** | Tendência de queda. Quem tem estoque não deve renovar agora. | Consumir estoque atual. Revisar em 15 a 30 dias. |

### 4.2 Campos de Análise de Mercado

Esses campos são preenchidos pela inteligência artificial com base nas diárias do CEPEA e notícias dos últimos 5 a 10 dias:

| Campo | Valor | O que significa para o comprador |
| --- | --- | --- |
| Postura do Produtor | Retraído | Produtor segurando estoque, não quer vender abaixo do preço esperado. Oferta restrita. |
| Postura do Produtor | Ofertante | Produtor vendendo ativamente. Oferta abundante, pressão baixista. |
| Postura do Comprador | Ativo | Compradores disputando produto. Demanda aquecida, tendência de alta. |
| Postura do Comprador | Retraído | Compradores esperando queda. Demanda fraca, mercado lateralizado. |
| Liquidez | Baixa | Poucos negócios sendo fechados. Preço pode não refletir tendência real. |
| Liquidez | Alta | Mercado ativo com muitas transações. Preço mais confiável. |
| Fator Externo | Texto livre | Cotações internacionais (Chicago, NY), câmbio, exportações, clima global que impacta o preço. |
| Postura de Mercado | Texto livre | Frase curta resumindo a dinâmica atual do mercado naquele dia. |

### 4.3 Tendências

O dashboard exibe duas tendências calculadas com base no histórico de preços:

- **Tendência 7-30 dias (curto prazo):** calculada com base na variação acumulada do período de coleta. Reflete o movimento recente de preço.
- **Tendência 30-90 dias (médio prazo):** baseada no histórico estendido disponível. Indica a direção estrutural do mercado.

Cada tendência assume um dos valores:

- **Alta:** variação acumulada ≥ +1,5%
- **Queda:** variação acumulada ≤ -1,5%
- **Estável:** entre -1,5% e +1,5%
- **Indefinida:** histórico insuficiente para calcular

### 4.4 Estratégia de Volume

Além da recomendação, o dashboard indica *quanto* comprar:

- **Volume Total:** comprar o volume total necessário agora (ex: 60 dias de consumo)
- **Parcial:** comprar uma parte agora e aguardar um evento específico para o restante
- **Aguardar:** não comprar agora, aguardar o gatilho indicado

### 4.5 Gatilho de Revisão

Todo card de decisão indica quando e por que revisar a recomendação. Exemplos:

- Relatório USDA de área plantada (evento datado que pode mover preço em ±3% em um dia)
- Início da safra nova (mudança estrutural de oferta)
- Dólar abaixo de R$ 5,00 (barateamento de commodities importadas)
- Revisão em 30 dias (quando não há evento específico identificado)

---

## 5. Como o Dashboard Gera os Insights

Os insights e recomendações são gerados automaticamente por inteligência artificial (Claude Haiku da Anthropic) com base em um conjunto estruturado de dados e regras. Entender essa lógica ajuda o comprador a interpretar corretamente as recomendações.

### 5.1 Fontes de dados usadas pela IA

- Histórico de preços dos últimos 5 dias úteis (CEPEA e fontes secundárias)
- Diárias qualitativas do CEPEA/ESALQ (publicadas diariamente por Planeta Arroz, SNA e outros especializados) — essas notas descrevem postura do produtor, liquidez e dinâmica do mercado físico com grande precisão
- Notícias dos últimos 5 dias de fontes especializadas (Notícias Agrícolas, CNN Brasil Agro, SAFRAS & Mercado, IBRAFE, MilkPoint)
- Cotações de futuros internacionais quando citadas nas notícias (Chicago CBOT para soja, NY Sugar #11 para açúcar)
- Preço Mínimo Governamental (PGPM/CONAB) como referência de piso estrutural

### 5.2 Hierarquia de sinais

A IA segue uma hierarquia clara ao ponderar as informações:

1. **Preço atual e sua trajetória recente** — sinal mais forte (fatos consumados)
2. **Diárias CEPEA** — descrição qualitativa do mercado físico, alta confiabilidade
3. **Notícias dos últimos 5 dias** de fontes especializadas
4. **Mercado externo** (futuros, exportações, clima global) quando mencionado

### 5.3 Análise de assimetria de risco

A recomendação final não é baseada apenas na direção do preço, mas na **assimetria entre o risco de alta e o risco de queda**:

**Exemplo para arroz:** preço abaixo do PGPM (R$ 63,74/sc) + produtor retraído + oferta restrita = downside limitado (governo pode intervir) + upside real (safra 2026/27 pode vir menor). Assimetria favorável ao comprador → **COMPRAR**.

**Exemplo para soja:** preço em alta + relatório USDA em 2 dias (pode subir ou cair 3%) = incerteza bilateral. Assimetria neutra → **ATENÇÃO** até o relatório.

### 5.4 Evento futuro como condicionador

Quando as notícias mencionam um evento datado relevante (relatório USDA, reunião de política agrícola, início de safra, resultado climático), a IA condiciona a estratégia de volume a esse evento e o registra no campo **Gatilho de Revisão**. Isso evita que o comprador tome uma decisão definitiva às vésperas de uma informação que pode mudar tudo.

### 5.5 Especificidades por commodity

- **Açúcar:** a IA analisa se o etanol em alta está competindo pelo mix de cana nas usinas (etanol valorizado = menos açúcar produzido = pressão de alta no cristal).
- **Arroz:** sempre verifica se o preço está abaixo do PGPM e menciona o piso governamental na análise.
- **Soja e Café:** prioriza cotações de futuros internacionais (Chicago, NY) e transmissão para o mercado físico brasileiro.
- **Leite:** foca em sazonalidade e balanço oferta/demanda do mercado interno.

---

## 6. Como Usar o Dashboard na Prática

Rotina sugerida para o comprador:

| Passo | Ação | Detalhes |
| --- | --- | --- |
| 1 | Acesse o dashboard às 08h00 | Após a atualização automática das 07h50, todos os dados do dia já estão disponíveis. |
| 2 | Verifique o Painel de Cotações | Identifique quais commodities tiveram variação de preço relevante no dia e no período. |
| 3 | Foque nos cards com COMPRAR | Leia o insight de curto prazo e a decisão de compra. Verifique a estratégia de volume e o gatilho de revisão. |
| 4 | Avalie os cards com ATENÇÃO | Identifique o gatilho de revisão. Se o evento é amanhã ou esta semana, priorize o acompanhamento. |
| 5 | Para SEGURAR: monitore o estoque | Verifique em quantos dias o estoque atual se esgota e marque a data de revisão do dashboard. |
| 6 | Consulte as notícias por commodity | As notícias dos últimos 5 dias dão contexto qualitativo para a decisão. Especialmente as marcadas como DIÁRIA CEPEA. |
| 7 | Documente a decisão | Registre o preço comprado, o volume, a data e o gatilho de revisão para acompanhamento posterior. |

---

## 7. Limitações e Pontos de Atenção

- Os insights são gerados com base nas informações disponíveis na data de atualização. Eventos ocorridos após as 07h50 não são captados até o dia seguinte.
- Em dias sem publicação de diária CEPEA (feriados, fins de semana), a IA usa as notícias mais recentes disponíveis, com peso reduzido.
- O campo Fator Externo depende de notícias que citem cotações internacionais. Se as fontes RSS do dia não mencionarem, o campo pode vir vazio.
- A recomendação é um **apoio à decisão**, não uma ordem. O comprador deve considerar contratos vigentes, condições de pagamento e contexto específico da empresa.
- Volumes de compra, prazos de entrega e condições comerciais são responsabilidade do comprador e não são considerados pelo sistema.

---

## 8. Registro de Atualizações (01/07/2026)

Principais mudanças incorporadas nesta revisão do dashboard e deste manual:

- Cotação do dólar: coleta agora tenta 3 vezes a fonte principal (AwesomeAPI) e, se falhar, usa como reserva a API oficial do Banco Central (PTAX) — reduz os casos de cotação ausente no cabeçalho.
- Insights de curto e médio prazo passaram de texto corrido para tópicos (bullet points), mantendo a mesma profundidade analítica (postura do produtor/comprador, PGPM, fatores externos etc.).
- Recomendação intermediária foi renomeada de AGUARDAR para ATENÇÃO (mesmo significado: cenário incerto, monitorar antes de decidir).
- "Variação do período" corrigida para usar uma janela fixa de ~21 pregões (não mais mês-calendário, que zerava a métrica no 1º pregão de cada mês).
- Gráfico do card passou a mostrar todo o histórico acumulado (não mais só 5 dias); o card de "Dias de histórico" foi removido e essa informação agora aparece como texto no título do gráfico.
- Cards de mercado (Postura do Produtor/Comprador/Liquidez/Fator Externo) redesenhados para tamanho proporcional ao conteúdo.

---

*Dashboard Mercado Commodities · Vila Vitória Distribuidora de Alimentos · Departamento de Compras · Julho 2026*
