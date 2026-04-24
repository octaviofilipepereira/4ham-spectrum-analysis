<!--
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
Last update: 2026-04-02
-->

# 📊 QUICK STATUS - Trabalhos Pendentes

**Atualização**: 2026-04-23
**Versão**: v0.14.0 (unstable)

---

## 🆕 ÚLTIMA ENTREGA

### External Mirrors + Public Dashboard ✅ (v0.14.0)
```
Concluído em v0.14.0 (2026-04-23)
- Módulo backend external_mirrors/ (pusher, repository, http_client, snapshots)
- Receptor PHP/MySQL em external_academic_analytics/
- Snapshot bundler in-process (6 endpoints replicados verbatim)
- Dashboard público em https://cs5arc.pt/external_academic_analytics/
- 8 testes adicionais; 374/374 testes passam
- Latência push default: 5 min; sem WebSocket; sem superfície admin
```

---

## ✅ CONCLUÍDO RECENTEMENTE

### ~~Remover main_legacy.py~~ ✅
```
Concluído em v0.7.0
Ficheiro removido; main.py limpo (250 linhas)
```

### SSB Voice Signature Detection ✅ (v0.8.0)
```
Concluído em v0.8.0
Hold-validation pipeline, Whisper ASR, SNR gate
184 testes (100% sucesso)
```

### SSB Threshold Tuning ✅ (unstable)
```
Concluído em unstable (e9c4b87)
focus_hits alinhado (API=2, engine=2)
MARKER_MIN_SNR_DB 10→8 dB
Merge → main concluído em v0.8.3
```

### VOICE DETECTED Waterfall Markers ✅ (v0.8.3)
```
Concluído em v0.8.3 (2026-04-02)
Markers SSB_VOICE no waterfall (black+gold, 45 s TTL)
Mode-filtered event fetch (eventos persistem ao trocar modo)
ASR startup fix (config restaurada da DB ao arrancar)
```

### Migração Frontend ES6 Modules (parcial) ✅
```
Concluído parcialmente em v0.8.3
waterfall.js, utils.js, constants.js extraídos de app.js
```

---

## 🎯 PRÓXIMOS 3 TRABALHOS PRIORITÁRIOS

### 1️⃣ Validação Real-Band SSB (unstable → main)
```
Status: ✅ CONCLUÍDO
Prioridade: 🟢 RESOLVIDO
Progresso: ██████████ 100%

Limiares SSB aplicados e merge para main em v0.8.3
```

### 2️⃣ Migração Frontend ES6 Modules
```
Status: 🟡 EM PROGRESSO
Prioridade: 🔴 ALTA
Progresso: ████░░░░░░ 40%

Objetivo: Refatorar app.js → estrutura modular

Tarefas:
[x] Criar waterfall.js
[x] Criar constants.js
[x] Criar utils.js
[ ] Criar events.js
[ ] Criar controls.js
[ ] Criar charts.js
[ ] Criar websocket.js
[ ] Criar propagation.js
[ ] Migrar lógica restante
[ ] Testes
```

### 3️⃣ Implementar Middleware Customizado
```
Status: 📋 TODO
Prioridade: 🔴 ALTA
Progresso: ░░░░░░░░░░ 0%

Objetivo: Logging, security headers, rate limiting

Tarefas:
[ ] RequestLoggingMiddleware
[ ] SecurityHeadersMiddleware
[ ] CORSMiddleware (origin whitelist)
[ ] RateLimitMiddleware
[ ] Configuração por ambiente
```
[ ] Testes
```

---

## 📈 PROGRESSO GERAL

```
Sprint 1 (Refactoring)     ░░░░░░░░░░  0/10  (0%)
Sprint 2 (Infrastructure)  ░░░░░░░░░░  0/10  (0%)
Sprint 3 (Quality)         ░░░░░░░░░░  0/10  (0%)
Sprint 4 (Documentation)   ░░░░░░░░░░  0/10  (0%)
```

**Total Tasks**: 0/40 (0%)

---

## ✅ COMPLETADO RECENTEMENTE

- ✅ v0.3.1: 5 novos endpoints API implementados
- ✅ v0.3.0: Frontend ES6 modules parcial (config, api, websocket, ui, dom)
- ✅ v0.3.0: Type hints adicionados
- ✅ v0.3.0: Bug fixes críticos (scan engine)
- ✅ v0.3.0: CI/CD pipeline completo

---

## 🔥 ISSUES CRÍTICOS

```
Nenhum issue crítico identificado
```

---

## 💡 SUGESTÕES PARA HOJE

1. **Começar Tarefa 1**: Criar estrutura base dos novos módulos frontend
2. **Review Tarefa 2**: Análise preliminar do main_legacy.py
3. **Planning**: Detalhar tarefas do middleware

---

**Para detalhes completos**: Ver [ROADMAP.md](ROADMAP.md)
