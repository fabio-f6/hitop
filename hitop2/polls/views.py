import math
import random

from django.http import HttpResponse
from django.urls import reverse
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.core.paginator import Paginator

from .models import Question, UserAnswer

from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer


answer_choices = [
    ('1', 'Nunca'),
    ('2', 'Raramente'),
    ('3', 'Às vezes'),
    ('4', 'Sempre'),
]

# opção extra da última página
last_page_extra_choice = ('5', 'Não sei / Prefiro não responder')

def questionnaire(request):
    user_profile = request.user.userprofile

    # Inicializa ordem das questões na sessão
    if 'question_order' not in request.session:
        questions = list(
            Question.objects.filter(
                scale__subfactor__spectra__in=user_profile.spectra.all()
            ).distinct()
        )
        random.shuffle(questions)
        request.session['question_order'] = [q.id for q in questions]

    question_ids = request.session['question_order']
    questions = list(Question.objects.filter(id__in=question_ids))
    questions.sort(key=lambda q: question_ids.index(q.id))

    # Paginação
    per_page = math.ceil(len(questions) / 6)
    paginator = Paginator(questions, per_page)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # Carrega respostas parciais já salvas na sessão ou DB
    partial_answers = request.session.get('partial_answers', {})
    user_answers_qs = UserAnswer.objects.filter(user=request.user)
    for ua in user_answers_qs:
        partial_answers[str(ua.question.id)] = ua.answer

    if request.method == "POST":
        # Salva respostas da página atual
        for question in page_obj:
            field_name = f"question_{question.id}"
            selected_value = request.POST.get(field_name)

            if selected_value:
                partial_answers[str(question.id)] = selected_value
                UserAnswer.objects.update_or_create(
                    user=request.user,
                    question=question,
                    defaults={'answer': selected_value}
                )

        request.session['partial_answers'] = partial_answers

        # Última página: verifica se todas as perguntas foram respondidas
        if not page_obj.has_next():
            unanswered = [q for q in page_obj if str(q.id) not in partial_answers]
            if unanswered:
                messages.error(request, "Por favor, responda todas as perguntas antes de finalizar.")
                return redirect(f"{reverse('polls:questionnaire')}?page={page_obj.number}")

        # Próxima página ou finaliza
        if page_obj.has_next():
            return redirect(f"{reverse('polls:questionnaire')}?page={page_obj.next_page_number()}")
        else:
            # Remove respostas parciais da sessão ao finalizar
            request.session.pop('partial_answers', None)
            return redirect("polls:thank_you")

    # Calcula progress bar
    progress = (page_obj.number / page_obj.paginator.num_pages) * 100

    # Define choices da página atual (última página inclui opção extra)
    current_answer_choices = answer_choices.copy()
    if not page_obj.has_next():
        current_answer_choices.append(last_page_extra_choice)

    return render(request, "polls/questionnaire.html", {
        "page_obj": page_obj,
        "answer_choices": current_answer_choices,
        "progress": progress,
        "partial_answers": partial_answers
    })

@login_required
def index(request):
    latest_question_list = Question.objects.order_by("id")
    context = {
    	'latest_question_list': latest_question_list
    }
    return render(request, 'polls/index.html', context)

@login_required
def thank_you(request):
    return render(request, "polls/thank_you.html")

def export_patient_pdf(request, user_id):
    user = User.objects.get(id=user_id)
    answers = UserAnswer.objects.filter(user=user).select_related('question')

    try:
        professional_name = user.userprofile.professional.get_full_name() if user.userprofile.professional else "Não especificado"
    except AttributeError:
        professional_name = "Não especificado"

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="respostas_{user.username}.pdf"'

    doc = SimpleDocTemplate(response, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    elements = []
    styles = getSampleStyleSheet()

    elements.append(Paragraph(f"Relatório de Respostas - Paciente: {user.get_full_name() or user.username}", styles['Title']))
    elements.append(Spacer(1, 12))

    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    info_text = f"""
        <b>Profissional:</b> {professional_name}<br/>
        <b>Data de geração do relatório:</b> {now_str}<br/>
        <b>Total de respostas:</b> {answers.count()}<br/>
    """
    elements.append(Paragraph(info_text, styles['Normal']))
    elements.append(Spacer(1, 12))

    data = [["Pergunta", "Resposta", "Data da resposta"]]
    for ua in answers:
        data.append([ua.question.question_text, ua.get_answer_display(), ua.answered_at.strftime("%d/%m/%Y %H:%M")])

    table = Table(data, colWidths=[300, 100, 120], repeatRows=1)
    table_style = TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#9ec9ff')),  # cabeçalho azul suave
        ('TEXTCOLOR', (0,0), (-1,0), colors.black),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 12),
        ('ALIGN', (0,0), (-1,0), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.whitesmoke, colors.HexColor('#e2f0ff')]),  # linhas alternadas azul suave
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ])
    table.setStyle(table_style)

    elements.append(table)
    doc.build(elements)

    return response