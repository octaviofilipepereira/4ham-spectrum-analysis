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

Além da interface principal, existe uma página dedicada a análise académica e agregada de eventos:

- Acessível via o botão **Data Analysis** na barra de ferramentas (abre num novo separador)
- Ou diretamente em `http://localhost:8000/4ham_academic_analytics.html`

Os dados vêm do endpoint `/api/analytics/academic` e são **atualizados automaticamente a cada 60 segundos**. Um contador de contagem regressiva indica o próximo refresh.

### Seletor de período

| Preset | Período |
|---|---|
| **1h** | Última hora (padrão no primeiro acesso) |
| **12h** | Últimas 12 horas |
| **24h** | Últimas 24 horas |
| **7d** | Últimos 7 dias |
| **30d** | Últimos 30 dias |
| **Custom** | Intervalo personalizado (data/hora de início e fim) |

O preset ativo é memorizado na sessão do browser. Os presets curtos (≤ 2 h) usam agregação ao minuto para maior resolução; acima de 72 h agrega por dia; caso contrário por hora.

### Filtros de banda e modo

- **Band** — filtrar por banda individual (160m … 70cm) ou **All**
- **Mode** — filtrar por modo (SSB, FT8, FT4, CW, WSPR) ou **All**
- Clicar em **Apply Filters** após alterar filtros ou o período personalizado

### Cartões KPI (resumo)

Seis cartões no topo apresentam métricas agregadas para o período selecionado:

| Cartão | Descrição |
|---|---|
| **Total events** | Soma de todos os eventos no período/filtro |
| **Unique callsigns** | Número de indicativos distintos |
| **Average SNR** | SNR médio ponderado (dB) |
| **Time coverage** | Percentagem de horas UTC com dados vs. total de horas na janela |
| **Overall Propagation** | Score composto (0–100) com badge colorido (Excellent/Good/Fair/Poor) |
| **Best band** | Banda com melhor score de propagação + estabilidade |

### Gráficos

#### Event Time Series
Gráfico de área com sobreposição de linha mostrando total de eventos por hora (ou minuto/dia conforme resolução). Hover mostra data e contagem.

#### Distribution by Band and Mode
Gráfico de barras empilhadas — cada barra é uma banda, cada segmento de cor representa um modo. Legenda inline com cores: SSB (azul), FT8 (verde), FT4 (púrpura), CW (âmbar), WSPR (rosa).

#### Hour of Day × Band — Heatmap Pro
Matriz interativa: 24 linhas (horas UTC 0–23) × colunas (bandas). A intensidade da cor indica o volume de eventos. Funcionalidades:
- **Cross-highlighting** — ao passar o rato, toda a linha e coluna são destacadas
- **Barras marginais** — totais por banda (topo, **Σ band**) e por hora (lado direito, **Σ hour**)
- Escala de cor normalizada por potência (expoente 0.62) de azul-escuro a branco

#### Top Callsigns in Period
Gráfico de barras horizontais com os **top 20 indicativos** por total de aparições no período filtrado.

#### Propagation Score by Band
Gráfico de barras verticais com o score de propagação (0–100) por banda. Rótulos numéricos acima de cada barra.

#### Propagation Time Trend
Gráfico de linha mostrando a evolução do score global de propagação ao longo do tempo. Linha tracejada horizontal indica a média do período.

### Ícones de ajuda

Cada painel de gráfico tem um ícone **"i"** no cabeçalho. Ao passar o rato, aparece um cartão flutuante com o título e uma descrição detalhada do gráfico.

### Exportação

Botão **Export ▾** com três formatos:

| Formato | Conteúdo exportado |
|---|---|
| **CSV** | Linhas agregadas: banda, modo, total eventos, SNR pico, SNR médio |
| **JSON** | Objeto estruturado com séries agregadas, eventos por bucket temporal, todos os eventos individuais, propagação por banda e período |
| **XLSX** | Workbook com 4 folhas: "Events by Band-Mode" (agregado), "Aggregated Events" (por bucket temporal), "All Events" (todos os eventos individuais com indicativo, grid, SNR, frequência), "Propagation by Band" (score + eventos por banda) |

Nome do ficheiro: `4ham-analytics_{início}_{fim}.{ext}`

### Metadados (rodapé)

Quatro campos informativos: snapshot dos dados (timestamp UTC), frequência de atualização (1 min), período analisado, e qualidade dos dados.

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
