<!--
© 2026 Octávio Filipe Gonçalves
Indicativo: CT7BFV
Última atualização: 2026-04-10
-->

# 🗺️ ROADMAP — 4ham-spectrum-analysis

> **Also available in:** [English](ROADMAP.md)

**Versão Atual**: v0.10.0  
**Última Atualização**: 2026-04-10  
**Estado**: 🟢 Produção-Ready (branch unstable)

---

## 📊 VISÃO GERAL DO PROJETO

### Estado Atual
- ✅ Backend modular (FastAPI, 58 módulos Python, 203 testes — 100% sucesso)
- ✅ Frontend com módulos ES6 (app.js + 10 módulos em `modules/` e `utils/`)
- ✅ 56+ rotas API
- ✅ Instalador interactivo TUI (whiptail) — Ubuntu/Debian/Mint/RPi OS
- ✅ Detecção de Voz SSB com pipeline de hold-validation
- ✅ Pipeline Whisper ASR (FT-991A / IC-7300 USB)
- ✅ Mapa de Propagação com globo 3D e scoring a 3 fórmulas (Digital/CW/SSB)
- ✅ Dashboard Academic Analytics com exportação multi-formato (CSV/XLSX/JSON)
- ✅ Scheduler de Rotação de Scan (ciclo multi-banda/modo)
- ✅ Decoders: FT8, FT4, WSPR, CW, SSB integrados
- ✅ Validação ITU de indicativos (padrões letter-start + digit-start)
- ✅ Atalho Desktop (GNOME/Cinnamon/XFCE/KDE/MATE/LXQt)
- ✅ Botão Check for Updates (git pull + auto-restart)
- ✅ BW cap SSB a 2800 Hz (eliminação de eventos fantasma)
- ✅ Sistema de focus hold SSB (fórmula auto span÷15k, máx. 16 holds/passagem)
- ✅ Documentação: install, manuais de utilizador (PT/EN), help.html, scoring de propagação (PT/EN)
- ⚠️ Frontend app.js ainda com 4230 linhas (parcialmente modularizado)
- ⚠️ Directório middleware placeholder (apenas `__init__.py`)

### Histórico de Versões
| Versão | Data | Marco |
|--------|------|-------|
| v0.3.1 | 2026-02-23 | Backend modular, 54 testes, CI/CD |
| v0.6.0 | 2026-03-14 | Waterfall WebGL, retenção, i18n EN |
| v0.7.0 | 2026-03-15 | Target Linux-only, instalador TUI |
| v0.8.0 | 2026-03-22 | SSB Voice Signature, Whisper ASR, gate SNR |
| v0.8.3 | 2026-04-02 | Markers VOICE DETECTED no waterfall, eventos filtrados por modo |
| v0.8.5 | 2026-04-03 | Dashboard Academic Analytics |
| v0.8.7 | 2026-04-05 | Atalho Desktop, Check for Updates |
| v0.9.0 | 2026-04-06 | Scoring de propagação 3 fórmulas, exportação multi-formato |
| v0.10.0 | 2026-04-08 | Scheduler de Rotação de Scan, correção de modos fantasma |

---

## ✅ CONCLUÍDO (desde v0.8.3)

### Qualidade de Sinal SSB ✅ (unstable, 2026-04-10)
- Correção do flood de markers SSB — debounce 60 s + gate SNR ≥ 8 dB
- Cache de voice markers preservada antes do debounce
- `band_display` backend atualizado após clipping de sub-banda SSB
- Melhoria da cobertura de focus hold (hold_ms 15→10 s, fórmula auto span÷15k, máx. 16)
- Eliminação de eventos SSB fantasma — BW cap a 2800 Hz em todos os 4 pontos de filtragem (pipeline, events, decoders, helpers)

### Rotação de Scan ✅ (v0.10.0)
- Ciclo automatizado multi-banda/modo com tempo de permanência configurável
- Opção de loop e barra de status com contagem regressiva
- Painel UI completo com editor de slots e sincronização WebSocket

### Academic Analytics ✅ (v0.8.5 – v0.9.0)
- Dashboard completo com timeline de actividade, distribuição por banda, heatmap, mapa de propagação
- Scoring a 3 fórmulas (Digital/CW/SSB com normalização SNR específica)
- Exportação multi-formato (CSV/XLSX/JSON), presets 1 h / 12 h
- Validação ITU de indicativos

### Correção de Modos Fantasma ✅ (v0.10.0)
- Eventos de ocupação forçados a corresponder ao modo do decoder activo
- Query SQL de modos confirmados limitada ao período analisado

---

## 🎯 LEGENDA DE PRIORIDADES

- 🔴 **ALTA** — Próximos 1–2 sprints, crítico para qualidade ou usabilidade
- 🟡 **MÉDIA** — 2–4 sprints, importante mas não bloqueante
- 🟢 **BAIXA** — Backlog, nice-to-have

---

## 🔴 PRIORIDADE ALTA

### 1. Gate SNR SSB Configurável 🎛️
**Objetivo**: Tornar o threshold de SNR para eventos SSB configurável pelo utilizador, adaptando-se ao setup de antena/receptor de cada estação

**Contexto**: O gate SSB está hardcoded a 8 dB em 4 pontos do código. Com uma boa antena (ex. Prosistel PST-1524VC), 45% dos eventos estão na faixa 8–10 dB. Uma estação com antena modesta (fio, indoor) teria sinais a 4–6 dB — o gate actual rejeitaria praticamente tudo.

**Dados de produção (2026-04-10)**: 1820 eventos SSB — 17.6% entre 6–8 dB, 45.3% entre 8–10 dB, SNR máximo 27.5 dB.

**Tarefas**:
- [ ] 1.1. Adicionar `ssb_snr_gate_db` ao `state.py` (env var `SSB_SNR_GATE_DB`, default 8.0)
- [ ] 1.2. Substituir os 4 hardcodes (8.0 dB) por referência a `state.ssb_snr_gate_db`
  - `events.py` — gate da cache de voice markers
  - `events.py` — emissão de evento SSB (pós-debounce)
  - `events.py` — gate geral de ocupação SSB (6.0 dB → derivar do gate)
  - `decoders.py` — loop do detector SSB
- [ ] 1.3. Expor no endpoint `/api/settings` (GET/PUT)
- [ ] 1.4. Adicionar controlo no frontend (Settings → SSB → SNR Gate)
- [ ] 1.5. Validação: intervalo 3.0–20.0 dB
- [ ] 1.6. Testes unitários (gate a 4, 8, 12 dB)
- [ ] 1.7. Documentação (install.md, help.html)

**Benefício**: Adaptação a qualquer setup de antena/receptor — menos falsos positivos em estações fortes, sinais fracos capturados em setups modestos

---

### 2. Validação Real-Band SSB 🎙️
**Objetivo**: Validar os limiares SSB com testes de antena real em várias bandas

**Tarefas**:
- [ ] 2.1. Scan SSB 40 m durante período de actividade (18–22 UTC)
- [ ] 2.2. Scan SSB 20 m durante período de actividade (10–16 UTC)
- [ ] 2.3. Medir taxa de markers por minuto (falsos vs legítimos)
- [ ] 2.4. Medir tempo até primeiro evento confirmado
- [ ] 2.5. Testar detecção de QSOs curtos (3–5 s)
- [ ] 2.6. Ajustar gate SNR via nova configuração se necessário
- [ ] 2.7. Merge unstable → main quando validado

**Benefício**: Confiança nos limiares, merge seguro para main

---

### 3. Modularização Frontend (Fase 2) 📦
**Objetivo**: Continuar a refatoração do app.js (ainda 4230 linhas) em módulos ES6 mais pequenos

**Estado actual**: 10 módulos já extraídos (`waterfall.js`, `api.js`, `websocket.js`, `config.js`, `constants.js`, `dom.js`, `ui.js`, `utils.js`, `presets.js`). Orquestrador principal ainda demasiado grande.

**Tarefas**:
- [ ] 3.1. Extrair módulo `events.js` (gestão da tabela de eventos)
- [ ] 3.2. Extrair módulo `controls.js` (painel de controlo de scan)
- [ ] 3.3. Extrair módulo `charts.js` (visualizações)
- [ ] 3.4. Extrair módulo `propagation.js` (mapa e propagação)
- [ ] 3.5. Reduzir app.js a orquestrador (<500 linhas)
- [ ] 3.6. Atualizar testes frontend
- [ ] 3.7. Validar funcionalidade completa pós-migração

**Benefício**: Manutenibilidade, testabilidade, legibilidade

---

### 4. Implementação de Middleware Customizado 🛡️
**Objetivo**: Adicionar middleware para logging, métricas e segurança

**Tarefas**:
- [ ] 4.1. RequestLoggingMiddleware (logs estruturados por request)
- [ ] 4.2. SecurityHeadersMiddleware (HSTS, CSP, X-Frame-Options)
- [ ] 4.3. CORSMiddleware refinado (production-ready, origin whitelist)
- [ ] 4.4. RateLimitMiddleware (protecção contra abuso)
- [ ] 4.5. Configuração por ambiente (dev/staging/prod)
- [ ] 4.6. Testes de middleware
- [ ] 4.7. Documentação

**Benefício**: Observabilidade, segurança, compliance

---

## 🟡 PRIORIDADE MÉDIA

### 5. Testes End-to-End (E2E) 🧪
**Objetivo**: Adicionar testes de integração completos

**Tarefas**:
- [ ] 5.1. Setup Playwright ou Cypress
- [ ] 5.2. Testes de fluxo de scan completo
- [ ] 5.3. Testes de exportação (CSV/JSON/XLSX)
- [ ] 5.4. Testes de gestão de decoders
- [ ] 5.5. Testes de WebSocket real-time
- [ ] 5.6. Testes de autenticação
- [ ] 5.7. Integração no CI/CD
- [ ] 5.8. Screenshots em caso de falha

---

### 6. Dashboard de Monitorização 📈
**Objetivo**: Observabilidade em produção

**Tarefas**:
- [ ] 6.1. Integração com Prometheus/Grafana
- [ ] 6.2. Métricas de sistema (CPU, RAM, disco)
- [ ] 6.3. Métricas de aplicação (requests/s, latência)
- [ ] 6.4. Métricas de decoder (eventos/min, SNR médio)
- [ ] 6.5. Métricas de SDR (sample rate, overflows)
- [ ] 6.6. Alertas automáticos (email/webhook)
- [ ] 6.7. Dashboard Grafana personalizado

---

### 7. Otimização de Performance 🚀
**Objetivo**: Melhorar throughput e reduzir latência

**Tarefas**:
- [ ] 7.1. Profiling de endpoints lentos
- [ ] 7.2. Otimização de queries SQLite (índices)
- [ ] 7.3. Caching de dados frequentes (Redis opcional)
- [ ] 7.4. Compressão de respostas HTTP (gzip/brotli)
- [ ] 7.5. WebSocket message batching
- [ ] 7.6. Lazy loading de dados históricos
- [ ] 7.7. Benchmarks antes/depois

---

## 🟢 PRIORIDADE BAIXA

### 8. Novas Features 🎁

#### 8.1. Suporte Multi-Dispositivo
- [ ] Scan simultâneo em múltiplos SDRs
- [ ] Agregação de dados multi-device
- [ ] UI para gestão de múltiplos dispositivos

#### 8.2. Integração com PSKReporter
- [ ] Envio automático de spots para PSKReporter
- [ ] Configuração de indicativo e locator
- [ ] Rate limiting e validação

#### 8.3. Agendador de Scans
- [ ] Agendamento de scans por hora/dia
- [ ] Perfis de scan programáveis
- [ ] Notificações de eventos importantes

#### 8.4. UI Mobile-Responsive
- [ ] Layout responsivo para tablets
- [ ] UI otimizada para smartphones
- [ ] Controlos touch-friendly

#### 8.5. Temas e Personalização
- [ ] Alternador tema Dark/Light
- [ ] Personalização de cores do waterfall
- [ ] Layout configurável (painéis drag-and-drop)

---

### 9. Otimizações de Infraestrutura 🏗️

#### 9.1. Docker Compose Stack
- [ ] Dockerfile multi-stage otimizado
- [ ] docker-compose.yml completo
- [ ] Volumes para persistência
- [ ] Health checks

#### 9.2. Backups Automatizados
- [ ] Backup automático de SQLite
- [ ] Rotação de backups (7 dias, 4 semanas)
- [ ] Scripts de restore
- [ ] Verificação de integridade

---

### 10. Melhorias de Segurança 🔒

#### 10.1. Autenticação OAuth2/JWT
- [ ] Substituir Basic Auth por JWT
- [ ] Refresh tokens
- [ ] Controlo de acesso baseado em roles (RBAC)
- [ ] Gestão de sessões

#### 10.2. Auditoria de Segurança
- [ ] Scan de vulnerabilidades (OWASP Top 10)
- [ ] Atualização de dependências
- [ ] Testes de penetração
- [ ] Auditoria de security headers

#### 10.3. Rate Limiting Avançado
- [ ] Limites por utilizador
- [ ] Throttling por IP
- [ ] Rate limiting distribuído (Redis)
- [ ] Rate limiting adaptativo

---

## 🎯 MÉTRICAS DE SUCESSO

| Categoria | Métrica | Objetivo |
|-----------|---------|----------|
| **Testes** | Cobertura de testes | >80% |
| **API** | Tempo de resposta (p95) | <100 ms |
| **UI** | Tempo de carregamento | <2 s |
| **Segurança** | Vulnerabilidades críticas | 0 |
| **Uptime** | Disponibilidade | >99.5% |
| **Deploy** | Tempo de deploy | <5 min |
| **Ops** | MTTR | <30 min |

---

## 📝 DECISÕES ARQUITECTURAIS

1. **Manter Vanilla JS** — Sem framework (React/Vue) por enquanto. Projecto pequeno, performance excelente sem framework.
2. **SQLite em Produção** — Aceitável para uso single-instance. Backups simples, performance adequada.
3. **WebSocket Delta Compression** — Estratégia actual mantida (eficiente, testada, funcional).
4. **BW Cap SSB a 2800 Hz** — Filtro SSB standard 2400 Hz + wide 2700 Hz + 100 Hz margem FFT. Sinais acima de 2800 Hz são ruído/interferência.
5. **Gate SNR SSB a 8 dB** — Calibrado para setups com boa antena. Será tornado configurável (ver item 1).
