from collections import defaultdict

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Q
from django.http import HttpResponse
from django.views.decorators.http import require_http_methods, require_POST
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from polls.attention_checks import evaluate_attention_checks
from polls.models import (
    DynamicAnswer,
    NormativeDatasetVersion,
    QuestionnaireCollection,
    QuestionnaireSubmission,
    SociodemographicAnswer,
    UserAnswer,
)
from polls.percentiles import (
    calculate_percentile,
    calculate_spectrum_percentile,
)
from polls.questions import get_questions_for_submission
from polls.normative_export import evaluate_normative_eligibility
from polls.normative_versions import get_or_assign_report_normative_version
from polls.report_constants import SPECTRUM_KEYS
from polls.report_interpretation import build_report_analysis
from polls.scoring import calculate_scale_scores_from_answers
from polls.spectrum_scores import calculate_spectrum_scores
from polls.translations import translate_scale, translate_spectrum

from .forms import EditPatientForm, QuestionnaireCollectionForm, SignUpForm
from .models import UserProfile
from .patient_deletion import (
    ActivePatientDeletionBlocked,
    PendingNormativeStatusBlocked,
    permanently_delete_patient,
)
from .professional_environment import (
    ProfessionalEnvironment,
    archive_patient_response,
    archived_patients_response,
    create_patient_response,
    dashboard_response,
    new_questionnaire_response,
    patient_answers_response,
    patient_submissions_response,
    restore_patient_response,
)
from .decorators import (
    PENDING_VERIFICATION_MESSAGE,
    can_use_general_collections,
    collection_owner_is_authorized,
    is_unverified_professional,
    researcher_required,
    verified_professional_required,
)
from administration.audit import record_admin_action
from administration.models import AdministrativeAuditLog
from email_notifications.forms import EmailNotificationPreferencesForm
from email_notifications.services import notify_professional_registration, preferences_for


@researcher_required
def collection_list(request):
    collections = (
        QuestionnaireCollection.objects.filter(owner=request.user, is_test_data=False)
        .annotate(
            submission_count=Count("submissions"),
            completed_count=Count("submissions", filter=Q(submissions__completed=True)),
        )
    )
    return render(request, "website/collection_list.html", {
        "collections": collections,
        "collection_create_url_name": "website:collection_create",
        "collection_detail_url_name": "website:collection_detail",
        "collection_heading": "Coletas Gerais",
    })


@researcher_required
def collection_create(request):
    form = QuestionnaireCollectionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        collection = form.save(commit=False)
        collection.owner = request.user
        collection.is_test_data = False
        collection.save()
        form.save_m2m()
        record_admin_action(
            actor=request.user,
            action=AdministrativeAuditLog.Action.COLLECTION_CREATED,
            object_type=AdministrativeAuditLog.ObjectType.QUESTIONNAIRE_COLLECTION,
            object_id=collection.pk,
            object_label=collection.name,
        )
        messages.success(request, "Coleta Geral criada com sucesso.")
        return redirect("website:collection_detail", collection_id=collection.pk)
    return render(request, "website/collection_form.html", {
        "form": form,
        "collection_list_url_name": "website:collection_list",
        "collection_form_heading": "Nova Coleta Geral",
    })


@researcher_required
def collection_detail(request, collection_id):
    collection = get_object_or_404(
        QuestionnaireCollection.objects.prefetch_related("spectra"),
        pk=collection_id,
        owner=request.user,
    )
    submissions = collection.submissions.order_by("-participant_number")
    counts = submissions.aggregate(
        total=Count("id"),
        completed_total=Count("id", filter=Q(completed=True)),
        incomplete_total=Count("id", filter=Q(completed=False)),
    )
    public_url = request.build_absolute_uri(
        reverse("website:collection_public", args=[collection.public_token])
    )
    return render(request, "website/collection_detail.html", {
        "collection": collection,
        "submissions": submissions,
        "counts": counts,
        "public_url": public_url,
        "collection_list_url_name": "website:collection_list",
        "collection_toggle_url_name": "website:collection_toggle",
        "collection_report_preview_url_name": "website:collection_report_preview",
        "collection_report_export_url_name": "website:collection_report_export",
    })


@require_POST
@researcher_required
def collection_toggle(request, collection_id):
    collection = get_object_or_404(
        QuestionnaireCollection, pk=collection_id, owner=request.user,
    )
    collection.is_active = not collection.is_active
    collection.save(update_fields=["is_active", "updated_at"])
    action = (
        AdministrativeAuditLog.Action.COLLECTION_ACTIVATED
        if collection.is_active
        else AdministrativeAuditLog.Action.COLLECTION_DEACTIVATED
    )
    record_admin_action(
        actor=request.user,
        action=action,
        object_type=AdministrativeAuditLog.ObjectType.QUESTIONNAIRE_COLLECTION,
        object_id=collection.pk,
        object_label=collection.name,
    )
    return redirect("website:collection_detail", collection_id=collection.pk)


def collection_public(request, token):
    collection = get_object_or_404(QuestionnaireCollection, public_token=token)
    return render(request, "website/collection_public.html", {
        "collection": collection,
        "collection_available": (
            collection.is_active
            and collection_owner_is_authorized(collection)
        ),
    })


@require_POST
def collection_start(request, token):
    with transaction.atomic():
        collection = get_object_or_404(
            QuestionnaireCollection.objects.select_for_update(), public_token=token,
        )
        if (
            not collection.is_active
            or not collection_owner_is_authorized(collection)
        ):
            messages.error(request, "Esta coleta não está disponível neste momento.")
            return redirect("website:collection_public", token=token)

        current_id = request.session.get("submission_id")
        current_token = request.session.get("submission_access_token")
        submission = QuestionnaireSubmission.objects.filter(
            pk=current_id,
            collection=collection,
            is_open=True,
            completed=False,
            access_token=current_token,
        ).first() if current_id and current_token else None
        if submission is None:
            last_number = collection.submissions.aggregate(value=Max("participant_number"))["value"] or 0
            submission = QuestionnaireSubmission.objects.create(
                collection=collection,
                participant_number=last_number + 1,
                title=collection.name,
                questionnaire_type="hitop",
                no_identifying_data_confirmed=True,
                is_test_data=collection.is_test_data,
            )
            submission.spectra.set(collection.spectra.all())
            get_or_assign_report_normative_version(submission)

    request.session.cycle_key()
    request.session["submission_id"] = submission.pk
    request.session["submission_access_token"] = str(submission.access_token)
    request.session["anonymous_questionnaire"] = True
    return redirect("polls:sociodemographic")


def _owned_collection_submission_or_404(user, submission_id):
    return get_object_or_404(
        QuestionnaireSubmission.objects.select_related("collection"),
        pk=submission_id,
        collection__owner=user,
    )


@researcher_required
def collection_report_preview(request, submission_id):
    submission = _owned_collection_submission_or_404(request.user, submission_id)
    if not submission.completed:
        return HttpResponse("O relatório ainda não está disponível.", status=409)
    context = _build_report_context(submission)
    context.update({
        "is_collection_submission": True,
        "collection_detail_url": reverse(
            "website:collection_detail", args=[submission.collection_id]
        ),
        "collection_export_url": reverse(
            "website:collection_report_export", args=[submission.pk]
        ),
    })
    return render(request, "website/report_preview.html", context)


@researcher_required
def collection_report_export(request, submission_id):
    submission = _owned_collection_submission_or_404(request.user, submission_id)
    if not submission.completed:
        return HttpResponse("O relatório ainda não está disponível.", status=409)
    from .docx_report import build_report_docx
    document = build_report_docx(_build_report_context(submission))
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    response["Content-Disposition"] = (
        f'attachment; filename="relatorio-coleta-{submission.participant_number:03d}.docx"'
    )
    response.write(document.getvalue())
    return response


def home(request):

    # Se já estiver autenticado, não faz sentido mostrar a landing page
    if request.user.is_authenticated:

        if is_unverified_professional(request.user):
            logout(request)
            messages.error(request, PENDING_VERIFICATION_MESSAGE)
            return redirect("website:home")

        if request.user.userprofile.user_type == "professional":
            return redirect("website:dashboard")

        elif request.user.userprofile.user_type == "patient":
            return redirect("polls:questionnaire")

        elif request.user.userprofile.user_type == "admin":
            return redirect("administration:dashboard")

        else:
            return redirect("website:home")

    # Login
    if request.method == "POST":

        username = request.POST["username"]
        password = request.POST["password"]

        user = authenticate(
            request,
            username=username,
            password=password
        )

        if user is not None:

            if is_unverified_professional(user):
                messages.error(request, PENDING_VERIFICATION_MESSAGE)
                return redirect("website:home")

            login(request, user)

            messages.success(
                request,
                "Logged in successfully!"
            )

            if user.userprofile.user_type == "patient":
                return redirect("polls:questionnaire")

            elif user.userprofile.user_type == "professional":
                return redirect("website:dashboard")

            elif user.userprofile.user_type == "admin":
                return redirect("administration:dashboard")

            else:
                return redirect("website:home")

        else:

            messages.error(
                request,
                "Invalid username or password."
            )

            return redirect("website:home")

    return render(
        request,
        "website/home.html"
    )

def logout_user(request):
    logout(request)
    messages.success(request, "Logged out successfully!")
    return redirect('website:home')


def username_unavailable(request):
    return render(
        request,
        "website/username_unavailable.html",
        status=409,
    )


def register_user(request):
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            # cria o usuário mas ainda não salva completamente
            user = form.save(commit=False)

            # gera username automaticamente a partir do email
            user.username = form.cleaned_data['email'].split('@')[0]

            if User.objects.filter(username=user.username).exists():
                return username_unavailable(request)

            try:
                with transaction.atomic():
                    user.save()
                    # atualiza o perfil que já foi criado automaticamente
                    profile = user.userprofile
                    profile.user_type = 'professional'  # apenas profissionais podem registrar
                    profile.is_verified = False
                    profile.area_formacao = form.cleaned_data['area_formacao']
                    profile.objetivo_uso = form.cleaned_data['objetivo_uso']
                    profile.cedula_profissional = form.cleaned_data['cedula_profissional']
                    profile.save()
                    notify_professional_registration(profile)
            except IntegrityError:
                return username_unavailable(request)

            messages.success(
                request,
                "O pedido de registo foi submetido com sucesso. "
                "A sua conta aguarda verificação por um administrador. "
                f"O seu nome de utilizador é: {user.username}",
            )
            return redirect('website:home')

    else:
        form = SignUpForm()

    return render(request, 'website/register.html', {'form': form})


@login_required(login_url="website:home")
def notification_preferences(request):
    preferences = preferences_for(request.user)
    profile = request.user.userprofile
    form = EmailNotificationPreferencesForm(request.POST or None, instance=preferences)

    visible_fields = set()
    if profile.user_type == "admin":
        visible_fields.add("professional_registration")
    elif profile.user_type == "professional":
        visible_fields.add("questionnaire_completed")
        if profile.is_researcher:
            visible_fields.add("collection_daily_summary")

    for field_name in list(form.fields):
        if field_name != "email_notifications_enabled" and field_name not in visible_fields:
            form.fields.pop(field_name)

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Preferências de notificações guardadas com sucesso.")
        return redirect("website:notification_preferences")

    return render(request, "website/notification_preferences.html", {
        "form": form,
        "profile": profile,
    })

@verified_professional_required
def create_patient(request):
    return create_patient_response(
        request,
        ProfessionalEnvironment.clinical(request.user),
    )

@verified_professional_required
def edit_patient(request, patient_id):
    patient_profile = get_object_or_404(UserProfile, id=patient_id, user_type='patient')

    if patient_profile.professional != request.user:
        messages.error(request, "Sem permissão.")
        return redirect('website:dashboard')

    if request.method == "POST":
        form = EditPatientForm(request.POST, instance=patient_profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Paciente atualizado com sucesso.")
            return redirect('website:dashboard')
    else:
        form = EditPatientForm(instance=patient_profile)

    return render(request, 'website/edit_patient.html', {
            'form': form,
            'patient': patient_profile
            })

@verified_professional_required
def new_questionnaire(request, patient_id):
    return new_questionnaire_response(
        request,
        ProfessionalEnvironment.clinical(request.user),
        patient_id,
    )

@verified_professional_required
def dashboard(request):
    return dashboard_response(
        request,
        ProfessionalEnvironment.clinical(request.user),
    )


@verified_professional_required
def archived_patients(request):
    return archived_patients_response(
        request,
        ProfessionalEnvironment.clinical(request.user),
    )


@require_POST
@verified_professional_required
def archive_patient(request, patient_id):
    return archive_patient_response(
        request,
        ProfessionalEnvironment.clinical(request.user),
        patient_id,
    )


@require_POST
@verified_professional_required
def restore_patient(request, patient_id):
    return restore_patient_response(
        request,
        ProfessionalEnvironment.clinical(request.user),
        patient_id,
    )


@require_http_methods(["GET", "POST"])
@verified_professional_required
def permanently_delete_patient_view(request, patient_id):
    patient = get_object_or_404(
        UserProfile.objects.select_related("user"),
        id=patient_id,
        user_type="patient",
        professional=request.user,
        archived_at__isnull=False,
    )

    submissions = QuestionnaireSubmission.objects.filter(user=patient.user)
    has_pending_submissions = submissions.filter(
        normative_status=QuestionnaireSubmission.NormativeStatus.PENDING,
    ).exists()

    if request.method == "POST":
        try:
            permanently_delete_patient(
                patient_id=patient.id,
                professional=request.user,
            )
        except ActivePatientDeletionBlocked:
            messages.error(
                request,
                "Apenas pacientes arquivados podem ser eliminados permanentemente.",
            )
            return redirect("website:dashboard")
        except PendingNormativeStatusBlocked:
            messages.error(
                request,
                "A eliminação foi bloqueada: existem aplicações cujo estado "
                "relativamente à base normativa ainda não foi determinado.",
            )
            return redirect("website:archived_patients")

        messages.success(request, "Paciente e dados clínicos eliminados permanentemente.")
        return redirect("website:archived_patients")

    return render(
        request,
        "website/confirm_permanent_patient_deletion.html",
        {
            "patient": patient,
            "submission_count": submissions.count(),
            "has_pending_submissions": has_pending_submissions,
        },
    )

@verified_professional_required
def patient_answers(request, submission_id):
    return patient_answers_response(
        request,
        ProfessionalEnvironment.clinical(request.user),
        submission_id,
    )

@verified_professional_required
def patient_submissions(request, patient_id):
    return patient_submissions_response(
        request,
        ProfessionalEnvironment.clinical(request.user),
        patient_id,
    )

@verified_professional_required
def submission_detail(request, submission_id):

    submission = get_object_or_404(
        QuestionnaireSubmission,
        id=submission_id
    )

    # segurança: só o profissional dono pode ver
    if submission.user.userprofile.professional != request.user:
        messages.error(request, "Acesso negado.")
        return redirect("website:dashboard")

    answers = UserAnswer.objects.filter(
        submission=submission
    ).select_related('question')

    return render(request, "website/submission_detail.html", {
        "submission": submission,
        "answers": answers
    })

def _report_sociodemographics(submission):
    fields = ("age", "sex", "gender", "education")
    socio = {
        answer.question_id: answer.answer_label
        for answer in SociodemographicAnswer.objects.filter(
            user=submission.user,
            question_id__in=fields,
        )
    }

    answers = DynamicAnswer.objects.filter(
        submission=submission,
        user=submission.user,
        question__question_id__in=fields,
    ).select_related("question").prefetch_related("question__choices")

    for answer in answers:
        question = answer.question
        if question.question_type in ("radio", "checkbox"):
            socio[question.question_id] = next(
                (choice.label for choice in question.choices.all()
                 if choice.value == answer.answer_value),
                answer.answer_value,
            )
        else:
            socio[question.question_id] = answer.answer_value

    return socio


def _build_report_context(submission):
    patient = submission.user
    normative_version = submission.report_normative_version
    normative_version_name = (
        submission.report_normative_version_name
        or (normative_version.name if normative_version else "")
    )
    normative_version_environment = (
        submission.report_normative_version_environment
        or (normative_version.environment if normative_version else "")
    )
    normative_environment_display = dict(
        NormativeDatasetVersion.Environment.choices
    ).get(normative_version_environment, "")
    normative_version_was_removed = bool(
        normative_version_name and normative_version is None
    )
    if normative_version_name:
        normative_version_display = (
            f"{normative_version_name} ({normative_environment_display})"
        )
        if normative_version_was_removed:
            normative_version_display += " — versão removida"
    else:
        normative_version_display = "ainda não atribuída"

    answers = UserAnswer.objects.filter(
        submission=submission,
        question__in=get_questions_for_submission(submission),
    ).select_related(
        "question__scale__subfactor__spectra"
    ).distinct()

    scale_scores = calculate_scale_scores_from_answers(answers)

    attention_checks = evaluate_attention_checks(answers)

    spectrum_scores = calculate_spectrum_scores(
        scale_scores
    )

    spectrum_results = {}

    for spectrum, spectrum_data in spectrum_scores.items():

        spectrum_results[spectrum] = {

            "score":
                spectrum_data["score"],

            "percentile":
                calculate_spectrum_percentile(
                    spectrum,
                    spectrum_data["score"],
                    version=normative_version,
                ) if spectrum_data["is_valid"] else None,

            "missing_answers":
                spectrum_data["missing_answers"],

            "missing_percentage":
                spectrum_data["missing_percentage"],

            "is_valid":
                spectrum_data["is_valid"],

            "total_items":
                spectrum_data["total_items"],

        }

    grouped_scores = defaultdict(list)

    for scale, scale_data in scale_scores.items():

        spectrum_name = scale.subfactor.spectra.name

        group_key = SPECTRUM_KEYS.get(
            spectrum_name,
            "other",
        )

        grouped_scores[group_key].append({

            "scale": scale,

            "name":
                    translate_scale(
                        scale.name,
                    ),

            "score":
                scale_data["score"],

            "percentile":
                calculate_percentile(
                    scale,
                    scale_data["score"],
                    version=normative_version,
                ) if scale_data["is_valid"] else None,

            "missing_answers":
                scale_data["missing_answers"],

            "missing_percentage":
                scale_data["missing_percentage"],

            "is_valid":
                scale_data["is_valid"],

            "total_items":
                scale_data["total_items"],

        })

    grouped_chart_data = {}

    global_chart_data = {}

    # Gráfico

    GRAPH_LEFT = 640
    GRAPH_RIGHT = 1170
    GRAPH_WIDTH = GRAPH_RIGHT - GRAPH_LEFT

    PERCENTILE_MARKS = [

        {
            "label": "P1",
            "line_x": GRAPH_LEFT + (1 / 100) * GRAPH_WIDTH,
            "label_x": GRAPH_LEFT + 12,
        },

        {
            "label": "P5",
            "line_x": GRAPH_LEFT + (5 / 100) * GRAPH_WIDTH,
            "label_x": GRAPH_LEFT + 35,
        },

        {
            "label": "P15",
            "line_x": GRAPH_LEFT + (15 / 100) * GRAPH_WIDTH,
            "label_x": GRAPH_LEFT + 85,
        },

        {
            "line_x": GRAPH_LEFT + (50 / 100) * GRAPH_WIDTH,
        },

        {
            "label": "P85",
            "line_x": GRAPH_LEFT + (85 / 100) * GRAPH_WIDTH,
            "label_x": GRAPH_RIGHT - 85,
        },

        {
            "label": "P95",
            "line_x": GRAPH_LEFT + (95 / 100) * GRAPH_WIDTH,
            "label_x": GRAPH_RIGHT - 28,
        },

        {
            "label": "P99",
            "line_x": GRAPH_LEFT + (99 / 100) * GRAPH_WIDTH,
            "label_x": GRAPH_RIGHT + 6,
        },

    ]

    FIRST_ROW_Y = 55
    ROW_HEIGHT = 28

    for spectrum, items in grouped_scores.items():

        chart_items = []

        chart_height = FIRST_ROW_Y + len(items) * ROW_HEIGHT

        y = FIRST_ROW_Y

        for item in items:

            chart_items.append({

                "name":
                    item["name"],

                "score":
                    item["score"],

                "percentile":
                    item["percentile"],

                "missing_answers":
                    item["missing_answers"],

                "missing_percentage":
                    item["missing_percentage"],

                "is_valid":
                    item["is_valid"],

                "x":
                    None if item["percentile"] is None else
                    GRAPH_LEFT + (
                        item["percentile"] / 100
                    ) * GRAPH_WIDTH,

                "y":
                    y,

            })

            y += ROW_HEIGHT

        grouped_chart_data[spectrum] = {

            "items": chart_items,
            "height": chart_height,
        }

    global_items = []

    chart_height = (
        FIRST_ROW_Y
        + len(spectrum_results) * ROW_HEIGHT
    )

    y = FIRST_ROW_Y

    for spectrum, data in spectrum_results.items():

        global_items.append({

            "name":
                translate_spectrum(
                    spectrum.name,
                ),

            "score":
                data["score"],

            "percentile":
                data["percentile"],

            "missing_answers":
                data["missing_answers"],

            "missing_percentage":
                data["missing_percentage"],

            "is_valid":
                data["is_valid"],

            "x":
                None if data["percentile"] is None else
                GRAPH_LEFT + (
                    data["percentile"] / 100
                ) * GRAPH_WIDTH,

            "y":
                y,

        })

        y += ROW_HEIGHT


    global_chart_data = {

        "items": global_items,
        "height": chart_height,
    }

    if submission.collection_id:
        professional = submission.collection.owner
        professional_profile = professional.userprofile
        professional_area = professional_profile.area_formacao
        professional_license = professional_profile.cedula_profissional
        subject_label = (
            f"Coleta Geral: {submission.collection.name} — "
            f"Participação: {submission.participant_label}"
        )
    else:
        patient_profile = patient.userprofile
        subject_label = patient.username
    if not submission.collection_id and submission.is_test_data:
        professional = patient_profile.test_environment_owner
        professional_area = "Ambiente administrativo de teste"
        professional_license = "Não aplicável"
    elif not submission.collection_id:
        professional = patient_profile.professional
        professional_area = professional.userprofile.area_formacao
        professional_license = professional.userprofile.cedula_profissional

    socio = _report_sociodemographics(submission)

    report_data = {

        "patient_name":
            subject_label,

        "age":
            socio.get("age", "-"),

        "sex":
            socio.get("sex", "-"),

        "gender":
            socio.get("gender", "-"),

        "education":
            socio.get("education", "-"),

        "professional_name":
            professional.get_full_name()
            or professional.username,

        "professional_area":
            professional_area,

        "professional_license":
            professional_license,

        "submission_date":
            submission.started_at,
    }

    analysis = {}

    global_analysis = build_report_analysis(
        [
            {
                "name": translate_spectrum(spectrum.name),
                **data,
            }
            for spectrum, data in spectrum_results.items()
        ]
    )

    for spectrum, items in grouped_scores.items():

        analysis[spectrum] = build_report_analysis(
            items
        )

    detailed_section_titles = {
        "externalizing": "Externalização",
        "internalizing": "Internalização",
        "detachment": "Desafiliação",
        "somatization": "Somatização",
        "thought_disorder": "Alterações de pensamento",
    }

    detailed_sections = [
        {
            "key": key,
            "title": title,
            "chart": grouped_chart_data[key],
            "analysis": analysis[key],
        }
        for key, title in detailed_section_titles.items()
        if key in grouped_chart_data
    ]

    return {
            "submission": submission,
            "normative_version": normative_version,
            "normative_version_display": normative_version_display,
            "normative_version_was_removed": normative_version_was_removed,
            "report": report_data,
            "scale_scores": scale_scores,
            "attention_checks": attention_checks,
            "grouped_scores": grouped_scores,
            "grouped_chart_data": grouped_chart_data,
            "analysis": analysis,
            "detailed_sections": detailed_sections,
            "spectrum_results": spectrum_results,
            "global_chart_data": global_chart_data,
            "global_analysis": global_analysis,
            "percentile_marks": PERCENTILE_MARKS,
            "graph_left": GRAPH_LEFT,
            "graph_right": GRAPH_RIGHT,
            "graph_width": GRAPH_WIDTH,
        }


def _report_context_for_environment(submission, environment):
    context = _build_report_context(submission)
    context.update(environment.template_context())
    context["normative_eligibility"] = (
        evaluate_normative_eligibility(submission)
        if environment.is_test_environment
        else None
    )
    return context


def report_preview_response(request, submission, environment):
    return render(
        request,
        "website/report_preview.html",
        _report_context_for_environment(submission, environment),
    )


def export_report_docx_response(submission, environment):
    from .docx_report import build_report_docx

    document = build_report_docx(
        _report_context_for_environment(submission, environment)
    )
    filename = f"relatorio-hitop-{submission.id}.docx"
    response = HttpResponse(
        document.getvalue(),
        content_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@verified_professional_required
def report_preview(request, submission_id):
    environment = ProfessionalEnvironment.clinical(request.user)
    submission = environment.get_submission(submission_id)
    return report_preview_response(
        request,
        submission,
        environment,
    )


@verified_professional_required
def export_report_docx(request, submission_id):
    environment = ProfessionalEnvironment.clinical(request.user)
    submission = environment.get_submission(submission_id)
    return export_report_docx_response(
        submission,
        environment,
    )
