# 4HAM Spectrum Analysis - Manual do Utilizador

## Índice

1. [Eventos SSB — Voice Signature](#eventos-ssb--voice-signature)
2. [Compreender as Métricas](#compreender-as-métricas)
   - [SNR vs Propagation Score](#snr-vs-propagation-score)

---

## Eventos SSB — Voice Signature

### O que é um evento Voice Signature?

A partir da **v0.8.0**, o sistema deteta e transcreve transmissões SSB em tempo real usando demodulação de voz e ASR (Automatic Speech Recognition — Whisper).

Existem dois tipos de resultado para sinais SSB:

| Badge | Significado |
|-------|------------|
| **Voice Signature** (azul) | SSB detetado, sem indicativo resolvido — Whisper não identificou um indicativo válido na transcrição |
| **callsign** (azul) | SSB detetado **e** indicativo resolvido com sucesso pelo ASR |

### Pipeline de deteção SSB

1. O scanner deteta ocupação de banda com largura de banda típica de SSB (2,4–3 kHz).
2. O bloco DSP demódula USB ou LSB conforme a banda e segmento de frequência.
3. O VAD (Voice Activity Detection) segmenta a transmissão em trechos de voz.
4. O Whisper transcreve o áudio — todos os tokens que correspondam a um indicativo válido (regex IARU) são extraídos.
5. Se um indicativo for encontrado → evento `callsign` com `source: asr`.
6. Se nenhum indicativo for encontrado → evento `callsign` com `_is_ssb_voice: true` → badge **Voice Signature**.

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

## [Em desenvolvimento]

Este manual será expandido com mais secções sobre:
- Configuração inicial
- Interface do utilizador (painel de eventos, waterfall, propagação)
- Interpretação do espectrograma
- Exportação de dados
- Resolução de problemas
