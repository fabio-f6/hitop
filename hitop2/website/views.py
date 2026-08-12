from collections import defaultdict

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from polls.models import (
    QuestionnaireSubmission,
    SociodemographicAnswer,
    Spectra,
    UserAnswer,
)
from polls.percentiles import calculate_percentile
from polls.report_constants import SPECTRUM_KEYS
from polls.scoring import calculate_scale_scores
from polls.simulation import simulate_submission
from polls.translations import (
    SCALE_TRANSLATIONS,
    translate_scale,
    translate_spectrum,
    translate_subfactor,
)

from .forms import CreatePatientForm, EditPatientForm, SignUpForm
from .models import UserProfile


def home(request):

    # Se já estiver autenticado, não faz sentido mostrar a landing page
    if request.user.is_authenticated:

        if request.user.userprofile.user_type == "professional":
            return redirect("website:dashboard")

        elif request.user.userprofile.user_type == "patient":
            return redirect("polls:questionnaire")

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

            login(request, user)

            messages.success(
                request,
                "Logged in successfully!"
            )

            if user.userprofile.user_type == "patient":
                return redirect("polls:questionnaire")

            elif user.userprofile.user_type == "professional":
                return redirect("website:dashboard")

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

def register_user(request):
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            # cria o usuário mas ainda não salva completamente
            user = form.save(commit=False)

            # gera username automaticamente a partir do email
            user.username = form.cleaned_data['email'].split('@')[0]
            user.save()

            # atualiza o perfil que já foi criado automaticamente
            profile = user.userprofile
            profile.user_type = 'professional'  # apenas profissionais podem registrar
            profile.area_formacao = form.cleaned_data['area_formacao']
            profile.objetivo_uso = form.cleaned_data['objetivo_uso']
            profile.cedula_profissional = form.cleaned_data['cedula_profissional']
            profile.save()

            # autentica e loga o usuário
            user = authenticate(
                request,
                username=user.username,
                password=form.cleaned_data['password1']
            )
            login(request, user)

            messages.success(request, f"Registo realizado com sucesso! O seu nome de utilizador é: {user.username}")
            return redirect('website:dashboard')

    else:
        form = SignUpForm()

    return render(request, 'website/register.html', {'form': form})

@login_required
def create_patient(request):

    # garante que apenas profissionais podem acessar
    if request.user.userprofile.user_type != 'professional':
        messages.error(request, "Apenas profissionais podem criar pacientes.")
        return redirect('website:home')

    if request.method == "POST":

        temp_credentials = request.session.get('temp_credentials')

        form = CreatePatientForm(request.POST)

        if temp_credentials:
            form.generated_username = temp_credentials['username']
            form.generated_password = temp_credentials['password']

        if form.is_valid():
            user = form.save()

            profile = user.userprofile
            profile.user_type = 'patient'
            profile.professional = request.user
            profile.save()

            submission = QuestionnaireSubmission.objects.create(
                user=user,
                questionnaire_type="hitop",
                title=form.cleaned_data["title"],
                completed=False,
                is_open=True,
                simulation_mode=form.cleaned_data["simulation_mode"],
            )

            submission.spectra.set(
                form.cleaned_data["spectra"]
            )

            if submission.simulation_mode != "normal":
                simulate_submission(submission)

            request.session.pop('temp_credentials', None)

            return redirect(
                'website:patient_submissions',
                patient_id=user.id
                )

    else:
        form = CreatePatientForm()

        request.session['temp_credentials'] = {
            'username': form.generated_username,
            'password': form.generated_password
        }

    return render(request, 'website/create_patient.html', {'form': form})

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

@login_required
def new_questionnaire(request, patient_id):

    patient_profile = get_object_or_404(
        UserProfile,
        id=patient_id,
        user_type="patient"
    )

    if patient_profile.professional != request.user:
        messages.error(request, "Sem permissão.")
        return redirect("website:dashboard")

    spectra = Spectra.objects.all()

    if request.method == "POST":

        title = request.POST.get("title")
        selected_spectra_ids = request.POST.getlist("spectra")

        title = title.strip()

        if not title:
            messages.error(
                request,
                "O nome da submissão é obrigatório."
            )
            return redirect(
                "website:new_questionnaire",
                patient_id=patient_id
            )

        if not selected_spectra_ids:
            messages.error(
                request,
                "Selecione pelo menos um spectra."
            )
            return redirect(
                "website:new_questionnaire",
                patient_id=patient_id
            )

        submission = QuestionnaireSubmission.objects.create(
            user=patient_profile.user,
            questionnaire_type="hitop",
            title=title,
            completed=False,
            is_open=True,
            simulation_mode=request.POST.get("simulation_mode", "normal"),
        )

        submission.spectra.set(selected_spectra_ids)

        if submission.simulation_mode != "normal":
            simulate_submission(submission)

        messages.success(
            request,
            "Novo questionário criado com sucesso."
        )

        return redirect("website:dashboard")

    return render(
        request,
        "website/new_questionnaire.html",
        {
            "patient": patient_profile,
            "spectra": spectra,
        }
    )

@login_required
def dashboard(request):

    if request.user.userprofile.user_type != "professional":
        messages.error(request, "Acesso negado.")
        return redirect("website:home")

    patients = request.user.patients.all()

    patient_cards = []

    for patient in patients:

        submissions = QuestionnaireSubmission.objects.filter(
            user=patient.user
        ).order_by("-started_at")

        last_submission = submissions.first()

        patient_cards.append({
            "profile": patient,
            "submission_count": submissions.count(),
            "open_count": submissions.filter(is_open=True).count(),
            "last_submission": last_submission,
            "spectra": last_submission.spectra.all() if last_submission else [],
        })

    total_patients = len(patient_cards)

    total_submissions = QuestionnaireSubmission.objects.filter(
        user__userprofile__professional=request.user
    ).count()

    open_submissions = QuestionnaireSubmission.objects.filter(
        user__userprofile__professional=request.user,
        is_open=True
    ).count()

    return render(
        request,
        "website/dashboard.html",
        {
            "patients": patient_cards,
            "total_patients": total_patients,
            "total_submissions": total_submissions,
            "open_submissions": open_submissions,
        },
    )

@login_required
def patient_answers(request, submission_id):

    submission = get_object_or_404(
        QuestionnaireSubmission,
        id=submission_id
    )

    # segurança
    if submission.user.userprofile.professional != request.user:
        messages.error(request, "Acesso negado.")
        return redirect("website:dashboard")

    answers = UserAnswer.objects.filter(
        submission=submission
    ).select_related('question')

    return render(request, "website/patient_answers.html", {
        "submission": submission,
        "answers": answers
    })

@login_required
def patient_submissions(request, patient_id):

    patient = get_object_or_404(User, id=patient_id)

    # segurança: só profissional dono pode ver
    if patient.userprofile.professional != request.user:
        messages.error(request, "Acesso negado.")
        return redirect("website:dashboard")

    submissions = QuestionnaireSubmission.objects.filter(
        user=patient,
        questionnaire_type="hitop"
    ).order_by("-started_at")

    has_open_submission = QuestionnaireSubmission.objects.filter(
        user=patient,
        questionnaire_type="hitop",
        is_open=True
    ).exists()

    for submission in submissions:

        submission.access_link = request.build_absolute_uri(
            reverse(
                "polls:questionnaire_by_token",
                args=[submission.access_token]
            )
        )

        submission.spectra_list = submission.spectra.all()

    return render(request, "website/patient_submissions.html", {
        "patient": patient,
        "submissions": submissions,
        "has_open_submission": has_open_submission,
    })

@login_required
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

@login_required
def report_preview(request, submission_id):

    submission = get_object_or_404(
        QuestionnaireSubmission,
        id=submission_id
    )

    if submission.user.userprofile.professional != request.user:
        messages.error(request, "Acesso negado.")
        return redirect("website:dashboard")

    patient = submission.user

    scale_scores = calculate_scale_scores(submission)

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

    # Gráfico

    GRAPH_LEFT = 600
    GRAPH_RIGHT = 1160
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

    professional = patient.userprofile.professional

    socio = {
        answer.question_id: answer.answer_label
        for answer in SociodemographicAnswer.objects.filter(
            user=patient
        )
    }

    report_data = {

        "patient_name":
            patient.username,

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
            professional.userprofile.area_formacao,

        "professional_license":
            professional.userprofile.cedula_profissional,

        "submission_date":
            submission.started_at,
    }

    return render(
        request,
        "website/report_preview.html",
        {
            "report": report_data,
            "scale_scores": scale_scores,
            "grouped_scores": grouped_scores,
            "grouped_chart_data": grouped_chart_data,
            "percentile_marks": PERCENTILE_MARKS,
            "graph_left": GRAPH_LEFT,
            "graph_right": GRAPH_RIGHT,
            "graph_width": GRAPH_WIDTH,
        }
    )