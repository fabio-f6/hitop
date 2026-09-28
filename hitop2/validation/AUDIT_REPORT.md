# Auditoria de scoring, interpretação e percentis — HiTOP Platform

Data: 2026-09-28. Âmbito: working tree atual e v1 de produção, ID técnico 8.
Execução: Python 3.13.5, Django 6.0.1; tolerância absoluta de scores `1e-12`.
Este relatório distingue **consistência matemática**, **integridade dos dados** e
**validade científica/clínica**. Os resultados não constituem certificação clínica.

## Conclusão baseada na evidência

**Os percentis frequentemente altos das simulações são, em grande parte, uma
consequência quantitativamente demonstrada dos perfis geradores e da distribuição
da v1.** Isso não elimina os problemas independentes encontrados.

* BD.csv tem **255 participantes**, **503 colunas**, **436 itens**: 429 científicos
  e 7 attention checks. Existem 93 escalas científicas e 5 espectros.
* Os **255 vetores completos** do CSV foram relacionados de forma única com os
  participantes da v1. **111.180 células importadas, zero diferenças**, zero
  duplicados de respostas, zero linhas perdidas e zero divergências age/sex após
  a normalização prevista no importador. Não foi usada a hipótese PK = linha.
* **23.715/23.715 scores de escalas** coincidem exatamente. **1.275/1.275 scores
  de espectros** coincidem dentro de `1e-12`; diferença máxima `4,44e-16`.
* A distribuição random gera média aproximadamente **2,5**, mas **92 das 93
  escalas** têm média normativa abaixo de 2,5. Em **64/93 escalas**, a mediana
  random é pelo menos P90. A média entre escalas da proporção de simulações
  ≥P95 é **52,41%** (estatística agregada por escala, não percentagem de pessoas).
* O oracle demonstra os resultados das escalas e o algoritmo de percentil sobre
  inputs idênticos. **Não demonstra equivalência exata de todos os percentis de
  espectro sob métodos diferentes de arredondamento**: 75/1.275 casos diferem,
  abrangendo 65 participantes, máximo de 4 pontos percentílicos.
* **Não é possível afirmar readiness clínica.** Faltam a chave científica oficial
  da versão portuguesa efetivamente usada, protocolo normativo e validação da
  direção/agregação das escalas. Há defeitos e limitações de implementação abaixo.

## Fontes de verdade e pipeline encontrado

```text
BD.csv (UTF-8, delimitador ;)
  → polls/management/commands/import_normative_data.py
  → NormativeParticipant + NormativeAnswer (valores literais, sem reverse)
  → NormativeDatasetMembership fixa os participantes da versão
  → prepare_normative_version em polls/normative_versions.py
      → polls/scoring.py: média dos itens por Scale
      → polls/spectrum_scores.py: média não ponderada das escalas válidas
  → NormativeScaleScore / NormativeSpectrumScore associados à versão
  → polls/percentiles.py: ECDF inclusiva, arredondada a inteiro
  → versão pinned em QuestionnaireSubmission
  → website/views.py::_build_report_context
  → report_interpretation.py + report_preview.html / docx_report.py
```

Mapping: `scripts/import_questions.py` contém `spectra_list`, `subfactor_list`,
`scale_list`, `questions_data`; é a fonte de importação encontrada. O modelo chama
o Spectrum **Spectra**. `Question.scale → Scale.subfactor → Subfactor.spectra`.
`Question.item_code` é unique e os FKs são obrigatórios. `id-name_en-name_pt.txt`
e as traduções são rótulos, não uma chave de validação científica.

`polls/models.py` define todos os modelos pedidos, incluindo `UserAnswer`,
`QuestionnaireSubmission`, `NormativeDatasetVersion`, membership e scores.
`polls/questions.py` seleciona os espectros da submissão e acrescenta os checks.
`polls/normative_export.py` copia respostas clínicas elegíveis; impede exportar
TEST/simulated para a normativa real. Normas não são alteradas pela simples
criação de um participante: uma nova versão precisa de snapshot/preparação.

`calculate_normative_scores` delega na preparação de drafts. A migração 0024
associou os scores legados a v1 e aproximou o histórico de reports pelas
submissões concluídas; não recalculou nem certificou esses scores. A auditoria
atual comprova o conteúdo da v1 encontrada, não a cronologia integral dos imports.
Reset/master_reset existem; **nenhum foi executado na base real**.

## BD.csv e fidelidade de importação

UTF-8 válido, sem BOM; 503 cabeçalhos distintos, sem linhas estruturalmente
malformadas, sem linhas completas duplicadas e sem vetores de itens duplicados.
As 436 colunas do mapping existem no CSV e na DB. As 67 restantes são campos
sociodemográficos, auxiliares, substâncias e a coluna `ATTENTION CHECK`;
o importador só conserva age/sex além dos itens. Lista integral em `summary.json`.
Não existe um ID de origem persistido pelo importador; os números de linha usados
nos exemplos são índices técnicos 1-based, excluindo o cabeçalho.

| Resposta | 429 itens científicos × 255 |
|---|---:|
| 1 | 64.784 |
| 2 | 28.939 |
| 3 | 11.202 |
| 4 | 4.470 |
| 5, blank, null, NaN | 0 |

Total científico: 109.395. Nos checks existem 1.777 valores `1` e oito `0`.
São os únicos tokens fora de ANSWER_CHOICES entre os itens. Os oito zeros estão
nas linhas 60, 75, 172, 174, 196, 228, 241 e 242. Não entram no scoring científico.
Há blanks legítimos em campos auxiliares e oito tokens de tipo null em `mental_med`;
`column_audit.csv` documenta tipos lexicais, blanks, whitespace e cardinalidade
por coluna sem revelar os valores demográficos. CSV não tem tipos nativos: o
importador lê strings; só age é convertido em int, sex é normalizado por prefixo.

**Attention checks têm semântica incompatível com respostas brutas.** O avaliador
atual classificaria cada um dos 255 participantes com 2/7 checks corretos e 5/7
incorretos. A coluna auxiliar está vazia em 247 linhas e vale `1` nas restantes
8. A interpretação plausível é codificação de sucesso/erro já derivada, mas
isto depende do dicionário de dados original. Não reconstruir respostas brutas
a partir de 0/1 sem essa documentação. A preparação normativa não filtra estes
participantes por attention checks. A fidelidade literal do import é comprovada;
a equivalência semântica destes sete campos **não** é.

Importador: faz lookup pelo item_code.lower(), ignora valores vazios, não valida
ANSWER_CHOICES nem aplica full_clean às respostas; atualmente recusa importação
destrutiva se já existem versões. Não possui transação global para recuperar um
import parcial. Estes riscos futuros não produziram discrepâncias no CSV atual.

## Mapping, reverse e direção

Zero diferenças entre DB e script quanto a item_code, texto, Scale, Subfactor,
Spectrum, attention flag e expected_answer. Zero escalas vazias, zero códigos
duplicados, zero Catch a contribuir para scores. Isto prova consistência interna
com o importador, **não** a correção científica do mapping.

**Não existe campo/configuração `rk`, nem transformação reverse no pipeline
encontrado.** A transformação real para todos os itens científicos é
`1→1, 2→2, 3→3, 4→4`. Normativa, submissões e simulações partilham essa regra.
O oracle inclui um golden hipotético com `5−answer` (`1→4,2→3,3→2,4→1`), mas não
o aplica a itens reais sem uma chave oficial. Não se pode identificar o número
de scores cientificamente errados por reverse ausente sem saber quais itens
deveriam ser invertidos e se o CSV já sofreu transformações anteriores.

**Well-being** é composta por cinco itens positivos (orgulho, alegria, otimismo,
bem-estar, motivação). A média normativa é 2,63765. É adicionada diretamente às
outras cinco escalas de Detachment. Aumentar bem-estar aumenta o score agregado
de Detachment, mantendo o resto constante. O report utiliza o texto genérico
“sintomatologia” tanto para percentis altos como baixos, sem metadata de direção.
Isto exige revisão científica explícita da interpretação e do agregado. Existem
255 scores Well-being e 255 Detachment potencialmente relevantes para essa
revisão; **não** são 510 erros científicos já comprovados. A direção das restantes
92 escalas também não foi certificada apenas pelo nome/texto dos itens.

Foi consultada a [página oficial da HiTOP Society](https://www.hitop-system.org/hitop-self-report-measures),
que remete para recursos e scoring do instrumento. A documentação atual do
[score_hitopsr](https://jmgirard.github.io/hitop/reference/score_hitopsr.html)
descreve 405 itens/76 escalas e reverse-coding; não corresponde diretamente aos
429 itens científicos/93 escalas deste projeto. Não foi usada para substituir
o mapping local. As [definições oficiais](https://jmgirard.github.io/hitop/articles/scales-hitopsr.html)
descrevem Well Being em termos positivos. Falta estabelecer a correspondência
de versão, tradução e itens antes de usar uma chave externa como oracle.

## Fórmulas efetivas e omissões

**Scale:** após excluir attention checks, agrupa as linhas de respostas existentes
por escala; ignora apenas a string `"5"`. `total_items` é o número dessas linhas,
não o número de perguntas configuradas. Com M respostas `"5"` em T linhas:

`is_valid = (100 × M/T < 25)`; score válido = soma(int(answer))/n_válidas.

Não há arredondamento explícito da média, Decimal ou ponderação. O resultado é
float e os scores normativos são FloatField; scores clínicos são recalculados
on-demand. Zero respostas válidas implica invalidade se houver linhas; zero
linhas elimina inteiramente a escala do resultado.

* Missing 24,99%: válida; 25% ou superior: inválida. O oracle testa 10.000 itens
  para representar exatamente 24,99%, 25% e 25,01%, e todas as contagens de
  omissões para comprimentos 1–20.
* **Linha ausente não conta como missing.** Num exemplo real de escala de cinco
  itens, só uma linha com resposta 4 produz score 4 e 0% missing. Com o denominador
  configurado deveria ter 80% missing e ser inválida. Na v1: zero linhas ausentes;
  nas submissões concluídas inspecionadas: zero incompletas. O bug está reproduzido
  e o impacto observado nos dados atuais por esse mecanismo é zero.
* `None` ou `""` numa linha provocam TypeError/ValueError em int(). Null não é
  permitido pelo campo DB, mas o motor não trata estas entradas defensivamente.
* `"0"` e `"9"` são convertidos em scores válidos 0 e 9. Choices não é, só por si,
  uma constraint de DB. O POST em `polls/views.py` guarda selected_value sem validar
  pertença às choices. Nenhum score normativo atual está fora de [1,4]; o domínio
  do motor não está garantido para dados inválidos futuros.

**Spectrum:** cada escala válida contribui com peso igual, independentemente do
número de itens; Subfactor apenas determina o grupo, não tem score intermédio.
Missing do espectro = soma dos missings de todas as escalas / soma dos seus itens,
incluindo escalas inválidas. Se missing global <25%, calcula média das escalas
válidas. Por exemplo, escala A inválida com 1/4 missing + escala B válida sem
missing em 4 itens → espectro 12,5% missing e score igual ao de B. Não exige todas
as escalas válidas. Uma escala sem linhas nem sequer participa no denominador.
Normativa e submissões usam a mesma função; adequação científica do peso igual
e da direção de Well-being carece de protocolo oficial.

## Percentis e empates

Para a versão explicitamente escolhida e o constructo: N scores armazenados,
B = número estritamente abaixo de X e E = número igual a X.

**Produção: `round(100 × (B+E)/N)`**. É uma ECDF inclusiva (“weak”), sem interpolação,
normalização por idade/sexo, z-score, ajuste de caudas ou remoção de duplicados.
None como score ou distribuição vazia → None. Sem versão explícita, procura a
versão ativa de produção; o report passa a versão pinned.

Arredonda ao inteiro mais próximo, com empate .5 para par, segundo round do Python.
P0 é possível abaixo do mínimo; P100 no máximo ou acima e, por arredondamento,
também pode ocorrer antes do máximo. Um score mínimo observado pode ter percentil
alto quando há muitos empates. P1/P99 são ranks arredondados, não cutoffs clínicos
validados. Com N=255, um registo corresponde a cerca de 0,392 pontos percentílicos.

| Convenção | Fórmula antes de arredondar |
|---|---|
| Strict / proporção abaixo | 100 B/N |
| Weak / produção | 100 (B+E)/N |
| Midrank / média de strict e weak | 100 (B+E/2)/N |
| Average rank (quando X existe na amostra) | 100 (B+(E+1)/2)/N |

A última coincide com strict/weak quando X não existe. Estas convenções estão
documentadas no [SciPy percentileofscore](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.percentileofscore.html).
Não foi encontrada no projeto uma justificação científica da escolha weak.
O CSV `percentile_conventions.csv` compara todos os scores distintos da v1 e
probes adicionais, por escala e espectro. Não se alterou a convenção.

Exemplos de empates: Agoraphobia X=1 → B=0,E=138,N=255 → weak 54,12%, P54;
strict 0%; midrank 27,06%. Antisocial Behavior X=1 → E=227 → P89; midrank 44,51%.
Logo “muitos têm o mínimo” e “o mínimo recebe percentil alto” podem coexistir.

**Sensibilidade numérica:** o reference spectrum usa statistics.mean das médias,
enquanto produção soma e divide. Comparar esses floats diretamente com a mesma
normativa pode alterar a inclusão de empates. Em Detachment, P1799 tem referência
1,4666666666666666 e armazenado 1,4666666666666668: P7 versus P11. Há 75 casos
(65 participantes), máximo 4 pontos. Produção atual versus armazenado: **zero
diferenças de percentil**; inversão da ordem de respostas testada: zero. Não é
evidência de que o report atual calculou P11 incorretamente segundo a sua definição
de float. É evidência de que tolerância nos scores não basta para provar igualdade
dos ranks. Uma futura regra canónica de precisão/empates requer decisão explícita,
análise de todos os deltas e eventualmente nova versão normativa, nunca alteração
silenciosa de v1.

## Recomposição total e distribuições

| Comparação independente, DB e CSV | Esperado | Existente | Matches | Mismatches | Max abs diff | Mean abs diff |
|---|---:|---:|---:|---:|---:|---:|
| Scale | 23.715 | 23.715 | 23.715 | 0 | 0 | 0 |
| Spectrum | 1.275 | 1.275 | 1.275 | 0 | 4,44e-16 | 5,49e-17 |

Os resultados são iguais quer o ponto de partida sejam as NormativeAnswers,
quer sejam diretamente as linhas BD.csv e o mapping do importador. Todos os
constructos têm N válido=255. Médias das escalas variam entre 1,02206 e 2,63765.
`scale_statistics.csv` e `spectrum_statistics.csv` incluem N, mean, median,
desvio-padrão amostral (n−1), min, max, P5/P10/P25/P50/P75/P90/P95/P99.
Estes quantis descritivos usam interpolação linear em (N−1)p; não confundir essa
função inversa com a ECDF que calcula o percentile de um participante.

## Simulações: medição, seeds e omissões

| Perfil | Probabilidades de 1/2/3/4 | Média teórica | Escalas com mediana ≥P90 | Média por escala da fração ≥P95 |
|---|---|---:|---:|---:|
| random | 25/25/25/25% | 2,50 | 64/93 | 52,41% |
| low | 45/35/15/5% | 1,80 | 25/93 | 21,14% |
| medium | 10/40/40/10% | 2,50 | 62/93 | 52,41% |
| high | 5/15/35/45% | 3,20 | 91/93 | 84,66% |

Monte Carlo: 1.000 participantes por perfil, todos os 429 itens científicos,
zero missing na comparação principal. Random produziu contagens
107.361/107.141/107.078/107.420: aproximadamente 25% cada. Usa o sampler puro real
`_profile_answer`, sem escrever UserAnswer; scores vêm do oracle e foram também
comparados com o motor real nos 4.000 participantes, sem diferenças >1e-12.
O gerador não modela correlações entre itens nem a população normativa; não se
deve esperar distribuição uniforme dos percentis ou prevalências clínicas reais.

`random.Random(submission.simulation_seed)` é local. Seeds None não garantem
reprodutibilidade. Em batches, SHA-256 de repr(base_seed):index fornece seed
inteira de 31 bits; num batch unitário mantém base_seed. A simulação sociodemográfica
consome o mesmo RNG antes dos itens; mesma seed pode gerar respostas diferentes
se configuração, perguntas ou caminho sociodemográfico mudarem. O Monte Carlo
usa seeds explícitas `20260928:<profile>:<index>`; é um experimento reproduzível
da distribuição do sampler, não um replay bit-a-bit da UI de batches.

Missing é aplicado por escala, excluindo checks, com
`int(n×percentage/100 + 0.5)` itens amostrados e substituídos por `"5"`.
25% solicitado: n=3 →1/3 (inválida); n=4 →1/4 (inválida); n=5 →1/5 (válida);
n=6 →2/6 (inválida); n=7 →2/7 (inválida); n=8 →2/8 (inválida).
O pedido não representa uma percentagem exata para todas as escalas.
`simulation_missing.csv` cobre 0,10,24,99,25,30,50,100% como probes do helper;
nem todos estes valores são opções da UI. O modo legado simulated_nulls com
missing configurado 0 usa 10%. Checks corretos são gerados separadamente; modos
de falha mudam até 1 ou 2 checks e não os scores científicos.

Exemplos random: Agoraphobia mean=2,5024 vs norma=1,2753, mediana P98, 78,4% ≥P95.
Antisocial Behavior mean=2,4996 vs norma=1,0221, 100% dos 1.000 ≥P99.
Por espectro, medianas random: Detachment P93, Externalizing P100, Internalizing
P100, Somatoform P98, Thought Disorder P100. Tabela completa por perfil/constructo
com proporções ≥P75/P90/P95/P99 em `monte_carlo.csv`.

## Exemplos verificáveis com calculadora

Nenhum destes exemplos tem reverse ou missing. Os códigos e respostas ordenadas
de todos os 18 traces estão em `traces.json`.

| Origem | Escala | Respostas | Soma/n | B | E | N | Percentil |
|---|---|---|---|---:|---:|---:|---:|
| BD linha 1, P1687 | Agoraphobia | 1,1,1,1,1 | 5/5=1 | 0 | 138 | 255 | round(100×138/255)=54 |
| BD linha 1, P1687 | Well-being | 2,2,2,2,3 | 11/5=2,2 | 52 | 30 | 255 | round(100×82/255)=32 |
| BD linha 1, P1687 | Antisocial Behavior | 1,1,1,1,1,1,1,1 | 8/8=1 | 0 | 227 | 255 | 89 |
| random seed 20260928:random:0 | Antisocial Behavior | 3,3,1,4,3,4,2,2 | 22/8=2,75 | 255 | 0 | 255 | 100 |
| mesma seed | Conversion Symptoms | 3,3,1,3,2,1,1 | 14/7=2 | 252 | 3 | 255 | 100 |

O trace inclui raw, scored, numerador, denominador, score, below/equal/N, quatro
convenções e resultado final. Além da linha 1, existem exemplos das linhas 2 e 3,
e dos participantes simulados 0,1,2. Os itens reversos reais não podem ser
demonstrados porque não existe configuração identificada.

## Oracle, golden snapshot e testes

`validation/reference.py` não importa funções de produção nem Django. O mapping
é extraído por AST de uma fonte separada da DB, mas não cientificamente independente
do importador. A fórmula é uma segunda implementação com Fraction, statistics
e bisect. `audit.py` é o adaptador que compara com produção e DB; não é o oracle.

Dez golden cases em JSON incluem todos os inputs e resultados intermédios/finais:
normal, reverse hipotético, missing abaixo do limiar, limiar exato, answer 5,
mínimo/P0, máximo/P100, P50, ties, zero respostas válidas. Checks adicionais
incluem P1/P99, arredondamento .5 para par, Spectrum de escalas com comprimentos
diferentes, exclusão de escala inválida e missing global.

Invariantes: range, monotonicidade direta e reversed, exclusão de attention,
answer 5, limiares discretos, monotonicidade e determinismo de percentis,
pinning perante mudança de active e isolamento TEST. Todas as 625 combinações
de quatro respostas 1–5 são comparadas entre produção e oracle. O teste full CSV
recalcula os 255 participantes e verifica hashes, contagens e goldens selecionados.

`v1_snapshot.json` regista contagens, hash de BD.csv, do script, do mapping e dos
outputs normalizados. Foi fixado após revisão dos resultados desta auditoria,
não gerado como expected dentro do teste. É baseline de consistência do estado
observado, mesmo com os blockers científicos conhecidos. Não deve ser atualizado
automaticamente para fazer testes passar. Os ficheiros de mismatch vazios têm
apenas um cabeçalho; zero mismatches não oculta participantes não relacionados.

End-to-end novo: cria submissão com respostas 1,2,2,3 numa DB SQLite descartável,
norma [1,2,2,3,4], score=2 e P60 calculados independentemente; verifica contexto,
espectro, dados do gráfico e HTML. Ativa outra versão e uma TEST e confirma que
o report continua pinned à primeira e mostra P60. Nenhuma fixture clínica foi
criada na development database.

Suite relacionada: **82 testes, 78 passaram e 4 falharam**, todos numa DB em
memória. As quatro falhas preexistentes foram preservadas:

1. `test_card_uses_pinned_version_and_unassigned_card_is_read_only`: procura
   texto contíguo `card-test (Teste)`; o template separa nome/ambiente com whitespace.
   Falha de asserção de apresentação, sem prova de percentile incorreto.
2. `test_production_report_rejects_structurally_test_version`: contexto não recusa
   pin TEST colocado por QuerySet.update numa submissão clínica. Save normal
   valida o ambiente; geração do contexto não revalida. Não foi demonstrada
   contaminação da v1, mas falta defesa perante estado inconsistente.
3. `test_report_generation_keeps_using_existing_pinning_mechanism`: report de
   submissão criada sem pin não atribui a versão ativa.
4. `test_test_report_production_fallback_is_labelled_production_and_pinned`:
   mesmo caminho sem pin não aplica fallback. A criação normal atual fixa a versão
   em `_create_submission`, portanto isto afeta especialmente objetos legados ou
   criados por outros caminhos. Com scores válidos e sem norma, o classificador
   pode comparar None com int e falhar; reproduzido em teste adicional.

Na base real foram inspecionadas **4 submissões concluídas**: zero sem pin,
zero pins TEST em submissões clínicas, zero conjuntos incompletos de itens e
zero UserAnswers com tokens fora de 1–5. Portanto as falhas de ambiente/pin são
reproduções em fixtures e riscos de caminhos alternativos, não contaminação
demonstrada destes quatro reports.

Não se executou toda a suite do repositório nem se alegou compatibilidade de
locking/concorrência PostgreSQL a partir de SQLite. A base real foi auditada
em PostgreSQL; os testes de integração novos foram isolados.

## Findings e ações propostas — sem correções nesta execução

| ID | Severidade | Finding / evidência | Impacto observado e ação recomendada |
|---|---|---|---|
| F01 | CRITICAL / blocker científico | Falta chave oficial/versionada, protocolo normativo, validação PT e método de agregação | Impede afirmar validade clínica de todos os resultados. Obter documentos e chave com correspondência item a item; não presumir que versão atual pública é a mesma. |
| F02 | HIGH | Well-being positiva tratada em narrativa de sintomatologia e agregada diretamente em Detachment | 255 scores de cada constructo relevantes; erro científico exato ainda não quantificável. Rever direção e texto; se mudar scoring, nova norma/versionamento. |
| F03 | HIGH | Missing sem linha não entra no denominador | Reprodução score4/0% vs esperado inválido/80%; zero participantes v1 e zero submissões completas atualmente afetados por ausência. Corrigir futuramente com universo de perguntas da submissão/versão; avaliar versões com respostas incompletas antes de recalcular. |
| F04 | HIGH | Domínio de resposta não validado no motor/POST/import | 0/9 podem dar scores fora de range; blank/null fazem erro. Oito zeros atuais apenas em Catch, zero scores científicos v1 fora de range. Adicionar validação explícita numa alteração aprovada; não converter dados silenciosamente. |
| F05 | HIGH | Semântica dos catch CSV 0/1 incompatível com avaliador de respostas 1–4 | 255/255 falhariam, apesar de o auxiliar marcar só 8. Não afeta médias por exclusão, mas elegibilidade normativa depende do protocolo. Preservar original; esclarecer codificação/filtros antes de qualquer reconstrução. |
| F06 | MEDIUM | Empates float não canónicos entre métodos independentes | 75 spectra/65 participantes com ranks diferentes, máximo4; motor atual reproduz armazenado. Definir precisão/empates e medir impacto antes de eventual nova norma. |
| F07 | HIGH | Report não revalida ambiente e caminho sem pin falha | Três testes funcionais relacionados falham em fixtures; números de reports reais afetados não demonstrados. Auditar estados legados, validar contexto e tratar ausência de norma explicitamente numa tarefa separada. |
| F08 | MEDIUM | Snapshot normativo não inclui toda a configuração científica e respostas do report | FK de versão fixa distribuição, mas report recalcula com Question/Scale/answers atuais. Alterações a mapping/itens podem mudar report pinned; modelos de proteção também podem ser contornados por QuerySet.update/bulk. Considerar chave/algoritmo versionados e snapshot de report. |
| F09 | LOW | Fragilidade da asserção de whitespace no card | Uma falha de apresentação, sem evidência de dados incorretos; ajustar teste apenas após confirmar requisito visual. |
| F10 | INFORMATIONAL | ECDF weak e normas com efeito de chão produzem percentis altos | Comportamento esperado da definição encontrada. Não mudar para midrank só para baixar números; requer especificação científica e análise de versões. |

Para F02/F03/F04/F05/F06, não é apropriado sobrescrever v1 automaticamente.
Se a fórmula/chave/população mudar, preparar versão nova explicitamente e definir
como tratar reports históricos. Correções só de apresentação podem não exigir
recalcular normas, mas exigem revisão do texto e rastreabilidade. Não há evidência
de que se deva reconstruir agora os 23.715 scores pelo simples facto de random
dar percentis altos.

## Readiness separada e evidências em falta

**A — Implementation correctness:** forte para médias de escalas completas,
exclusão dos checks, answer5 e limiar sobre linhas presentes, ECDF inclusiva,
seleção de versão nas chamadas testadas e reprodução do dataset atual. Não
comprovada globalmente: existem F03/F04/F06/F07/F08. O novo comando devolve exit1,
de propósito, em vez de apresentar um PASS global enganador.

**B — Data correctness:** fidelidade literal de 255×436 células comprovada;
mapping DB/script comprovado; 23.715+1.275 scores fortemente reconciliados.
Persistem semântica dos catch, ausência de ID original persistido, ausência de
proveniência anterior ao CSV e elegibilidade/representatividade da amostra.

**C — Scientific/clinical validity:** bloqueada. São necessários: instrumento e
versão portuguesa exatos; chave oficial Question/Scale/Subfactor/Spectrum e rk;
dicionário BD.csv com transformações prévias e codificação catch; protocolo de
missing, agregação e direção; definição aprovada de percentil/empates/precisão;
protocolo de amostragem, critérios de exclusão e estudo normativo dos 255;
evidência de adaptação linguística, fiabilidade, validade, invariância/subgrupos,
precisão e interpretação clínica, incluindo fundamentação dos cutoffs narrativos.
Um percentile relativo a esta amostra não demonstra diagnóstico nem adequação
a pessoas com “características semelhantes”; o motor usa norma global, sem
estratificação demográfica. Necessária revisão por responsáveis científicos
e validação externa com casos oficialmente pontuados.

## Ficheiros e garantias de preservação

Criados: `validation/reference.py`, `audit.py`, `checks.py`, `golden_cases.json`,
`v1_snapshot.json`, `test_reference.py`, `test_report.py`, `test_settings.py`,
`__init__.py`, `README.md`, este relatório, `artifacts/*.csv/json` e
`polls/management/commands/validate_scientific_pipeline.py`.

**Nenhum ficheiro de scoring/import/report/normativa de produção foi modificado.**
`scripts/import_questions.py` já aparecia modificado no início e foi preservado.
BD.csv foi apenas lido; a assinatura guardada confirma o original analisado.
**Nenhuma escrita na development database foi executada.** A leitura decorreu
numa transação PostgreSQL REPEATABLE READ/READ ONLY, confirmada como `on` pelo
servidor. Os testes escreveram apenas na base SQLite descartável em memória.
O comando só escreve artefactos locais de validação e não chama funções de
pinning/import/preparação/reset na base real.

Os dados individuais publicados aqui são apenas números técnicos e pequenos
exemplos pseudonimizados pedidos na auditoria. Não foram exportados nomes,
idades, localidades ou outros identificadores pessoais.
