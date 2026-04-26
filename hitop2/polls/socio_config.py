SOCIO_QUESTIONS = [

# =====================================================
# IDENTIFICAÇÃO / BASE
# =====================================================

{
    "id": "age",
    "label": "Idade",
    "type": "number",
},

{
    "id": "country_born",
    "label": "Em que país nasceu?",
    "type": "text",
},

{
    "id": "country_residence",
    "label": "Em que país reside atualmente?",
    "type": "text",
},

# =====================================================
# PORTUGAL / CONTEXTO CULTURAL
# =====================================================

{
    "id": "PT_residence_years",
    "label": "Há quantos anos vive em Portugal?",
    "type": "radio",
    "choices": [
        ("1", "Nunca"),
        ("2", "Menos de 1 ano"),
        ("3", "Menos de 5 anos"),
        ("4", "A maior parte da minha vida"),
        ("5", "Toda a vida"),
        ("6", "Outro"),
    ]
},

{
    "id": "PT_lang",
    "label": "Fala com frequência o Português-Europeu na sua vida diária?",
    "type": "radio",
    "choices": [
        ("1", "Não"),
        ("2", "Sim"),
    ]
},

{
    "id": "PT_residence_region",
    "label": "Zona de residência habitual",
    "type": "radio",
    "choices": [
        ("1", "Norte"),
        ("2", "Centro"),
        ("3", "Grande Lisboa"),
        ("4", "Península de Setúbal"),
        ("5", "Oeste e Vale do Tejo"),
        ("6", "Alentejo"),
        ("7", "Algarve"),
        ("8", "Região Autónoma dos Açores"),
        ("10", "Região Autónoma da Madeira"),
        ("9", "Não aplicável"),
    ]
},

{
    "id": "freguesia",
    "label": "Freguesia onde residiu a maior parte do último ano",
    "type": "text",
},

{
    "id": "urbanicity",
    "label": "Tipo de zona onde viveu a maior parte da vida",
    "type": "radio",
    "choices": [
        ("1", "Rural"),
        ("2", "Semiurbano"),
        ("3", "Urbano"),
        ("9", "Prefiro não responder"),
    ]
},

# =====================================================
# IDENTIDADE ÉTNICO-RACIAL / GÉNERO / SEXO
# =====================================================

{
    "id": "race",
    "label": "Pertença étnico-racial (pode selecionar várias)",
    "type": "radio",
    "choices": [
        ("1", "Branca"),
        ("2", "Negra"),
        ("3", "Asiática"),
        ("4", "Cigana"),
        ("5", "Hispânica/Latina"),
        ("6", "Outra"),
        ("9", "Prefiro não responder"),
    ]
},

{
    "id": "gender",
    "label": "Com que género se identifica?",
    "type": "radio",
    "choices": [
        ("1", "Cisgénero"),
        ("2", "Transgénero"),
        ("3", "Não binário"),
        ("9", "Outro / Prefiro não responder"),
    ]
},

{
    "id": "sex",
    "label": "Sexo atribuído à nascença",
    "type": "radio",
    "choices": [
        ("1", "Feminino"),
        ("2", "Masculino"),
        ("4", "Intersexo"),
    ]
},

# =====================================================
# EDUCAÇÃO
# =====================================================

{
    "id": "education",
    "label": "Nível mais alto de escolaridade atingido",
    "type": "radio",
    "choices": [
        ("1", "Alguma educação primária"),
        ("2", "1º Ciclo concluído"),
        ("3", "2º Ciclo concluído"),
        ("4", "3º Ciclo concluído"),
        ("5", "Ensino Secundário concluído"),
        ("6", "Ensino pós-secundário não superior"),
        ("7", "Ensino Superior concluído"),
    ]
},

# =====================================================
# EMPREGO
# =====================================================

{
    "id": "employment",
    "label": "Situação profissional principal",
    "type": "radio",
    "choices": [
        ("1", "Empregado/a"),
        ("2", "Desempregado/a"),
        ("3", "Estudante"),
        ("4", "Pausa na carreira"),
        ("5", "Incapacidade prolongada"),
        ("6", "Reformado/a"),
        ("9", "Outro / Prefiro não responder"),
    ]
},

# =====================================================
# SOCIOECONÓMICO
# =====================================================

{
    "id": "socioeconomic",
    "label": "Nível socioeconómico",
    "type": "radio",
    "choices": [
        ("1", "Baixo"),
        ("2", "Médio-baixo"),
        ("3", "Médio"),
        ("4", "Médio-alto"),
        ("5", "Alto"),
        ("9", "Prefiro não responder"),
    ]
},

{
    "id": "income",
    "label": "Rendimento mensal bruto do agregado familiar",
    "type": "radio",
    "choices": [
        ("1", "Até 1 050€"),
        ("2", "1 051 - 1 201 €"),
        ("3", "1 201 - 1 500 €"),
        ("4", "1 501 - 1 800 €"),
        ("5", "1 801 - 2 800 €"),
        ("6", "2 801 - 4 000 €"),
        ("7", "4 001 - 6 000 €"),
        ("9", "Mais de 6 000€ / Não sei / Prefiro não responder"),
    ]
},

# =====================================================
# FAMÍLIA
# =====================================================

{
    "id": "marital_status",
    "label": "Estado civil",
    "type": "radio",
    "choices": [
        ("1", "Solteiro/a"),
        ("2", "Casado/a ou União de Facto"),
        ("3", "Separado/a ou Divorciado/a"),
        ("4", "Viúvo/a"),
        ("9", "Outro / Prefiro não responder"),
    ]
},

{
    "id": "household_adults",
    "label": "Quantos adultos vivem em sua casa?",
    "type": "radio",
    "choices": [
        ("1", "1 (só eu)"),
        ("2", "2"),
        ("3", "3"),
        ("4", "4"),
        ("5", "5"),
        ("6", "6"),
        ("7", "+6"),
    ]
},

{
    "id": "household_children",
    "label": "Tem filhos?",
    "type": "radio",
    "choices": [
        ("0", "Não"),
        ("1", "1 filho/a"),
        ("2", "2 filhos/as"),
        ("3", "3 filhos/as"),
        ("4", "Mais de 3 filhos/as"),
        ("9", "Prefiro não responder"),
    ]
},

# =====================================================
# ESPIRITUALIDADE
# =====================================================

{
    "id": "spirituality",
    "label": "A religião ou espiritualidade é importante na sua vida?",
    "type": "radio",
    "choices": [
        ("1", "Nada importante"),
        ("2", "Pouco importante"),
        ("3", "Mais ou menos importante"),
        ("4", "Muito importante"),
        ("9", "Prefiro não responder"),
    ]
},

]