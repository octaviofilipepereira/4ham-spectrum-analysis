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
