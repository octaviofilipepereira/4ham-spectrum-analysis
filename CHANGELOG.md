<!--
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
Last update: 2026-03-15 UTC
-->

# Changelog

## v0.6.2 - 2026-03-15

### Fixed
- CI test fragility in `test_storage_db_metrics.py`: replaced hardcoded timestamps from `2026-03-06` with dynamic relative timestamps (`datetime.now(timezone.utc) - timedelta(minutes=X)`) so the SSB metrics tests always fall within the query window regardless of when they run.

## v0.6.1 - 2026-03-15

### Added
- Waterfall transition overlay covering the full spectrum+waterfall area (spectrum canvas and waterfall canvas are now wrapped in a common `waterfall-area` container; the overlay is positioned relative to it).
- Improved transition overlay visual design: dual-ring counter-rotating spinner, fade-in entry animation, pulsing message text, and a gradient dark backdrop with stronger blur.

### Changed
- All user-facing strings (toasts, status messages, log lines) translated to English — no more Portuguese in the UI.
- Retention system: count-based threshold raised to 500,000 events; when triggered, all events are exported and only the 50,000 most recent are kept (`RETENTION_KEEP_EVENTS` env var, default 50 000). Age-based purge (30 days) still runs independently.
- Waterfall status line colour changed to yellow (`#facc15`) for better contrast against the dark waterfall background.
- Propagation Map no longer shows an "Unknown" band entry — events without a `band` value are now silently skipped in the summary builder.

### Fixed
- `modeFilter is not defined` JS error when switching mode during an active scan — the variable was never declared; replaced with the correct `eventsSearchModeInput` in four call sites (`startScan`, `syncScanState`, mode button handler).
- "No live spectrum data available" error appearing in preview/idle mode (no scan running) — the fallback timer and WebSocket error handlers now only show the error when `isScanRunning` is `true`.
- Waterfall not centering on the correct mode segment after a live band switch — `lastSpectrumFrame` is now cleared between `stopScan` and `startScan` in `switchBandLive` so `recenterWaterfallForMode` uses the new band's frequency range.
- Structured log configuration extracted to `backend/app/log_config.py`, fixing log formatting on startup.

## v0.6.0 - 2026-03-14

### Added
- Session-based authentication stored in SQLite, with login, logout, and session validation via cookie instead of browser Basic Auth prompts.
- Frontend auth bootstrap that validates the session on reload and only starts protected streams after authentication is confirmed.
- Scan context summary in the main UI showing the active scan range and, when CW is selected, the active CW decoder segment.

### Changed
- CW decoder 20 m segment corrected to `14.000-14.070 MHz`.
- CW mode changes during an active scan now start the CW decoder with the correct subsegment for the current band.
- Logout control restyled as a proper status chip and the login modal inputs restyled for readable black-on-white entry.

### Fixed
- Removed `WWW-Authenticate` prompts that were causing browser-native auth popups.
- Waterfall and protected WebSocket/data startup now happen after successful login, avoiding manual reload after authentication.
- WebSocket authentication now accepts the authenticated session cookie, keeping logs, events, spectrum, and status streams aligned with the UI login state.

## v0.5.0 - 2026-03-14

### Added

#### CW Decoder — Módulo Completo
- **`backend/app/decoders/cw/`** — decoder Morse puro Python (sem binários externos):
  - Bandpass Butterworth 4ª ordem (300–900 Hz)
  - Extracção de envelope via transformada de Hilbert + média móvel
  - Binarização automática com threshold estilo Otsu
  - Análise temporal: run-length encode → dit estimation → WPM = 1200/dit_ms
  - Tabela Morse completa com lookup de indicativos via regex
  - Confidence scoring: `0.5×char + 0.3×wpm + 0.2×length`
  - Suporte para CW de alta velocidade (contest, até 60+ WPM)
  - SNR e WPM configuráveis com validações
- **`backend/app/decoders/cw_sweep.py`** — `CWSweepDecoder` para varrimento de banda:
  - Sweep guiado por FFT com step configurável (default 6500 Hz)
  - Dwell time ajustável (default 30 s)
  - Detecção multi-peak com rejeição near-Nyquist
  - Diagnósticos de produção integrados
- **`backend/app/decoders/cw_session.py`** — `CWDecoderSession` para monitorização contínua:
  - Feed IQ em tempo real com janela deslizante
- **Integração API**:
  - CW decoder integrado em `/api/scan/mode` com start/stop automático
  - Auto-start ao arranque da aplicação
  - Exclusão mútua entre CW e FT decoders (um activo de cada vez)
  - Eventos de texto CW emitidos mesmo sem callsign + campos de ocupação

#### CW no Frontend
- Controlos CW sweep no painel de scan (step Hz, dwell s)
- Marcadores CW injectados no waterfall como `mode_markers`
- Botão CW corrigido: já não fica sempre seleccionado após parar o scan

#### RTL-SDR V4 Support
- **`backend/app/sdr/controller.py`**:
  - Detecção automática de RTL-SDR V4 (tuner R828D)
  - V4 usa upconverter integrado — não aplica direct sampling para HF
  - Desactivação de hardware AGC para melhor descodificação de sinais fracos
- **`backend/app/api/scan.py`**:
  - Preview scan bounds configuráveis via env vars (`PREVIEW_START_HZ`, `PREVIEW_END_HZ`)
  - Limpeza de scan bounds stale ao parar
  - Estado de scan correcto durante modo preview

### Fixed

#### WSPR
- Frequências dial WSPR corrigidas para IARU Região 1
- Fix de OOM (Out-of-Memory) em janelas WSPR longas
- Interrupção da janela WSPR quando a banda muda mid-scan
- Abort da janela WSPR quando o modo muda durante slot wait
- Reset de estado parked no início do scan + reavaliação de dial freq após slot wait

#### CW
- 3 bugs críticos que causavam zero eventos CW descodificados
- Degradação Butterworth near-Nyquist + detecção multi-peak
- Default dwell corrigido para 30s; leitura de `cw_dwell_s`/`cw_step_hz` do scan payload
- Deadlock no event loop resolvido (USB open)
- Revert de park do scan engine durante CW decoder activo (abordagem abandonada)

#### Frontend / UX
- Marcadores WSPR agora visíveis no waterfall (pipeline DSP occupancy)
- Botão CW no frontend: estado correcto após scan stop
- Parâmetro duplicado removido no events endpoint (legacy)

### Changed

#### Layout & UX
- VFO display maior com fontes aumentadas
- Status movido para a barra VFO abaixo do SNR
- Signal Quality reposicionado junto ao botão GO
- Largura fixa para `vfo-goto-group` (elimina layout shift)
- Altura fixa para status inline display
- Linhas de banda com cores vibrantes e maior opacidade
- Onboarding overlay: wrapper element em falta adicionado
- Default waterfall zoom: 4x com vista centrada (revertido para 1x na primeira visita)

#### Mapa de Propagação
- Velocidade de drag do globo reduzida (0.5 → 0.25)
- Globe SVG preenche altura do card (100%/100%, `getBoundingClientRect`)
- Card Propagation Map mesma altura que Events
- Botões de controlo maiores (30 → 40px), ícones substituídos (reset=↻, fullscreen=⤢)
- Removido círculo de glow atmosférico
- Raio de glow actualiza correctamente com zoom

### Dependencies
- `scipy` adicionado a `requirements.txt` (necessário para CW decoder)

---

## v0.4.0 - 2026-02-26

### Added

#### 3D Propagation Globe
- **`frontend/map.js`** (347 linhas) — globo 3D interativo com `d3.geoOrthographic`:
  - Drag-to-rotate: arrastar roda o globo em qualquer direção
  - Scroll-to-zoom: roda do rato aumenta/diminui `proj.scale`
  - Botões overlay: `+` zoom in, `−` zoom out, `⌂` reset, `⛶` fullscreen
  - Double-click: repõe rotação centrada na estação
  - Arcos de grande-círculo via GeoJSON `LineString` (clipping automático pelo D3)
  - `d3.geoDistance` oculta dots no hemisfério oposto
  - Gradiente radial SVG para efeito de profundidade oceânica
  - Halo de atmosfera (círculo translúcido à volta do globo)
  - Legenda de bandas (cores por banda — paleta HF/VHF standard)
  - Tooltip `position:fixed` com callsign, país, banda, SNR, distância
  - Modal fullscreen Bootstrap (`modal-fullscreen`) com re-render ao abrir
  - Auto-refresh a cada 60 segundos
  - Todos os assets servidos localmente — funciona offline
- **`backend/app/api/map.py`** — `GET /api/map/contacts?window_minutes=60&limit=500`
  - Lê config da estação (callsign, locator Maidenhead)
  - Resolve cada callsign para entidade DXCC via longest-prefix-match
  - Calcula distância estação↔contacto via haversine
- **`backend/app/dependencies/helpers.py`** — novas funções:
  - `callsign_to_dxcc(callsign)` — longest-prefix-match contra 4528 prefixos DXCC
  - `maidenhead_to_latlon(grid)` — converte locator Maidenhead 4/6 chars para (lat, lon)
  - `haversine_km(lat1, lon1, lat2, lon2)` — distância em km entre dois pontos
- **`prefixes/dxcc_coords.json`** — base de dados DXCC gerada de cty.dat (AD1C):
  - 346 entidades DXCC com nome, continente, zona CQ, lat/lon
  - 4528 prefixos no índice de lookup
- **`prefixes/cty.dat`** — ficheiro fonte DXCC (AD1C, versão 25 Feb 2026, 99 KB)
- **`scripts/build_dxcc_coords.py`** — script de geração de `dxcc_coords.json` a partir de `cty.dat`
- **Assets frontend locais** (sem CDN):
  - `frontend/lib/d3.min.js` — D3.js v7.9.0 UMD (274 KB)
  - `frontend/lib/topojson.min.js` — TopoJSON Client 3.0.2 (21 KB)
  - `frontend/lib/countries-110m.json` — Natural Earth 110m em formato TopoJSON (106 KB)

#### Search Events Modal
- Modal Bootstrap dark com campos: Callsign (LIKE parcial), Mode, Band, Min SNR
- `AbortController` cancela fetches anteriores em voo (evita race conditions)
- Occupancy events filtrados — resultados mostram apenas eventos com callsign
- SNR colorido por valor em cada resultado

#### Propagation Card
- Card movido para `col-12 col-lg-6` ao lado do card Events
- Score colorido dinamicamente: `Poor`=red / `Fair`=yellow / `Good|Excellent`=green

### Fixed
- `build_propagation_summary()` — resposta reestruturada de dict plano para dict aninhado
  (`data.overall.score`, `data.event_count`) para compatibilidade com o frontend
- Rate limit da API de events: 30 → 300 req/min (evitava timeout em pesquisa rápida)
- Search modal z-index: modal movido para fora de `</main>`

### Libraries Added
| Biblioteca | Versão | Uso |
|------------|--------|-----|
| D3.js UMD | 7.9.0 | Projeção ortográfica, drag, gradientes SVG, geodésica |
| TopoJSON Client | 3.0.2 | Deserialização de topologia vectorial (países) |
| Natural Earth 110m | — | Geometria dos países em TopoJSON |

### Technical Notes
- A projeção `geoOrthographic` com `clipAngle(90)` garante que apenas o hemisfério
  frontal é renderizado — D3 recorta automaticamente arcos e países no limbo.
- O globo não usa `d3.zoom()` (que faz transform CSS); em vez disso manipula
  diretamente `proj.rotate()` e `proj.scale()` e chama `redraw()` a cada evento,
  para garantir que os arcos geo e a clipAngle são sempre recalculados corretamente.
- O endpoint `/api/map/contacts` resolve callsigns em tempo real sem cache —
  o lookup DXCC é O(n·k) onde k ≤ 6 (comprimento máximo do prefixo).

---

## v0.3.1 - 2026-02-23

### Added
- **5 Novos Endpoints API**:
  - `GET /api/events/export/csv` - Export de eventos em formato CSV com rate limiting (10 req/min)
  - `GET /api/events/export/json` - Export de eventos em formato JSON com rate limiting (10 req/min)
  - `POST /api/decoders/start/{decoder_type}` - Endpoint unificado para iniciar decoders (internal-ft, external-ft)
  - `POST /api/decoders/stop/{decoder_type}` - Endpoint unificado para parar decoders (internal-ft, external-ft)
  - `GET /api/admin/audio/detect` - Detecção automática de dispositivos e configuração de áudio

### Changed
- Limite máximo de 10.000 eventos por operação de export
- Rate limiting diferenciado: 10 req/min para exports, 30 req/min para queries normais
- Respostas API padronizadas com `{"status": "ok", ...}`
- Arquivos modificados:
  - `backend/app/api/events.py` - +115 linhas (302 total)
  - `backend/app/api/decoders.py` - +96 linhas (599 total)
  - `backend/app/api/admin.py` - +23 linhas (235 total)

### Enhanced
- Documentação completa (docstrings) em todos os novos endpoints
- Suporte a aliases de tipos de decoder (internal-ft, internal_ft, ft-internal, ft_internal)
- Validação de tipos de decoder com mensagens de erro descritivas (HTTPException 400)
- Autenticação opcional nos endpoints de export (`optional_verify_basic_auth`)
- Autenticação obrigatória no admin (`verify_basic_auth`)
- Formatação CSV otimizada com PlainTextResponse

### Testing
- **Validação de Novos Endpoints**: 10/10 testes passaram (100%)
- **Backend Tests**: 37/37 testes pytest passaram (100%)
- **Frontend Tests**: 17/17 testes passaram (100%)
- **Integração**: 47 rotas API registradas, todos endpoints frontend compatíveis
- **Sintaxe Python**: Validada em todos os arquivos modificados
- Scripts de teste criados:
  - `test_new_endpoints.sh` - Validação dos 5 novos endpoints
  - `validate_api_endpoints.sh` - Análise completa da API

## v0.3.0 - 2026-02-23

### Added
- **Frontend Modularization**: Created ES6 modules for better code organization:
  - `modules/config.js` - Constants and configuration
  - `modules/dom.js` - Centralized DOM element references
  - `modules/api.js` - REST API client with authentication
  - `modules/ui.js` - UI utilities (toasts, formatters, helpers)
  - `modules/websocket.js` - WebSocket manager with auto-reconnection
- **CI/CD Pipeline**: GitHub Actions workflow for automated testing and quality checks
  - Backend tests on Python 3.10, 3.11, 3.12
  - Frontend tests on Node.js 18, 20, 22
  - Code quality checks with Ruff, Black, and mypy
  - Security audits with pip-audit and safety
- **Type Hints**: Added comprehensive type hints to core Python modules:
  - `scan/engine.py` - Full type annotations for ScanEngine class
  - `streaming.py` - Type hints for encoding/decoding functions
- **Frontend Tests**: Created `package.json` for proper test management
- **Documentation**: Added README files for frontend modules and GitHub workflows

### Fixed
- **Critical Bug**: Fixed uninitialized `_parked_event` in `scan/engine.py`
  - Added proper asyncio.Event initialization in `__init__`
  - Improved park/unpark flow with event-based synchronization
- **File Handle Leak**: Enhanced `stop_async()` with proper exception handling
  - Guaranteed cleanup of file handles even on errors
  - Added proper task cancellation handling

### Changed
- **Improved Error Handling**: Better exception handling in critical paths
- **Code Quality**: Backend already refactored into modular API structure
- **Testing**: All 37 backend tests passing, 17 frontend tests passing

### Technical Debt Paid
- Resolved `_parked_event` RuntimeError risk
- Improved async cleanup in scan engine
- Better separation of concerns in frontend code

## v0.2.5 - 2026-02-22

### Changed
- Removed Fake waterfall mode from frontend controls and runtime behavior.
- Waterfall now stays in LIVE mode and does not render simulated spectrum data.

### Fixed
- Replaced simulated fallback rendering with a generic user-facing no-data message when no SDR device is available or live frames become stale.
- Improved readability of the waterfall no-data message with larger, centered, high-contrast presentation.

## v0.2.0 - 2026-02-21

### Added
- Configuration loader and schema validation for scan and region profile inputs.
- DSP occupancy improvements with mode heuristics and confidence scoring.
- Decoder pipelines for WSJT-X UDP, Direwolf KISS, CW parsing, and SSB ASR controlled vocabulary.
- WebSocket spectrum streaming backpressure handling and `delta_int8` compressed frames.
- WebGL waterfall rendering with fallback plus JSON/PNG export controls in frontend.
- Persistent export metadata and file rotation workflow in SQLite storage layer.
- IQ-sample QA harness with fixture-driven assertions.
- DSP benchmark tool for cross-platform performance comparison.
- Deployment packaging assets for Linux (`systemd`) and Windows service installation.

### Changed
- Same-origin frontend serving integrated into backend runtime flow.
- Decoder process management supports optional autostart and clean shutdown lifecycle.
- Documentation expanded for installation, operations, storage schema, and websocket contract updates.
- Repository hygiene improved with `.gitignore` for runtime artifacts.

### Fixed
- WSJT-X text parsing now correctly extracts `grid` and `report` from payload tokens.
- Decoder status visibility improved through runtime process state fields.
- Runtime validation paths aligned with current API/event payload behavior.
