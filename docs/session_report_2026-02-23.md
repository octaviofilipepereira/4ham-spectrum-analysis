# Relatório de Sessão — 4ham Spectrum Analysis
**Data:** 2026-02-23  
**Callsign:** CT7BFV  
**Âmbito:** Correção de 4 bugs críticos + validação completa do sistema

---

## Resumo Executivo

Foram identificados e corrigidos 4 bugs (dois críticos, dois médios) que impediam:
- O decoder JT9 de arrancar automaticamente após reinício do servidor
- O RTL-SDR v3 de receber sinais HF nas bandas abaixo de 24 MHz
- A tooltip do waterfall de se manter visível durante atualização de frames
- A legibilidade da tooltip (CSS subdimensionado)

Após as correções, o sistema validou com sucesso em produção:  
**56 sinais FT8/FT4 decodificados e guardados em base de dados em ~3 minutos de scan na banda 40m.**

---

## Bugs Corrigidos

### 🔴 Fix A — JT9 não arrancava após reinício (CRÍTICO)
**Ficheiro:** `backend/app/main.py`  
**Problema:** Não existia nenhum mecanismo de auto-arranque dos decoders. A variável `state.ft_external_decoder` ficava `None` após cada reinício do servidor. O decoder só podia ser iniciado manualmente via `POST /api/decoders/external-ft/start`.

**Impacto:** Em qualquer reinício do servidor (ex: após atualização), o JT9 não estava ativo → zero events FT8/FT4.

**Correção:** Adicionado um **FastAPI `lifespan` context manager** que auto-inicia os decoders configurados no startup e os para graciosamente no shutdown.

```python
@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """Auto-start enabled decoders on startup and stop them gracefully on shutdown."""
    if _state.ft_external_enable:
        await _start_ft_external_decoder(force=False)
    if _state.ft_internal_enable:
        await _start_ft_internal_decoder(force=False)
    yield
    # Graceful shutdown
    if _state.ft_external_decoder:
        await _stop_ft_external_decoder()
    ...
```

**Evidência no log:**
```
INFO: FT external decoder startup: {'started': True, 'reason': None}
INFO: Application startup complete.
```

---

### 🔴 Fix B — RTL-SDR v3 Direct Sampling não ativava (CRÍTICO)
**Ficheiro:** `backend/app/sdr/controller.py`  
**Problema:** A variável `_last_direct_samp_mode` era **module-level** e nunca era reiniciada entre scans. Quando o `device.close()` era chamado, o hardware do RTL-SDR revertia para o modo padrão (`"0"` = tuner R820T2). Mas o Python continuava com a cache `"2"` (Q-branch), pelo que na próxima `open()` a chamada `device.writeSetting("direct_samp", "2")` era **silenciosamente ignorada**.

**Resultado:** A partir do 2.º scan, o RTL-SDR v3 ficava na banda 40m (7 MHz) a usar o tuner R820T2 — que não recebe abaixo de 24 MHz — produzindo **zero sinal HF**.

**Linha do bug:**
```python
# ANTES (BUGGY):
_last_direct_samp_mode: str = ""  # module-level, mantinha valor entre scans

def open(...):
    # _apply_direct_sampling verificava cache → SKIP se mode == last
    _apply_direct_sampling(device, center_hz)  # SILENTLY SKIPPED!
```

**Correção:** Reset da cache no início de cada `open()`:
```python
def open(self, device_id=None, sample_rate=48000, center_hz=0, gain=None):
    global _last_direct_samp_mode
    # Reset cache: hardware reverts to mode "0" every time the device is
    # closed, so the next open() MUST re-apply the correct mode even when
    # the frequency (and therefore the desired mode) hasn't changed.
    _last_direct_samp_mode = ""
    ...
```

**Evidência no log (confirmação hardware):**
```
Found Rafael Micro R820T tuner
Enabled direct sampling mode, input 2   ← Q-branch ativo
[INFO] Using format CF32.
```
A mensagem "Enabled direct sampling mode, input 2" passou a aparecer em **todos** os arranques de scan (antes só aparecia no 1.º).

---

### 🟡 Fix C — Tooltip desaparecia a cada frame WebSocket (MÉDIO)
**Ficheiro:** `frontend/app.js`  
**Problema:** A função `renderWaterfallModeOverlay()` era chamada a cada frame WebSocket (~1s). Dentro dela, `innerHTML = ""` destruía todos os elementos de markers (sem disparar `mouseleave`) e depois `hideWaterfallHoverTooltip()` era chamado incondicionalmente → tooltip ocultado mesmo que o utilizador estivesse a hover.

**Correção:** 
1. Adicionadas variáveis de tracking: `_waterfallHoverActive`, `_waterfallLastTooltipText`, `_waterfallLastTooltipX/Y`
2. `showWaterfallHoverTooltip()` grava o estado; `hideWaterfallHoverTooltip()` limpa-o
3. Em `renderWaterfallModeOverlay()`: removida a chamada `hideWaterfallHoverTooltip()` do path de redraw com markers
4. No final do render, se hover estava ativo: restabel‍ece o tooltip com o último texto/posição guardados

**Resultado:** Tooltip persiste enquanto o utilizador mantém o cursor sobre um marker, independentemente dos frames WebSocket.

---

### 🟢 Fix D — Tooltip CSS subdimensionado (BAIXO)
**Ficheiro:** `frontend/styles.css`  
**Antes:**
```css
.waterfall-hover-tooltip {
  max-width: min(360px, calc(100% - 24px));
  padding: 6px 10px;
  font-size: 0.78rem;
  line-height: 1.25;
}
```
**Depois:**
```css
.waterfall-hover-tooltip {
  max-width: min(560px, calc(100% - 24px));
  min-width: 260px;
  padding: 10px 16px;
  font-size: 0.92rem;
  line-height: 1.4;
}
```
**Resultado:** Tooltip legível com texto completo `FT8 | 7.074 MHz | callsign AO5SE | last 0s | -7.0 dB`.

---

## Validação do Sistema

### Sequência de Validação

| Passo | Resultado | Detalhe |
|---|---|---|
| Stop/Start servidor | ✅ | PID 187508, startup em <5s |
| Health check | ✅ | `{"status":"ok","devices":4}` |
| FT External Decoder auto-start | ✅ | `running: true`, `started_at: 20:40:29 UTC` |
| RTL-SDR detectado | ✅ | `driver=rtlsdr`, R820T2 tuner found |
| Scan 40m iniciado | ✅ | `state=running`, banda 7.000–7.200 MHz |
| Direct Sampling ativo | ✅ | `Enabled direct sampling mode, input 2` |
| JT9 primeiro decode | ✅ | `M2X DJ2KP JO42` em 20:44:31 UTC |
| FT8 events em DB | ✅ | 40 events FT8 (7.074–7.078 MHz) |
| FT4 events em DB | ✅ | 16 events FT4 (7.047–7.051 MHz) |
| Total events após ~3 min | ✅ | **56 events** (decode_invocations=6, windows=8) |

### Snapshot do JT9 Decoder (final)
```
running:            True
modes:              ['FT8', 'FT4']
decode_invocations: 6
windows_processed:  8
lines_parsed:       56
events_emitted:     56
last_event_at:      2026-02-23T20:46:45 UTC
last_error:         None
```

### Amostra de Sinais Decodificados (últimos 5)
| Timestamp (UTC) | Callsign | Modo | Frequência | SNR |
|---|---|---|---|---|
| 20:46:45 | DF1AN | FT4 | 7.050 MHz | -4.0 dB |
| 20:46:45 | HB9AWS | FT4 | 7.050 MHz | -6.0 dB |
| 20:46:45 | G4CXQ | FT4 | 7.049 MHz | 0.0 dB |
| 20:46:34 | G5NGL | FT8 | 7.077 MHz | +4.0 dB |
| 20:46:34 | F1LNS | FT8 | 7.075 MHz | -16.0 dB |

---

## Nota Técnica — Base de Dados

O servidor backend corre a partir do directório `scripts/` (CWD do processo uvicorn), pelo que a base de dados activa é:
```
scripts/data/events.sqlite
```
A base de dados em `data/events.sqlite` (root) contém os 11.394 eventos históricos de sessões anteriores em que o backend era iniciado a partir do directório raiz.

**Recomendação:** Normalizar o CWD do uvicorn para o directório raiz do projecto, adicionando `cd "$ROOT_DIR"` antes do `nohup` em `scripts/run_dev.sh`, para que todos os dados persistam na mesma base de dados.

---

## Ficheiros Modificados

| Ficheiro | Fix | Linhas alteradas |
|---|---|---|
| `backend/app/sdr/controller.py` | Fix B — Reset cache `_last_direct_samp_mode` | +5 linhas em `open()` |
| `backend/app/main.py` | Fix A — Lifespan handler JT9 auto-start | +42 linhas |
| `frontend/app.js` | Fix C — Tooltip persistence + tracking vars | +14 linhas |
| `frontend/styles.css` | Fix D — CSS tooltip maior | ~6 linhas alteradas |

---

## Estado do Sistema Após Correção

```
Backend:   ✅ running  PID 187508
Health:    ✅ ok  devices=4
Scan:      ✅ running  40m  RTL-SDR  7.074 MHz
Direct Sampling: ✅ Q-branch (mode 2) activo em HF
JT9:       ✅ running  FT8+FT4  56 events  sem erros
DB:        ✅ 56 events guardados  FT8:40  FT4:16
Frontend:  ✅ Tooltip CSS aumentado  hover persistente
```
