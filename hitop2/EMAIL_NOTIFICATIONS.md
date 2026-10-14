# Notificações por e-mail

## Configuração local

Por omissão, o Django usa o Mailpit em `127.0.0.1:1025` e constrói links com
`http://127.0.0.1:8000`. Todos os valores podem ser alterados sem modificar o
código:

```text
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=127.0.0.1
EMAIL_PORT=1025
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
EMAIL_USE_TLS=false
EMAIL_USE_SSL=false
EMAIL_TIMEOUT=10
DEFAULT_FROM_EMAIL=HiTOP Platform <no-reply@hitop.local>
PLATFORM_BASE_URL=http://127.0.0.1:8000
TIME_ZONE=Europe/Lisbon
```

Nunca ative TLS e SSL simultaneamente. As credenciais do futuro SMTP
institucional devem existir apenas no ambiente, não no repositório.

## Arranque e migrations

1. Inicie o Mailpit da forma como foi instalado localmente e confirme a
   interface em <http://localhost:8025>.
2. Execute `python manage.py migrate`.
3. Execute `python manage.py runserver`.

## Validação manual

Use apenas endereços fictícios, por exemplo `admin@hitop.test`,
`professional.a@hitop.test`, `professional.b@hitop.test` e
`researcher@hitop.test`.

1. Crie dois administradores operacionais (`UserProfile.user_type=admin`) e
   desative “Novos registos profissionais” num deles. Registe um profissional
   pela página pública. O Mailpit deve mostrar uma mensagem apenas para o
   administrador que manteve a opção ativa.
2. Em Administração > Profissionais, aprove um pedido pendente. A conta deve
   receber “Conta aprovada”. Repetir o POST não cria outra mensagem.
3. Rejeite outro pedido pendente. A conta deve ficar inativa e receber “Pedido
   de registo não aprovado”. As preferências opcionais não bloqueiam estas duas
   comunicações essenciais.
4. Associe pacientes diferentes aos profissionais A e B. Em “Preferências de
   Notificações”, mantenha “Questionários concluídos” ativa apenas para A.
   Conclua aplicações clínicas normais de ambos. Apenas A deve receber a
   notificação; o conteúdo não deve incluir respostas ou resultados.
5. Como investigador aprovado, crie duas Coletas Gerais de produção e conclua
   várias participações normais. Execute
   `python manage.py send_collection_digests --date AAAA-MM-DD`. Deve surgir um
   único e-mail consolidado para esse investigador. Uma segunda execução para
   a mesma data não deve duplicá-lo.
6. Confirme que simulações, Ambiente de Teste e Coletas Gerais de Teste não
   originam mensagens reais.
7. Pare o Mailpit, provoque um evento e confirme no Django Admin que a outbox
   ficou em `failed` sem reverter o evento principal. Reinicie o Mailpit e
   execute `python manage.py retry_email_notifications`. O estado deve passar
   para `sent` (“aceite pelo SMTP”) e a mensagem deve aparecer no Mailpit.

O SMTP não oferece exatamente-uma-vez de ponta a ponta. Se o servidor aceitar
uma mensagem e o processo terminar antes de gravar `sent`, um retry pode
duplicá-la. A chave lógica única e o estado persistente evitam duplicações nas
operações normais e nas execuções concorrentes.

## Comandos

- `python manage.py send_collection_digests`: resume o dia civil anterior no
  timezone configurado.
- `python manage.py send_collection_digests --date 2026-10-14`: processa uma
  data específica.
- `python manage.py retry_email_notifications --limit 100`: tenta novamente
  mensagens pendentes, falhadas e envios interrompidos há mais de 15 minutos.
