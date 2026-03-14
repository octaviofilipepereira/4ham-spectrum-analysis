# 📻 4HAM Spectrum Analysis

### Plataforma open-source de análise de espectro para radioamadores
**Autor:** Octávio Filipe Gonçalves — CT7BFV  
**Licença:** GNU AGPL-3.0  
**Repositório:** [github.com/octaviofilipepereira/4ham-spectrum-analysis](https://github.com/octaviofilipepereira/4ham-spectrum-analysis)

---

## O que é?

O **4HAM Spectrum Analysis** é uma plataforma web completa para monitorização e análise de espectro de rádio amador. Basta ligar um RTL-SDR ao computador ou a um Raspberry Pi, abrir o browser, e tens um painel de controlo profissional com waterfall em tempo real, descodificação automática de sinais e mapa de propagação 3D.

---

## Funcionalidades Principais

### 🌊 Waterfall em Tempo Real
- Renderização WebGL de alta performance (com fallback Canvas 2D)
- Paleta de cores estilo Yaesu FT-DX10
- Zoom até 16x com pan por arrasto
- Modo fullscreen para monitorização dedicada
- Tooltip com frequência, indicativo, SNR e último contacto

### 📡 Varrimento de Bandas
- Scan automático de qualquer banda HF/VHF/UHF
- Detecção de ocupação com threshold adaptativo
- Troca rápida de banda durante o scan (quick band switching)
- Suporte para bandas IARU Região 1 (160m a 70cm)

### 🔍 Descodificação Automática de Sinais

| Modo | Método | Detalhes |
|------|--------|----------|
| **FT8** | Externo (jt9/WSJT-X) | Captura de 15s, resample, descodificação automática |
| **FT4** | Externo (jt9/WSJT-X) | Captura de 7.5s, mais rápido que FT8 |
| **WSPR** | Externo (wsprd) | Janela de 120s, inclui grid square e potência |
| **CW** | Interno (Python puro) | Decoder Morse completo: filtro → envelope → Hilbert → binarização → tabela Morse |
| **APRS** | Externo (Direwolf) | Protocolo KISS via TCP/IP, descodificação AX.25 |

### 🌍 Mapa de Propagação 3D
- Globo interativo com projecção ortográfica (D3.js)
- Arcos de grande-círculo para cada contacto
- Resolução DXCC automática (4528 prefixos)
- Cálculo de distância via haversine
- Tooltip com indicativo, país, banda, SNR e distância
- Legenda de cores por banda, funciona offline

### 📊 Gestão de Eventos
- Painel de eventos filtrável por banda, modo e indicativo
- Pesquisa avançada de indicativos (modal dedicado)
- Score de propagação em tempo real (Poor/Fair/Good/Excellent)
- Exportação em CSV, JSON e PNG (screenshot do waterfall)
- Armazenamento persistente em SQLite

### ⚙️ Administração
- Configuração de dispositivo SDR com auto-detecção
- Parâmetros de scan ajustáveis (step, dwell, sample rate, ganho)
- Gestão de decoders (start/stop individual)
- Autenticação para acesso administrativo
- Interface multi-idioma (Português, English, Español)

---

## Hardware Suportado

| Plataforma | Capacidade |
|------------|------------|
| **Raspberry Pi 4** (4 GB) | FFT + ocupação + FT8/FT4 + APRS + CW |
| **Raspberry Pi 5** (8 GB) | Todos os decoders + SSB/ASR leve |
| **PC Linux/Windows** | Todos os decoders com scan rates elevadas |

### Dispositivos SDR
- **RTL-SDR V3** (R820T2, direct sampling para HF)
- **RTL-SDR V4** (R828D, upconverter integrado)
- **HackRF**, **Airspy** e transceivers com interface SDR (via SoapySDR)

---

## Stack Tecnológico

- **Backend:** Python 3 + FastAPI + NumPy + SciPy
- **Frontend:** HTML5 + JavaScript vanilla + Bootstrap 5 + D3.js
- **SDR:** SoapySDR (abstracção multi-dispositivo)
- **Decoders:** jt9, wsprd, Direwolf (externos) + CW decoder nativo
- **Streaming:** WebSocket com compressão delta_int8
- **Storage:** SQLite3
- **Deploy:** systemd (Linux)

---

## Como Começar

```bash
# 1. Clonar o repositório
git clone https://github.com/octaviofilipepereira/4ham-spectrum-analysis.git
cd 4ham-spectrum-analysis

# 2. Criar ambiente virtual e instalar dependências
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt

# 3. Lançar o servidor
python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000

# 4. Abrir no browser
# http://localhost:8000
```

---

## Bandas Suportadas (IARU Região 1)

| Banda | Frequências |
|-------|-------------|
| 160m | 1.810 – 2.000 MHz |
| 80m | 3.500 – 3.800 MHz |
| 40m | 7.000 – 7.200 MHz |
| 20m | 14.000 – 14.350 MHz |
| 17m | 18.068 – 18.168 MHz |
| 15m | 21.000 – 21.450 MHz |
| 12m | 24.890 – 24.990 MHz |
| 10m | 28.000 – 29.700 MHz |
| 2m | 144 – 146 MHz |
| 70cm | 430 – 440 MHz |

---

## Versão Actual: v0.5.0

**Destaques da última versão:**
- **Decoder CW completo** — descodificação Morse em Python puro (filtro Butterworth, envelope Hilbert, binarização automática, análise temporal, tabela Morse)
- **CW Sweep** — varrimento de banda guiado por FFT com marcadores no waterfall
- **Suporte RTL-SDR V4** — detecção automática do tuner R828D com upconverter integrado
- **Fixes WSPR** — frequências dial IARU Região 1, correcção de OOM, abort mid-scan
- **UI melhorada** — VFO maior, status na barra VFO, linhas de banda vibrantes
- **Mapa de Propagação** — globo optimizado, drag mais suave, botões maiores

---

**73 de CT7BFV!** 🇵🇹

*Software livre, feito por radioamadores, para radioamadores.*
