def evaluate_attention_checks(answers):

    total = 0
    correct = 0

    for answer in answers:

        question = answer.question

        if not question.is_attention_check:
            continue

        total += 1

        if (
            answer.answer is not None and
            answer.answer == question.expected_answer
        ):
            correct += 1

    return {
        "total": total,
        "correct": correct,
        "incorrect": total - correct,
        "passed": correct == total,
    }