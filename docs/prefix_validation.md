<!--
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
Last update: 2026-02-22 00:34:50 UTC
-->

# Prefix Sources and Validation

## Sources
- National regulator prefix tables (per country)
- IARU regional allocations
- ITU allocations (reference only)

## Validation Rules
- Normalize callsign to uppercase.
- Remove separators and whitespace.
- Validate with regional prefix tables.
- Validate against baseline regex.

## Update Process
1. Add official source URL per country.
2. Update prefix list for that country.
3. Record source date and notes.
4. Run validation tests against sample callsigns.
