SOCIO_QUESTIONS = [

    # -----------------------
    # IDENTIFICAÇÃO BÁSICA
    # -----------------------

    {
        "id": "age",
        "label": "Qual é a sua idade?",
        "type": "number",
    },
    {
        "id": "gender",
        "label": "Género",
        "type": "radio",
        "choices": [
            ("1", "Masculino"),
            ("2", "Feminino"),
            ("3", "Outro"),
            ("4", "Prefiro não responder"),
        ]
    },

    # -----------------------
    # LÍNGUA / CONTEXTO
    # -----------------------

    {
        "id": "PT_lang",
        "label": "Português é a sua língua materna?",
        "type": "radio",
        "choices": [
            ("1", "Sim"),
            ("2", "Não"),
        ]
    },

    {
        "id": "country_birth",
        "label": "País de nascimento",
        "type": "text",
    },

    {
        "id": "country_residence",
        "label": "País de residência atual",
        "type": "text",
    },

    # -----------------------
    # EDUCAÇÃO
    # -----------------------

    {
        "id": "education_level",
        "label": "Nível de escolaridade",
        "type": "radio",
        "choices": [
            ("1", "Ensino básico"),
            ("2", "Ensino secundário"),
            ("3", "Licenciatura"),
            ("4", "Mestrado"),
            ("5", "Doutoramento"),
        ]
    },

    # -----------------------
    # EMPREGO
    # -----------------------

    {
        "id": "employment",
        "label": "Situação profissional",
        "type": "radio",
        "choices": [
            ("1", "Empregado"),
            ("2", "Desempregado"),
            ("3", "Estudante"),
            ("4", "Reformado"),
        ]
    },

    # -----------------------
    # FAMÍLIA
    # -----------------------

    {
        "id": "marital_status",
        "label": "Estado civil",
        "type": "radio",
        "choices": [
            ("1", "Solteiro"),
            ("2", "Casado/União de facto"),
            ("3", "Divorciado"),
            ("4", "Viúvo"),
        ]
    },

    {
        "id": "children",
        "label": "Tem filhos?",
        "type": "radio",
        "choices": [
            ("1", "Sim"),
            ("2", "Não"),
        ]
    },
]