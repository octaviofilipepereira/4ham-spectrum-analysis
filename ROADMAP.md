<!--
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
Last update: 2026-03-25
-->

# 🗺️ ROADMAP - 4ham-spectrum-analysis
## Estrutura de Trabalhos Seguintes

**Versão Atual**: v0.8.2  
**Última Atualização**: 2026-03-25  
**Status**: 🟢 Produção-Ready

---

## 📊 VISÃO GERAL DO PROJETO

### Estado Atual
- ✅ Backend modular e funcional (FastAPI, 55 módulos Python)
- ✅ Frontend funcional (Vanilla JS + WebGL)
- ✅ 56 rotas API implementadas
- ✅ 184 testes (100% sucesso)
- ✅ Instalador interactivo TUI (whiptail)
- ✅ Documentação abrangente (install, user manual, help.html)
- ✅ SSB Voice Signature Detection com hold-validation pipeline
- ✅ Whisper ASR pipeline preparado (FT-991A / IC-7300 USB)
- ✅ Propagation Map com globo 3D
- ✅ Decoders FT8/FT4/WSPR/CW/SSB integrados
- ✅ main_legacy.py removido (arquitetura limpa)
- ⚠️ Frontend monolítico (5349 linhas em app.js)
- ⚠️ Middleware placeholder (apenas __init__.py)

### Histórico de Versões Relevantes
| Versão | Data | Milestone |
|--------|------|-----------|
| v0.3.1 | 2026-02-23 | Backend modular, 54 testes, CI/CD |
| v0.6.0 | 2026-03-14 | Waterfall WebGL, retention, i18n EN |
| v0.7.0 | 2026-03-15 | Linux-only target, instalador TUI |
| v0.8.0 | 2026-03-22 | SSB Voice Signature, Whisper ASR, SNR gate |

---

## ✅ CONCLUÍDO (desde v0.3.1)

### ~~Remoção de main_legacy.py~~ ✅
- Ficheiro removido. Funcionalidade útil migrada para `main.py` (250 linhas).
- Testes revalidados.

### SSB Voice Signature Detection ✅ (v0.8.0)
- Hold-validation pipeline com 15 s de confirmação
- SSB candidate-focus mode com bucket/cooldown
- SNR gate a 6 dB (eventos) / 8 dB (markers)
- Alinhamento de defaults `ssb_focus_hits_required=2` (API + engine)

### Hotfixes v0.8.0 ✅
- AM→SSB reclassification em HF <30 MHz
- Occupancy flood suppression (rate limiter backend)
- False-positive marker fix + event restoration
- SSB threshold tuning para sinais curtos (unstable branch)

---

## 🎯 PRIORIDADES ESTRATÉGICAS

### 🔴 Prioridade ALTA (Próximos 1-2 sprints)
Trabalhos críticos para manutenibilidade e qualidade

### 🟡 Prioridade MÉDIA (2-4 sprints)
Melhorias importantes mas não bloqueantes

### 🟢 Prioridade BAIXA (Backlog)
Features nice-to-have e otimizações

---

## 🔴 PRIORIDADE ALTA

### 1. Migração Frontend para Módulos ES6 📦
**Objetivo**: Refatorar app.js monolítico (5349 linhas) para arquitetura modular

**Tarefas**:
- [ ] 1.1. Criar módulo `waterfall.js` (renderização WebGL)
- [ ] 1.2. Criar módulo `events.js` (gestão de eventos e tabela)
- [ ] 1.3. Criar módulo `controls.js` (painel de controlo de scan)
- [ ] 1.4. Criar módulo `charts.js` (gráficos e visualizações)
- [ ] 1.5. Criar módulo `websocket.js` (gestão de conexões WS)
- [ ] 1.6. Criar módulo `propagation.js` (mapa e propagação)
- [ ] 1.7. Atualizar `index.html` com imports ES6
- [ ] 1.8. Migrar lógica de `app.js` para módulos
- [ ] 1.9. Manter `app.js` como orchestrator minimalista (<300 linhas)
- [ ] 1.10. Atualizar testes frontend
- [ ] 1.11. Validar funcionalidade completa pós-migração

**Benefícios**: Manutenibilidade +80%, Testabilidade +60%, Legibilidade +90%

---

### 2. Implementação de Middleware Customizado 🛡️
**Objetivo**: Adicionar middleware para logging, metrics e security

**Tarefas**:
- [ ] 2.1. RequestLoggingMiddleware (logs estruturados por request)
- [ ] 2.2. SecurityHeadersMiddleware (HSTS, CSP, X-Frame-Options)
- [ ] 2.3. CORSMiddleware refinado (production-ready, origin whitelist)
- [ ] 2.4. RateLimitMiddleware (protecção contra abuse)
- [ ] 2.5. Configuração por ambiente (dev/staging/prod)
- [ ] 2.6. Testes de middleware
- [ ] 2.7. Documentação

**Benefícios**: Observabilidade, segurança, compliance

---

### 3. Validação Real-Band SSB (unstable) 🎙️
**Objetivo**: Validar os novos limiares SSB com testes de antena em banda real

**Tarefas**:
- [ ] 3.1. Scan SSB 40m durante período de actividade (18h-22h UTC)
- [ ] 3.2. Scan SSB 20m durante período de actividade (10h-16h UTC)
- [ ] 3.3. Medir taxa de markers por minuto (falsos vs legítimos)
- [ ] 3.4. Medir tempo até primeiro evento confirmado
- [ ] 3.5. Testar detecção de QSOs curtos (3-5 s)
- [ ] 3.6. Ajustar `MARKER_MIN_SNR_DB` via env var se necessário
- [ ] 3.7. Merge unstable → main quando validado

**Benefícios**: Confiança nos limiares, merge seguro

---

## 🟡 PRIORIDADE MÉDIA

### 4. Testes End-to-End (E2E) 🧪
**Objetivo**: Adicionar testes de integração completos

**Tarefas**:
- [ ] 4.1. Setup Playwright ou Cypress
- [ ] 4.2. Testes de fluxo de scan completo
- [ ] 4.3. Testes de export (CSV/JSON)
- [ ] 4.4. Testes de gestão de decoders
- [ ] 4.5. Testes de WebSocket real-time
- [ ] 4.6. Testes de autenticação
- [ ] 4.7. Integração no CI/CD
- [ ] 4.8. Screenshots em caso de falha

**Benefícios**: Confiança em releases, detecção precoce de bugs

---

### 5. Dashboard de Métricas e Monitorização 📈
**Objetivo**: Observabilidade em produção

**Tarefas**:
- [ ] 5.1. Integração com Prometheus/Grafana
- [ ] 5.2. Métricas de sistema (CPU, RAM, disk)
- [ ] 5.3. Métricas de aplicação (requests/s, latency)
- [ ] 5.4. Métricas de decoder (eventos/min, SNR médio)
- [ ] 5.5. Métricas de SDR (sample rate, overflows)
- [ ] 5.6. Alertas automáticos (email/webhook)
- [ ] 5.7. Dashboard Grafana personalizado

**Benefícios**: Visibilidade operacional, diagnóstico rápido

---

### 6. Otimização de Performance 🚀
**Objetivo**: Melhorar throughput e reduzir latência

**Tarefas**:
- [ ] 6.1. Profiling de endpoints lentos
- [ ] 6.2. Otimização de queries SQLite (índices)
- [ ] 6.3. Caching de dados frequentes (Redis opcional)
- [ ] 6.4. Compressão de respostas HTTP (gzip/brotli)
- [ ] 6.5. WebSocket message batching
- [ ] 6.6. Lazy loading de dados históricos
- [ ] 6.7. Benchmarks antes/depois

**Benefícios**: Latência -30%, throughput +50%, UX melhorada

---

## 🟢 PRIORIDADE BAIXA

### 7. Features Novas 🎁

#### 7.1. Multi-Device Support
- [ ] Scan simultâneo em múltiplos SDRs
- [ ] Agregação de dados multi-device
- [ ] UI para gestão de múltiplos dispositivos

#### 7.2. Integração com PSKReporter
- [ ] Envio automático de spots para PSKReporter
- [ ] Configuração de callsign e locator
- [ ] Rate limiting e validação

#### 7.3. Scheduler de Scans
- [ ] Agendamento de scans por hora/dia
- [ ] Perfis de scan programáveis
- [ ] Notificações de eventos importantes

#### 7.4. Mobile-Responsive UI
- [ ] Layout responsivo para tablets
- [ ] UI otimizada para smartphones
- [ ] Touch-friendly controls

#### 7.5. Themes e Customização
- [ ] Dark/Light theme switcher
- [ ] Customização de cores do waterfall
- [ ] Layout configurável (drag-and-drop panels)

---

### 8. Otimizações de Infraestrutura 🏗️

#### 8.1. Docker Compose Stack
- [ ] Dockerfile multi-stage otimizado
- [ ] docker-compose.yml completo
- [ ] Volumes para persistência
- [ ] Health checks

#### 8.2. Automated Backups
- [ ] Backup automático de SQLite
- [ ] Rotação de backups (7 dias, 4 semanas)
- [ ] Restore scripts
- [ ] Verificação de integridade

---

### 9. Melhorias de Segurança 🔒

#### 9.1. OAuth2/JWT Authentication
- [ ] Substituir Basic Auth por JWT
- [ ] Refresh tokens
- [ ] Role-based access control (RBAC)
- [ ] Session management

#### 10.2. Security Audit
- [ ] Scan de vulnerabilidades (OWASP Top 10)
- [ ] Dependency updates
- [ ] Penetration testing
- [ ] Security headers audit

**Estimativa**: 4-6 horas

#### 10.3. Rate Limiting Avançado
- [ ] Per-user rate limits
- [ ] IP-based throttling
- [ ] Distributed rate limiting (Redis)
- [ ] Adaptive rate limiting

**Estimativa**: 4-5 horas

---

## 📅 CRONOGRAMA SUGERIDO

### Sprint 1 (Semana 1-2) - Refactoring Core
- ✅ Tarefa 1: Migração Frontend ES6 (80%)
- ✅ Tarefa 2: Remoção main_legacy.py (100%)

### Sprint 2 (Semana 3-4) - Infrastructure
- 🔄 Tarefa 3: Middleware (100%)
- 🔄 Tarefa 5: Dashboard métricas (50%)

### Sprint 3 (Semana 5-6) - Quality
- 📋 Tarefa 4: Testes E2E (0%)
- 📋 Tarefa 6: Otimização performance (0%)

### Sprint 4 (Semana 7-8) - Documentation & Polish
- 📋 Tarefa 7: Documentação utilizador (0%)
- 📋 Features prioritárias do backlog

---

## 🎯 MÉTRICAS DE SUCESSO

### Técnicas
- Cobertura de testes: >80%
- Tempo de resposta API: <100ms (p95)
- Tempo de carregamento UI: <2s
- Zero critical vulnerabilities
- Uptime: >99.5%

### Qualidade de Código
- Complexidade ciclomática: <10
- Duplicação de código: <3%
- Type hints coverage: >90%
- Documentação: 100% endpoints

### Operacionais
- Deploy time: <5 min
- MTTR (Mean Time To Repair): <30 min
- CI/CD pipeline: <10 min
- Zero-downtime deployments

---

## 📝 NOTAS E DECISÕES

### Decisões Arquiteturais
1. **Manter Vanilla JS**: Não adicionar framework (React/Vue) por enquanto
   - Justificação: Projeto pequeno, performance excelente sem framework
   
2. **SQLite em Produção**: Aceitável para uso single-instance
   - Justificação: Simplicidade, backups fáceis, performance adequada
   
3. **WebSocket Delta Compression**: Manter estratégia atual
   - Justificação: Eficiente, testado, funcional

### Technical Debt Identificado
- ⚠️ Frontend monolítico (3744 linhas) - **RESOLVER SPRINT 1**
- ⚠️ main_legacy.py (2000+ linhas) - **RESOLVER SPRINT 1**
- ⚠️ Falta de middleware customizado - **RESOLVER SPRINT 2**
- ⚠️ Ausência de testes E2E - **RESOLVER SPRINT 3**
- ✅ Endpoints API faltantes - **RESOLVIDO v0.3.1**

---

## 🔄 PROCESSO DE ATUALIZAÇÃO

Este roadmap deve ser revisto e atualizado:
- ✅ Após cada sprint completo
- ✅ Quando surgirem bugs críticos
- ✅ Quando houver feedback de utilizadores
- ✅ Quando houver mudanças de prioridade

**Responsável**: CT7BFV (Octávio Filipe Gonçalves)  
**Próxima Revisão**: 2026-03-09 (2 semanas)

---

## 📞 FEEDBACK E CONTRIBUIÇÕES

Para sugerir novos trabalhos ou alterar prioridades:
1. Criar issue no repositório
2. Adicionar label apropriada (enhancement, bug, documentation)
3. Discussão na próxima reunião de sprint planning

---

**Versão**: 1.0  
**Estado**: 🟢 Aprovado para execução  
**Última atualização**: 2026-02-23
