<!--
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
Last update: 2026-02-23 UTC
-->

# Changelog

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
