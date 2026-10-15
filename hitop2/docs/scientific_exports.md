# Exportações científicas

As exportações estão disponíveis apenas a utilizadores autenticados com perfil
operacional `admin` e `is_staff=True`. A geração é iniciada por `POST`, exige a
password atual e produz um ZIP transitório enviado com `Cache-Control: no-store`.
O servidor não mantém um histórico dos ficheiros.

## Exportação de dados científicos

Endpoint: `/administration/questionnaires/export-scientific-data/`

O pacote contém `participants.csv`, `submissions.csv`, a estrutura atual do
instrumento e, conforme as opções, `answers.csv`,
`sociodemographic_answers.csv`, `scale_scores.csv` e
`spectrum_scores.csv`. `normative_versions.csv` só é incluído quando existem
versões normativas referenciadas. `metadata.json`, `README.txt` e
`manifest.csv` documentam o pacote.

`participant_id` (`P000001`) e `submission_id` (`S000001`) são criados de novo
para cada exportação. Várias submissões clínicas do mesmo paciente partilham o
mesmo pseudónimo dentro do pacote. Um participante de Coleta Geral continua
anónimo e não é transformado num paciente. Não é criada qualquer tabela de
reversão.

Em `answers.csv`, `answer` é o valor bruto armazenado. `response_status` usa:

- `answered_valid`: resposta 1–4;
- `explicitly_omitted`: valor 5 (“Não sei / Prefiro não responder”);
- `presented_unanswered`: item pertencente à aplicação sem resposta persistida;
- `not_included`: item da estrutura atual que não pertenceu à aplicação.

Os scores clínicos não estão persistidos. Quando pedidos, são calculados pelos
serviços científicos atuais e marcados como
`calculated_at_export_with_current_scoring_service`. Submissões incompletas não
recebem scores. Percentis só são calculados com a versão já associada em
`report_normative_version`; a exportação nunca atribui uma versão.

Os dados sociodemográficos usam as `DynamicQuestion` existentes. Texto livre e
variáveis configuradas de elevada sensibilidade são excluídos. O estado distingue
resposta, ausência apresentada, condição não apresentada e “não aplicável”. As
respostas sociodemográficas antigas ligadas apenas ao utilizador não são
associadas retroativamente a uma submissão.

## Exportação de dataset normativo

Endpoint: `/administration/normative/versions/<version_id>/export/`

Os participantes são determinados exclusivamente por
`NormativeDatasetMembership`. O pacote inclui participantes (`N000001`),
memberships, respostas e os `NormativeScaleScore` e `NormativeSpectrumScore`
persistidos para a versão selecionada. A operação aceita versões `draft`,
`active` e `retired`, não prepara/recalcula scores e não altera o lifecycle. Em
TEST, `source` preserva a distinção entre baseline real e participante sintético.
Uma associação sintética inválida em PRODUÇÃO bloqueia a exportação em vez de
contaminar silenciosamente o pacote.

## Convenções técnicas

Todos os CSV são RFC 4180 em UTF-8, com cabeçalhos estáveis. Uma célula textual
que comece por `=`, `+`, `-`, `@`, tab ou carriage return recebe um apóstrofo
inicial contra formula injection. A transformação é reversível removendo
exatamente esse apóstrofo apenas nos campos enumerados pela coluna
`csv_injection_escaped_fields` da mesma linha. Assim, um apóstrofo que já fizesse
parte do valor original não fica ambíguo. Campos vazios devem ser interpretados em
conjunto com `response_status` e `is_valid`.

O manifesto contém o SHA-256 de cada ficheiro, exceto do próprio manifesto. A
base de dados não mantém uma versão histórica completa da estrutura do
instrumento; por isso, os CSV de estrutura descrevem a configuração existente no
momento da exportação. Esta limitação também consta de `metadata.json`.
Os models de escala, subfator e espectro têm nomes, mas não códigos científicos
dedicados; esses nomes são usados nas relações do pacote. Respostas e demografia
normativas são participant-scoped na arquitetura atual, enquanto memberships e
scores são version-scoped. A exportação síncrona científica está limitada a
10 000 submissões; acima desse limite é necessário reduzir os filtros.

Python/pandas:

```python
import pandas as pd

submissions = pd.read_csv("submissions.csv", dtype=str)
answers = pd.read_csv("answers.csv", dtype=str)
data = answers.merge(submissions, on="submission_id", validate="many_to_one")
```

R:

```r
submissions <- read.csv("submissions.csv", colClasses = "character")
answers <- read.csv("answers.csv", colClasses = "character")
data <- merge(answers, submissions, by = "submission_id")
```
