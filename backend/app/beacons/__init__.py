# © 2026 Octávio Filipe Gonçalves / CT7BFV — AGPL-3.0
"""
Beacon Analysis — NCDXF/IARU International Beacon Project monitor.

Core feature (not an optional module): synchronised UTC monitoring of the
18-beacon NCDXF/IARU rotation across 5 HF bands (14.100, 18.110, 21.150,
24.930, 28.200 MHz). Each beacon transmits for 10 s in a fixed sequence;
a full cycle on a given band lasts 3 minutes.

Submodules:
- catalog: the 18 beacons + slot/band -> beacon mapping
- scheduler: UTC-aligned slot loop (TBD)
- matched_filter: callsign template correlation (TBD)
- session: lifecycle + IQ provider integration with ScanEngine (TBD)
"""
