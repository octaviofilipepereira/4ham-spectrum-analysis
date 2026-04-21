# 4HAM Spectrum Analysis - Manual do Utilizador

## Índice

1. [Eventos SSB — Voice Signature](#eventos-ssb--voice-signature)
2. [Compreender as Métricas](#compreender-as-métricas)
   - [SNR vs Propagation Score](#snr-vs-propagation-score)
3. [Dashboard Academic Analytics](#dashboard-academic-analytics)
4. [Scan Rotation (Rotação de Scan)](#scan-rotation-rotação-de-scan)
5. [Presets de Rotação & Scheduler](#presets-de-rotação--scheduler)
6. [Mapa de Propagação — Seletor de Janela Temporal](#mapa-de-propagação--seletor-de-janela-temporal)
7. [Mapa de Propagação QTH-Cêntrico](#mapa-de-propagação-qth-cêntrico)
8. [Painel de Clima Espacial Ionosférico](#painel-de-clima-espacial-ionosférico)
9. [Configuração Inicial](#configuração-inicial)
10. [Interface do Utilizador](#interface-do-utilizador)
11. [Interpretação do Espectrograma](#interpretação-do-espectrograma)
12. [Exportação de Dados](#exportação-de-dados)
13. [Incorporar o Dashboard Académico num Website Externo](#incorporar-o-dashboard-académico-num-website-externo)
14. [Descodificação APRS — Pipeline VHF](#descodificação-aprs--pipeline-vhf)
15. [Resolução de Problemas](#resolução-de-problemas)

---

## Eventos SSB — Voice Signature

### O que é um evento Voice Signature?

A partir da **v0.8.0**, o sistema deteta e transcreve transmissões SSB em tempo real usando demodulação de voz e ASR (Automatic Speech Recognition — Whisper).

Existem três tipos de resultado para sinais SSB:

| Label | Significado |
|-------|------------|
| **Voice Confirmed** | SSB detetado, sem transcrição disponível — apenas confirmação de atividade de voz |
| **Voice Transcript** | SSB detetado com transcrição Whisper, mas sem indicativo resolvido — o botão **TXT** mostra o texto transcrito |
| **Callsign** (indicativo) | SSB detetado **e** indicativo resolvido com sucesso pelo ASR |

### Pipeline de deteção SSB

1. O scanner deteta ocupação de banda com largura de banda típica de SSB (2,4–3 kHz).
2. O bloco DSP demódula USB ou LSB conforme a banda e segmento de frequência.
3. O VAD (Voice Activity Detection) segmenta a transmissão em trechos de voz.
4. O Whisper transcreve o áudio — todos os tokens que correspondam a um indicativo válido (regex IARU) são extraídos.
5. Se um indicativo for encontrado → evento com o indicativo resolvido.
6. Se houver transcrição mas sem indicativo → label **Voice Transcript** com botão **TXT** mostrando o texto.
7. Se só houver deteção de voz sem transcrição → label **Voice Confirmed**.

### Proteção contra flood de ocupação

Durante transmissões SSB longas, o sistema aplica vários mecanismos para evitar que o painel de eventos e a cascata fiquem saturados:

- **Debounce por segmento de 2 kHz** — suprime eventos de ocupação repetidos para o mesmo segmento durante **30 segundos** (v0.8.4; era 8 s).
- **Gate de SNR** — sinais abaixo de **8 dB SNR** são rejeitados e não geram eventos.
- **Marcadores SSB_VOICE condicionais** — os marcadores "VOICE DETECTED" na cascata só são criados quando o Whisper ASR confirma voz ativa; detecções de ocupação sem ASR não geram marcadores.

### Configuração ASR no painel Admin

1. Abrir a interface web e iniciar sessão.
2. Ir a **Admin** → **Settings**.
3. Ativar **SSB ASR** e selecionar o modelo Whisper (`tiny` recomendado, `base` para maior precisão).
4. O modelo é descarregado automaticamente na primeira utilização (~75 MB para `tiny`).

> **Nota:** O Whisper requer `openai-whisper` instalado (incluído se selecionado durante `./install.sh`, ou instalável manualmente: `pip install openai-whisper`).

---

## Compreender as Métricas

### SNR vs Propagation Score

O sistema apresenta duas métricas importantes que podem parecer contraditórias à primeira vista:

#### 📡 SNR (Signal-to-Noise Ratio)

**O que é**: Medida **instantânea** de um **sinal individual**.

**Cálculo**:
```
SNR = nível_do_sinal_dB - ruído_de_fundo_dB
```

**Como interpretar**:
- **< 8 dB**: Sinal rejeitado (demasiado fraco para descodificar)
- **8-15 dB**: Sinal fraco mas descodificável
- **15-25 dB**: Sinal forte
- **> 25 dB**: Sinal muito forte

**Onde aparece**: O valor SNR apresentado junto a cada banda representa o **pico máximo (max_snr_db)** registado nessa banda nos últimos 60 minutos.

---

#### 🌍 Propagation Score (Score de Propagação)

> **⚠️ Nota importante sobre a origem dos dados:**
> O Propagation Score é calculado com base em **descodificações confirmadas** — eventos com um **indicativo verificado**, independentemente do modo. Uma descodificação bem-sucedida fornece indicativo + SNR, o fundamento fiável para avaliar um caminho de propagação real.
>
> Eventos **sem indicativo** (em qualquer modo) refletem **ocupação de banda** (*band occupancy*): confirmam que a banda está activa com tráfego, mas **não contribuem para o cálculo de propagação**.

**O que é**: Avaliação **agregada** das condições de propagação baseada em **múltiplos eventos recentes**.

**Como é calculado (v0.9.0 — 3 fórmulas por categoria de modo)**:

Desde a v0.9.0, o sistema usa **três fórmulas distintas** adaptadas às características de cada tipo de modo. Cada fórmula combina métricas ponderadas, normalizadas entre 0 e 1, e produz um score final entre 0 e 100.

##### Categoria 1 — Digital (FT8 / FT4 / WSPR / JT65 / JT9 / FST4 / FST4W / Q65)

Estes modos descodificam toda a passband em paralelo. A taxa de descodificação (proporção de indicativos vs. eventos totais) é a métrica primária.

| Componente | Peso | Descrição |
|---|---|---|
| `decode_rate` | **40 %** | Proporção de eventos com indicativo vs. total de deteções |
| `median_snr` | **35 %** | SNR mediano normalizado pelo limiar do modo |
| `unique_callsigns` | **15 %** | Número de indicativos únicos (diversidade) |
| `recency` | **10 %** | Eventos mais recentes pesam mais |

**Normalização SNR (específica por modo)**:

| Modo | Floor (limiar descodificação) | Ceiling | Faixa |
|---|---|---|---|
| FT8 | −20 dB | +10 dB | 30 dB |
| FT4 | −17,5 dB | +10 dB | 27,5 dB |
| WSPR | −31 dB | 0 dB | 31 dB |

```
snr_norm = clamp((SNR - floor) / faixa, 0, 1)
```

##### Categoria 2 — CW (Morse) — Apenas Descodificações Confirmadas

CW usa varrimento sequencial por frequência com dwell curto. Apenas eventos com um **indicativo verificado** contribuem para o score de propagação. Eventos sem indicativo refletem ocupação de banda.

| Componente | Peso | Descrição |
|---|---|---|
| `snr_quality` | **35 %** | SNR normalizado (floor −15 dB, ceiling +20 dB) — apenas dos eventos com indicativo |
| `callsign_diversity` | **25 %** | Indicativos únicos confirmados (diversidade) |
| `signal_strength` | **20 %** | Nível de sinal RF dos eventos com indicativo |
| `recency` | **20 %** | Eventos com indicativo mais recentes pesam mais |

##### Categoria 3 — SSB (Voz) — Apenas Descodificações Confirmadas

SSB partilha a limitação de varrimento sequencial do CW. Apenas eventos com um **indicativo verificado** contribuem para o score de propagação. Eventos sem indicativo refletem ocupação de banda.

| Componente | Peso | Descrição |
|---|---|---|
| `snr_quality` | **35 %** | SNR normalizado (floor +3 dB, ceiling +30 dB) — apenas dos eventos com indicativo |
| `callsign_diversity` | **25 %** | Indicativos únicos confirmados (diversidade) |
| `signal_strength` | **20 %** | Nível de sinal RF dos eventos com indicativo |
| `recency` | **20 %** | Eventos com indicativo mais recentes pesam mais |

**Classificação (comum a todas as categorias)**:
- **≥ 70**: Excellent 🟢 (Excelente)
- **≥ 50**: Good 🟡 (Bom)
- **≥ 30**: Fair 🟠 (Razoável)
- **< 30**: Poor 🔴 (Fraco)

> Referência completa com validação científica e fontes: [docs/propagation_scoring_reference.md](propagation_scoring_reference.md)

---

#### 🤔 Porque SNR alto pode ter Score baixo?

É comum observar situações aparentemente contraditórias como:

| Banda | max_snr_db | Score | Estado |
|-------|-----------|-------|--------|
| **20m** | 32 dB ⚡ | 30.8/100 | Fair |
| **40m** | 28.1 dB | 60.7/100 | Good |

**Explicação**:

O **SNR apresentado é o valor máximo** registado na banda, mas o **Score de Propagação representa a média ponderada de TODOS os eventos** nessa banda.

**Cenário típico - 20m (SNR 32 dB → Score 30.8/100)**:
- Teve **um pico** de 32 dB há 55 minutos
- Mas apenas **3-4 eventos** no total
- Eventos são **antigos** (peso temporal baixo)
- Maioria tem **SNR baixo** (9-15 dB)
- Resultado: **banda inconsistente** → Score Fair

**Cenário típico - 40m (SNR 28.1 dB → Score 60.7/100)**:
- **Muitos eventos** (25+ total)
- Eventos **recentes** (peso temporal alto)
- SNR **consistentemente alto** (18-28 dB)
- Maioria são **callsigns** (peso 1.0)
- **Confidence alta** nas descodificações
- Resultado: **banda estável e ativa** → Score Good

---

#### 💡 Analogia do Restaurante

**Restaurante A (20m)**: 
- Serviu **um prato excelente** ontem (32 dB)
- Mas hoje apenas 2-3 pratos medianos
- **Avaliação média**: 3/5 ⭐⭐⭐ (Fair)

**Restaurante B (40m)**:
- Todos os pratos hoje foram **muito bons** (25-28 dB)
- Serviu 25+ pratos consistentes
- **Avaliação média**: 4/5 ⭐⭐⭐⭐ (Good)

O "melhor prato" foi no Restaurante A, mas a **experiência geral** é melhor no Restaurante B!

---

#### 🎯 Conclusão

- **SNR** = qualidade de **um sinal específico** (o melhor registado)
- **Propagation Score** = qualidade **geral da banda** nos últimos 60 minutos

**Um SNR alto isolado não garante score "Excellent"** porque o sistema avalia:
- ✅ **Consistência** do SNR ao longo do tempo
- ✅ **Quantidade** de eventos
- ✅ **Idade** dos eventos (mais recentes pesam mais)
- ✅ **Tipo** de eventos (callsigns vs occupancy)
- ✅ **Confiança** nas descodificações

O Propagation Score fornece uma **visão holística da qualidade da propagação** em cada banda, não apenas o pico máximo instantâneo.

---

---

## Configuração Inicial

### Pré-requisitos
- SDR: RTL-SDR (recomendado), HackRF, Airspy ou outro hardware compatível com SoapySDR
- Sistema operativo: Linux Ubuntu 20.04+ / Debian 11+ / Linux Mint 20+ / Raspberry Pi OS 11+ (64-bit)
- Python 3.10+
- Sincronização de tempo NTP (obrigatório para FT8/FT4)

### Instalação rápida (instalador gráfico)
A partir da v0.7.1, o projeto inclui um instalador TUI interativo:

```bash
git clone https://github.com/octaviofilipepereira/4ham-spectrum-analysis.git
cd 4ham-spectrum-analysis
chmod +x install.sh && ./install.sh
```

O instalador configura: pacotes do sistema, driver RTL-SDR Blog v4 (opcional), ambiente Python virtual, conta de administrador (password bcrypt em SQLite) e serviço systemd.

### Iniciar o servidor
```bash
source .venv/bin/activate
python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
```

Ou via script de controlo do servidor:
```bash
./scripts/server_control.sh start
```

Abrir a interface no browser: `http://localhost:8000/`

---

## Dashboard Academic Analytics

### Objetivo

O Academic Analytics é uma ferramenta de análise agregada desenhada para responder a perguntas concretas sobre atividade de radioamador:

- **Quais bandas estão mais ativas** neste momento, hoje, ou nos últimos 30 dias?
- **A que horas UTC existe mais propagação** em cada banda? (fundamental para planear operações DX)
- **Qual a qualidade real da propagação** — não apenas um pico de SNR, mas a consistência ao longo do tempo?
- **Quais estações estão mais ativas** no período analisado?
- **Como evoluiu a propagação** ao longo das horas ou dos dias?

Ao contrário do dashboard principal (que mostra dados em tempo real, evento a evento), o Academic Analytics **agrega e sintetiza** grandes volumes de dados para revelar padrões e tendências que não são visíveis no fluxo de eventos individual.

É especialmente útil para:
- Radioamadores que querem **identificar os melhores horários e bandas** para operar
- Análise pós-sessão de uma noite de operação ou de um contest
- Trabalho académico ou relatórios sobre condições de propagação HF
- Comparação da atividade entre bandas e modos ao longo de dias ou semanas

### Acesso

- Botão **Data Analysis** na barra de ferramentas (abre num novo separador)
- Ou diretamente em `http://localhost:8000/4ham_academic_analytics.html`

Os dados vêm do servidor e são **atualizados automaticamente a cada 60 segundos**. O cabeçalho mostra o timestamp da última consulta e um contador regressivo para o próximo refresh.

### Seletor de período

| Preset | Período | Resolução temporal |
|---|---|---|
| **1h** | Última hora (padrão no primeiro acesso) | Minuto |
| **12h** | Últimas 12 horas | Hora |
| **24h** | Últimas 24 horas | Hora |
| **7d** | Últimos 7 dias | Hora |
| **30d** | Últimos 30 dias | Dia |
| **Custom** | Intervalo personalizado (data/hora de início e fim) | Automático |

O preset ativo é memorizado na sessão do browser. A resolução temporal (minuto, hora, dia) é escolhida automaticamente para garantir que os gráficos tenham detalhe suficiente sem ficarem sobrecarregados.

> **Dica:** Use **1h** para acompanhar a sessão de operação atual em tempo quase real. Use **7d** ou **30d** para estudar padrões de propagação sazonal.

### Filtros de banda e modo

- **Band** — filtrar por banda individual (160m … 70cm) ou **All** para ver todas
- **Mode** — filtrar por modo (SSB, FT8, FT4, CW, WSPR) ou **All** para ver todos
- Clicar em **Apply Filters** após alterar filtros ou o período personalizado

Os filtros aplicam-se a **todos os gráficos e KPIs simultaneamente**. Isto permite análises focadas — por exemplo, ver apenas FT8 na banda dos 20m para avaliar se a propagação transatlântica está ativa.

### Cartões KPI (resumo) — como interpretar

Seis cartões no topo sumarizam o estado geral do período selecionado:

| Cartão | O que mostra | Como interpretar |
|---|---|---|
| **Total events** | Número total de eventos (ocupações + indicativos) | Valores altos indicam bandas ativas e condições de propagação favoráveis. Compare com períodos anteriores para avaliar tendências |
| **Unique callsigns** | Número de indicativos distintos descodificados | Quanto mais indicativos únicos, melhor a propagação — indica que sinais de múltiplas estações estão a chegar. Um valor alto com Total events alto indica propagação diversificada |
| **Average SNR** | SNR médio ponderado em dB | Valores acima de 0 dB indicam sinais geralmente fortes. Valores negativos (ex.: -8 dB) indicam sinais fracos mas descodificáveis. Compare com o threshold do modo: FT8 descodifica até -20 dB, SSB precisa de pelo menos +3 dB |
| **Time coverage** | Percentagem de horas UTC que tiveram atividade | 100% = atividade em todas as horas da janela. Valores baixos (ex.: 30%) indicam propagação esporádica — a banda só esteve aberta em algumas horas |
| **Overall Propagation** | Score composto (0–100) | Avaliação global baseada em descodificações confirmadas (indicativo verificado). **≥ 70** Excellent (🟢), **≥ 50** Good (🟡), **≥ 30** Fair (🟠), **< 30** Poor (🔴). O badge colorido dá uma leitura rápida. Referência: [propagation_scoring_reference_pt.md](propagation_scoring_reference_pt.md) |
| **Best band** | Banda com melhor score de propagação | Indica qual banda ofereceu as melhores condições no período. O sub-texto mostra o score e a estabilidade (%) — estabilidade alta significa propagação consistente, não apenas picos isolados |

### Gráficos — como interpretar

Cada gráfico tem um ícone **"i"** no canto do cabeçalho. Ao passar o rato sobre o ícone, aparece uma descrição detalhada. Ao passar o rato sobre elementos do gráfico (barras, células, pontos), aparece um tooltip com os valores exatos.

#### Event Time Series (Série temporal de eventos)

**O que mostra**: Volume de eventos ao longo do tempo, agregados por hora (ou minuto/dia conforme a resolução do período selecionado).

**Como interpretar**:
- **Picos** indicam momentos de alta atividade — provavelmente abertura de propagação ou contest
- **Vales** indicam períodos sem atividade — propagação fechada ou scan parado
- **Padrão cíclico** (picos repetidos às mesmas horas em dias diferentes) revela o ciclo solar diário normal — propagação HF aumenta após o nascer do sol e diminui à noite
- **Linha ascendente** ao longo de vários dias pode indicar melhoria das condições solares

#### Distribution by Band and Mode (Distribuição por banda e modo)

**O que mostra**: Gráfico de barras empilhadas — uma barra por banda, dividida por cores de modo. Cores: SSB (azul), FT8 (verde), FT4 (púrpura), CW (âmbar), WSPR (rosa).

**Como interpretar**:
- **Barras altas** = bandas muito ativas no período
- **Barras ausentes** = essa banda não teve atividade (propagação fechada, ou simplesmente não foi monitorizada)
- **Composição da barra**: se uma banda é dominada por uma cor (ex.: tudo verde = FT8), os restantes modos não estiveram ativos nessa banda
- **Comparar alturas entre bandas** para decidir onde operar — por exemplo, se 20m tem barra alta e 15m tem barra baixa, a propagação está melhor nos 20m

> **Nota:** Apenas bandas+modo que tiveram um decoder a correr aparecem neste gráfico. Se nunca correu scan SSB nos 12m, não aparecerão eventos SSB nos 12m — isto não é um erro, é filtragem inteligente.

#### Hour of Day × Band — Heatmap Pro

**O que mostra**: Matriz interativa de 24 linhas (horas UTC 0–23) × colunas (bandas). Intensidade da cor = volume de eventos nessa hora+banda.

**Como interpretar**:
- **Células claras/brancas** = muita atividade nessa combinação hora+banda
- **Células escuras/pretas** = pouca ou nenhuma atividade
- **Linhas claras horizontais** = horas com muita atividade em todas as bandas (ex.: 14h–18h UTC nos 20m = alta propagação em Europa→América)
- **Colunas claras verticais** = bandas ativas em muitas horas do dia (bandas com propagação consistente)
- **Barras marginais**: no topo (**Σ band**) mostra o total por banda; à direita (**Σ hour**) mostra o total por hora
- **Cross-highlighting**: ao passar o rato numa célula, a linha e coluna ficam destacadas para facilitar a leitura cruzada

**Uso prático**: Identifique em que horas UTC a sua banda preferida está mais ativa. Exemplo: se a célula [15h UTC, 20m] está muito clara, esse é um bom horário para operar 20m.

#### Top Callsigns in Period (Top 20 indicativos)

**O que mostra**: Os 20 indicativos mais frequentemente detetados no período, ordenados por número de aparições.

**Como interpretar**:
- Indicativos com muitas aparições são estações que estiveram consistentemente ativas e com boa propagação até ao seu recetor
- Útil para identificar beacons, estações de contest, ou super-estações DX
- Se o seu próprio indicativo aparece (porque está a monitorizar outra estação que o vê), confirma que o seu sinal está a chegar

#### Propagation Score by Band (Score de propagação por banda)

**O que mostra**: Barra vertical com o score de propagação (0–100) para cada banda no período selecionado.

**Como interpretar**:
- **Barras altas** (≥ 70) = propagação excelente — descodificação consistente, bom SNR, muitos indicativos
- **Barras médias** (50–69) = propagação boa — condições fiáveis para operação
- **Barras baixas** (30–49) = propagação razoável — sinais marginais, descodificação intermitente
- **Barras muito baixas** (< 30) = propagação fraca — poucos ou nenhuns decodes
- **Comparar barras entre bandas** para escolher a melhor banda para operar agora
- A etiqueta numérica acima de cada barra dá o valor exato

#### Propagation Time Trend (Tendência temporal da propagação)

**O que mostra**: Linha contínua mostrando como o score global de propagação variou ao longo do tempo. Linha tracejada horizontal = média do período.

**Como interpretar**:
- **Linha acima da média** = condições melhores que o habitual nesse momento
- **Linha abaixo da média** = condições piores que o habitual
- **Tendência ascendente** ao longo do dia = propagação a melhorar (típico nas horas matinais até ao pico solar)
- **Tendência descendente** = propagação a deteriorar (típico após o pôr do sol em HF)
- **Oscilações frequentes** = propagação instável
- **Linha quase plana e alta** = condições estáveis e boas — ideal para operação

### Como exportar dados

O dashboard permite exportar os dados analisados em três formatos. Para exportar:

1. Selecionar o **período** e **filtros** desejados (banda, modo)
2. Clicar no botão **Export ▾** (canto superior direito da barra de controlos)
3. Escolher o formato no menu dropdown:

| Formato | Melhor para | Conteúdo |
|---|---|---|
| **CSV** | Abrir em Excel/LibreOffice, importar noutra ferramenta | Todos os eventos individuais com campos enriquecidos (ver abaixo). Cabeçalhos de coluna legíveis com unidades de medida. |
| **JSON** | Processamento programático (Python, JavaScript, etc.) | Objeto completo com: séries agregadas por banda+modo, eventos por bucket temporal, todos os eventos individuais (enriquecidos, com indicativo, grid, SNR, frequência, DXCC, geolocalização), scores de propagação por banda, e intervalo temporal |
| **XLSX** | Relatórios profissionais, análise detalhada em Excel | Workbook com **4 folhas separadas**: |

**Folhas do ficheiro XLSX:**

| Folha | Conteúdo | Uso |
|---|---|---|
| **Events by Band-Mode** | Dados agregados por combinação banda+modo | Visão geral: quantos eventos em cada banda e modo |
| **Aggregated Events** | Eventos agrupados por bucket temporal (hora/dia) | Análise de tendências temporais |
| **All Events** | Todos os eventos individuais com campos enriquecidos: timestamp, indicativo, banda, modo, frequência, SNR, grid locator, nome da entidade DXCC, continente, código DXCC, latitude, longitude, potência (dBm), confiança, crest (dB), desvio Doppler (Hz), fonte, banda derivada, modo normalizado | Análise detalhada evento a evento com dados de geolocalização e qualidade de sinal |
| **Propagation by Band** | Score de propagação e contagem de eventos por banda | Resumo da qualidade de propagação |

O ficheiro é gerado no browser e descarregado automaticamente com o nome `4ham-analytics_{início}_{fim}.{ext}` (ex.: `4ham-analytics_2026-04-07-14-00_2026-04-08-14-00.xlsx`).

> **Colunas de exportação enriquecidas:** Todos os formatos de exportação usam agora cabeçalhos de coluna legíveis com unidades de medida (ex.: "Frequency (Hz)", "SNR (dB)", "Power (dBm)") em vez de identificadores internos. A folha "All Events" inclui 13 campos adicionais por evento: nome da entidade DXCC, continente, código DXCC, latitude/longitude GPS, potência (dBm), confiança, crest (dB), desvio Doppler (Hz), fonte, grid locator, banda derivada e modo normalizado — permitindo análise geográfica e estudos de qualidade de sinal diretamente a partir da exportação.

### Metadados (rodapé)

Quatro campos informativos no final da página:

| Campo | Informação |
|---|---|
| **Data snapshot** | Timestamp UTC da última consulta ao servidor |
| **Update frequency** | Frequência de atualização automática (cada 1 minuto) |
| **Analyzed period** | Intervalo temporal completo da análise atual |
| **Data quality** | Indicador de consistência dos dados |

---

## Scan Rotation (Rotação de Scan)

### O que é?

O Scan Rotation permite definir uma **sequência de slots (banda + modo)** que o sistema percorre automaticamente, mudando de banda/modo em intervalos configuráveis. É ideal para monitorizar múltiplas bandas e modos durante períodos longos sem intervenção manual.

### Como configurar

1. Clicar em **Config Scan Rotation** (botão na barra de scan).
2. O painel de rotação expande-se com os seguintes controlos:
   - **Modo de rotação** — `Band + Mode` (cada slot define banda e modo) ou `Band only` (rota apenas por bandas, mantendo o modo atual).
   - **Banda e Modo** — selecionar a banda e modo para o próximo slot.
   - **Dwell** — tempo de permanência em cada slot antes de mudar (30 s, 1 min, 2 min, 5 min, 10 min, 15 min, 30 min).
   - **Loop** — se ativado, a rotação recomeça após o último slot; se desativado, para no final.
3. Clicar em **+ Add New Slot** para adicionar cada combinação banda/modo à lista.
4. Os slots aparecem como badges editáveis — clicar em **×** para remover um slot.
5. Clicar em **Start Rotation** para iniciar.

### Durante a rotação

- A barra de estado mostra em tempo real: slot atual (banda + modo), tempo restante no countdown, e o próximo slot.
- O indicador de pulsação vermelho confirma que a rotação está ativa.
- O botão **Stop scanning** para a rotação (e o scan atual).
- Os dados de todas as bandas/modos varridos acumulam-se na base de dados e aparecem nos dashboards analíticos.

---

## Presets de Rotação & Scheduler

### Presets de Rotação

Os Presets de Rotação permitem **guardar configurações de rotação com nome** (lista de slots, tempo de permanência, modo loop) para alternar rapidamente entre diferentes estratégias de monitorização sem recriar a sequência de slots de cada vez.

#### Gerir presets

1. Clicar em **Rotation Presets** na barra de scan para abrir o modal de Presets.
2. A secção **Available Presets** lista todos os presets guardados com o resumo dos slots.
3. Clicar **Load** para aplicar um preset à configuração de rotação atual.
4. Clicar **Delete** para remover um preset que já não é necessário.
5. Para criar um novo preset, configurar os slots de rotação e dwell no painel de Scan Rotation, inserir um nome e clicar **Save current config as preset**.

### Preset Scheduler

O Scheduler ativa automaticamente presets com base na **hora do dia (UTC)**, permitindo que o sistema se adapte às mudanças de propagação entre bandas diurnas e noturnas sem intervenção manual.

#### Configurar schedules

1. No modal de Presets, descer até à secção **Preset Scheduler**.
2. Selecionar um preset no dropdown, inserir hora de **Início** e **Fim** (HH:MM, UTC), e clicar **Add Schedule**.
3. A tabela de schedules mostra todas as janelas temporais configuradas, ordenadas por hora de início.
4. Usar o toggle **On/Off** para ativar ou desativar schedules individuais.
5. Clicar **Start Scheduler** para iniciar a comutação automática de presets.

#### Comportamento

- O scheduler verifica a cada **30 segundos** qual janela temporal está ativa e aplica o preset correspondente.
- Se a rotação parar inesperadamente (ex: erro do SDR), o scheduler deteta e **re-aplica** o preset automaticamente.
- **Janelas que cruzam a meia-noite** são suportadas (ex: 22:00 → 06:00).
- **Janelas sobrepostas** são rejeitadas — a API retorna erro se um novo schedule conflituar com um existente.
- O scheduler **inicia automaticamente no arranque** se existirem schedules ativos na base de dados.
- A hora UTC atual é mostrada acima da tabela de schedules para referência.

> 💡 **Dica:** Crie presets para bandas diurnas (ex: 10m, 15m, 20m) e noturnas (ex: 40m, 80m, 160m) e programe-os para comutar automaticamente — o sistema funciona 24/7 sem supervisão.

---

## Mapa de Propagação — Seletor de Janela Temporal

O mapa de propagação inclui um seletor de janela temporal que controla o período de eventos mostrados no globo:

| Opção | Período |
|---|---|
| **1h** | Última hora |
| **2h** | Últimas 2 horas |
| **4h** | Últimas 4 horas |
| **8h** | Últimas 8 horas |
| **24h** | Últimas 24 horas (padrão) |

Eventos fora da janela selecionada não aparecem no mapa. Isto permite focar na atividade recente ou alargar para uma visão diária.

---

## Mapa de Propagação QTH-Cêntrico

### Visão geral

O mapa de propagação é um globo ortográfico 3D centrado no QTH do utilizador, renderizado com D3.js no dashboard Academic Analytics. Combina duas camadas de dados:

1. **Previsão de zonas ionosféricas** — cobertura de propagação prevista por banda, calculada em tempo real a partir dos índices solares/geomagnéticos do NOAA SWPC através de um modelo ionosférico calibrado.
2. **Contactos SDR confirmados** — descodificações com indicativo confirmado das sessões SDR, representadas como pontos e arcos de ortodrómia até à posição do locator da estação remota.

### Elementos do mapa

| Elemento | Descrição |
|----------|-----------|
| **Zonas coloridas** | Cobertura de propagação prevista por banda. Três camadas de intensidade: **Forte** (opaco), **Moderada** (semi-transparente), **Franja** (ténue). As zonas expandem-se para o lado iluminado e contraem-se no lado noturno, modeladas pela absorção da camada D e pelo modelo ionosférico. |
| **Terminador dia/noite** | Linha amarela tracejada a separar os hemisférios iluminado e escuro, calculada a partir do ponto subsolar atual. O hemisfério noturno fica escurecido para indicar propagação por salto reduzida. |
| **Pontos e arcos** | Contactos SDR confirmados na janela temporal selecionada: ponto = posição geográfica da estação remota, arco = trajeto de ortodrómia desde o QTH. |
| **Gratícu­lo** | Grade de latitude/longitude com etiquetas de graus; as etiquetas escalam proporcionalmente com o nível de zoom. |

### Botões de banda

Os botões de banda verticais no lado esquerdo do mapa ativam ou desativam bandas individualmente. Uma banda ativa é mostrada na sua cor exclusiva; uma banda inativa aparece a branco. A seleção é guardada em `sessionStorage` e restaurada na próxima visita. Por defeito, nenhuma banda está selecionada — clique numa banda para visualizar as suas zonas de propagação.

### Controlos do mapa

| Ação | Efeito |
|------|--------|
| **Arrastar** | Rodar o globo para qualquer orientação |
| **Ctrl + Roda do rato** | Aproximar ou afastar; nível guardado via `sessionStorage` |
| **Duplo clique** | Repor orientação e zoom predefinidos |

### Legenda

Dois painéis de legenda abaixo do globo:

- **Esquerda**: coordenadas do QTH, total de contactos confirmados no período selecionado, contagem de anomalias.
- **Direita**: amostras de intensidade das zonas (Forte / Moderada / Franja), amostra do hemisfério noturno, nota de que cada banda usa uma cor exclusiva.

### Modelo ionosférico

Os limites das zonas são calculados pelo endpoint `/api/map/ionospheric` a partir dos dados do NOAA SWPC em tempo real:

| Parâmetro | Fórmula / Modelo |
|-----------|-----------------|
| **foF2** | `3,5 + 0,6 × √SSN` MHz — calibrado contra dados de ionossonda; piso noturno de 45 % fora do hemisfério iluminado |
| **Absorção camada D** | `k = (500 + 4×SSN) / f² × sin(elevação_solar)` — dependente do SSN, tabelas de absorção VOACAP; tolerância ±15 dB |
| **Salto multi-hop** | 2 500 km por reflexão ionosférica, máximo 4 saltos |
| **Limite NVIS** | Bandas < 8 MHz durante o dia limitadas a incidência quasi-vertical quando a camada D impede propagação a longa distância |
| **Reavaliação do estado** | Propagação apenas NVIS → **Marginal**; absorção total → **Absorbed** |

> **Nota**: O modelo usa SFI e Kp do NOAA SWPC (atualização a cada 15 min) e foi calibrado para condições médias de média latitude. Eventos de Sporadic-E, distúrbios ionosféricos súbitos e variabilidade local não são capturados.

---

## Painel de Clima Espacial Ionosférico

A barra lateral estreita à direita do globo (1/4 da largura da página) mostra dados de clima espacial em tempo real do **NOAA Space Weather Prediction Center (SWPC)**, traduzidos em estado de propagação HF por banda para o seu QTH.

### Indicadores de clima espacial

| Indicador | Descrição | Interpretação |
|-----------|-----------|---------------|
| **SFI** (Índice de Fluxo Solar, 10,7 cm) | Indicador da radiação ionizante solar UV/raios-X | < 80: pobre; 80–120: moderado; > 120: bom, esp. 10–15 m; > 200: excelente para 10–15 m |
| **Kp** (Índice geomagnético planetário, 0–9) | Grau de perturbação geomagnética | 0–2: calmo (ideal); 3–4: instável; 5–6: tempestade ativa; ≥ 7: tempestade severa / risco de apagão HF |
| **foF2** (Frequência crítica F2, MHz) | Frequência máxima refletida verticalmente pela camada F2 | Bandas abaixo do foF2 não conseguem propagar por salto. foF2 mais alto = mais bandas abertas para longa distância. |

### Indicadores de estado de banda

| Estado | Cor | Significado |
|--------|-----|-------------|
| **Open** | 🟢 Verde | Salto F2 previsto — distâncias multi-hop alcançáveis |
| **Marginal** | 🟠 Âmbar | Condições limite — apenas NVIS ou salto curto; pouco fiável para DX |
| **Closed** | 🔴 Carmesim | Frequência da banda abaixo do foF2 — sem propagação por salto |
| **Absorbed** | ⚫ Cinzento | Absorção da camada D demasiado elevada — normalmente 40 m / 80 m em pleno dia sob alta atividade solar |

Os dados atualizam automaticamente de **15 em 15 minutos** a partir do NOAA SWPC.

> O estado de banda é um guia baseado em modelo. Confirme sempre com as condições reais de operação e com o DX Cluster / WSPRnet para evidência em tempo real.

---

## Interface do Utilizador

### Barra de ferramentas (toolbar)

| Botão | Função |
|-------|--------|
| **Band Config** | Configurar bandas, intervalos de frequência, ativar/desativar individualmente |
| **Logs & Reports** | Estado dos decoders, Resumo de sessão, Logs, Painel de pesquisa/exportação |
| **Admin Config** | SDR, ganho, retenção de dados, autenticação. Requer login de administrador |
| **Help** | Manual do utilizador (este documento) |

### Painel Admin Config — Secções de configuração

| Secção | O que configura |
|--------|-----------------|
| **SDR** | Seleção do dispositivo, ganho (dB), sample rate, correção PPM, offset de frequência, perfil de ganho |
| **Device Configuration** | Classe do dispositivo (RTL / HackRF / AirSpy / outro), correção PPM, offset de frequência (Hz), perfil de ganho (auto/manual) |
| **Audio Configuration** | Nome do dispositivo de entrada/saída de áudio (placa de som), sample rate (Hz), multiplicador RX gain, multiplicador TX gain. Reservado para modos SDR em placa de som |
| **Scan** | Dwell time padrão, tamanho FFT, overlap |
| **Retention** | Limite máximo de eventos antes de auto-exportar+purge; número de eventos recentes a manter; diretório de exportação |
| **Authentication** | Alterar password de administrador |
| **SSB Voice Transcription** | Ativar/desativar Whisper ASR para SSB voice-to-text. Requer pacote `openai-whisper` |

### Painel Admin Config — Botões

| Botão | Função |
|-------|--------|
| **Refresh Devices** | Força nova enumeração SoapySDR contornando o cache de 300 s. Atualiza o dropdown de dispositivos e aplica automaticamente os valores correctos de ganho e sample rate para o dispositivo detectado (RTL-SDR: gain 30, 2,048 MS/s; HackRF: gain 20, 2 MS/s; AirSpy: gain 20, 2,5 MS/s) |
| **Save device** | Persiste os campos de Device Configuration (classe, PPM, offset, perfil de ganho) na base de dados. As alterações no formulário são temporárias até este botão ser premido |
| **Save audio** | Persiste os campos de Audio Configuration (dispositivo de entrada/saída, sample rate, RX/TX gain) na base de dados |
| **Test Config** | Valida a configuração actual sem guardar. Verifica: disponibilidade do dispositivo SoapySDR, ferramentas de áudio presentes no sistema (`arecord`, `aplay`, `pactl`, `pw-cli`), e que os valores de sample rate e ganho estão dentro dos limites aceites. Reporta pass/fail com detalhe num toast |
| **Auto-detect Device** | Assistente de configuração automática em dois passos. Passo 1 (dry run): consulta o backend para pacotes necessários, mostra diálogo de confirmação com estado actual e dependências em falta. Passo 2 (se aprovado): instala pacotes de sistema em falta via `sudo`/`pkexec`, detecta o dispositivo SDR, aplica o perfil recomendado (ganho, sample rate, PPM, perfil de ganho) aos campos do formulário, e guarda a configuração na base de dados |
| **Auto-detect Audio** | Consulta o backend para dispositivos de áudio disponíveis (PipeWire / PulseAudio / ALSA). Preenche os campos de Audio Configuration com os nomes dos dispositivos detectados e o sample rate. **Não guarda automaticamente** — clicar em **Save audio** depois para persistir |
| **Purge invalid events** | Pede confirmação e elimina da base de dados todos os eventos de ocupação e callsign incompletos ou mal formados (sem timestamp, frequência inválida, callsign nulo/unknown, etc.). Atualiza os contadores no UI após a conclusão |
| **Reset defaults** | Pede confirmação e repõe as definições padrão da aplicação (modos activos, opções de summary e outras configurações gerais). **Não afecta** eventos guardados, bandas customizadas, device configuration nem audio configuration |
| **Reset total** | ⚠️ Destrutivo. Pede confirmação e elimina **todas** as definições e bandas customizadas da base de dados (`DELETE FROM settings`, `DELETE FROM bands`), limpa o localStorage do browser e recarrega a página. Equivale a estado de instalação limpa. Os eventos não são afectados |

### Controlos de scan
- **Start scanning / Stop scanning** — inicia ou para o scan ativo
- **Botões de banda** (160m … 10m) — mudam de banda imediatamente, mesmo com scan em curso
- **Botões de modo** (CW / WSPR / FT4 / FT8 / SSB) — selecionam o decoder ou mudam o scan em tempo real; o painel de eventos sincroniza imediatamente ao mudar de modo (v0.8.4)
- **SSB Max Holds** (modo SSB, padrão `0` = auto) — número máximo de *pauses* por passagem completa da banda em frequências SSB ativas. `0` = cálculo adaptivo (~1 hold por 50 kHz de largura, mín. 4, máx. 12). Apenas aplicado ao iniciar o scan; não tem efeito com scan em curso.

### Filtro de eventos (dropdown)

| Opção | Mostra |
|-------|--------|
| **Show All** | Todos os eventos com indicativo: FT8/FT4, WSPR, CW, APRS, SSB Voice Signature |
| **Callsign Only** | Apenas eventos com indicativo descodificado (exclui Voice Signature) |
| **SSB Callsign Detected** | SSB com indicativo resolvido por Whisper ASR |
| **SSB Traffic Only** | Ocupação SSB (voz detetada, sem indicativo) |
| **CW Only** | Decodes CW |
| **All + Occupancy (raw)** | Tudo, incluindo ocupação bruta — útil para diagnóstico |

---

## Interpretação do Espectrograma

### Cascata (Waterfall)
- **Eixo horizontal**: frequência em MHz
- **Eixo vertical**: tempo (mais recente no topo, flui para baixo)
- **Cor**: intensidade do sinal — azul escuro = ruído de fundo, amarelo/vermelho = sinal forte
- **Marcadores de modo**: etiquetas coloridas fixas nas frequências dial conhecidas (ex.: FT8 14.074 MHz)

### Cores dos marcadores

| Cor | Modo |
|-----|------|
| Azul | FT8 |
| Verde | FT4 |
| Laranja | WSPR |
| Rosa/Púrpura | CW |
| Azul claro | SSB / Voice Signature |

### TTL dos marcadores

| Modo | TTL | Janela de decode |
|------|-----|-----------------|
| FT8  | 45 s | 15 s |
| FT4  | 23 s | 7,5 s |
| WSPR | 360 s | 120 s |
| CW   | 45 s | dwell 30 s |
| SSB  | 20 s | contínuo |

### Interação com a cascata
- **Drag horizontal** — pan quando zoom > ×1
- **Slider de zoom** — zoom horizontal de ×1 (banda completa) a ×16
- **Hover** — VFO bar mostra a frequência sob o cursor e o SNR em tempo real
- **Campo "Go to"** — escrever a frequência em MHz e premir `Enter` para centrar a vista

---

## Exportação de Dados

### Painel Search & Export Data
Acedido via **Logs & Reports → Search & Export Data**.

**Filtros disponíveis:**
- Intervalo de datas/horas (de / até)
- Banda
- Modo
- Indicativo (pesquisa parcial)
- País / prefixo DXCC
- SNR mínimo

**Formatos de exportação:**
- **CSV** — compatível com Excel, LibreOffice Calc
- **JSON** — dados estruturados para processamento programático
- **PNG** — captura do estado atual da tabela de eventos

Os ficheiros são guardados em `data/exports/`.

### Exportação automática (retenção)
Quando o total de eventos excede o limite configurado (padrão: 500.000), o sistema:
1. Exporta todos os eventos para CSV em `data/exports/`
2. Mantém apenas os 50.000 eventos mais recentes (configurável)

A retenção corre no máximo uma vez por dia e pode ser acionada manualmente no painel Admin.

---

## Incorporar o Dashboard Académico num Website Externo

O dashboard Academic Analytics (`4ham_academic_analytics.html`) pode ser incorporado num website externo para que os visitantes possam visualizar dados de propagação sem aceder directamente ao servidor 4HAM. Isto é feito através de um **reverse proxy** que encaminha os pedidos API do website público para o backend 4HAM privado.

### Arquitectura

```
Browser do visitante
    │
    ▼
Servidor web externo (ex. exemplo.pt)
    ├── index.html / index.php    ← serve a página do dashboard
    └── /api/*                    ← reverse proxy para o backend 4HAM
            │
            ▼
    Backend 4HAM (ex. 192.168.1.x:8000)
```

O servidor externo necessita de:
1. Uma página que carregue o dashboard Academic Analytics
2. Uma regra de reverse proxy que encaminhe pedidos `/api/` para o backend 4HAM

### Opção A — Apache + PHP

**1. Criar `config.php`** com o URL do backend 4HAM:

```php
<?php
$BACKEND_URL = "http://192.168.1.x:8000";  // IP e porta do servidor 4HAM
```

**2. Criar `.htaccess`** com as regras de reverse proxy:

```apache
RewriteEngine On

# Proxy dos pedidos API para o backend 4HAM
RewriteRule ^api/(.*)$ http://192.168.1.x:8000/api/$1 [P,L]

# Proxy dos assets i18n e lib
RewriteRule ^i18n/(.*)$ http://192.168.1.x:8000/i18n/$1 [P,L]
RewriteRule ^lib/(.*)$ http://192.168.1.x:8000/lib/$1 [P,L]
```

Requer módulos Apache: `mod_rewrite`, `mod_proxy`, `mod_proxy_http`.

**3. Criar `index.php`** que obtém e serve o dashboard:

```php
<?php
require_once 'config.php';
$html = file_get_contents("$BACKEND_URL/4ham_academic_analytics.html");
if ($html === false) {
    http_response_code(502);
    echo "Backend indisponível";
    exit;
}
echo $html;
```

### Opção B — Nginx

```nginx
location /monitor/ {
    # Servir a página do dashboard
    location = /monitor/ {
        proxy_pass http://192.168.1.x:8000/4ham_academic_analytics.html;
    }

    # Proxy para API, i18n e lib
    location /monitor/api/ {
        proxy_pass http://192.168.1.x:8000/api/;
    }
    location /monitor/i18n/ {
        proxy_pass http://192.168.1.x:8000/i18n/;
    }
    location /monitor/lib/ {
        proxy_pass http://192.168.1.x:8000/lib/;
    }
}
```

### Considerações de segurança

- O reverse proxy expõe apenas os endpoints `/api/analytics/` e assets estáticos — o painel admin, controlos de scan e streams WebSocket **não** são proxied.
- **Não** fazer proxy de `/api/auth/`, `/api/admin/`, `/api/scan/`, ou `/ws/`.
- Considere adicionar rate limiting no servidor externo para prevenir abuso.
- O backend 4HAM deve permanecer numa rede privada; apenas o servidor web externo necessita de acesso.

### Resolução de problemas

| Sintoma | Causa | Solução |
|---|---|---|
| Dashboard carrega mas não mostra dados | Proxy da API não funciona | Verificar que `/api/analytics/academic` retorna JSON a partir do URL externo |
| 502 Bad Gateway | Backend 4HAM inacessível | Verificar que o backend está em execução e o URL/IP do proxy está correcto |
| Aviso de conteúdo misto | Site externo usa HTTPS, backend usa HTTP | Garantir que o proxy trata a transição HTTP→HTTPS (o browser só vê o URL HTTPS externo) |
| Erros CORS na consola | Pedidos directos browser→backend | Verificar que todos os pedidos API passam pelo proxy, não directamente para o IP do backend |
| i18n / traduções não carregam | Regra de proxy para `/i18n/` em falta | Adicionar a regra de rewrite/proxy para i18n |

---

## Descodificação APRS — Pipeline VHF

O 4HAM inclui descodificação APRS nativa a partir de RF, utilizando o dongle RTL-SDR ligado diretamente na frequência APRS VHF da Região 1 IARU (144.800 MHz). Não é utilizada ligação à internet — toda a descodificação é feita localmente a partir dos sinais recebidos pelo QTH.

### Arquitetura do Pipeline

Quando o utilizador seleciona o modo **APRS**, o pipeline é composto por três componentes em cadeia:

```
RTL-SDR → rtl_fm → Direwolf → KISS TCP → 4HAM
```

#### 1. rtl_fm (Demodulador FM)

- **Papel:** "O rádio" — sintoniza o RTL-SDR em 144.800 MHz e demodula o sinal NFM para áudio PCM.
- **Responsabilidade:** Receber o sinal RF do dongle USB, aplicar a desmodulação de frequência (NFM) e produzir uma stream de áudio digital (22050 Hz, mono, 16-bit).
- **Porquê rtl_fm:** É uma ferramenta nativa em C do projecto rtl-sdr, testada e comprovada em milhares de iGates APRS em todo o mundo. Ao contrário de um demodulador Python, garante baixa latência e qualidade de DSP fiável.

#### 2. Direwolf (Software TNC)

- **Papel:** "O descodificador" — recebe o áudio PCM e descodifica os pacotes AX.25/APRS.
- **Responsabilidade:** Descodificar os tons AFSK 1200 baud (mark=1200 Hz, space=2200 Hz), extrair os frames AX.25 (indicativos de origem e destino, payload APRS) e disponibilizá-los via protocolo KISS numa porta TCP (por defeito: 8001).
- **Porquê Direwolf:** É o software TNC de referência para APRS no ecossistema Linux. Em modo KISS, funciona como um servidor TCP que o 4HAM consulta para obter os pacotes descodificados.

#### 3. KISS TCP (Protocolo de Transporte)

- **Papel:** "O carteiro" — protocolo de entrega entre o Direwolf e o 4HAM.
- **Responsabilidade:** Transportar os frames AX.25 em bruto desde o Direwolf até ao cliente TCP do 4HAM, utilizando tramas delimitadas por `0xC0` com sequências de escape.
- **O que acontece no 4HAM:** O módulo `direwolf_kiss.py` liga-se ao servidor KISS do Direwolf, recebe os frames, faz o parse dos endereços AX.25 (indicativos de 7 bytes) e extrai o payload APRS (posição, símbolo, comentário). Cada pacote válido é registado como um evento na base de dados.

### Comportamento ao Mudar de Modo

Quando o utilizador sai do modo APRS e volta para outro modo de scan (ex.: FT8 em 20m), o 4HAM:
1. Pára os processos rtl_fm e Direwolf
2. Liberta o dongle RTL-SDR
3. Reabre o SDR via SoapySDR para o scan normal de HF/VHF

Este ciclo é automático e transparente — basta selecionar o modo de scan desejado.

### Requisitos

| Componente | Instalação |
|---|---|
| `rtl-sdr` | `sudo apt install rtl-sdr` |
| `direwolf` | `sudo apt install direwolf` |

Ambos são instalados automaticamente pelo script `install.sh`.

---

## Resolução de Problemas

### A cascata está em branco / "No live spectrum data"
Aparece apenas quando o scan está ativo mas não chegam frames FFT. Verificar:
- O SDR está ligado e reconhecido (`rtl_test` ou `SoapySDRUtil --find`)
- Nenhum outro programa (GQRX, SDR#) está a usar o dispositivo
- O backend está a correr — verificar em **Logs & Reports → Server logs**

### Não aparecem callsigns FT8/FT4
- Verificar se `jt9` (do pacote WSJT-X) está instalado e no PATH do sistema
- Em **Decoder Status**: o pipeline jt9 deve mostrar "running"
- Propagação fraca pode resultar em zero decodes mesmo com espectro visível

### O RTL-SDR v4 não é detectado
- Confirmar que o driver `rtlsdrblog/rtl-sdr-blog` foi compilado (o pacote `apt rtl-sdr` não suporta a versão v4)
- Verificar blacklist dos módulos do kernel: `cat /etc/modprobe.d/blacklist-rtl.conf`
- Reiniciar e reconectar o dongle USB

### Muitos eventos SSB_TRAFFIC / Voice Signature no painel
Desde v0.8.4 o sistema tem proteção incorporada: debounce de 30 s por segmento, gate de SNR (8 dB mínimo) e marcadores SSB_VOICE apenas com confirmação ASR. Se ainda houver muita actividade:
- Usar filtro **Callsign Only** para mostrar apenas eventos com indicativo resolvido
- Usar filtro **SSB Callsign Detected** para apenas eventos Whisper com callsign confirmado

### O servidor parou / não responde
- Verificar logs do sistema: `journalctl -u 4ham-spectrum-analysis -n 50`
- Se o RTL-SDR estava com USB instável, reconectar o dongle e reiniciar o serviço
- O sistema usa cache de enumeração de dispositivos (TTL 30 s) para reduzir chamadas USB em condições de hardware instável
- A enumeração SoapySDR corre num processo filho desde v0.8.4 — se a biblioteca `libuhd` causar uma falha nativa (SIGSEGV), apenas o processo filho termina e o servidor continua em execução

### Onde estão os dados guardados?
- Eventos: `data/events.sqlite`
- Exportações automáticas e manuais: `data/exports/`
- Logs do servidor: `logs/`
