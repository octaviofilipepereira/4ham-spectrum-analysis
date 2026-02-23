# Guia de Refactoring - 4ham Spectrum Analysis

## Objetivo

Refactoring do `backend/app/main.py` (2300+ linhas) em módulos menores e mais manuteníveis.

## Estrutura Criada

```
backend/app/
├── api/                    # REST API endpoints (APIRouter modules)
│   ├── __init__.py
│   ├── health.py          # ✅ COMPLETO - Health, devices, bands
│   ├── scan.py            # TODO - Scan start/stop/status
│   ├── events.py          # TODO - Events query/stats
│   ├── decoders.py        # TODO - Decoder control
│   ├── exports.py         # TODO - Export management
│   ├── settings.py        # TODO - Settings CRUD
│   └── admin.py           # TODO - Admin operations
├── websocket/             # WebSocket handlers
│   ├── __init__.py
│   ├── logs.py            # TODO - /ws/logs
│   ├── events.py          # TODO - /ws/events
│   ├── spectrum.py        # TODO - /ws/spectrum
│   └── status.py          # TODO - /ws/status
├── dependencies/          # Shared dependencies
│   ├── __init__.py
│   ├── state.py           # ✅ COMPLETO - Global application state
│   ├── auth.py            # ✅ COMPLETO - Authentication dependencies
│   ├── utils.py           # ✅ COMPLETO - System utilities
│   └── helpers.py         # ✅ COMPLETO - API helper functions
└── main.py                # TODO - Simplified app + router includes
```

## Padrão de Refactoring

### 1. Criação de Módulos API

Cada módulo em `api/` deve:

**Estrutura base:**
```python
# © 2026 Octávio Filipe Gonçalves
# License: GNU AGPL-3.0

"""
Module Description
==================
Brief description of endpoints in this module.
"""

from typing import Dict, List
from fastapi import APIRouter, Depends, HTTPException
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.dependencies import state
from app.dependencies.auth import verify_basic_auth
from app.dependencies.helpers import log, sanitize_events_for_api

# Create router
router = APIRouter(prefix="/api", tags=["module_name"])

# Rate limiter (if needed)
limiter = Limiter(key_func=get_remote_address)


@router.get("/endpoint")
def endpoint_name(_: None = Depends(verify_basic_auth)) -> Dict:
    """
    Endpoint description.
    
    Returns:
        Response dict
    """
    # Implementation using state.* for global variables
    log("operation")
    return {"status": "ok"}
```

**Exemplo completo - `api/health.py`:**
- ✅ Endpoints: `/api/health`, `/api/devices`, `/api/bands` (GET/POST)
- ✅ Usa `Depends(verify_basic_auth)` para autenticação
- ✅ Importa `state.controller` e `state.db` para acesso a recursos
- ✅ Type hints completos
- ✅ Docstrings descritivas

### 2. Estado Global (`dependencies/state.py`)

Todas as variáveis globais do `main.py` foram movidas para `state.py`:

```python
from app.dependencies import state

# Acesso a variáveis globais:
state.controller          # SDRController instance
state.scan_engine         # ScanEngine instance
state.db                  # Database instance
state.export_manager      # ExportManager instance

state.scan_state         # Dict com estado do scan
state.default_modes      # Dict com modos padrão
state.spectrum_cache     # Cache de espectro
state.logs               # Lista de logs

# Configurações:
state.agc_enabled
state.ws_spectrum_fps
state.ft_internal_enable
# ...etc
```

### 3. Autenticação (`dependencies/auth.py`)

Duas funções de dependency injetável:

**`verify_basic_auth`** - Obrigatória (lança HTTPException se falhar):
```python
@router.get("/protected")
def protected_endpoint(_: None = Depends(verify_basic_auth)):
    return {"data": "sensitive"}
```

**`optional_verify_basic_auth`** - Opcional (retorna bool):
```python
@router.get("/public")
def public_endpoint(is_auth: bool = Depends(optional_verify_basic_auth)):
    if is_auth:
        return {"data": "full"}
    return {"data": "limited"}
```

### 4. Funções Auxiliares (`dependencies/helpers.py`)

Funções compartilhadas entre endpoints:

- `log(message)` - Adiciona log à lista global
- `safe_float(value, default)` - Conversão segura para float
- `clamp(value, min, max)` - Limita valor entre mín/máx
- `sanitize_events_for_api(items)` - Sanitiza eventos para API
- `build_propagation_summary()` - Calcula sumário de propagação
- `infer_band_from_frequency(freq_hz)` - Infere banda pela frequência
- `touch_decoder_source(source)` - Atualiza timestamp do decoder
- `record_decoder_event_saved(event)` - Regista métricas de evento
- `fallback_sample_rate_for_device()` - Taxa de amostragem de fallback

### 5. Utilitários de Sistema (`dependencies/utils.py`)

Funções para detecção de dispositivos e sistema:

- `command_exists(command)` - Verifica se comando existe
- `run_command(command, timeout)` - Executa comando shell
- `check_apt_packages(packages)` - Verifica pacotes APT instalados
- `probe_audio_setup()` - Deteta configuração de áudio
- `probe_device_setup(choice)` - Deteta SDR e requisitos
- `device_profile(choice)` - Perfil de config para tipo de device
- `normalize_device_choice(choice)` - Normaliza tipo de device

### 6. Rate Limiting

Para endpoints que precisam de rate limiting:

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@router.post("/scan/start")
@limiter.limit("10/minute")
async def scan_start(...):
    # Implementation
    pass
```

**Note:** O limiter deve ser adicionado ao `app.state.limiter` no main.py.

## Próximos Passos

### Fase 1: Completar Módulos API Principais

1. **`api/scan.py`** - Endpoints de scan:
   - POST `/api/scan/start` (com rate limit)
   - POST `/api/scan/stop`
   - GET `/api/scan/status`
   - GET `/api/scans`

2. **`api/events.py`** - Endpoints de eventos:
   - GET `/api/events` (com rate limit, suporta CSV)
   - GET `/api/events/count`
   - GET `/api/events/stats`
   - POST `/api/admin/events/purge-invalid`
   - GET `/api/propagation/summary`

3. **`api/decoders.py`** - Controle de decoders:
   - GET `/api/decoders/status`
   - Endpoints FT internal (status, start, stop)
   - Endpoints FT external (status, start, stop, modes)
   - POST `/api/decoders/events`
   - POST `/api/decoders/aprs`
   - POST `/api/decoders/cw`
   - POST `/api/decoders/ssb`

4. **`api/exports.py`** - Gestão de exports:
   - GET `/api/export` (legacy)
   - POST `/api/exports`
   - GET `/api/exports`
   - GET `/api/exports/{export_id}`

5. **`api/settings.py`** - Configurações:
   - GET `/api/settings`
   - POST `/api/settings`
   - POST `/api/settings/reset-defaults`

6. **`api/admin.py`** - Operações admin:
   - POST `/api/admin/reset-all-config`
   - POST `/api/admin/device/setup`
   - POST `/api/admin/config/test`

7. **`api/logs.py`** - Logs:
   - GET `/api/logs`

### Fase 2: Módulos WebSocket

1. **`websocket/logs.py`** - `/ws/logs`
2. **`websocket/events.py`** - `/ws/events`
3. **`websocket/spectrum.py`** - `/ws/spectrum`
4. **`websocket/status.py`** - `/ws/status`

### Fase 3: Refactoring do main.py

Transformar `main.py` em orchestrator simples:

```python
from fastapi import FastAPI
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Import routers
from app.api import health, scan, events, decoders, exports, settings, admin, logs

app = FastAPI(title="4ham Spectrum Analysis")

# Rate limiting
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS middleware (existing code)
# Security headers middleware (existing code)

# Include routers
app.include_router(health.router)
app.include_router(scan.router)
app.include_router(events.router)
app.include_router(decoders.router)
app.include_router(exports.router)
app.include_router(settings.router)
app.include_router(admin.router)
app.include_router(logs.router)

# Static files
app.mount("/", StaticFiles(...), name="static")

# Startup/shutdown handlers
@app.on_event("startup")
async def startup():
    # Initialization code
    pass

@app.on_event("shutdown")
async def shutdown():
    # Cleanup code
    pass
```

### Fase 4: Testes e Validação

1. Executar suite de testes existente
2. Verificar todos os endpoints funcionam
3. Testar WebSockets
4. Validar rate limiting
5. Verificar autenticação

## Benefícios da Refatoração

- **Manutenibilidade**: Código organizado em módulos lógicos
- **Testabilidade**: Módulos pequenos são mais fáceis de testar
- **Legibilidade**: Código mais fácil de entender e navegar
- **Reutilização**: Funções compartilhadas centralizadas
- **Escalabilidade**: Fácil adicionar novos endpoints
- **Type Safety**: Type hints completos em todos os módulos
- **Documentação**: Docstrings descritivas em todas as funções

## Notas de Implementação

1. **Imports Circulares**: Evitar importando apenas o necessário
2. **Estado Mutável**: Usar `state.*` para acesso a estado global
3. **Async/Await**: Manter endpoints async quando necessário
4. **Error Handling**: Usar HTTPException para erros de API
5. **Logging**: Usar `helpers.log()` para logs consistentes
6. **Rate Limiting**: Aplicar aos endpoints apropriados
7. **Autenticação**: Usar `Depends(verify_basic_auth)` consistentemente

##Status Atual

- ✅ Estrutura de diretórios criada
- ✅ `dependencies/state.py` - Estado global centralizado
- ✅ `dependencies/auth.py` - Dependencies de autenticação
- ✅ `dependencies/utils.py` - Utilitários de sistema
- ✅ `dependencies/helpers.py` - Funções auxiliares de API
- ✅ **Fase 1 COMPLETA: Todos os módulos API (8/8)**
  - ✅ `api/health.py` - 4 endpoints
  - ✅ `api/events.py` - 5 endpoints  
  - ✅ `api/scan.py` - 4 endpoints
  - ✅ `api/settings.py` - 3 endpoints
  - ✅ `api/logs.py` - 1 endpoint
  - ✅ `api/exports.py` - 4 endpoints
  - ✅ `api/admin.py` - 3 endpoints
  - ✅ `api/decoders.py` - 13 endpoints
- ✅ **Fase 2 COMPLETA: Todos os módulos WebSocket (4/4)**
  - ✅ `websocket/logs.py` - /ws/logs (log streaming)
  - ✅ `websocket/events.py` - /ws/events (occupancy detection pipeline)
  - ✅ `websocket/spectrum.py` - /ws/spectrum (FFT waterfall + markers)
  - ✅ `websocket/status.py` - /ws/status (system metrics)
- ✅ **Fase 3 COMPLETA: Refactoring do main.py**
  - ✅ Novo main.py modular: 127 linhas (94.5% redução vs 2299 linhas)
  - ✅ Todos os routers incluídos (8 API + 4 WebSocket)
  - ✅ Backup criado: `main_legacy.py`
  - ✅ Mantido apenas: FastAPI setup, middleware, router includes, static files
- ⏳ Fase 4: Testes e validação

**Total de Endpoints REST Refatorados: 37/37 ✅**
**Total de WebSockets Refatorados: 4/4 ✅**
**Redução de Linhas no main.py: 94.5% (2299 → 127 linhas) ✅**

## Exemplo de Migração

**Antes (main.py):**
```python
@app.get("/api/health")
def health(request: Request):
    _enforce_auth(request)
    return {
        "status": "ok",
        "version": "0.2.0",
        "devices": len(_controller.list_devices())
    }
```

**Depois (api/health.py):**
```python
@router.get("/health")
def health(_: None = Depends(verify_basic_auth)) -> Dict:
    """Health check endpoint."""
    return {
        "status": "ok",
        "version": "0.2.0",
        "devices": len(state.controller.list_devices())
    }
```

**Mudanças:**
1. `@app` → `@router`
2. `request: Request` + `_enforce_auth(request)` → `Depends(verify_basic_auth)`
3. `_controller` → `state.controller`
4. Adicionado type hint de retorno
5. Adicionado docstring

---

## Sumário Final do Refactoring

### Métricas de Transformação

**Before (Monolithic):**
- `main.py`: 2299 linhas
- Todos endpoints, WebSockets, helpers, e estado num único arquivo
- Difícil de navegar, testar e manter

**After (Modular):**
- `main.py`: 127 linhas (**94.5% de redução**)
- 8 módulos API: ~2400 linhas
- 4 módulos WebSocket: ~1036 linhas
- 4 módulos dependencies: ~1200 linhas
- **Total: ~4600 linhas organizadas em 17 módulos**

### Arquitetura Final

```
backend/app/
├── main.py (127 linhas)           # Entry point - router orchestration
├── api/ (8 módulos, 37 endpoints)
│   ├── health.py      (80 linhas)    # 4 endpoints
│   ├── events.py      (185 linhas)   # 5 endpoints
│   ├── scan.py        (195 linhas)   # 4 endpoints
│   ├── settings.py    (124 linhas)   # 3 endpoints
│   ├── logs.py        (33 linhas)    # 1 endpoint
│   ├── exports.py     (178 linhas)   # 4 endpoints
│   ├── admin.py       (199 linhas)   # 3 endpoints
│   └── decoders.py    (661 linhas)   # 13 endpoints
├── websocket/ (4 módulos, 4 handlers)
│   ├── logs.py        (69 linhas)    # /ws/logs
│   ├── events.py      (248 linhas)   # /ws/events
│   ├── spectrum.py    (367 linhas)   # /ws/spectrum
│   └── status.py      (129 linhas)   # /ws/status
└── dependencies/ (4 módulos)
    ├── state.py       (340 linhas)   # Global state
    ├── auth.py        (115 linhas)   # Auth dependencies
    ├── utils.py       (305 linhas)   # System utilities
    └── helpers.py     (490 linhas)   # API helpers
```

### Conquistas

✅ **Modularidade**: 17 módulos especializados vs 1 monolito
✅ **Type Safety**: Type hints completos em todos os módulos
✅ **Documentação**: Docstrings detalhadas em todas as funções
✅ **Padrões**: APIRouter + dependency injection consistentes
✅ **Segurança**: Rate limiting + autenticação unificada
✅ **Testabilidade**: Módulos pequenos e isolados
✅ **Manutenibilidade**: Código organizado por domínio

### Fases Completadas

1. ✅ **Fase 1**: 8 módulos API (37 REST endpoints)
2. ✅ **Fase 2**: 4 módulos WebSocket (4 handlers)
3. ✅ **Fase 3**: Refactoring do main.py (94.5% redução)

### Próxima Fase: Validação

**Fase 4: Testes e Validação**

1. **Testes Unitários**
   - Validar cada módulo API isoladamente
   - Testar helpers e utilities
   - Mock de dependencies onde necessário

2. **Testes de Integração**
   - Validar fluxos completos de endpoints
   - Testar WebSocket connections
   - Verificar autenticação end-to-end

3. **Testes de Performance**
   - Rate limiting funcional
   - WebSocket frame rates
   - Compression vs uncompressed performance

4. **Validação Manual**
   - Testar frontend com novo backend
   - Verificar todos os workflows
   - Confirmar compatibilidade

5. **Documentação**
   - Atualizar README com nova estrutura
   - Documentar módulos no /api/docs
   - Guias de contribuição

### Comandos Úteis

```bash
# Validar sintaxe de todos os módulos
python3 -m py_compile backend/app/**/*.py

# Executar testes
cd backend && pytest tests/

# Iniciar servidor de desenvolvimento
cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8002

# Verificar imports
python3 -c "from app.main import app; print(len(app.routes))"

# Ver documentação interativa
# http://localhost:8002/api/docs
```

### Lições Aprendidas

1. **Dependency Injection**: FastAPI Depends() simplifica autenticação
2. **Estado Centralizado**: Módulo `state.py` evita imports circulares
3. **Type Hints**: Facilitam manutenção e catching de bugs
4. **Small Modules**: Módulos < 400 linhas são mais fáceis de entender
5. **Docstrings**: Documentação inline ajuda novos desenvolvedores
6. **Rate Limiting**: Aplicar seletivamente em endpoints críticos
7. **WebSocket Auth**: Headers funcionam bem com Basic Auth

---

**Projeto:** 4ham Spectrum Analysis  
**Versão:** 2.0.0 (Modular Architecture)  
**Data:** 2026-02-23  
**Autor:** CT7BFV (Octávio Filipe Gonçalves)  
**Licença:** GNU AGPL-3.0
