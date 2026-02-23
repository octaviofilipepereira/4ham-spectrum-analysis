# GitHub Actions Workflows

Este diretório contém os workflows de CI/CD para o projeto 4ham Spectrum Analysis.

## Workflows Disponíveis

### `ci.yml` - Continuous Integration

Executado automaticamente em:
- Push para branches `main` e `develop`
- Pull requests para `main` e `develop`
- Manual trigger via GitHub UI

**Jobs incluídos:**

1. **Backend Tests** - Executa testes Python em múltiplas versões (3.10, 3.11, 3.12)
2. **Frontend Tests** - Executa testes JavaScript em Node.js 18, 20, 22
3. **Code Quality** - Verifica código com Ruff, Black e mypy
4. **Security Audit** - Verifica dependências com pip-audit e safety
5. **Build Validation** - Valida estrutura do projeto e imports

## Configuração Local

Para executar os mesmos checks localmente:

### Backend
```bash
cd backend

# Testes
python -m pytest tests/ -v --cov=app

# Linting
ruff check app/

# Formatação
black --check app/

# Type checking
mypy app/ --ignore-missing-imports

# Security
pip-audit -r requirements.txt
```

### Frontend
```bash
cd frontend

# Testes
npm test

# Validação de estrutura
test -f index.html && test -f app.js && echo "OK"
```

## Badges

Adicione estes badges ao README.md principal:

```markdown
![CI Status](https://github.com/octaviofilipepereira/4ham-spectrum-analysis/workflows/CI%2FCD/badge.svg)
[![codecov](https://codecov.io/gh/octaviofilipepereira/4ham-spectrum-analysis/branch/main/graph/badge.svg)](https://codecov.io/gh/octaviofilipepereira/4ham-spectrum-analysis)
```

## Notas

- Os checks de qualidade de código usam `continue-on-error: true` para não bloquear o workflow
- Coverage reports são enviados para Codecov apenas no Python 3.10
- Todos os workflows respeitam a licença GNU AGPL-3.0

---
© 2026 Octávio Filipe Gonçalves (CT7BFV)
