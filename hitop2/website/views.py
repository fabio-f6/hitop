from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from .forms import SignUpForm, AddRecordForm, CreatePatientForm, EditPatientForm
from .models import Record, UserProfile
from polls.models import UserAnswer, QuestionnaireSubmission

def home(request):
    records = Record.objects.all()

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
        return render(request, 'website/home.html', {'records': records})

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

            profile.spectra.set(form.cleaned_data['spectra'])

            request.session['new_patient_credentials'] = {
                'username': form.generated_username,
                'password': form.generated_password
            }

            request.session.pop('temp_credentials', None)

            return redirect('website:patient_credentials')

    else:
        form = CreatePatientForm()

        request.session['temp_credentials'] = {
            'username': form.generated_username,
            'password': form.generated_password
        }

    return render(request, 'website/create_patient.html', {'form': form})

def patient_credentials(request):
    credentials = request.session.get('new_patient_credentials')

    if not credentials:
        return redirect('website:my_patients')

    del request.session['new_patient_credentials']

    return render(request, 'website/patient_credentials.html', {
        'credentials': credentials
        })

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

def reopen_questionnaire(request, patient_id):
    patient_profile = get_object_or_404(
        UserProfile,
        id=patient_id,
        user_type='patient'
    )

    if patient_profile.professional != request.user:
        messages.error(request, "Sem permissão.")
        return redirect('website:my_patients')

    # ----------------------------
    # RESET DO PROFILE
    # ----------------------------
    patient_profile.questionnaire_completed = False
    patient_profile.save()

    # ----------------------------
    # FECHAR SUBMISSÕES ANTIGAS (NÃO APAGAR)
    # ----------------------------
    QuestionnaireSubmission.objects.filter(
        user=patient_profile.user,
        questionnaire_type="hitop"
    ).update(is_open=False)

    # ----------------------------
    # CRIAR NOVA SUBMISSÃO ABERTA
    # ----------------------------
    submission = QuestionnaireSubmission.objects.create(
        user=patient_profile.user,
        questionnaire_type="hitop",
        completed=False,
        is_open=True
    )

    messages.success(request, "Questionário reaberto com sucesso.")
    return redirect('website:my_patients')

def customer_record(request, pk):
    if request.user.is_authenticated:
        customer_record = Record.objects.get(id=pk)
        return render(request, 'website/record.html', {'customer_record': customer_record})
    else:
        messages.error(request, "You must be logged in to view that page.")
        return redirect('website:home')

def delete_record(request, pk):
    if request.user.is_authenticated:
        delete_it = Record.objects.get(id=pk)
        delete_it.delete()
        messages.success(request, "Record deleted successfully.")
        return redirect('website:home')
    else:
        messages.error(request, "You must be logged in to view that page.")
        return redirect('website:home')

def add_record(request):
    form = AddRecordForm(request.POST or None)
    if request.user.is_authenticated:
        if request.method == "POST":
            if form.is_valid():
                add_record = form.save()
                messages.success(request, "Record added successfully.")
                return redirect('website:home')
        else:
            return render(request, 'website/add_record.html', {'form':form})
    else:
        messages.error(request, "You must be logged in to view that page.")
        return redirect('website:home')

def update_record(request, pk):
    if request.user.is_authenticated:
        current_record = Record.objects.get(id=pk)
        form = AddRecordForm(request.POST or None, instance=current_record)
        if form.is_valid():
            form.save()
            messages.success(request, "Record updated successfully.")
            return redirect('record', pk=pk)
        return render(request, 'website/update_record.html', {'form':form, 'record':current_record})
    else:
        messages.error(request, "You must be logged in to view that page.")
        return redirect('website:home')

# website/views.py
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

    return render(request, "website/patient_submissions.html", {
        "patient": patient,
        "submissions": submissions
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