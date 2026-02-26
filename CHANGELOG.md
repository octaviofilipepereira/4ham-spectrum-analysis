<!--
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
Last update: 2026-02-26 UTC
-->

# Changelog

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
