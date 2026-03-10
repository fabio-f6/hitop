from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User

from .models import Question, UserAnswer

from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer


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
    # Obtém o paciente
    user = User.objects.get(id=user_id)
    answers = UserAnswer.objects.filter(user=user).select_related('question')

    # Exemplo: supondo que você tenha userprofile e queira o profissional associado
    try:
        professional_name = user.userprofile.professional.get_full_name() if user.userprofile.professional else "Não especificado"
    except AttributeError:
        professional_name = "Não especificado"

    # Cria a resposta HTTP como PDF
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="respostas_{user.username}.pdf"'

    # Cria o documento
    doc = SimpleDocTemplate(response, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    elements = []
    styles = getSampleStyleSheet()

    # Título do relatório
    elements.append(Paragraph(f"Relatório de Respostas - Paciente: {user.get_full_name() or user.username}", styles['Title']))
    elements.append(Spacer(1, 12))

    # Informações extras
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    info_text = f"""
        <b>Profissional:</b> {professional_name}<br/>
        <b>Data de geração do relatório:</b> {now_str}<br/>
        <b>Total de respostas:</b> {answers.count()}<br/>
    """
    elements.append(Paragraph(info_text, styles['Normal']))
    elements.append(Spacer(1, 12))

    # Cabeçalho da tabela
    data = [["Pergunta", "Resposta", "Data da resposta"]]
    for ua in answers:
        data.append([ua.question.question_text, ua.get_answer_display(), ua.answered_at.strftime("%d/%m/%Y %H:%M")])

    # Cria a tabela
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