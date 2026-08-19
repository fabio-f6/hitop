def translated_name(item):

    return item["name"]

def join_item_names(items):

    return ", ".join(
        translated_name(item)
        for item in items
    )


def build_atypical_text(
    p1,
    p2_p5,
    p95_p98,
    p99,
):

    parts = []

    if p1:

        parts.append(
            f"Os valores obtidos em {join_item_names(p1)} "
            "situam-se no percentil igual ou inferior a P1."
        )

    if p2_p5:

        parts.append(
            f"Os valores obtidos em {join_item_names(p2_p5)} "
            "situam-se entre P2 e P5."
        )

    if p1 or p2_p5:

        parts.append(
            "Assim, os valores desta sintomatologia parecem ter uma "
            "distribuição inferior ao que pessoas com características "
            "semelhantes tendem a reportar."
        )

    if p99:

        parts.append(
            f"Os valores obtidos em {join_item_names(p99)} "
            "situam-se no percentil igual ou superior a P99."
        )

    if p95_p98:

        parts.append(
            f"Os valores obtidos em {join_item_names(p95_p98)} "
            "situam-se entre P95 e P98."
        )

    if p95_p98 or p99:

        parts.append(
            "Assim, os valores desta sintomatologia parecem ter uma "
            "distribuição superior ao que as pessoas com características "
            "semelhantes tendem a reportar."
        )

    return " ".join(parts)


def build_normal_text(p15_p85):

    if not p15_p85:
        return None

    return (
        f"Os valores obtidos em {join_item_names(p15_p85)} "
        "situam-se entre P15 e P85, o que sugere que o nível de "
        "sintomatologia se situa nos intervalos médios esperados "
        "face aos valores de referência."
    )


def build_null_text(null_items):

    if not null_items:
        return None

    return (
        f"Não foi possível calcular os valores obtidos em "
        f"{join_item_names(null_items)}, uma vez que 25% ou mais "
        "dos itens foram respondidos com a opção "
        "\"Não sei / Não aplicável\". Assim, não foi possível "
        "determinar a respetiva pontuação bruta nem comparar "
        "estes resultados com os valores de referência."
    )

def build_report_analysis(items):

    analysis = {

        "p1": [],
        "p2_p5": [],
        "p15_p85": [],
        "p95_p98": [],
        "p99": [],
        "null": [],
        "paragraphs": [],

    }

    for item in items:

        if not item["is_valid"]:

            analysis["null"].append(item)
            continue

        percentile = item["percentile"]

        if percentile <= 1:

            analysis["p1"].append(item)

        elif 2 <= percentile <= 5:

            analysis["p2_p5"].append(item)

        elif 15 <= percentile <= 85:

            analysis["p15_p85"].append(item)

        elif 95 <= percentile <= 98:

            analysis["p95_p98"].append(item)

        elif percentile >= 99:

            analysis["p99"].append(item)

    text = build_atypical_text(

        analysis["p1"],
        analysis["p2_p5"],
        analysis["p95_p98"],
        analysis["p99"],

    )

    if text:
        analysis["paragraphs"].append(text)

    text = build_normal_text(
        analysis["p15_p85"]
    )

    if text:
        analysis["paragraphs"].append(text)

    text = build_null_text(
        analysis["null"]
    )

    if text:
        analysis["paragraphs"].append(text)

    return analysis