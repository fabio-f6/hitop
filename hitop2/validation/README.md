# Auditoria científica — ferramentas fora do runtime

Leia [AUDIT_REPORT.md](AUDIT_REPORT.md) para conclusões e limitações. Este diretório
não é importado por nenhuma função clínica. O único ponto de entrada na aplicação
é um management command explicitamente invocado.

## Executar com a base real em modo read-only

```sh
../venv/bin/python manage.py validate_scientific_pipeline
```

Opções: `--csv BD.csv`, `--normative-version v1`, `--output validation/artifacts`,
`--simulations 1000`, `--seed 20260928`. PostgreSQL obrigatório. A primeira instrução
na transação é `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY`.
Não executa importação, preparação, exportação, criação de submissões ou pinning.
Escreve apenas ficheiros no diretório de outputs. Código de saída 1 é atualmente
esperado: omissões sem linha, domínio dos catch e sensibilidade numérica estão
documentados. PASS não equivale a validade clínica; a categoria científica é BLOCKED.

## Testes sem acesso à development database

```sh
../venv/bin/python manage.py test validation --settings=validation.test_settings --noinput
```

`validation.test_settings` substitui a ligação PostgreSQL por SQLite `:memory:`.
Os testes de integração criam dados exclusivamente nessa base descartável.
Os testes que caracterizam defeitos passam quando reproduzem o comportamento
documentado; o management command mantém os respetivos FAILs de conformidade.

Suite relacionada usada na auditoria:

```sh
../venv/bin/python manage.py test validation polls.test_normative_versions polls.test_normative_environments polls.test_simulation polls.test_simulation_normative_isolation website.test_normative_traceability --settings=validation.test_settings --noinput
```

## Independência e limitações

`reference.py` usa apenas a biblioteca standard. Não importa Django nem scoring,
percentiles ou spectrum_scores. A média das escalas usa Fraction; a dos espectros
usa statistics.mean; o percentil usa pesquisa binária. O adaptador `audit.py`
chama produção apenas como objeto da comparação e para amostrar perfis simulados.

O mapping é extraído com AST dos literais de `scripts/import_questions.py`, sem
executar esse ficheiro. Isto permite detetar divergências DB/import script, mas
ambos podem partilhar um erro científico. NÃO é uma chave oficial independente.
Reverse nos golden cases é hipotético e explicitamente separado da chave atual.

O snapshot é uma assinatura de consistência do estado observado, não uma
certificação científica. `snapshot_candidate.json` é um candidato gerado; nunca
substitui automaticamente `v1_snapshot.json`. Atualizações do baseline requerem
revisão explícita do relatório e dos deltas. Scores são normalizados para 12
algarismos significativos; a comparação numérica usa tolerância absoluta `1e-12`.
Percentis são comparados como inteiros exatos, sem tolerância.

O CSV não preserva um identificador que o importador armazene. Os 255 vínculos
foram estabelecidos por igualdade única dos vetores completos das 436 respostas.
Se uma resposta mudar, o comando reportará participante não relacionado e FAIL;
não inventará um vínculo por ordem de PK ou por proximidade das respostas.

Os artefactos contêm estatísticas e IDs técnicos, nunca nomes/demografia individual.
Os traces selecionados contêm respostas sensíveis pseudonimizadas: manter o mesmo
controlo de acesso do repositório e não publicar em serviços públicos.
