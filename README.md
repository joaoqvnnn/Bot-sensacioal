# Larizinha Store Bot

Bot Telegram completo para comércio digital, com catálogo, estoque real, pagamentos Pix, carteira, afiliados, gift cards, suporte IA/humano, WhatsApp, Mini App e painel administrativo.

---

## ✅ Funcionalidades principais

- **Bot Telegram** com interface de mensagem única (edição in-place)
- **Painel administrativo** dentro do Telegram (dashboard, admins, configurações)
- **Catálogo de produtos** com categorias, detalhes e estoque em tempo real
- **Estoque real** com reserva, venda e liberação automática (estados AVAILABLE, RESERVED, SOLD)
- **Carteira digital** com ledger (crédito, débito, bônus) e saldo em centavos
- **Pagamentos Pix reais** via Mercado Pago
- **Gift Cards** com resgate atômico e hash seguro
- **Afiliados** com comissões, pontos e saques
- **Rankings** (serviços, recargas, compras, saldo)
- **Alertas de estoque** com notificações
- **Notificações programadas**
- **Anti-flood** e modo manutenção
- **Suporte com IA** (OpenAI) + transferência para humano
- **Pesquisa inline** no Telegram
- **Mini App (WebApp)** com carrinho e pagamento
- **Website de ativação** de produtos
- **WhatsApp Business API** para entrega e suporte
- **Multi-tenant** isolado por tenant_id
- **Workers assíncronos** (arq) para pagamentos, entregas, notificações e alertas

---

## 🧱 Stack

- Python 3.12+
- aiogram 3.x
- SQLAlchemy 2.0 + asyncpg
- Alembic (migrations)
- Redis 7
- PostgreSQL 16
- FastAPI (Mini App/WebSite)
- arq (filas)
- Mercado Pago API
- WhatsApp Business API
- OpenAI API
- Docker + docker-compose

---

## 📁 Estrutura de diretórios

\`\`\`
larizinha_store/
├── bot/
│   ├── core/               # config, database, redis, security, logging, utils
│   ├── models/             # modelos SQLAlchemy
│   ├── services/           # regras de negócio
│   ├── handlers/           # handlers do Telegram
│   ├── keyboards/          # helpers para teclados
│   ├── middlewares/        # anti-flood, manutenção, tenant
│   ├── integrations/       # mercadopago, whatsapp, email, openai
│   ├── workers/            # tarefas assíncronas (arq)
│   └── __main__.py         # entrypoint do bot
├── webapp/                 # API do Mini App
├── website/                # API do website de ativação
├── scripts/                # scripts utilitários (criar tenant, admin, canal)
├── migrations/             # alembic
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env.example
\`\`\`

---

## 🚀 Instalação e execução

### 1. Clone o repositório

\`\`\`bash
git clone https://seu-repositorio.com/larizinha-store.git
cd larizinha-store
\`\`\`

### 2. Configure as variáveis de ambiente

Copie o `.env.example` para `.env` e preencha com seus dados reais.

\`\`\`bash
cp .env.example .env
nano .env
\`\`\`

**Importante:** nunca commit o arquivo `.env`.

### 3. Execute com Docker

\`\`\`bash
docker-compose up -d
\`\`\`

Isso iniciará:
- PostgreSQL
- Redis
- Bot (polling)
- Worker (arq)
- Mini App (webapp) na porta 8000

### 4. Criar tenant inicial

\`\`\`bash
docker-compose exec bot python -m scripts.create_tenant "Larizinha Store" larizinha --plan "gold" --vip --dias 365
\`\`\`

### 5. Criar usuário administrador

\`\`\`bash
docker-compose exec bot python -m scripts.create_admin larizinha 6995978182 --owner
\`\`\`

### 6. Configurar canal de compras

\`\`\`bash
docker-compose exec bot python -m scripts.set_channel larizinha -1001234567890
\`\`\`

---

## 🛒 Fluxo de compra

1. Usuário envia `/start` e verifica canal obrigatório (se configurado).
2. Navega por categorias e produtos (catálogo).
3. Clica em COMPRAR, informa quantidade.
4. Se saldo suficiente, escolhe método de entrega (Telegram, WhatsApp, e-mail).
5. Se saldo insuficiente, gera Pix via Mercado Pago.
6. Após pagamento aprovado, saldo é creditado e compra é concluída.
7. Estoque é marcado como SOLD, pedido gerado, entrega criada e canal notificado.

---

## 🔐 Segurança

- Saldo em **centavos** (inteiro), nunca float.
- **Idempotência** em pagamentos, compras, saques e gift cards.
- **Locks** em estoque e carteira para evitar corridas.
- **Hash** de senhas (bcrypt) e gift cards (SHA-256).
- **Criptografia** de dados sensíveis (Fernet).
- **Anti-flood** com bloqueio temporário/permanente.
- **Isolamento multi-tenant** (tenant_id em todas as tabelas).
- **Validação de webhook** e origem.

---

## 📝 Configurações editáveis no painel

- Textos e botões da home
- Mensagens de canal obrigatório
- Templates de e-mail e WhatsApp
- Regras de afiliados (comissão, pontos, mínimo)
- Regras de Pix (mínimo, máximo, bônus, expiração)
- Canal de compras/estoque
- Modo manutenção
- Anti-flood

---

## 🧪 Testes (opcional)

\`\`\`bash
pytest
\`\`\`

---

## 📄 Licença

Proprietário. Uso autorizado apenas para o contratante.

---

## 👥 Suporte

Para dúvidas ou customizações, contate o desenvolvedor responsável.
