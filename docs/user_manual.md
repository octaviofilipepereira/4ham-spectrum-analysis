# 4HAM Spectrum Analysis - Manual do Utilizador

## Índice

1. [Eventos SSB — Voice Signature](#eventos-ssb--voice-signature)
2. [Compreender as Métricas](#compreender-as-métricas)
   - [SNR vs Propagation Score](#snr-vs-propagation-score)

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

Durante transmissões SSB longas, o sistema aplica um gate adaptativo que suprime eventos de ocupação repetidos para o mesmo segmento. Isto evita que o painel de eventos fique saturado de entradas de ocupação enquanto a mesma estação está a transmitir.

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

**Como é calculado**:

Para cada evento na janela temporal (60 minutos), o sistema calcula um score ponderado considerando:

1. **SNR normalizado** (0 a 1):
   ```
   snr_norm = (SNR + 20) / 40
   ```
   - SNR -20 dB → 0.0 (0%)
   - SNR 0 dB → 0.5 (50%)
   - SNR 20 dB → 1.0 (100%)
   - SNR ≥ 20 dB → 1.0 (limite máximo)

2. **Confidence** (confiança da descodificação):
   - Mede quão "limpa" foi a descodificação do sinal
   - Varia entre 0.01 e 0.99

3. **Recency weight** (peso temporal):
   ```
   recency = 1.0 - (idade_minutos / janela_minutos)
   ```
   - Evento recém-recebido: peso 1.0
   - Evento há 60 minutos: peso 0.2
   - **Sinais recentes têm mais influência no score**

4. **Base weight** (tipo de evento):
   - **Callsign** (indicativo descodificado): peso 1.0
   - **Occupancy** (ocupação detetada): peso 0.55

**Score final**:
```
Score por evento = snr_norm × confidence × base_weight × recency_weight

Propagation Score = (soma de todos os scores / soma dos pesos) × 100
```

**Classificação**:
- **≥ 70**: Excellent 🟢 (Excelente)
- **≥ 50**: Good 🟡 (Bom)
- **≥ 30**: Fair 🟠 (Razoável)
- **< 30**: Poor 🔴 (Fraco)

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
./run_dev.sh
```

Abrir a interface no browser: `http://localhost:8000/`

---

## Interface do Utilizador

### Barra de ferramentas (toolbar)

| Botão | Função |
|-------|--------|
| **Band Config** | Configurar bandas, intervalos de frequência, ativar/desativar individualmente |
| **Logs & Reports** | Estado dos decoders, Resumo de sessão, Logs, Painel de pesquisa/exportação |
| **Admin Config** | SDR, ganho, retenção de dados, autenticação. Requer login de administrador |
| **Help** | Manual do utilizador (este documento) |

### Controlos de scan
- **Start scanning / Stop scanning** — inicia ou para o scan ativo
- **Botões de banda** (160m … 10m) — mudam de banda imediatamente, mesmo com scan em curso
- **Botões de modo** (CW / WSPR / FT4 / FT8 / SSB) — selecionam o decoder ou mudam o scan em tempo real

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
Comportamento normal durante scan SSB em bandas com atividade de voz. Para uma vista mais limpa:
- Usar filtro **Callsign Only** para mostrar apenas eventos com indicativo resolvido
- Usar filtro **SSB Callsign Detected** para apenas eventos Whisper com callsign confirmado

### O servidor parou / não responde
- Verificar logs do sistema: `journalctl -u 4ham-spectrum-analysis -n 50`
- Se o RTL-SDR estava com USB instável, reconectar o dongle e reiniciar o serviço
- O sistema usa cache de enumeração de dispositivos (TTL 30 s) para reduzir chamadas USB em condições de hardware instável

### Onde estão os dados guardados?
- Eventos: `data/events.sqlite`
- Exportações automáticas e manuais: `data/exports/`
- Logs do servidor: `logs/`
