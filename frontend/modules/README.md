# Frontend Modules

Esta pasta contém os módulos JavaScript que compõem o frontend do 4ham Spectrum Analysis.

## Estrutura

- **config.js** - Constantes, configurações e endpoints da API
- **dom.js** - Referências centralizadas aos elementos DOM
- **api.js** - Cliente REST API para comunicação com o backend
- **ui.js** - Utilitários de UI (toasts, formatação, helpers)
- **websocket.js** - Gestão de conexões WebSocket com reconexão automática

## Uso

Os módulos são importados como ES6 modules no `app.js` principal:

```javascript
import { elements } from './modules/dom.js';
import { API_ENDPOINTS } from './modules/config.js';
import { showToast } from './modules/ui.js';
import { getEvents } from './modules/api.js';
import { WebSocketManager } from './modules/websocket.js';
```

## Benefícios da Modularização

1. **Manutenibilidade** - Código organizado por responsabilidade
2. **Reusabilidade** - Funções podem ser reutilizadas facilmente
3. **Testabilidade** - Módulos podem ser testados independentemente
4. **Escabilidade** - Fácil adicionar novas funcionalidades sem afetar código existente
5. **Performance** - Apenas os módulos necessários são carregados

## Notas

- Todos os ficheiros seguem a licença GNU AGPL-3.0
- © 2026 Octávio Filipe Gonçalves (CT7BFV)
