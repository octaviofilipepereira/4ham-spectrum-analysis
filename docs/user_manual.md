# 4HAM Spectrum Analysis - Manual do Utilizador

## Índice

1. [Eventos SSB — Voice Signature](#eventos-ssb--voice-signature)
2. [Compreender as Métricas](#compreender-as-métricas)
   - [SNR vs Propagation Score](#snr-vs-propagation-score)
3. [Dashboard Academic Analytics](#dashboard-academic-analytics)
4. [Scan Rotation (Rotação de Scan)](#scan-rotation-rotação-de-scan)
5. [Mapa de Propagação — Seletor de Janela Temporal](#mapa-de-propagação--seletor-de-janela-temporal)
6. [Configuração Inicial](#configuração-inicial)
7. [Interface do Utilizador](#interface-do-utilizador)
8. [Interpretação do Espectrograma](#interpretação-do-espectrograma)
9. [Exportação de Dados](#exportação-de-dados)
10. [Resolução de Problemas](#resolução-de-problemas)

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

##### Categoria 2 — CW (Morse)

CW usa varrimento sequencial por frequência com dwell curto. Não captar um indicativo **não indica propagação fraca** — o operador pode simplesmente não ter transmitido o indicativo durante a janela de escuta.

| Componente | Peso | Descrição |
|---|---|---|
| `traffic_volume` | **30 %** | CW_TRAFFIC detetado = banda ativa |
| `snr_quality` | **30 %** | SNR normalizado (floor −15 dB, ceiling +20 dB) |
| `signal_strength` | **15 %** | Nível de sinal RF como indicador de propagação |
| `callsign_bonus` | **15 %** | Bónus quando indicativo É captado (não penalização quando ausente) |
| `recency` | **10 %** | Eventos mais recentes pesam mais |

##### Categoria 3 — SSB (Voz)

SSB partilha a limitação de varrimento sequencial do CW. A avaliação depende da deteção de voz, qualidade do SNR e nível de sinal.

| Componente | Peso | Descrição |
|---|---|---|
| `traffic_volume` | **20 %** | SSB_TRAFFIC / VOICE_DETECTION = banda ativa |
| `snr_quality` | **25 %** | SNR normalizado (floor +3 dB, ceiling +30 dB) |
| `signal_strength` | **15 %** | Nível de sinal RF |
| `voice_quality` | **20 %** | Qualidade da deteção de voz (clareza) |
| `transcript` | **10 %** | Transcrição speech-to-text bem-sucedida = sinal inteligível |
| `callsign_bonus` | **5 %** | Bónus quando indicativo É captado |
| `recency` | **5 %** | Eventos mais recentes pesam mais |

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
- Sistema operativo: Linux Ubuntu 20.04+ / Debian 11+ / Raspberry Pi OS 64-bit
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

Ou via script de desenvolvimento:
```bash
./scripts/run_dev.sh start
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
| **Overall Propagation** | Score composto (0–100) | Avaliação global usando as 3 fórmulas (Digital/CW/SSB). **≥ 70** Excellent (🟢), **≥ 50** Good (🟡), **≥ 30** Fair (🟠), **< 30** Poor (🔴). O badge colorido dá uma leitura rápida. Referência: [propagation_scoring_reference_pt.md](propagation_scoring_reference_pt.md) |
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
| **CSV** | Abrir em Excel/LibreOffice, importar noutra ferramenta | Tabela simples com colunas: banda, modo, total de eventos, SNR pico, SNR médio |
| **JSON** | Processamento programático (Python, JavaScript, etc.) | Objeto completo com: séries agregadas por banda+modo, eventos por bucket temporal, todos os eventos individuais (com indicativo, grid, SNR, frequência), scores de propagação por banda, e intervalo temporal |
| **XLSX** | Relatórios profissionais, análise detalhada em Excel | Workbook com **4 folhas separadas**: |

**Folhas do ficheiro XLSX:**

| Folha | Conteúdo | Uso |
|---|---|---|
| **Events by Band-Mode** | Dados agregados por combinação banda+modo | Visão geral: quantos eventos em cada banda e modo |
| **Aggregated Events** | Eventos agrupados por bucket temporal (hora/dia) | Análise de tendências temporais |
| **All Events** | Todos os eventos individuais com: timestamp, indicativo, banda, modo, frequência, SNR, grid locator | Análise detalhada evento a evento, log completo |
| **Propagation by Band** | Score de propagação e contagem de eventos por banda | Resumo da qualidade de propagação |

O ficheiro é gerado no browser e descarregado automaticamente com o nome `4ham-analytics_{início}_{fim}.{ext}` (ex.: `4ham-analytics_2026-04-07-14-00_2026-04-08-14-00.xlsx`).

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
