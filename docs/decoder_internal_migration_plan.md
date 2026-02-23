<!--
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
Last update: 2026-02-22 17:40:00 UTC
-->

# Internal Native Decoder Migration Plan

> **Status: WSJT-X dependency fully removed.**
> FT8/FT4 decoding now uses `jt9` directly via `ExternalFtDecoder`.
> WSPR decoding uses `wsprd` directly.
> The WSJT-X GUI application is no longer required.

## Goal
Remove external runtime dependencies for digital/voice callsign extraction by implementing internal native RF decoders, while preserving event quality and system stability.

## Scope
- In scope:
  - native RX decode pipeline for FT8/FT4,
  - native CW from IQ,
  - native SSB voice/callsign extraction from IQ,
  - dedicated native PSK decoder,
  - event ingest integration, observability, rollout strategy.
- Out of scope (first pass): TX features, full WSJT-X feature parity UI, rig CAT control.

## Current Architecture
- FT8/FT4: `ExternalFtDecoder` (`ft_external.py`) → `jt9` subprocess → event ingest
- WSPR: `ExternalFtDecoder` → `wsprd` subprocess → event ingest
- Internal decoder (`ft_internal.py`) available as parallel path behind `FT_INTERNAL_ENABLE`
- No WSJT-X GUI or UDP protocol dependency

## Proposed Modules
- `backend/app/decoders/ft_internal.py`
  - orchestrates decode windows, sample buffering, and event normalization.
- `backend/app/decoders/ft_pipeline.py`
  - timing sync, candidate extraction, demod/decode glue.
- `backend/app/decoders/ft_metrics.py`
  - decode counters, false-positive rate indicators, per-band stats.
- `backend/app/decoders/cw_internal.py`
  - native CW chain from IQ/audio to symbols/callsign events.
- `backend/app/decoders/ssb_internal.py`
  - SSB demod + speech/callsign extraction from IQ inside backend.
- `backend/app/decoders/psk_internal.py`
  - dedicated PSK demod/decoder path from IQ/audio to callsign events.
- `backend/app/decoders/launchers.py` (extend)
  - feature-flag startup logic for internal decoder.
- `backend/app/main.py` (extend)
  - health/status exposure and runtime selection.

## Rollout Flags
- `FT_EXTERNAL_ENABLE=0|1` (enable jt9/wsprd decoding)
- `FT_EXTERNAL_MODES=FT8,FT4`
- `FT_INTERNAL_ENABLE=0|1` (default `0` initially)
- `FT_INTERNAL_MODES=FT8,FT4`
- `FT_INTERNAL_MIN_CONFIDENCE=<float>`
- `CW_INTERNAL_ENABLE=0|1`
- `SSB_INTERNAL_ENABLE=0|1`
- `PSK_INTERNAL_ENABLE=0|1`

## Migration Phases

### Phase 0 — Baseline & Telemetry ✅
- Freeze current baseline metrics (decode rate/hour, unique callsigns/hour, invalid events/day).
- Add comparison metrics endpoints to support A/B evaluation.
- Acceptance:
  - Baseline report captured for at least 24h of real RF operation.

### Phase 1 — Internal Decoder Skeleton
- Add internal decoder lifecycle (start/stop/status) behind `FT_INTERNAL_ENABLE`.
- Wire decoded outputs into existing `build_callsign_event` + DB insert flow.
- Add source tagging: `source=internal_ft`.
- Acceptance:
  - With feature enabled, backend stays stable and exposes internal decoder status.

### Phase 2 — FT8 RX Functional
- Implement FT8 decode path end-to-end for RX.
- Normalize fields: `mode`, `callsign`, `snr_db`, `frequency_hz`, `grid`, `report`, `time_s`, `dt_s`, `source`.
- Acceptance:
  - Synthetic + recorded sample tests pass.
  - In live test, internal path produces valid callsign events.

### Phase 3 — FT4 RX Functional
- Extend decode path to FT4 timing/symbol profile.
- Reuse same normalization contract.
- Acceptance:
  - FT4 appears as real `mode=FT4` events.
  - No regression on FT8 path.

### Phase 4 — Parallel Run (A/B)
- Run internal decoder and external jt9 decoder in parallel.
- Compare:
  - unique callsigns overlap,
  - decode count delta,
  - false positives.
- Acceptance gates (suggested):
  - internal decode count >= 90% of jt9 baseline,
  - false-positive rate <= baseline + 5%,
  - no backend stability regressions.

### Phase 5 — Production Default Switch ✅
- Set external jt9 decoder as default for FT8/FT4.
- WSJT-X dependency fully removed.
- Update docs/install and ops guides.
- Acceptance:
  - production runs without WSJT-X installed,
  - operational runbook updated,
  - rollback tested.

### Phase 6 — Native CW from IQ
- Implement CW decode path directly from backend IQ/audio stream.
- Integrate with existing event model (`mode=CW`, callsign/report/grid when available).
- Acceptance:
  - CW callsigns appear without external CW text feeder,
  - decode quality is validated against recorded/reference samples.

### Phase 7 — Native SSB Voice/Callsign from IQ
- Implement internal SSB demod + speech/callsign extraction pipeline from IQ.
- Remove requirement for external ASR text feed in production mode.
- Acceptance:
  - SSB callsign events are generated from IQ-only pipeline,
  - stability and latency within operational limits,
  - quality metrics tracked (confidence + validation rate).

### Phase 8 — Dedicated PSK Decoder
- Implement dedicated PSK demod/decoder path (not heuristic classification only).
- Normalize PSK events into existing schema (`mode=PSK*`, callsign fields when available).
- Acceptance:
  - PSK events appear as decoder output (not only `FSK/PSK` heuristic occupancy),
  - false-positive rate and decode coverage meet agreed baseline targets.

## Test Strategy
- Unit tests:
  - parser/normalizer invariants,
  - mode labeling correctness (`FT8` vs `FT4`),
  - confidence and source tagging.
- Integration tests:
  - ingest path + DB writes,
  - `/api/events`, `/api/events/stats`, `/api/decoders/status` correctness.
- Live validation:
  - real antenna + RTL-SDR session,
  - verify waterfall tooltip callsign population from internal events.

Mode-specific validation additions:
- CW: reference sample set with expected callsign recovery.
- SSB: IQ-to-callsign end-to-end tests with confidence thresholds.
- PSK: dedicated fixture set validating symbol decode and callsign extraction.

## Risk & Mitigation
- Decode quality below jt9:
  - mitigate with A/B parallel run and fallback flag.
- CPU increase on low-end hardware:
  - add decoder duty-cycle controls and per-band tuning.
- False positives in noisy bands:
  - confidence gating + stricter callsign validation.
- SSB speech ambiguity from noisy IQ:
  - enforce multi-signal corroboration (confidence + callsign regex + repetition window).
- PSK mode diversity (PSK31/63/etc.):
  - phase by protocol profile with per-profile gates.

## Deliverables Checklist
- [x] Internal decoder modules added
- [x] Feature flags documented
- [x] Telemetry and comparison metrics exposed
- [ ] FT8 functional in live RF
- [ ] FT4 functional in live RF
- [ ] A/B report documented
- [ ] CW native (IQ) functional in live RF
- [ ] SSB native (IQ to callsign) functional in live RF
- [ ] PSK dedicated decoder functional in live RF
- [x] WSJT-X no longer required in production
