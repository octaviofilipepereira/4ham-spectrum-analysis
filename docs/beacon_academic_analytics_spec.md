<!--
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0
-->

# Beacon Analysis - Academic Analytics Spec

## 1. Objetivo

Definir a especificação técnica da nova vista `Beacon Analysis - NCDXF/IARU`
para a Academic Analytics local e para a Academic Analytics externa.

O objetivo desta vista é transformar os dados do modo Beacon, hoje centrados
na operação em tempo quase-real, numa superfície de análise histórica,
exportação e correlação com contexto ionosférico NOAA SWPC.

Esta especificação cobre:

- a vista local em `frontend/4ham_academic_analytics.html`
- a vista externa em `external_academic_analytics/index.html`
- o contrato dos endpoints consumidos pela nova vista
- a replicação dos dados Beacon para o receiver PHP/MySQL externo
- o schema de `mirror_beacon_observations`
- as limitações explícitas impostas pelo modelo externo

## 2. Decisão de Produto

### 2.1 Nova vista

O Academic Analytics passa a ter **três** vistas de topo:

- `HF Propagation & Digital Mode Analysis`
- `APRS Network Topology & Coverage`
- `Beacon Analysis - NCDXF/IARU`

### 2.2 Natureza da vista Beacon

A vista Beacon é **analítica e read-only** tanto no dashboard local como no
externo.

Ficam explicitamente fora da vista Beacon Academic Analytics:

- controlo do scheduler Beacon
- live matrix do slot actual
- WebSocket do modo Beacon
- indicação operacional do estado actual do scan slot-a-slot

Isto é obrigatório porque o espelho externo:

- nao tem WebSocket
- nao tem controlo SDR
- trabalha em modo push com staleness >= `push_interval_seconds`
- expõe apenas superficies publicas e read-only

### 2.3 Princípio de paridade local/externo

A Beacon TAB deve apresentar **a mesma estrutura funcional** no local e no
externo. A diferença permitida e apenas a origem dos dados:

- local: FastAPI + SQLite + dados Beacon nativos
- externo: PHP/MySQL + eventos Beacon espelhados + snapshots publicos

## 3. Escopo Funcional da V1

### 3.1 Obrigatório

1. Reproduzir a tabela `Recent activity - last 12 h` com a mesma semântica da
   UI Beacon actual.
2. Permitir drill-down por célula da tabela histórica.
3. Disponibilizar exportação dos dados Beacon recolhidos.
4. Apresentar leitura de propagação Beacon por banda + score global.
5. Apresentar contexto NOAA SWPC actual.
6. Apresentar um `nowcast` Beacon + NOAA, não um forecast multi-hora clássico.
7. Mostrar freshness / staleness da vista, em especial no espelho externo.

### 3.2 Explicitamente adiado

- previsão NOAA multi-hora nativa com ingestão de produtos forecast adicionais
- animações live por slot
- replay do ciclo de 3 minutos
- exportação server-side para ficheiros persistidos no receiver externo
- reimplementação em PHP de lógica que já exista de forma canónica em Python,
  salvo quando o receiver externo precisar de a calcular localmente por falta
  de snapshot apropriado

## 4. Restrições Arquitecturais

### 4.1 Local

O backend local já dispõe de blocos reutilizáveis:

- `GET /api/beacons/heatmap`
- `GET /api/beacons/observations`
- `GET /api/beacons/propagation_summary`
- `GET /api/map/ionospheric`

A nova Beacon TAB nao deve duplicar esta lógica no frontend.

### 4.2 Externo

O espelho externo actual tem estas restrições:

- o dashboard e uma cópia estática de `frontend/4ham_academic_analytics.html`
- `api/events`, `api/analytics/academic` e `api/map/contacts` no receiver já
  consultam MySQL directamente
- `api/map/ionospheric` continua snapshot-backed
- nao existe hoje qualquer tabela `mirror_beacon_observations`
- o transporte actual usa apenas `callsign_events` e `occupancy_events`
- o payload do mirror usa hoje um **único watermark escalar**, o que nao é
  suficiente para um terceiro stream Beacon

### 4.3 Consequência obrigatória

Para Beacon Analytics externa, o espelho tem de evoluir de:

- `single scalar watermark`

para:

- `per-stream cursors`

Caso contrário, uma tabela com maior volume poderia avançar o cursor e provocar
salto de linhas noutra tabela.

## 5. Arquitectura Alvo

## 5.1 Vista local

```text
SQLite beacon_observations
  -> FastAPI /api/beacons/analytics/overview
  -> FastAPI /api/beacons/observations
  -> frontend/4ham_academic_analytics.html (Beacon TAB)
```

## 5.2 Vista externa

```text
SQLite beacon_observations
  -> external_mirrors payload.events.beacon_observations[]
  -> external_academic_analytics/ingest.php
  -> MySQL mirror_beacon_observations
  -> external_academic_analytics/api/beacons/*.php
  -> external_academic_analytics/index.html (Beacon TAB)
```

## 5.3 Fonte NOAA SWPC

O contexto ionosférico permanece a vir do modelo actual baseado em:

- snapshot/local `api/map/ionospheric`
- `Kp`
- `SFI`
- `foF2` estimado
- `MUF` / `skip` por banda

Na V1, a Beacon TAB usa isto como **contexto actual + nowcast**. Nao existe,
na V1, previsão histórica ou forecast multitemporal persistido.

## 6. Endpoint Contract

## 6.1 Endpoint principal da nova vista

### `GET /api/beacons/analytics/overview`

Endpoint novo, comum ao local e ao externo. Serve o payload principal da
Beacon TAB e reduz o número de fetches do frontend.

### Query params

| Param | Tipo | Default | Limites | Notas |
|---|---|---:|---|---|
| `heatmap_hours` | float | `12` | `1..72` | janela da tabela histórica |
| `propagation_window_minutes` | int | `180` | `30..1440` | janela para score Beacon |
| `forecast_window_minutes` | int | `180` | `30..360` | horizonte do nowcast |
| `mirror` | string | `""` | externo only | selecção de mirror no receiver |

### Resposta JSON

```json
{
  "status": "ok",
  "kind": "beacon_analytics",
  "source_kind": "live",
  "generated_at_utc": "2026-05-05T12:00:00Z",
  "snapshot_captured_at_utc": null,
  "staleness_seconds": 0,
  "windows": {
    "heatmap_hours": 12,
    "propagation_window_minutes": 180,
    "forecast_window_minutes": 180
  },
  "freshness": {
    "label": "fresh",
    "push_interval_seconds": null,
    "warning": null
  },
  "kpis": {
    "monitored_slots": 540,
    "detected_slots": 184,
    "detected_beacons": 14,
    "best_band": {
      "band": "20m",
      "score": 71.2,
      "state": "Excellent"
    },
    "global_score": 63.4,
    "global_state": "Good"
  },
  "recent_activity": {
    "hours": 12,
    "bands": ["20m", "17m", "15m", "12m", "10m"],
    "beacons": ["4U1UN", "VE8AT", "W6WX"],
    "matrix": [[null]]
  },
  "propagation": {
    "window_minutes": 180,
    "overall": {
      "score": 63.4,
      "state": "Good"
    },
    "bands": []
  },
  "ionospheric": {
    "kp": 2.3,
    "kp_condition": "Unsettled",
    "sfi": 158.0,
    "fof2_estimated_mhz": 9.6,
    "source": "NOAA SWPC",
    "last_update": "2026-05-05T11:45:00Z",
    "bands": {}
  },
  "reading": {
    "state": "aligned",
    "confidence": "moderate",
    "summary": "20m/17m alinhadas com MUF actual; 10m abaixo do esperado.",
    "bands": [
      {
        "band": "20m",
        "observed_state": "Excellent",
        "expected_state": "Open",
        "agreement": "aligned"
      }
    ]
  },
  "forecast": {
    "kind": "nowcast",
    "valid_for_minutes": 180,
    "confidence": "moderate",
    "summary": "Boa probabilidade de manutenção em 20m/17m; 10m permanece marginal.",
    "bands": [
      {
        "band": "20m",
        "forecast_state": "Good",
        "confidence": "high"
      }
    ]
  }
}
```

### Regras de implementação

- **local**: compõe dados a partir de `get_beacon_heatmap`,
  `build_beacon_propagation_summary` e `ionospheric_cache.get_summary()`.
- **externo**: compõe dados a partir de `mirror_beacon_observations` +
  snapshot `api/map/ionospheric`.
- `source_kind` vale `live` no local e `mirror` no externo.
- `snapshot_captured_at_utc` e `staleness_seconds` são obrigatórios no externo.

## 6.2 Endpoint de drill-down e export base

### `GET /api/beacons/observations`

O endpoint existente mantém-se e passa a ser o **contrato base** para:

- drill-down por célula
- paginação da tabela detalhada
- exportação client-side CSV / XLSX / JSON

### Query params

| Param | Tipo | Default | Limites | Notas |
|---|---|---:|---|---|
| `limit` | int | `100` | `1..500` | no externo manter baixo por RAM |
| `offset` | int | `0` | `>=0` | paginação |
| `band` | string | `null` | `20m/17m/15m/12m/10m` | filtro |
| `callsign` | string | `null` | beacon callsign | filtro |
| `detected_only` | bool | `false` | - | filtro |
| `hours` | float | `null` | `0.1..72` | janela |
| `slot_start_utc` | ISO string | `null` | opcional | filtro exacto para drill-down futuro |
| `mirror` | string | `""` | externo only | selecção de mirror |

### Resposta JSON

```json
{
  "observations": [
    {
      "id": 1234,
      "slot_start_utc": "2026-05-05T11:40:00Z",
      "slot_index": 14,
      "beacon_callsign": "CS3B",
      "beacon_index": 14,
      "beacon_location": "Madeira, Portugal",
      "beacon_status": "active",
      "band_name": "20m",
      "freq_hz": 14100000,
      "detected": true,
      "id_confirmed": true,
      "id_confidence": 0.98,
      "drift_ms": 21.4,
      "dash_levels_detected": 4,
      "snr_db_100w": 17.2,
      "snr_db_10w": 10.4,
      "snr_db_1w": 6.3,
      "snr_db_100mw": 2.1,
      "recorded_at": "2026-05-05T11:40:09.512000+00:00"
    }
  ],
  "count": 100,
  "offset": 0,
  "limit": 100,
  "has_more": true
}
```

### Regras de implementação

- `has_more` deve ser acrescentado tanto no local como no externo.
- o receiver externo deve replicar o shape do endpoint local byte-for-byte,
  excepto headers específicos do snapshot, quando existirem.
- a exportação V1 nao cria ficheiros server-side; o frontend pagina este
  endpoint até esgotar resultados e gera CSV/XLSX/JSON no browser.

## 6.3 Endpoint de exportação dedicado

Nao é obrigatório na V1.

Decisão: **adiado**.

Justificação:

- no local o browser já tem `xlsx.mini.min.js`
- no externo convém evitar geração server-side de ficheiros em shared hosting
- a paginação do endpoint de observações é suficiente para export V1

## 6.4 Endpoints existentes reutilizados

Os seguintes endpoints mantêm-se válidos e podem ser usados internamente pelo
backend ou pelo frontend fora da nova TAB:

- `GET /api/beacons/heatmap`
- `GET /api/beacons/propagation_summary`
- `GET /api/map/ionospheric`

Mas a Beacon TAB V1 deve consumir principalmente:

- `GET /api/beacons/analytics/overview`
- `GET /api/beacons/observations`

## 7. Mirror Transport Contract

## 7.1 Novo stream de payload

O payload do mirror ganha um terceiro stream:

```json
{
  "events": {
    "callsign": [],
    "occupancy": [],
    "beacon_observations": []
  }
}
```

Cada item de `events.beacon_observations[]` deve conter:

```json
{
  "id": 1234,
  "slot_start_utc": "2026-05-05T11:40:00Z",
  "slot_index": 14,
  "beacon_callsign": "CS3B",
  "beacon_index": 14,
  "beacon_location": "Madeira, Portugal",
  "beacon_status": "active",
  "band_name": "20m",
  "freq_hz": 14100000,
  "detected": 1,
  "id_confirmed": 1,
  "id_confidence": 0.98,
  "drift_ms": 21.4,
  "dash_levels_detected": 4,
  "snr_db_100w": 17.2,
  "snr_db_10w": 10.4,
  "snr_db_1w": 6.3,
  "snr_db_100mw": 2.1,
  "recorded_at": "2026-05-05T11:40:09.512000+00:00"
}
```

## 7.2 Novo contrato de cursores

O contrato deixa de depender de `previous_watermark` / `new_watermark` como
cursor único.

Passa a existir:

```json
{
  "meta": {
    "previous_cursors": {
      "callsign_events": 1200,
      "occupancy_events": 48102,
      "beacon_observations": 0
    },
    "new_cursors": {
      "callsign_events": 1235,
      "occupancy_events": 48210,
      "beacon_observations": 912
    }
  }
}
```

### Regra de compatibilidade de rollout

Durante a migração pode manter-se:

- `previous_watermark`
- `new_watermark`

mas apenas como campos legacy para o par `callsign/occupancy`. O receiver novo
deve preferir sempre `previous_cursors` / `new_cursors` quando existirem.

## 7.3 Alteração necessária no repositório de mirrors local

O modelo local de `external_mirrors` precisa de armazenar cursores por stream.

### Alteração proposta

Adicionar coluna SQLite:

```sql
ALTER TABLE external_mirrors
ADD COLUMN last_push_cursors_json TEXT NULL;
```

### Semântica

`last_push_cursors_json` guarda:

```json
{
  "callsign_events": 1235,
  "occupancy_events": 48210,
  "beacon_observations": 912
}
```

### Regra de migração

Ao migrar mirrors existentes:

- `callsign_events` = `last_push_watermark`
- `occupancy_events` = `last_push_watermark`
- `beacon_observations` = `0`

## 8. Receiver MySQL Schema

## 8.1 Nova tabela `mirror_beacon_observations`

```sql
CREATE TABLE IF NOT EXISTS mirror_beacon_observations (
  pk                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  mirror_name          VARCHAR(64)     NOT NULL,
  source_id            BIGINT          NOT NULL,
  received_at          DATETIME        NOT NULL,
  slot_start_utc       VARCHAR(32)     NOT NULL,
  slot_index           TINYINT UNSIGNED NOT NULL,
  beacon_callsign      VARCHAR(16)     NOT NULL,
  beacon_index         TINYINT UNSIGNED NOT NULL,
  beacon_location      VARCHAR(128)    NULL,
  beacon_status        VARCHAR(16)     NULL,
  band_name            VARCHAR(8)      NOT NULL,
  freq_hz              BIGINT          NOT NULL,
  detected             TINYINT(1)      NOT NULL,
  id_confirmed         TINYINT(1)      NOT NULL,
  id_confidence        DOUBLE          NULL,
  drift_ms             DOUBLE          NULL,
  dash_levels_detected TINYINT UNSIGNED NOT NULL DEFAULT 0,
  snr_db_100w          DOUBLE          NULL,
  snr_db_10w           DOUBLE          NULL,
  snr_db_1w            DOUBLE          NULL,
  snr_db_100mw         DOUBLE          NULL,
  recorded_at_utc      VARCHAR(40)     NULL,
  PRIMARY KEY (pk),
  UNIQUE KEY uniq_mirror_source (mirror_name, source_id),
  KEY idx_mirror_slot (mirror_name, slot_start_utc),
  KEY idx_mirror_band_slot (mirror_name, band_name, slot_start_utc),
  KEY idx_mirror_beacon_slot (mirror_name, beacon_callsign, slot_start_utc),
  KEY idx_mirror_beacon_band_slot (mirror_name, beacon_callsign, band_name, slot_start_utc)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

## 8.2 Justificação do schema

- `source_id` replica o `id` SQLite upstream e garante idempotência.
- `slot_start_utc` fica em `VARCHAR(32)` para manter paridade com o modelo já
  usado em `mirror_callsign_events.timestamp`.
- `received_at` fica em `DATETIME` porque é metadado do receiver.
- índices orientados a janelas temporais e filtros por beacon/banda.

## 8.3 Ingest no receiver

`external_academic_analytics/ingest.php` deve acrescentar:

- leitura de `events.beacon_observations`
- `INSERT IGNORE` na nova tabela
- contadores novos no audit opcionalmente em V2

Na V1 da replicação, os campos de audit existentes podem manter-se sem nova
coluna dedicada Beacon, desde que o log textual refira contagem Beacon.

## 9. Contrato do Receiver Externo

O receiver externo ganha os seguintes shims PHP:

- `external_academic_analytics/api/beacons/analytics/overview.php`
- `external_academic_analytics/api/beacons/observations.php`

### Regras

- `overview.php` consulta `mirror_beacon_observations` + snapshot
  `mirror_endpoint_snapshots(endpoint='map/ionospheric')`
- `observations.php` consulta `mirror_beacon_observations` directamente
- ambos aceitam `?mirror=<name>` como filtro opcional
- ambos devolvem `Cache-Control: no-store`
- `overview.php` adiciona:
  - `X-4HAM-Snapshot-Captured-At` quando houver snapshot NOAA
  - `X-4HAM-Snapshot-Mirror` quando aplicável

## 10. Wireframe Funcional

## 10.1 Estrutura desktop

```text
+----------------------------------------------------------------------------------+
|  [ HF ] [ APRS ] [ Beacon Analysis - NCDXF/IARU ]          Freshness: 4 min old |
+----------------------------------------------------------------------------------+
|  KPI: Global score | Best band | Detected slots | Beacons heard | NOAA Kp/SFI    |
+--------------------------------------------+-------------------------------------+
|  Recent activity - last 12 h               |  Beacon + NOAA reading              |
|  (historical, not current slot state)      |  - global state                     |
|                                            |  - agreement / disagreement by band |
|  [ 18 x 5 table ]                          |  - summary text                     |
|                                            +-------------------------------------+
|                                            |  Propagation by band                |
|                                            |  - 20m                              |
|                                            |  - 17m                              |
|                                            |  - 15m                              |
|                                            |  - 12m                              |
|                                            |  - 10m                              |
+--------------------------------------------+-------------------------------------+
|  Export controls                           |  Nowcast (next 3 h)                 |
|  [CSV] [XLSX] [JSON]                       |  - per-band forecast state          |
|  Filters: period / band / beacon / only detected                                 |
+----------------------------------------------------------------------------------+
|  Drill-down table: observations for selected cell / filters                       |
|  timestamp | beacon | band | detected | 100W SNR | dash seq | drift | confirmed |
+----------------------------------------------------------------------------------+
```

## 10.2 Estrutura mobile

```text
[Tabs]
[Freshness]
[KPI cards]
[Reading NOAA + Beacon]
[Recent activity table scroll horizontal]
[Propagation by band]
[Nowcast]
[Export controls]
[Detail table]
```

## 10.3 Regras UX obrigatórias

- o texto `historical - not the current slot state` deve aparecer sempre
- no externo deve existir badge visível de freshness / staleness
- nao mostrar botões de `Start monitoring` / `Stop monitoring`
- nao reutilizar a live matrix operacional dentro da Academic Analytics
- o drill-down deve manter a linguagem de `historical analysis`

## 11. Implementação por Fases

## Fase 1 - Local + Spec Parity

- adicionar terceira vista no Academic Analytics local
- implementar `GET /api/beacons/analytics/overview`
- reutilizar `GET /api/beacons/observations`
- export client-side

## Fase 2 - Mirror Transport

- adicionar stream `beacon_observations` ao payload
- migrar cursores de watermark escalar para cursores por stream
- criar `mirror_beacon_observations`
- estender `ingest.php`

## Fase 3 - External Academic Analytics

- replicar vista em `external_academic_analytics/index.html`
- implementar shims Beacon em PHP
- mostrar freshness badge e restrições read-only

## 12. Critérios de Aceitação

1. A Beacon TAB existe localmente e externamente com a mesma estrutura funcional.
2. A tabela `Recent activity - last 12 h` usa dados históricos reais e nao o
   estado live do slot actual.
3. A exportação funciona nos dois contextos sem endpoint server-side dedicado.
4. O receiver externo consegue reconstruir a vista Beacon apenas com:
   `mirror_beacon_observations` + snapshot `map/ionospheric`.
5. O espelho deixa de depender de watermark escalar único para suportar Beacon.
6. O utilizador vê sempre freshness / staleness no exterior.
