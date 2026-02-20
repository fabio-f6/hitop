from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .models import Question, UserAnswer

# Mantemos as opções para o template (mesmo que estejam no model)
answer_choices = Question.ANSWER_CHOICES

@login_required
def questionnaire(request):
    questions = Question.objects.order_by('?')

    if request.method == "POST":
        for question in questions:
            field_name = f"question_{question.id}"
            selected_value = request.POST.get(field_name)

            if selected_value:
                # Salva ou atualiza a resposta do usuário
                UserAnswer.objects.update_or_create(
                    user=request.user,
                    question=question,
                    defaults={'answer': selected_value}
                )

        # redireciona para uma página de "Obrigado" ou resultados
        return redirect("polls:thank_you")

    return render(request, "polls/questionnaire.html", {
        "questions": questions,
        "answer_choices": answer_choices
    })

def index(request):
    latest_question_list = Question.objects.order_by("-id")
    context = {
    	'latest_question_list': latest_question_list
    }
    return render(request, 'polls/index.html', context)

@login_required
def thank_you(request):
    return render(request, "polls/thank_you.html")