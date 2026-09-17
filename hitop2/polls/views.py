import json
import math
import random

from django.http import HttpResponse
from django.urls import reverse
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction

from .questions import get_questions_for_submission

from .models import Question, QuestionCategory, DynamicAnswer, UserAnswer, QuestionnaireSubmission

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

last_page_extra_choice = ('5', 'Não sei / Prefiro não responder')

SOCIODEMOGRAPHIC_CATEGORY_NAME = "Dados Sociodemográficos"


def _get_sociodemographic_category():
    return QuestionCategory.objects.filter(
        name=SOCIODEMOGRAPHIC_CATEGORY_NAME
    ).first()


def questionnaire(request):

    user_profile = None

    # ----------------------------
    # TENTAR SUBMISSION DA SESSION
    # ----------------------------
    submission = None

    submission_id = request.session.get("submission_id")

    if submission_id:

        submission = QuestionnaireSubmission.objects.filter(
            id=submission_id,
            questionnaire_type="hitop"
        ).first()

    if submission:
        user_profile = submission.user.userprofile

    # ----------------------------
    # FALLBACK PARA SISTEMA ANTIGO
    # ----------------------------
    if not submission:

        submission = QuestionnaireSubmission.objects.filter(
            user=request.user,
            questionnaire_type="hitop",
            completed=False
        ).order_by("-started_at").first()

        if submission:
            user_profile = submission.user.userprofile

    # ----------------------------
    # SOCIODEMOGRÁFICO
    # ----------------------------
    if not submission:
        return redirect("polls:thank_you")

    # ----------------------------
    # BLOQUEIO POR PROFISSIONAL
    # ----------------------------
    if not submission.is_open:
        return redirect("polls:thank_you")

    if not submission.sociodemographic_completed:
        return redirect("polls:sociodemographic")

    request.session["submission_id"] = submission.id

    # ----------------------------
    # ORDEM DAS QUESTÕES
    # ----------------------------
    if 'question_order' not in request.session:
        questions = list(
            get_questions_for_submission(submission)
        )

        random.shuffle(questions)
        request.session['question_order'] = [q.id for q in questions]

    question_ids = request.session['question_order']
    questions = list(Question.objects.filter(id__in=question_ids))
    questions.sort(key=lambda q: question_ids.index(q.id))

    if not questions:
        messages.error(
            request,
            "Esta submissão não possui spectras configurados."
        )
        return redirect("polls:thank_you")

    # ----------------------------
    # RESPOSTAS PARCIAIS
    # ----------------------------
    partial_answers = request.session.get('partial_answers', {})

    for ua in UserAnswer.objects.filter(submission=submission):
        partial_answers[str(ua.question.id)] = ua.answer

    # ----------------------------
    # PAGINAÇÃO
    # ----------------------------
    page_number = int(request.GET.get('page', 1))
    per_page = math.ceil(len(questions) / 6)
    paginator = Paginator(questions, per_page)
    num_pages = paginator.num_pages

    # ----------------------------
    # POST
    # ----------------------------
    if request.method == "POST":

        if page_number <= num_pages:

            current_page_obj = paginator.get_page(page_number)

        else:

            current_page_obj = [
                q for q in questions
                if str(q.id) not in partial_answers
            ]

        for question in current_page_obj:
            field_name = f"question_{question.id}"
            selected_value = request.POST.get(field_name)

            if selected_value:
                partial_answers[str(question.id)] = selected_value

                UserAnswer.objects.update_or_create(
                    user=submission.user,
                    submission=submission,
                    question=question,
                    defaults={'answer': selected_value}
                )

        request.session['partial_answers'] = partial_answers

        # ----------------------------
        # FINALIZAÇÃO
        # ----------------------------
        if page_number >= num_pages:
            unanswered_ids = [
                q.id for q in questions if str(q.id) not in partial_answers
            ]

            if unanswered_ids:
                return redirect(
                    f"{reverse('polls:questionnaire')}?page={num_pages + 1}"
                )

            request.session.pop('partial_answers', None)
            request.session.pop('question_order', None)
            request.session.pop('submission_id', None)

            submission.completed = True
            submission.completed_at = timezone.now()
            submission.is_open = False
            submission.save()

            return redirect("polls:thank_you")

        return redirect(f"{reverse('polls:questionnaire')}?page={page_number + 1}")

    # ----------------------------
    # GET
    # ----------------------------
    if page_number <= num_pages:
        page_obj = paginator.get_page(page_number)
        current_answer_choices = answer_choices.copy()
    else:
        unanswered_questions = [
            q for q in questions if str(q.id) not in partial_answers
        ]
        page_obj = unanswered_questions
        current_answer_choices = answer_choices.copy() + [last_page_extra_choice]

    progress = (
        page_number / num_pages
    ) * 100 if page_number <= num_pages else 100

    return render(request, "polls/questionnaire.html", {
        "page_obj": page_obj,
        "answer_choices": current_answer_choices,
        "progress": progress,
        "partial_answers": partial_answers,
        "page_number": page_number,
        "num_pages": num_pages,
    })

@login_required
def index(request):
    latest_question_list = Question.objects.order_by("id")
    context = {
    	'latest_question_list': latest_question_list
    }
    return render(request, 'polls/index.html', context)

def thank_you(request):

    request.session.pop(
        "anonymous_questionnaire",
        None
    )

    return render(
        request,
        "polls/thank_you.html"
    )

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

def sociodemographic_form(request):
    submission_id = request.session.get("submission_id")
    if not submission_id:
        return redirect("polls:thank_you")

    submission = get_object_or_404(
        QuestionnaireSubmission,
        id=submission_id,
        questionnaire_type="hitop",
        is_open=True,
    )
    category = _get_sociodemographic_category()
    if not category or not category.questions.exists():
        messages.error(request, "As perguntas ainda não foram configuradas.")
        return redirect("polls:thank_you")

    return _dynamic_questionnaire_response(
        request=request,
        category=category,
        user=submission.user,
        submission=submission,
        success_redirect="polls:questionnaire",
    )


@login_required
def dynamic_questionnaire(request, category_id):
    category = get_object_or_404(QuestionCategory, id=category_id)
    return _dynamic_questionnaire_response(
        request=request,
        category=category,
        user=request.user,
        success_redirect="polls:index",
    )


def _dynamic_answer_value(answer):
    if answer.question.question_type != "checkbox":
        return answer.answer_value
    try:
        value = json.loads(answer.answer_value)
    except json.JSONDecodeError:
        return [answer.answer_value]
    return value if isinstance(value, list) else [answer.answer_value]


def _question_is_visible(question, values):
    if not question.show_if_question:
        return True
    parent_value = values.get(question.show_if_question, "")
    if not isinstance(parent_value, list):
        parent_value = [parent_value]
    return bool(set(parent_value) & set(question.show_if_values))


def _dynamic_questionnaire_response(
    request, category, user, submission=None, success_redirect="polls:index",
):
    questions = list(
        category.questions.all().prefetch_related("choices").order_by("order", "id")
    )
    if not questions:
        messages.error(request, "Este questionário não tem perguntas.")
        return redirect(success_redirect)

    sections = {}
    for question in questions:
        sections.setdefault(question.section or category.name, []).append(question)
    section_names = list(sections)

    previous_answers = DynamicAnswer.objects.filter(
        user=user, submission=submission, question__category=category,
    ).select_related("question")
    values = {
        answer.question.question_id: _dynamic_answer_value(answer)
        for answer in previous_answers
    }

    first_incomplete = (
        len(section_names) - 1
        if submission and not submission.sociodemographic_completed else 0
    )
    if submission and not submission.sociodemographic_completed:
        for index, section_name in enumerate(section_names):
            if any(
                question.required
                and _question_is_visible(question, values)
                and not values.get(question.question_id)
                for question in sections[section_name]
            ):
                first_incomplete = index
                break

    try:
        section_index = int(request.GET.get("section", first_incomplete))
    except ValueError:
        section_index = first_incomplete
    section_index = max(0, min(section_index, len(section_names) - 1))
    if submission and not submission.sociodemographic_completed:
        section_index = min(section_index, first_incomplete)

    current_questions = sections[section_names[section_index]]
    error = False

    if request.method == "POST":
        submitted = dict(values)
        for question in current_questions:
            field_name = f"question_{question.id}"
            if question.question_type == "checkbox":
                submitted[question.question_id] = request.POST.getlist(field_name)
            else:
                submitted[question.question_id] = request.POST.get(
                    field_name, ""
                ).strip()

        for question in current_questions:
            if not _question_is_visible(question, submitted):
                submitted[question.question_id] = [] if question.question_type == "checkbox" else ""
                continue

            value = submitted[question.question_id]
            if question.required and not value:
                error = True
            if question.question_type in ("radio", "checkbox"):
                selected = value if isinstance(value, list) else [value]
                valid = {choice.value for choice in question.choices.all()}
                if any(option not in valid for option in selected):
                    error = True
            if question.question_type == "number" and value:
                if not value.isdecimal():
                    error = True

        if error:
            messages.error(request, "Revise as respostas obrigatórias desta secção.")
            values = submitted
        else:
            with transaction.atomic():
                DynamicAnswer.objects.filter(
                    user=user,
                    submission=submission,
                    question__in=current_questions,
                ).delete()
                for question in current_questions:
                    value = submitted[question.question_id]
                    if value:
                        DynamicAnswer.objects.create(
                            user=user,
                            submission=submission,
                            question=question,
                            answer_value=(
                                json.dumps(value)
                                if isinstance(value, list) else value
                            ),
                        )
                if submission and section_index == len(section_names) - 1:
                    submission.sociodemographic_completed = True
                    submission.save(update_fields=["sociodemographic_completed"])

            if section_index == len(section_names) - 1:
                return redirect(success_redirect)
            return redirect(f"{request.path}?section={section_index + 1}")

    answers_by_id = {
        question.id: values.get(question.question_id, "")
        for question in current_questions
    }
    return render(request, "polls/dynamic_questionnaire.html", {
        "category": category,
        "questions": current_questions,
        "answers": answers_by_id,
        "section_name": section_names[section_index],
        "section_index": section_index,
        "section_total": len(section_names),
        "previous_index": section_index - 1,
        "submit_label": (
            "Concluir" if section_index == len(section_names) - 1
            else "Guardar e continuar"
        ),
    })
def questionnaire_by_token(request, token):

    submission = QuestionnaireSubmission.objects.filter(
        access_token=token,
        is_open=True
    ).first()

    if not submission:
        return invalid_questionnaire_link(request, token)

    if request.session.get("submission_id") != submission.id:
        request.session.pop("question_order", None)
        request.session.pop("partial_answers", None)

    request.session["submission_id"] = submission.id
    request.session["anonymous_questionnaire"] = True

    return redirect("polls:questionnaire")


def invalid_questionnaire_link(request, token):
    request.session.pop("submission_id", None)
    request.session.pop("anonymous_questionnaire", None)

    return render(
        request,
        "polls/invalid_link.html"
    )
