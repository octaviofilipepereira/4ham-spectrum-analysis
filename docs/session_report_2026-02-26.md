<!--
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
Date: 2026-02-26
-->

# Relatório de Sessão — 4ham Spectrum Analysis
**Data:** 2026-02-24 a 2026-02-26  
**Callsign:** CT7BFV  
**Âmbito:** Search Modal, Propagation Card, 3D Propagation Globe

---

## Resumo Executivo

Em três dias de desenvolvimento foram implementadas três funcionalidades major:

1. **Search Modal** — pesquisa de eventos por callsign, modo, banda e SNR mínimo, com pré-visualização inline dos resultados.
2. **Propagation Card** — novo cartão no dashboard que mostra o score de propagação atual com cor dinâmica por estado.
3. **3D Propagation Globe** — mapa interativo tridimensional que representa os contactos decodificados sobre um globo D3 orthographic com drag-to-rotate, scroll-to-zoom, botões de controlo e modal fullscreen.

---

## 1. Search Modal (Events)

### Commits
| SHA | Descrição |
|-----|-----------|
| `e7829aa` | feat: move Events Search de sidebar para modal |
| `29ae8fb` | fix: aplicar tema app-modal ao modal |
| `4854663` | fix: mover modal para fora de `</main>` — corrigir z-index |
| `a8bdf63` | fix: query DB API em vez de cache em memória |
| `33e2ccb` | fix: LIKE partial match para mode+callsign; AbortController |
| `bb7699b` | fix: pular occupancy_events quando callsign filter ativo |
| `b214961` | fix: aplicar mode filter à query occupancy_events |
| `531b7ea` | fix: texto branco em inputs modal dark |
| `2bd72af` | fix: reset AbortController após erro para evitar lockup |
| `0d8d517` | feat: filtrar occupancy events — só mostra callsign events |
| `f417132` | fix: rate limit 30→300/min; cache bust |
| `723b107` | style: layout 2x2 grid, campos e labels maiores |
| `8c86001` | feat: rebuild modal — campos Callsign/Mode/Band/SNR-min + SNR por resultado |
| `deda699` | style: botão Search Events maior, letra branca |

### Ficheiros modificados
- `frontend/index.html` — estrutura do modal (`#eventsSearchModal`)
- `frontend/app.js` — lógica de search: fetch, AbortController, renderização de resultados
- `backend/app/api/events.py` — rate limit ajustado

### Comportamento final
- Botão **Search Events** na barra de ferramentas abre um `bootstrap.Modal` fullscreen estilizado a dark.
- Campos: **Callsign** (LIKE `%x%`), **Mode** (dropdown), **Band** (dropdown), **Min SNR** (número).
- Pesquisa via `GET /api/events?callsign=&mode=&band=&min_snr=&limit=50`.
- `AbortController` cancela fetches anteriores em voo para evitar race conditions.
- Resultados mostram: callsign, mode, band, SNR (com sinal `+`/`−`), timestamp.
- Occupancy events (sem callsign) são excluídos dos resultados.

---

## 2. Propagation Card

### Commits
| SHA | Descrição |
|-----|-----------|
| `79987e1` | style: Propagation card ao lado direito de Events |
| `af5985d` | fix: alinhar `build_propagation_summary` response com frontend |
| `34e4697` | style: colorir score por estado (Poor=red / Fair=yellow / Good\|Excellent=green) |

### Ficheiros modificados
- `frontend/index.html` — Propagation card movido para `col-12 col-lg-6` ao lado de Events
- `backend/app/dependencies/helpers.py` — `build_propagation_summary()` corrigida

### Bug corrigido — `build_propagation_summary`
A função retornava um dict plano (`overall_score`, `total_events`) mas o frontend
esperava a estrutura aninhada `data.overall.score` e `data.event_count`.

**Antes:**
```python
return {
    "overall_score": score,
    "condition": condition,
    "total_events": count,
    ...
}
```

**Depois:**
```python
return {
    "overall": {"score": score, "condition": condition},
    "event_count": count,
    "window_minutes": window_minutes,
    "bands": {...},
}
```

### Coloração dinâmica do score (app.js)
```javascript
const state = prop.overall?.condition ?? "Unknown";
const colorClass =
  state === "Excellent" || state === "Good" ? "text-success fw-semibold" :
  state === "Fair"                          ? "text-warning fw-semibold" :
  state === "Poor"                          ? "text-danger fw-semibold"  :
                                              "text-secondary";
```

---

## 3. 3D Propagation Globe

### Commits em ordem cronológica
| SHA | Descrição |
|-----|-----------|
| `82adb73` | feat: DXCC coords database (346 entidades, 4528 prefixos) de cty.dat |
| `c42621b` | feat: mapa de propagação D3 (initial: azimuthal equidistant, arcos, tooltips, assets offline) |
| `01107de` | feat: zoom/pan D3, botões +/−/reset, modal fullscreen |
| `8ef21f7` | feat: globo 3D orthographic — drag-to-rotate, scroll-zoom, gradiente radial |

### 3.1 Base de dados DXCC — `prefixes/dxcc_coords.json`

**Fonte:** ficheiro `cty.dat` de AD1C (<https://www.country-files.com/>), versão 25 Feb 2026.

**Script de geração:** `scripts/build_dxcc_coords.py`  
- Parseia `prefixes/cty.dat` (99 KB, ~346 entidades, 4528 prefixos)  
- Extrai por entidade: nome, continente, zona CQ, coordenadas (lat/lon), callsign
  representativo  
- Expande todos os prefixos alternativos por entidade para um índice plano  
- Serializa para `prefixes/dxcc_coords.json`

**Estrutura de `dxcc_coords.json`:**
```json
{
  "entities": {
    "CT": {
      "name": "Portugal",
      "continent": "EU",
      "cq_zone": 14,
      "lat": 39.5,
      "lon": -8.0,
      "callsign": "CT1"
    }
  },
  "prefix_index": {
    "CT": "CT",
    "CT1": "CT",
    "CT2": "CT",
    "W": "K",
    "DL": "DL",
    ...
  }
}
```

### 3.2 Backend — helpers.py

Ficheiro: `backend/app/dependencies/helpers.py`

**Funções adicionadas:**

```python
_DXCC_PATH = Path(__file__).resolve().parents[3] / "prefixes" / "dxcc_coords.json"

def _load_dxcc_index() -> dict:
    """Carrega e cacheia o índice DXCC. Retorna {} se ficheiro não existir."""

def callsign_to_dxcc(callsign: str) -> dict | None:
    """
    Converte um callsign para entidade DXCC por longest-prefix-match.
    Exemplo: 'DL5XYZ' → {name:'Germany', continent:'EU', lat:51.0, lon:10.0, ...}
    Retorna None se não encontrado.
    """

def maidenhead_to_latlon(grid: str) -> tuple[float, float] | None:
    """
    Converte locator Maidenhead (4 ou 6 caracteres) para (lat, lon).
    Exemplo: 'IN50' → (40.5, -8.0)
    """

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distância em km entre dois pontos via fórmula haversine."""
```

**Algoritmo de longest-prefix-match:**
```python
def callsign_to_dxcc(callsign):
    index = _load_dxcc_index()["prefix_index"]
    cs = callsign.upper()
    # Tenta prefixos de tamanho decrescente (máx 6 chars)
    for length in range(min(len(cs), 6), 0, -1):
        prefix = cs[:length]
        if prefix in index:
            entity_id = index[prefix]
            return _load_dxcc_index()["entities"].get(entity_id)
    return None
```

### 3.3 Backend — `GET /api/map/contacts`

Ficheiro: `backend/app/api/map.py`

```
GET /api/map/contacts?window_minutes=60&limit=500
Authorization: Basic <base64>
```

**Lógica:**
1. Lê a config da estação (`station_callsign`, `station_locator`) de `config/`.
2. Converte o locator Maidenhead da estação para (lat, lon) via `maidenhead_to_latlon`.
3. Consulta a DB: eventos recentes com callsign não nulo no janela `window_minutes`.
4. Para cada evento — resolve callsign para DXCC via `callsign_to_dxcc`.
5. Calcula `distance_km` via `haversine_km`.
6. Retorna JSON estruturado.

**Resposta:**
```json
{
  "status": "ok",
  "window_minutes": 60,
  "station": {
    "callsign": "CT7BFV",
    "locator": "IN50SN",
    "lat": 40.208,
    "lon": -8.396
  },
  "contact_count": 90,
  "contacts": [
    {
      "callsign": "DL5XYZ",
      "lat": 51.0,
      "lon": 10.0,
      "country": "Germany",
      "continent": "EU",
      "cq_zone": 14,
      "band": "20m",
      "mode": "FT8",
      "snr_db": -12,
      "distance_km": 2034,
      "timestamp": "2026-02-26T14:32:00Z"
    }
  ]
}
```

Router registado em `backend/app/main.py`:
```python
from app.api import map as map_api
app.include_router(map_api.router, prefix="/api/map", tags=["map"])
```

### 3.4 Frontend — Assets offline (sem CDN)

| Ficheiro | Tamanho | Fonte |
|----------|---------|-------|
| `frontend/lib/d3.min.js` | 274 KB | D3.js v7.9.0 UMD build |
| `frontend/lib/topojson.min.js` | 21 KB | TopoJSON Client 3.0.2 |
| `frontend/lib/countries-110m.json` | 106 KB | Natural Earth 110m (TopoJSON) |

Todos os assets são servidos localmente pelo backend FastAPI — **sem dependência de CDN externo**.

### 3.5 Frontend — `frontend/map.js` (347 linhas)

#### Projeção 3D — `d3.geoOrthographic`

```javascript
const proj = d3.geoOrthographic()
  .rotate([-sLon, -sLat])          // centrado na estação
  .scale(Math.min(W, H) * 0.44)
  .translate([W / 2, H / 2])
  .clipAngle(90);                   // só hemisfério visível
```

#### Arcos de grande-círculo

D3 com projeção orthographic e `clipAngle(90)` processa o clipping automaticamente
via GeoJSON `LineString` — não é necessário interpolar pontos manualmente:

```javascript
arcG.append("path")
  .datum({ type: "LineString", coordinates: [[sLon, sLat], [c.lon, c.lat]] })
  .attr("d", path);   // path = d3.geoPath().projection(proj)
```

#### Drag-to-rotate

```javascript
svg.call(
  d3.drag()
    .on("drag", (event) => {
      const [rx, ry, rz] = proj.rotate();
      proj.rotate([rx + event.dx * 0.5, ry - event.dy * 0.5, rz]);
      redraw();
    })
);
```

#### Scroll-to-zoom

```javascript
svg.node().addEventListener("wheel", (event) => {
  event.preventDefault();
  const factor = event.deltaY < 0 ? 1.15 : 1 / 1.15;
  kScale = Math.max(0.25, Math.min(12, kScale * factor));
  proj.scale(baseScale * kScale);
  redraw();
}, { passive: false });
```

#### Gradiente radial — efeito de profundidade oceânica

```javascript
const grad = defs.append("radialGradient")
  .attr("gradientUnits", "userSpaceOnUse")
  .attr("cx", W / 2).attr("cy", H / 2).attr("r", baseScale);
grad.append("stop").attr("offset", "0%").attr("stop-color", "#0e3266");
grad.append("stop").attr("offset", "70%").attr("stop-color", "#0a1e3d");
grad.append("stop").attr("offset", "100%").attr("stop-color", "#050d1a");
```

#### Visibilidade dos dots — só hemisfério frontal

```javascript
const center = proj.invert([W / 2, H / 2]);
contacts.forEach((c) => {
  // Oculta pontos no hemisfério oposto
  if (d3.geoDistance([c.lon, c.lat], center) >= Math.PI / 2) return;
  // Renderiza dot...
});
```

#### Controlos overlay

| Botão | Ação |
|-------|------|
| `+` | `proj.scale(baseScale * kScale * 1.6)` |
| `−` | `proj.scale(baseScale * kScale / 1.6)` |
| `⌂` | `proj.rotate([-sLon, -sLat])` + reset scale |
| `⛶` | Abre `#mapFullscreenModal` via `bootstrap.Modal.getOrCreateInstance` |
| Double-click | Reset rotação + escala |

### 3.6 Frontend — Modal Fullscreen

Adicionado em `frontend/index.html` antes do primeiro modal de eventos:

```html
<div class="modal fade" id="mapFullscreenModal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog modal-fullscreen">
    <div class="modal-content bg-dark">
      <div class="modal-header border-secondary py-2">
        <h5 class="modal-title text-light">Propagation Map</h5>
        <button type="button" class="btn-close btn-close-white"
                data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body p-2" style="overflow:hidden;">
        <div id="propagationMapModal" style="width:100%;height:100%;"></div>
      </div>
    </div>
  </div>
</div>
```

Ao abrir (`shown.bs.modal`), `PropMap.renderModal()` é invocado:
1. Renderiza imediatamente com `_lastData` (cache) para resposta instantânea.
2. Em background, faz fetch atualizado via `/api/map/contacts` e re-renderiza.

---

## 4. Dependências

### 4.1 Backend Python

| Pacote | Versão | Uso |
|--------|--------|-----|
| `fastapi` | latest | Framework API + routing |
| `uvicorn[standard]` | latest | ASGI server (WebSockets, lifespan) |
| `numpy` | latest | DSP — FFT, resample polyphase puro |
| `pyyaml` | latest | Parse de `scan_config.yaml` e region profiles |
| `jsonschema` | latest | Validação de config contra schemas JSON |
| `python-dotenv` | latest | Variáveis de ambiente (`.env`) |
| `bcrypt` | latest | Hash de palavras-passe para autenticação Basic |
| `slowapi` | latest | Rate limiting com `Limiter` (baseado em Starlette) |
| `psutil` | latest | Métricas de sistema (CPU, memória) em `/api/health` |
| `pytest` | latest | Testes automatizados |
| `pytest-asyncio` | latest | Testes de coroutines FastAPI |

**Dependências removidas (fev 2026):**
- `scipy` — substituída por `_resample_poly_np` em NumPy puro
- `aiosqlite` — nunca foi importada; SQLite acedido via `sqlite3` stdlib

### 4.2 Frontend JavaScript (todos os assets locais)

| Biblioteca | Versão | Ficheiro | Tamanho | Uso |
|------------|--------|----------|---------|-----|
| D3.js | 7.9.0 | `frontend/lib/d3.min.js` | 274 KB | Projeção geo, drag, gradientes SVG |
| TopoJSON Client | 3.0.2 | `frontend/lib/topojson.min.js` | 21 KB | Deserialização de topologia vectorial |
| Bootstrap | 5.3.3 | CDN | — | Layout, modais, botões |
| Natural Earth 110m | — | `frontend/lib/countries-110m.json` | 106 KB | Geometria dos países (TopoJSON) |

> Todos os assets D3/TopoJSON/dados geográficos são servidos **localmente** pelo
> backend. O globo funciona sem acesso à internet.

### 4.3 Dados de referência

| Ficheiro | Fonte | Conteúdo |
|----------|-------|---------|
| `prefixes/cty.dat` | AD1C — <https://www.country-files.com/> | 346 entidades DXCC, 4528 prefixos, cty v25-Feb-2026 |
| `prefixes/dxcc_coords.json` | Gerado por `scripts/build_dxcc_coords.py` | Index de entidades + index de prefixos |
| `prefixes/iaru_region1_prefixes.json` | Pré-existente | Lista de prefixos IARU Região 1 |
| `frontend/lib/countries-110m.json` | Natural Earth / topojson-world-atlas | Geometria 110m para renderização |

---

## 5. Arquitectura do fluxo de dados do globo

```
SDR → DSP → FT8/FT4 decoder → DB (events.sqlite)
                                        │
                              GET /api/map/contacts
                                        │
                              helpers.callsign_to_dxcc()
                              helpers.haversine_km()
                                        │
                              JSON {contacts: [{lat,lon,band,snr,...}]}
                                        │
                              frontend/map.js
                              drawGlobe() → d3.geoOrthographic
                              GeoJSON LineString arcs (auto-clipped D3)
                              dots → geoDistance visibility check
                              drag handler → proj.rotate()
                              wheel handler → proj.scale()
```

---

## 6. Paleta de cores das bandas

| Banda | Cor hex | Uso |
|-------|---------|-----|
| 160m | `#cc2200` | Vermelho escuro |
| 80m  | `#e0507a` | Rosa |
| 40m  | `#f5a623` | Laranja |
| 20m  | `#3b82f6` | Azul |
| 17m  | `#22c55e` | Verde |
| 15m  | `#a855f7` | Roxo |
| 12m  | `#06b6d4` | Ciano |
| 10m  | `#ef4444` | Vermelho |
| 6m   | `#f97316` | Laranja brilhante |
| 2m   | `#84cc16` | Verde-lima |
| 70cm | `#ec4899` | Cor-de-rosa |

---

## 7. Testes realizados (manual)

| Cenário | Resultado |
|---------|-----------|
| Globo carrega ao arrancar a página | ✅ |
| Drag roda o globo suavemente | ✅ |
| Scroll aumenta/diminui zoom | ✅ |
| Botão `+` faz zoom in | ✅ |
| Botão `−` faz zoom out | ✅ |
| Botão `⌂` re-centra na estação | ✅ |
| Double-click re-centra | ✅ |
| Dots desaparecem no hemisfério oposto | ✅ |
| Tooltip aparece ao passar o rato sobre dot | ✅ |
| Botão `⛶` abre modal fullscreen | ✅ |
| Modal renderiza globo em janela completa | ✅ |
| Modal actualiza dados em background | ✅ |
| Refresh automático a cada 60 s | ✅ |
| Funciona offline (sem CDN) | ✅ |
| Gradiente radial visível no oceano | ✅ |
| Legend de bandas na parte inferior esquerda | ✅ |
| Contador "N contacts · X min" no canto | ✅ |
| Score de propagação colorido por estado | ✅ |
| Search Events — partial match callsign | ✅ |
| Search Events — AbortController cancela fetch antigo | ✅ |

---

## 8. Ficheiros criados/modificados nesta sessão

### Novos
| Ficheiro | Descrição |
|----------|-----------|
| `prefixes/cty.dat` | Ficheiro fonte DXCC (AD1C, 99 KB) |
| `prefixes/dxcc_coords.json` | Base de dados DXCC gerada (346 entidades) |
| `scripts/build_dxcc_coords.py` | Script de geração do JSON a partir de cty.dat |
| `backend/app/api/map.py` | Endpoint `GET /api/map/contacts` |
| `frontend/lib/d3.min.js` | D3.js v7 UMD (274 KB, local) |
| `frontend/lib/topojson.min.js` | TopoJSON 3.0.2 (21 KB, local) |
| `frontend/lib/countries-110m.json` | Natural Earth 110m (106 KB, local) |
| `frontend/map.js` | Módulo do globo 3D (347 linhas) |

### Modificados
| Ficheiro | Alterações |
|----------|------------|
| `backend/app/dependencies/helpers.py` | +`callsign_to_dxcc`, `maidenhead_to_latlon`, `haversine_km`, `_load_dxcc_index` |
| `backend/app/main.py` | +import e registo do router `map_api` |
| `frontend/index.html` | +`#propagationMap` div, +`#mapFullscreenModal`, +script tags d3/topojson/map.js |
| `frontend/app.js` | +coloração do score de propagação, +lógica search modal com AbortController |
