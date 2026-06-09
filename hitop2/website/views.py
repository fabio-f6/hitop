from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.urls import reverse
from .forms import SignUpForm, CreatePatientForm, EditPatientForm
from .models import UserProfile
from polls.models import UserAnswer, QuestionnaireSubmission, Spectra

def home(request):
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, "Logged in successfully!")
            if request.user.userprofile.user_type == 'patient':
                return redirect('polls:questionnaire')
            elif request.user.userprofile.user_type == 'professional':
                return redirect('website:my_patients')
            else:
                return redirect('website:home')

        else:
            messages.error(request, "Invalid username or password.")
            return redirect('website:home')
    else:
        return render(request, 'website/home.html')

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
            return redirect('website:my_patients')

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
                is_open=True
            )

            submission.spectra.set(
                form.cleaned_data["spectra"]
            )

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
        return redirect('website:my_patients')

    if request.method == "POST":
        form = EditPatientForm(request.POST, instance=patient_profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Paciente atualizado com sucesso.")
            return redirect('website:my_patients')
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
        return redirect("website:my_patients")

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
            is_open=True
        )

        submission.spectra.set(selected_spectra_ids)

        messages.success(
            request,
            "Novo questionário criado com sucesso."
        )

        return redirect("website:my_patients")

    return render(
        request,
        "website/new_questionnaire.html",
        {
            "patient": patient_profile,
            "spectra": spectra,
        }
    )

@login_required
def my_patients(request):
    # Apenas profissionais podem acessar
    if request.user.userprofile.user_type != 'professional':
        messages.error(request, "Acesso negado.")
        return redirect('website:home')

    patients = request.user.patients.all()  # todos os pacientes associados
    return render(request, 'website/my_patients.html', {'patients': patients})

@login_required
def patient_answers(request, submission_id):

    submission = get_object_or_404(
        QuestionnaireSubmission,
        id=submission_id
    )

    # segurança
    if submission.user.userprofile.professional != request.user:
        messages.error(request, "Acesso negado.")
        return redirect("website:my_patients")

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
        return redirect("website:my_patients")

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
        return redirect("website:my_patients")

    answers = UserAnswer.objects.filter(
        submission=submission
    ).select_related('question')

    return render(request, "website/submission_detail.html", {
        "submission": submission,
        "answers": answers
    })