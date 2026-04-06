# Referência de Pontuação de Propagação — Validação & Design

> **Versão do documento**: 1.1 — 2026-04-06  
> **Autor**: CT7BFV / projecto 4ham-spectrum-analysis  
> **Objectivo**: Documento de referência para o sistema de pontuação de propagação com 3 fórmulas, validado contra standards da indústria e investigação científica.

---

## 1. Contexto & Definição do Problema

A fórmula anterior de pontuação de propagação usava um cálculo único para todos os modos:

```
score = snr_norm × confidence × base_weight × recency_weight
```

Onde `snr_norm = (SNR + 20) / 40` e `base_weight = 1.0` (callsign) ou `0.55` (ocupação).

### Falhas Identificadas

1. **Sem métrica de decode_rate** — Muitas detecções de sinal FT8 com poucos callsigns descodificados produziam incorrectamente uma pontuação "Boa". Exemplo: 100 eventos FT8 com apenas 3 callsigns descodificados a -15 dB de SNR pontuavam ~55 (Bom), quando a propagação real era Fraca.
2. **Peso de ocupação demasiado generoso** — `base_weight = 0.55` para eventos de ocupação inflacionava pontuações quando a banda tinha energia mas os sinais eram fracos demais para descodificar.
3. **Normalização de SNR demasiado genérica** — `(SNR + 20) / 40` não considerava os limiares de descodificação específicos de cada modo. Um sinal FT8 a -18 dB (mal descodificável) era tratado da mesma forma que um sinal CW a -18 dB (que seria bastante fraco).
4. **Sem diferenciação por modo** — CW e SSB usam varrimento sequencial de banda estreita com tempos de escuta curtos. Ao contrário de FT8/FT4/WSPR (descodificação paralela de banda larga), não capturar um callsign em CW/SSB não significa sinal fraco — o operador pode simplesmente não estar a transmitir o seu callsign durante a curta janela de escuta.

---

## 2. Análise da Indústria — Como as Ferramentas Existentes Avaliam a Propagação

### 2.1 Conclusão Principal

**Nenhuma ferramenta existente calcula uma "pontuação de propagação" única a partir de medições em tempo real como o 4HAM-Spectrum-Analysis.** Todas as ferramentas principais fornecem dados em bruto e deixam os utilizadores/investigadores interpretar:

| Ferramenta | Dados Recolhidos | Método de Avaliação da Propagação |
|---|---|---|
| **PSK Reporter** | Callsign, frequência, SNR, modo, hora | Mapa de spots: dispersão geográfica + contagem de spots + SNR |
| **WSPRnet / wspr.live** | Callsign, grid, potência, SNR, distância, drift | Existência de spot = caminho aberto; SNR + distância = qualidade |
| **WSJT-X** | Callsigns descodificados com SNR (dB/2500 Hz) | Relatório de SNR por QSO; sem pontuação agregada |
| **VOACAP** | Perda de caminho prevista, MUF, fiabilidade | **Fiabilidade %** (0-100%) baseada em modelo ionosférico |
| **HamSCI** (Frissell et al. 2014) | Spots do PSK Reporter para investigação ionosférica | Densidade de spots + distribuição geográfica + padrões temporais |
| **GridTracker** | Visualização de dados do PSK Reporter | Densidade visual de spots no mapa; sem pontuação |
| **Reverse Beacon Network (RBN)** | Spots CW/RTTY com SNR | Existência de spot + SNR; completamente separado dos modos digitais |

A **"percentagem de fiabilidade" do VOACAP** é o conceito existente mais próximo da nossa pontuação de propagação — produz um valor de 0-100% por banda. No entanto, é uma **previsão** prospectiva baseada em índices solares, não uma **medição** em tempo real a partir de sinais recebidos.

### 2.2 PSK Reporter — Princípio de Design Chave

Da especificação do Programador do PSK Reporter (Philip Gladstone, N1DQ):

> *"Cada callsign deve ser reportado no máximo uma vez por período de cinco minutos. Idealmente, um callsign deve ser reportado apenas uma vez por hora se não tiver 'mudado'."*

Isto separa explicitamente "detecções brutas de sinal" de "callsigns descodificados com sucesso" — exactamente a distinção que a nossa métrica `decode_rate` captura.

### 2.3 Filosofia WSPRnet

Cada spot na base de dados do WSPRnet É uma descodificação bem-sucedida. Se energia é detectada mas não pode ser descodificada, nenhum spot é criado. A proporção de "energia detectada" vs "spots criados" é precisamente o nosso conceito de `decode_rate`.

### 2.4 Investigação Científica HamSCI

O projecto HamSCI (Frissell et al., "Ionospheric Sounding Using Real-Time Amateur Radio Reporting Networks", Space Weather, 2014) usa dados do PSK Reporter para investigação ionosférica. A sua metodologia considera:

- Densidade de spots por banda/janela temporal
- Distribuição geográfica dos caminhos de recepção
- Padrões temporais de mudanças de propagação
- Callsigns únicos como pontos de dados independentes

---

## 3. Limiares de Descodificação Confirmados (Documentação WSJT-X v2.6)

Fonte: Guia do Utilizador WSJT-X, Especificações de Protocolo §17.2.10 (Tabela 7)

| Modo | Código FEC | Limiar S/N (dB/2500 Hz) | Largura de Banda (Hz) | Duração (s) |
|---|---|---|---|---|
| **FT8** | LDPC (174,91) | **-20** (confirmado: -21 em versões anteriores) | 50,0 | 12,6 |
| **FT4** | LDPC (174,91) | **-17,5** | 83,3 | 5,04 |
| **WSPR** | K=32, r=1/2 | **-31** | 5,9 | 110,6 |
| **FST4W-120** | LDPC (240,74) | **-32,8** | 5,9 | 109,3 |
| **JT65A** | RS (63,12) | **-25** | 177,6 | 46,8 |
| **JT9A** | K=32, r=1/2 | **-26** | 15,6 | 49,0 |
| **Q65-15A** | QRA (63,13) | **-22,2** | 433 | 12,8 |

Limiares práticos adicionais (não do WSJT-X, estimados a partir de experiência operacional):
- **CW**: ~-15 dB (descodificação prática de ouvido/software)
- **SSB**: ~+3 dB (limiar prático de inteligibilidade)

O Guia do Utilizador WSJT-X §7.1 também afirma:
> *"Os sinais tornam-se visíveis no waterfall por volta de S/N = -26 dB e audíveis (para alguém com audição muito boa) por volta de -15 dB. Os limiares de descodificação são cerca de -20 dB para FT8, -23 dB para JT4, -25 dB para JT65 e -27 dB para JT9."*

---

## 4. Abordagem Validada com 3 Fórmulas

### 4.1 Categoria 1: FT8 / FT4 / WSPR (Descodificação Paralela de Banda Larga)

Estes modos descodificam **toda a banda passante simultaneamente**. Cada sinal na largura de banda de 2500 Hz é processado em paralelo. Uma descodificação bem-sucedida produz um callsign + relatório de SNR. Se energia é detectada mas o sinal é fraco demais para descodificar, aparece como evento de ocupação sem callsign.

**Portanto**: `decode_rate` (proporção de callsigns para total de eventos) é uma medida directa da qualidade do sinal e da propagação.

| Componente | Peso | Fundamentação |
|---|---|---|
| `decode_rate` | **40%** | Métrica principal. Suportada pela filosofia do PSK Reporter e WSPRnet |
| `median_snr` | **35%** | Métrica universal em todas as ferramentas. Normalizada por limiar do modo |
| `unique_callsigns` | **15%** | Suportada pela metodologia HamSCI |
| `recency` | **10%** | Relevância para painel em tempo real |

**Normalização de SNR** (específica por modo):

| Modo | Piso (limiar de descodificação) | Tecto | Gama |
|---|---|---|---|
| FT8 | -20 dB | +10 dB | 30 dB |
| FT4 | -17,5 dB | +10 dB | 27,5 dB |
| WSPR | -31 dB | +0 dB | 31 dB |

Fórmula: `snr_norm = clamp((SNR - piso) / gama, 0, 1)`

### 4.2 Categoria 2: CW (Varrimento Sequencial de Banda Estreita)

CW usa varrimento sequencial de banda estreita com tempos de escuta curtos. O scanner ouve cada segmento de frequência brevemente. **Não capturar um callsign NÃO indica propagação fraca** — o operador pode simplesmente não estar a transmitir o seu callsign durante a curta janela de escuta.

A descodificação de callsigns CW é inerentemente menos fiável que FT8/FT4/WSPR devido a:
- Varrimento sequencial (não paralelo)
- Tempo de escuta curto por frequência
- Callsign só transmitido durante partes específicas de chamadas CQ
- Temporização variável do operador

| Componente | Peso | Fundamentação |
|---|---|---|
| `traffic_volume` | **30%** | Detecção CW_TRAFFIC = banda está activa |
| `snr_quality` | **30%** | SNR continua a ser métrica universal de qualidade |
| `signal_strength` | **15%** | Nível de sinal RF como indicador de propagação |
| `callsign_bonus` | **15%** | Bónus quando callsign É capturado (não penalização quando ausente) |
| `recency` | **10%** | Relevância para painel em tempo real |

**Normalização de SNR**: Piso = -15 dB, Tecto = +20 dB, Gama = 35 dB

### 4.3 Categoria 3: SSB (Varrimento Sequencial de Banda Estreita + Voz)

SSB partilha a limitação de varrimento sequencial do CW. Adicionalmente, SSB não tem mensagem digital estruturada — a avaliação da propagação depende da qualidade da detecção de voz, SNR e força do sinal.

**Nenhuma ferramenta externa fornece pontuação automática de propagação SSB como o 4HAM-Spectrum-Analysis.** Este é território genuinamente inovador.

| Componente | Peso | Fundamentação |
|---|---|---|
| `traffic_volume` | **20%** | SSB_TRAFFIC / VOICE_DETECTION = banda está activa |
| `snr_quality` | **25%** | Métrica de qualidade SNR |
| `signal_strength` | **15%** | Nível de sinal RF como indicador de propagação |
| `voice_quality` | **20%** | Qualidade da detecção de voz (clareza) |
| `transcript` | **10%** | Transcrição voz-para-texto bem-sucedida = sinal inteligível |
| `callsign_bonus` | **5%** | Bónus quando callsign É capturado |
| `recency` | **5%** | Relevância para painel em tempo real |

**Normalização de SNR**: Piso = +3 dB, Tecto = +30 dB, Gama = 27 dB

---

## 5. Limiares de Pontuação

| Gama de Pontuação | Estado | Descrição |
|---|---|---|
| ≥ 70 | **Excelente** | Sinais fortes, taxas de descodificação elevadas, múltiplos callsigns |
| ≥ 50 | **Bom** | Descodificações fiáveis, SNR decente |
| ≥ 30 | **Razoável** | Alguma actividade, sinais marginais |
| < 30 | **Fraco** | Propagação mínima ou inexistente |

---

## 6. Localizações da Implementação

### 6.1 Backend (implementação canónica)

| Ficheiro | Função | Objectivo |
|---|---|---|
| `backend/app/dependencies/helpers.py` | `build_propagation_summary()` | Ponto de entrada principal — pontuação de propagação para o painel em tempo real |
| `backend/app/dependencies/helpers.py` | `_compute_band_propagation()` | Motor de pontuação por banda (chamado pelo anterior) |
| `backend/app/dependencies/helpers.py` | `_normalise_snr()` | Normalização de SNR específica por modo |
| `backend/app/dependencies/helpers.py` | `_mode_category()` | Classificador modo → categoria (digital / cw / ssb) |
| `backend/app/dependencies/helpers.py` | `_score_to_state()` | Mapeamento pontuação → rótulo (Excelente / Bom / Razoável / Fraco) |
| `backend/app/api/analytics.py` | `_compute_category_score()` | Pontuação por categoria para analytics académico |
| `backend/app/api/analytics.py` | `_propagation_state()` | Mapeamento pontuação → rótulo (espelha `_score_to_state`) |
| `backend/app/api/events.py` | `propagation_summary()` | Endpoint REST `/api/propagation/summary` |

### 6.2 Frontend

| Ficheiro | Função | Objectivo |
|---|---|---|
| `frontend/app.js` | `renderPropagationSummary()` | Renderização dos dados de propagação calculados pelo backend |
| `frontend/app.js` | `requestPropagationSummary()` | Obtém dados de propagação da API |
| `frontend/4ham_academic_analytics.html` | `computePropagationAnalytics()` | Pontuação de propagação client-side (fallback) |

> **Nota**: A função frontend `computePropagationAnalytics()` é uma **aproximação simplificada** das fórmulas do backend, usada apenas como fallback do lado do cliente quando o endpoint do servidor não está disponível. Aplica os pesos correctos mas usa inputs simplificados (ex.: contagens de eventos log-normalizadas em vez de taxas reais de descodificação, valores fixos de recência/qualidade). A **implementação do backend é canónica**.

---

## 7. Fontes & Referências

1. **Especificação do Programador PSK Reporter** — Philip Gladstone, N1DQ  
   https://www.pskreporter.info/pskdev.html

2. **Guia do Utilizador WSJT-X v2.6** — Joseph H. Taylor Jr., K1JT  
   https://wsjt.sourceforge.io/wsjtx-doc/wsjtx-main-2.6.1.html  
   Especificações de Protocolo §17.2.10 (tabela de limiares de descodificação)

3. **Protocolo WSPR** — Wikipedia / Joe Taylor, K1JT  
   S/N mínimo para recepção: -31 dB (WSPR), -28 dB (especificação original)  
   https://en.wikipedia.org/wiki/WSPR_(amateur_radio_software)

4. **HamSCI** — Frissell, N. A. et al. (2014)  
   "Ionospheric Sounding Using Real-Time Amateur Radio Reporting Networks"  
   Space Weather, 12(12), 651-656. DOI: 10.1002/2014SW001132

5. **VOACAP** — Voice of America Coverage Analysis Program  
   https://www.voacap.com/

6. **PSK Reporter** — Wikipedia  
   https://en.wikipedia.org/wiki/PSK_Reporter  
   20+ mil milhões de relatórios de recepção desde 2021

7. **wspr.live** — Base de dados de spots WSPR com backend ClickHouse  
   https://wspr.live/

8. **Protocolos de Comunicação FT4 e FT8** — publicação QEX  
   https://wsjt.sourceforge.io/FT4_FT8_QEX.pdf
